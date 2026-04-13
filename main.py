#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

# ── Load .env if present ──────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def read_market_webhook_url() -> str:
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        raise RuntimeError("DISCORD_WEBHOOK_URL not set. Add it to .env or export it.")
    return url


def load_scan():
    from scan_market import scan
    return scan


def send_discord_chunk(webhook_url: str, content: str) -> str:
    """POST a single content chunk to a Discord webhook. Returns response body.

    To post into a thread, append ?thread_id=<id> to the webhook URL.
    """
    payload = {"content": content}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        webhook_url, data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (market-scanner, 1.0)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Discord webhook HTTP {e.code}: {body[:500]}")


def fmt_price(v):
    if v is None:
        return '?'
    return f"{v:.1f}" if isinstance(v, (int, float)) else str(v)


def fmt_pct(v):
    if v is None:
        return '?'
    return f"{v:+.1f}%"


def fmt_num(v):
    if v is None:
        return '?'
    return f"{v:.0f}" if isinstance(v, (int, float)) else str(v)


BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / 'templates'
REPORT_TEMPLATE_NAME = 'report.txt.j2'
REPORT_STRINGS_NAME = 'report_strings.json'


def load_report_strings() -> dict:
    with open(TEMPLATE_DIR / REPORT_STRINGS_NAME, encoding='utf-8') as f:
        return json.load(f)


def fmt_signal_summary(r: dict, text: dict) -> str:
    signals = []
    trend = r.get('trend', {}) or {}
    momentum = r.get('momentum', {}) or {}
    volume = r.get('volume', {}) or {}
    signal_text = text['signals']

    macd_hist = trend.get('macd_hist')
    rsi14 = momentum.get('rsi14')
    stoch_k = momentum.get('stoch_k')
    stoch_d = momentum.get('stoch_d')
    obv_trend = volume.get('obv_trend')
    vol_ratio = volume.get('ratio')

    if isinstance(macd_hist, (int, float)) and macd_hist > 0:
        signals.append(signal_text['macd_hist_positive'])
    if isinstance(rsi14, (int, float)) and 40 <= rsi14 <= 70:
        signals.append(signal_text['rsi_healthy'].format(rsi=fmt_num(rsi14)))
    if isinstance(stoch_k, (int, float)) and isinstance(stoch_d, (int, float)) and stoch_k > stoch_d:
        signals.append(signal_text['stoch_bullish'])
    if (obv_trend or '').lower() == 'rising':
        signals.append(signal_text['obv_rising'])
    if isinstance(vol_ratio, (int, float)) and vol_ratio > 1.5:
        signals.append(signal_text['volume_surge'].format(ratio=f'{vol_ratio:.1f}'))
    return text['signal_separator'].join(signals[:2]) if signals else signal_text['default']


def prepare_strong_buy_item(r: dict, text: dict) -> dict:
    ticker = r.get('ticker', '?')
    name = r.get('name') or ticker
    price_info = r.get('price', {}) or {}
    momentum = r.get('momentum', {}) or {}
    volume = r.get('volume', {}) or {}
    levels = r.get('levels', {}) or {}
    vol_ratio = volume.get('ratio')

    return {
        'ticker': ticker,
        'name': name,
        'label': r.get('label', 'STRONG BUY'),
        'score': r.get('score', '?'),
        'source': r.get('source', 'unknown'),
        'price': fmt_price(price_info.get('current')),
        'change': fmt_pct(price_info.get('change_1d_pct')),
        'rsi': fmt_num(momentum.get('rsi14')),
        'stoch_k': fmt_num(momentum.get('stoch_k')),
        'stoch_d': fmt_num(momentum.get('stoch_d')),
        'vol_ratio': None if vol_ratio is None else f'{vol_ratio:.1f}',
        'support': fmt_price(levels.get('S1')),
        'resistance': fmt_price(levels.get('R1')),
        'signal_summary': fmt_signal_summary(r, text),
        'news': (r.get('news_summary') or '').strip(),
        'recommendation_count': r.get('times_recommended', 0) if r.get('previously_recommended') else 0,
    }


def prepare_buy_item(r: dict, text: dict) -> dict:
    ticker = r.get('ticker', '?')
    name = r.get('name') or ticker
    price_info = r.get('price', {}) or {}
    momentum = r.get('momentum', {}) or {}

    return {
        'ticker': ticker,
        'name': name,
        'label': r.get('label', 'BUY'),
        'score': r.get('score', '?'),
        'price': fmt_price(price_info.get('current')),
        'change': fmt_pct(price_info.get('change_1d_pct')),
        'rsi': fmt_num(momentum.get('rsi14')),
        'signal_summary': fmt_signal_summary(r, text),
    }


def report_template_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=False,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def render_report_template(context: dict) -> str:
    template = report_template_env().get_template(REPORT_TEMPLATE_NAME)
    return template.render(context).strip() + '\n'


def _split_hard(text: str, limit: int) -> list[str]:
    return [text[i:i + limit] for i in range(0, len(text), limit)] if text else []


def _split_block(block: str, limit: int) -> list[str]:
    if len(block) <= limit:
        return [block]

    pieces = []
    current = []
    current_len = 0

    for line in block.split('\n'):
        if len(line) > limit:
            if current:
                pieces.append('\n'.join(current))
                current = []
                current_len = 0
            pieces.extend(_split_hard(line, limit))
            continue

        addition_len = len(line) if not current else len(line) + 1
        if current_len + addition_len <= limit:
            current.append(line)
            current_len += addition_len
        else:
            if current:
                pieces.append('\n'.join(current))
            current = [line]
            current_len = len(line)

    if current:
        pieces.append('\n'.join(current))

    return pieces


def chunk_text(text: str, limit: int = 2000) -> list[str]:
    text = text.strip()
    if not text:
        return ['']
    if len(text) <= limit:
        return [text]

    chunks = []
    current = ''

    for raw_block in text.split('\n\n'):
        block = raw_block.strip()
        if not block:
            continue

        for piece in _split_block(block, limit):
            if not current:
                current = piece
            elif len(current) + 2 + len(piece) <= limit:
                current += '\n\n' + piece
            else:
                chunks.append(current)
                current = piece

    if current:
        chunks.append(current)

    final_chunks = []
    for chunk in chunks:
        if len(chunk) <= limit:
            final_chunks.append(chunk)
        else:
            final_chunks.extend(_split_hard(chunk, limit))

    return final_chunks


def build_report(scan_output: dict) -> str:
    scan_date = scan_output.get('scan_date', datetime.now().strftime('%Y-%m-%d'))
    analyzed = scan_output.get('candidates_analyzed', 0)
    results = scan_output.get('results', [])
    text = load_report_strings()
    strong_buys = [r for r in results if r.get('score', 0) >= 6]
    buys = [r for r in results if 3 <= r.get('score', 0) < 6]

    return render_report_template({
        'scan_date': scan_date,
        'analyzed': analyzed,
        'strong_buys': [prepare_strong_buy_item(r, text) for r in strong_buys],
        'buys': [prepare_buy_item(r, text) for r in buys],
    })


def main():
    parser = argparse.ArgumentParser(description='Market scanner — scans TW market and posts report to Discord')
    parser.add_argument('--top',                  type=int,   default=10,             help='Number of top picks to include (default: 10)')
    parser.add_argument('--min-score',            type=int,   default=3,              help='Minimum TA score to include (default: 3)')
    parser.add_argument('--max-candidates',       type=int,   default=80,             help='Max tickers to analyse (default: 80)')
    parser.add_argument('--min-market-cap',       type=float, default=1e10,           help='Minimum market cap in TWD (default: 10B)')
    parser.add_argument('--period',               default='6mo',                      help='yfinance data period (default: 6mo)')
    parser.add_argument('--interval',             default='1d',                       help='Bar interval (default: 1d)')
    parser.add_argument('--watchlist',            default='market-watchlist.md',      help='Watchlist file to exclude (default: market-watchlist.md)')
    parser.add_argument('--no-exclude-watchlist', action='store_true',                help='Include watchlist tickers instead of excluding them')
    parser.add_argument('--history-path',         default=None,                       help='Custom path for recommendation history JSON')
    parser.add_argument('--no-history',           action='store_true',                help='Disable history tracking for this run')
    parser.add_argument('--enrich-news',          action='store_true',                help='Fetch news summaries for STRONG BUY picks')
    parser.add_argument('--max-news-articles',    type=int,   default=5,              help='Max news articles per ticker (default: 5)')
    parser.add_argument('--json',                 action='store_true', dest='as_json',help='Print scan output as JSON and exit without posting to Discord')
    parser.add_argument('--temp-root',            default='/tmp',                     help='Parent directory for run artifacts (default: /tmp)')
    parser.add_argument('--keep-temp',            action='store_true',                help='Keep temp directory after a successful run')
    parser.add_argument('--reuse-temp-dir',                                           help='Reuse an existing temp directory to skip completed stages')
    parser.add_argument('--delivery-only',        action='store_true',                help='Skip scan and resend an existing staged report')
    args = parser.parse_args()

    if args.as_json:
        scan = load_scan()
        scan_output = scan(
            watchlist=args.watchlist,
            top=args.top,
            min_score=args.min_score,
            min_market_cap=args.min_market_cap,
            period=args.period,
            interval=args.interval,
            max_candidates=args.max_candidates,
            history_path=args.history_path,
            no_history=args.no_history,
            enrich_news=args.enrich_news,
            no_exclude_watchlist=args.no_exclude_watchlist,
            max_news_articles=args.max_news_articles,
        )
        print(json.dumps(scan_output, indent=2, ensure_ascii=False))
        return

    webhook_url = read_market_webhook_url()

    if args.reuse_temp_dir:
        tmpdir = args.reuse_temp_dir
        os.makedirs(tmpdir, exist_ok=True)
        cleanup_tmpdir = False
    else:
        tmpdir = tempfile.mkdtemp(prefix='market-scanner-', dir=args.temp_root)
        cleanup_tmpdir = not args.keep_temp

    stage_dir = os.path.join(tmpdir, 'stages')
    os.makedirs(stage_dir, exist_ok=True)

    scan_json   = os.path.join(stage_dir, '01-scan-output.json')
    report_txt  = os.path.join(stage_dir, '02-report.txt')
    post_log    = os.path.join(stage_dir, '03-webhook.log')
    meta_json   = os.path.join(stage_dir, '00-meta.json')

    with open(meta_json, 'w', encoding='utf-8') as f:
        json.dump({'tmpdir': tmpdir, 'created_at': datetime.now().isoformat(), 'args': vars(args)}, f, indent=2)

    try:
        if args.delivery_only:
            if not os.path.exists(report_txt):
                raise RuntimeError(f'--delivery-only requires an existing staged report at {report_txt}')
            with open(report_txt, 'r', encoding='utf-8') as f:
                report = f.read()
            report_chunks = chunk_text(report, limit=2000)
        else:
            if os.path.exists(scan_json):
                print('Reusing existing scan output.', file=sys.stderr)
                with open(scan_json, 'r', encoding='utf-8') as f:
                    scan_output = json.load(f)
            else:
                scan = load_scan()
                scan_output = scan(
                    watchlist=args.watchlist,
                    top=args.top,
                    min_score=args.min_score,
                    min_market_cap=args.min_market_cap,
                    period=args.period,
                    interval=args.interval,
                    max_candidates=args.max_candidates,
                    history_path=args.history_path,
                    no_history=args.no_history,
                    enrich_news=args.enrich_news,
                    no_exclude_watchlist=args.no_exclude_watchlist,
                    max_news_articles=args.max_news_articles,
                )
                with open(scan_json, 'w', encoding='utf-8') as f:
                    json.dump(scan_output, f, indent=2, ensure_ascii=False)

            if os.path.exists(report_txt):
                print('Reusing existing report.', file=sys.stderr)
                with open(report_txt, 'r', encoding='utf-8') as f:
                    report = f.read()
            else:
                print('Building report...', file=sys.stderr)
                report = build_report(scan_output)
                with open(report_txt, 'w', encoding='utf-8') as f:
                    f.write(report)

            report_chunks = chunk_text(report, limit=2000)
            with open(report_txt, 'w', encoding='utf-8') as f:
                f.write('\n\n--- chunk separator ---\n\n'.join(report_chunks))

        print(f'Posting report to Discord ({len(report_chunks)} chunk(s))...', file=sys.stderr)
        delivery_logs = []
        for idx, chunk in enumerate(report_chunks, 1):
            try:
                resp_body = send_discord_chunk(webhook_url, chunk)
                print(f'  Chunk {idx}/{len(report_chunks)} sent.', file=sys.stderr)
                delivery_logs.append(f'--- chunk {idx}/{len(report_chunks)} --- OK\n{resp_body}')
            except RuntimeError as exc:
                delivery_logs.append(f'--- chunk {idx}/{len(report_chunks)} --- FAILED\n{exc}')
                with open(post_log, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(delivery_logs))
                raise RuntimeError(f'Webhook send failed on chunk {idx}/{len(report_chunks)}: {exc}. Artifacts: {tmpdir}')

        with open(post_log, 'w', encoding='utf-8') as f:
            f.write('\n'.join(delivery_logs))

        print(f'Report posted successfully to Discord in {len(report_chunks)} chunk(s). Artifacts: {tmpdir}')
    finally:
        if cleanup_tmpdir and os.path.isdir(tmpdir):
            shutil.rmtree(tmpdir)


if __name__ == '__main__':
    main()
