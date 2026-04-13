#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error
from datetime import datetime

# ── Load .env if present ──────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCAN_SCRIPT = os.path.join(SCRIPT_DIR, 'scan_market.py')


def read_market_webhook_url() -> str:
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        raise RuntimeError("DISCORD_WEBHOOK_URL not set. Add it to .env or export it.")
    return url


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


def fmt_signal_summary(r: dict) -> str:
    signals = []
    trend = r.get('trend', {}) or {}
    momentum = r.get('momentum', {}) or {}
    volume = r.get('volume', {}) or {}

    macd_hist = trend.get('macd_hist')
    rsi14 = momentum.get('rsi14')
    stoch_k = momentum.get('stoch_k')
    stoch_d = momentum.get('stoch_d')
    obv_trend = volume.get('obv_trend')
    vol_ratio = volume.get('ratio')

    if isinstance(macd_hist, (int, float)) and macd_hist > 0:
        signals.append('MACD 柱狀體為正')
    if isinstance(rsi14, (int, float)) and 40 <= rsi14 <= 70:
        signals.append(f"RSI 處於健康區間 ({fmt_num(rsi14)})")
    if isinstance(stoch_k, (int, float)) and isinstance(stoch_d, (int, float)) and stoch_k > stoch_d:
        signals.append('隨機指標看漲')
    if (obv_trend or '').lower() == 'rising':
        signals.append('OBV 上升')
    if isinstance(vol_ratio, (int, float)) and vol_ratio > 1.5:
        signals.append(f"成交量放大 {vol_ratio:.1f}×")
    return '、'.join(signals[:2]) if signals else '技術面維持偏多'


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
    strong_buys = [r for r in results if r.get('score', 0) >= 6]
    buys = [r for r in results if 3 <= r.get('score', 0) < 6]

    lines = []
    lines.append('📡 市場新機會掃描報告')
    lines.append(f'{scan_date} · 分析 {analyzed} 檔候選股票')
    lines.append('')
    lines.append('━━━━━━━━━━━━━━━━━━━━━━')
    lines.append('🏆 強力機會')
    lines.append('━━━━━━━━━━━━━━━━━━━━━━')
    lines.append('')

    if strong_buys:
        for r in strong_buys:
            ticker = r.get('ticker', '?')
            name = r.get('name') or ticker
            label = r.get('label', 'STRONG BUY')
            source = r.get('source', 'unknown')
            price_info = r.get('price', {}) or {}
            momentum = r.get('momentum', {}) or {}
            volume = r.get('volume', {}) or {}
            levels = r.get('levels', {}) or {}

            price = fmt_price(price_info.get('current'))
            change = fmt_pct(price_info.get('change_1d_pct'))
            rsi = fmt_num(momentum.get('rsi14'))
            stoch_k = fmt_num(momentum.get('stoch_k'))
            stoch_d = fmt_num(momentum.get('stoch_d'))
            vol_ratio = volume.get('ratio')
            vol_ratio_txt = '?' if vol_ratio is None else f"{vol_ratio:.1f}×均量"
            s1 = fmt_price(levels.get('S1'))
            r1 = fmt_price(levels.get('R1'))
            lines.append(f'🟢 {ticker} {name} [{label}] 分數: {r.get("score", "?")}/8 · 來源: {source}')
            lines.append(f'現價: ${price} ({change})')
            lines.append(f'RSI: {rsi} | Stoch K{stoch_k}/D{stoch_d} | 成交量: {vol_ratio_txt}')
            lines.append(f'✅ {fmt_signal_summary(r)}')
            lines.append(f'支撐: {s1}  阻力: {r1}')
            news = (r.get('news_summary') or '').strip()
            if news:
                lines.append(f'📰 {news}')
            if r.get('previously_recommended'):
                times = r.get('times_recommended', 0)
                if times:
                    lines.append(f'🔁 已連續推薦 {times} 次')
            lines.append('')
    else:
        lines.append('本次沒有達到 STRONG BUY 門檻的標的。')
        lines.append('')

    lines.append('━━━━━━━━━━━━━━━━━━━━━━')
    lines.append('👀 值得關注')
    lines.append('━━━━━━━━━━━━━━━━━━━━━━')
    lines.append('')

    if buys:
        for r in buys:
            ticker = r.get('ticker', '?')
            name = r.get('name') or ticker
            label = r.get('label', 'BUY')
            price_info = r.get('price', {}) or {}
            momentum = r.get('momentum', {}) or {}
            price = fmt_price(price_info.get('current'))
            change = fmt_pct(price_info.get('change_1d_pct'))
            rsi = fmt_num(momentum.get('rsi14'))
            lines.append(f'🟡 {ticker} {name} [{label}] 分數: {r.get("score", "?")}/8 · ${price} ({change}) RSI {rsi}')
            lines.append(fmt_signal_summary(r))
            lines.append('')
    else:
        lines.append('本次沒有達到 BUY 門檻的標的。')
        lines.append('')

    lines.append('━━━━━━━━━━━━━━━━━━━━━━')
    lines.append('*本報告僅供參考，非投資建議。來源：市場篩選器 + ETF 持倉。*')
    return '\n'.join(lines).strip() + '\n'


def main():
    parser = argparse.ArgumentParser(description='Deterministic market scanner runner with verified webhook delivery')
    parser.add_argument('--top', type=int, default=10)
    parser.add_argument('--min-score', type=int, default=3)
    parser.add_argument('--max-candidates', type=int, default=80)
    parser.add_argument('--max-news-articles', type=int, default=5)
    parser.add_argument('--period', default='6mo')
    parser.add_argument('--interval', default='1d')
    parser.add_argument('--min-market-cap', type=float, default=1e10)
    parser.add_argument('--watchlist', default='market-watchlist.md')
    parser.add_argument('--temp-root', default='/tmp', help='Parent directory for run artifacts (default: /tmp)')
    parser.add_argument('--keep-temp', action='store_true', help='Keep temp run directory after success')
    parser.add_argument('--reuse-temp-dir', help='Reuse an existing temp run directory to skip completed stages')
    parser.add_argument('--delivery-only', action='store_true', help='Skip scan/report generation and resend from an existing staged report')
    args = parser.parse_args()

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

    scan_json = os.path.join(stage_dir, '01-scan-output.json')
    scan_stderr = os.path.join(stage_dir, '01-scan-stderr.log')
    report_txt = os.path.join(stage_dir, '02-report.txt')
    post_stdout = os.path.join(stage_dir, '03-webhook-stdout.log')
    post_stderr = os.path.join(stage_dir, '03-webhook-stderr.log')
    meta_json = os.path.join(stage_dir, '00-meta.json')

    metadata = {
        'tmpdir': tmpdir,
        'stage_dir': stage_dir,
        'created_at': datetime.now().isoformat(),
        'args': vars(args),
        'files': {
            'scan_json': scan_json,
            'scan_stderr': scan_stderr,
            'report_txt': report_txt,
            'post_stdout': post_stdout,
            'post_stderr': post_stderr,
        },
    }
    with open(meta_json, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    try:
        if args.delivery_only:
            if not os.path.exists(report_txt):
                raise RuntimeError(f'--delivery-only requires an existing staged report at {report_txt}')
            with open(report_txt, 'r', encoding='utf-8') as f:
                report = f.read()
            report_chunks = chunk_text(report, limit=2000)
        else:
            if os.path.exists(scan_json):
                with open(scan_json, 'r', encoding='utf-8') as f:
                    scan_output = json.load(f)
            else:
                scan_cmd = [
                    sys.executable,
                    SCAN_SCRIPT,
                    '--watchlist', args.watchlist,
                    '--top', str(args.top),
                    '--min-score', str(args.min_score),
                    '--min-market-cap', str(int(args.min_market_cap)),
                    '--period', args.period,
                    '--interval', args.interval,
                    '--max-candidates', str(args.max_candidates),
                    '--enrich-news',
                    '--max-news-articles', str(args.max_news_articles),
                ]

                scan_proc = subprocess.run(scan_cmd, capture_output=True, text=True)
                with open(scan_stderr, 'w', encoding='utf-8') as f:
                    f.write(scan_proc.stderr or '')
                if scan_proc.returncode != 0:
                    sys.stderr.write(scan_proc.stderr)
                    raise RuntimeError(f'scan_market.py failed with rc={scan_proc.returncode}. Artifacts: {tmpdir}')

                with open(scan_json, 'w', encoding='utf-8') as f:
                    f.write(scan_proc.stdout)
                scan_output = json.loads(scan_proc.stdout)

            if os.path.exists(report_txt):
                with open(report_txt, 'r', encoding='utf-8') as f:
                    report = f.read()
            else:
                report = build_report(scan_output)
                with open(report_txt, 'w', encoding='utf-8') as f:
                    f.write(report)

            report_chunks = chunk_text(report, limit=2000)
            with open(report_txt, 'w', encoding='utf-8') as f:
                f.write('\n\n--- chunk separator ---\n\n'.join(report_chunks))

        delivery_logs = []
        for idx, chunk in enumerate(report_chunks, 1):
            try:
                resp_body = send_discord_chunk(webhook_url, chunk)
                delivery_logs.append(f'--- chunk {idx}/{len(report_chunks)} --- OK\n{resp_body}')
            except RuntimeError as exc:
                delivery_logs.append(f'--- chunk {idx}/{len(report_chunks)} --- FAILED\n{exc}')
                with open(post_stdout, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(delivery_logs))
                open(post_stderr, 'w').close()
                raise RuntimeError(f'Webhook send failed on chunk {idx}/{len(report_chunks)}: {exc}. Artifacts: {tmpdir}')

        with open(post_stdout, 'w', encoding='utf-8') as f:
            f.write('\n'.join(delivery_logs))
        open(post_stderr, 'w').close()

        print(f'Report posted successfully to Discord webhook in {len(report_chunks)} chunk(s). Artifacts: {tmpdir}')
    finally:
        if cleanup_tmpdir and os.path.isdir(tmpdir):
            shutil.rmtree(tmpdir)


if __name__ == '__main__':
    main()
