#!/usr/bin/env python3
"""
Market Discovery Scanner
Fetches candidate tickers from multiple screeners and ETF holdings,
filters out the existing watchlist, runs TA on the remaining candidates,
and ranks them by opportunity score.

Uses the stock-ta skill's analyze() function for all technical analysis —
single source of truth for indicators, scoring, and labels.

Usage:
    python3 scan_market.py [--watchlist PATH] [--top N] [--min-score N]
                           [--period 6mo] [--interval 1d] [--max-candidates N]

Dependencies: yfinance, pandas, ta
Install:      pip install yfinance pandas ta
"""

import argparse
import json
import os
import sys
import time
import re
import urllib.request
import urllib.parse
import urllib.error

# ── Load .env if present (optional dependency) ────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Import recommendation history tracker ─────────────────────────────────────
from recommendation_history import record_recommendations, annotate_results

# ── Import news enrichment ─────────────────────────────────────────────────
try:
    from news_enrichment import enrich_from_scan_results
    HAS_NEWS_ENRICHMENT = True
except ImportError:
    HAS_NEWS_ENRICHMENT = False

# ── Import LLM summarizer (uses dedicated OpenClaw "summarizer" agent) ─────
try:
    from llm_summarize import summarize_news_for_ticker
    HAS_LLM_SUMMARIZE = True
except ImportError:
    HAS_LLM_SUMMARIZE = False

# ── HTTP client for stock-ta ──────────────────────────────────────────────────
# Connect to the stock-ta HTTP server instead of importing directly.
# Set STOCK_TA_URL in .env or environment (default: http://localhost:8000).
_STOCK_TA_URL = os.environ.get("STOCK_TA_URL", "http://localhost:8000").rstrip("/")


def analyze(ticker: str, period: str = "6mo", interval: str = "1d") -> dict:
    """Call stock-ta /analyze endpoint and return result dict."""
    params = urllib.parse.urlencode({"ticker": ticker, "period": period, "interval": interval})
    url = f"{_STOCK_TA_URL}/analyze?{params}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return json.loads(body)
        except Exception:
            return {"error": f"HTTP {e.code}: {body[:200]}"}
    except Exception as e:
        return {"error": str(e)}


try:
    import yfinance as yf
    import pandas as pd
except ImportError as e:
    print(json.dumps({"error": f"Missing dependency: {e}. Run: pip install yfinance pandas ta"}))
    sys.exit(1)


# ── Candidate sources — Taiwan market focused ────────────────────────────────
# No yfinance built-in screeners for TWSE/OTC, so we rely entirely on TW ETF holdings.
# ETFs are chosen to cover: large-cap, semiconductors, tech, mid/small-cap, high-dividend.
# Each ETF contributes its top holdings as discovery candidates.
SCREENER_SOURCES = []  # No TW screeners available via yfinance

# TW ETF sources — ordered by breadth/diversity of holdings
ETF_SOURCES = [
    "0050.TW",    # 元大台灣50 — top 50 by market cap (broad large-cap)
    "0056.TW",    # 元大高股息 — high dividend, different mix from 0050
    "00881.TW",   # 國泰台灣5G+ — tech/telecom/semi focus
    "00891.TW",   # 中信關鍵半導體 — semiconductor supply chain
    "00904.TW",   # 新光台灣半導體30 — semiconductor 30
    "00929.TW",   # 復華台灣科技優息 — tech + yield mix
    "00912.TW",   # 中信台灣智慧50 — AI/smart tech
    "00733.TW",   # 富邦台灣中小 — mid/small cap discovery
    "006208.TW",  # 富邦台灣50 — alternative large-cap coverage
    "00900.TW",   # 富邦特選高股息30 — value/dividend names
]


def parse_watchlist(path: str) -> set:
    """Parse tickers from market-watchlist.md table format."""
    tickers = set()
    try:
        with open(path) as f:
            for line in f:
                # Match markdown table rows: | TICKER | ...
                m = re.match(r"\|\s*([A-Z0-9\.\-]+)\s*\|", line.strip())
                if m:
                    ticker = m.group(1).strip()
                    # Skip header/separator rows
                    if ticker.upper() not in ("TICKER", "") and not re.match(r'^-+$', ticker):
                        tickers.add(ticker.upper())
    except FileNotFoundError:
        print(f"Warning: watchlist not found at {path}", file=sys.stderr)
    return tickers


def gather_candidates(max_per_source: int = 30) -> list:
    """Gather candidate tickers from TW ETF holdings."""
    candidates = []
    seen = set()

    # ETF holdings — primary source for TW market
    for etf in ETF_SOURCES:
        try:
            tk = yf.Ticker(etf)
            holdings_df = tk.funds_data.top_holdings
            added = 0
            for s in holdings_df.index:
                if s not in seen:
                    seen.add(s)
                    name = str(holdings_df.loc[s, "Name"]) if "Name" in holdings_df.columns else None
                    candidates.append({"ticker": s, "name": name, "source": f"ETF:{etf}"})
                    added += 1
            print(f"  [ETF:{etf}] {added} new candidates (total in ETF: {len(holdings_df)})", file=sys.stderr)
        except Exception as e:
            print(f"  [ETF:{etf}] ERROR: {e}", file=sys.stderr)
        time.sleep(0.3)

    return candidates


def main():
    parser = argparse.ArgumentParser(description="Market Discovery Scanner")
    parser.add_argument("--watchlist",      default="market-watchlist.md",
                        help="Path to watchlist file to exclude (default: market-watchlist.md)")
    parser.add_argument("--top",            type=int, default=10,
                        help="Number of top opportunities to return (default: 10)")
    parser.add_argument("--min-score",      type=int, default=2,
                        help="Minimum score to include in results (default: 2)")
    parser.add_argument("--min-market-cap", type=float, default=1e10,
                        help="Minimum market cap in TWD to include (default: 10B TWD ~300M USD)")
    parser.add_argument("--period",         default="6mo")
    parser.add_argument("--interval",       default="1d")
    parser.add_argument("--max-candidates", type=int, default=80,
                        help="Max candidates to analyze after dedup/filter (default: 80)")
    parser.add_argument("--history-path", default=None,
                        help="Path to recommendation history JSON (default: ~/.openclaw/workspace/data/scanner-history.json)")
    parser.add_argument("--no-history", action="store_true",
                        help="Disable history tracking for this run")
    parser.add_argument("--enrich-news", action="store_true",
                        help="Run news searches on top picks for recent context (requires headed browser)")
    parser.add_argument("--no-enrich-news", action="store_true",
                        help="Explicitly disable news enrichment")
    parser.add_argument("--no-exclude-watchlist", action="store_true",
                        help="Include watchlist tickers in analysis instead of excluding them")
    parser.add_argument("--max-news-articles", type=int, default=5,
                        help="Max news articles per ticker (default: 5)")
    args = parser.parse_args()

    # Step 1: load exclusion list
    if args.no_exclude_watchlist:
        watchlist = set()
        print("Watchlist exclusion disabled (--no-exclude-watchlist)", file=sys.stderr)
    else:
        watchlist = parse_watchlist(args.watchlist)
        print(f"Watchlist exclusions: {sorted(watchlist)}", file=sys.stderr)

    # Step 2: gather candidates
    print("\nGathering candidates...", file=sys.stderr)
    candidates = gather_candidates()
    print(f"Total candidates before filter: {len(candidates)}", file=sys.stderr)

    # Step 3: filter out watchlist tickers and non-TW symbols
    filtered = []
    skipped = []
    for c in candidates:
        t = c["ticker"].upper()
        # Skip if in watchlist (only when exclusion is enabled)
        if t in watchlist:
            skipped.append(t)
            continue
        # Keep only TW/TWO market tickers (suffix .TW or .TWO)
        if not (t.endswith(".TW") or t.endswith(".TWO")):
            skipped.append(t)
            continue
        # Skip obvious non-equity symbols
        if any(x in t for x in ["^", "="]):
            continue
        filtered.append(c)

    # Deduplicate while preserving first-seen source
    seen = {}
    deduped = []
    for c in filtered:
        if c["ticker"] not in seen:
            seen[c["ticker"]] = c["source"]
            deduped.append(c)

    # Cap at max-candidates
    deduped = deduped[:args.max_candidates]
    print(f"Candidates to analyze: {len(deduped)} (skipped {len(skipped)} from watchlist)", file=sys.stderr)

    # Step 4: run TA on each candidate (using stock-ta's analyze())
    results = []
    errors = []

    for i, c in enumerate(deduped):
        ticker = c["ticker"]
        print(f"  [{i+1}/{len(deduped)}] Analyzing {ticker} (from {c['source']})...", file=sys.stderr)
        result = analyze(ticker, args.period, args.interval)
        result["source"] = c["source"]
        # Carry over the authoritative company name from ETF holdings
        if c.get("name") and not result.get("name"):
            result["name"] = c["name"]

        if "error" in result:
            errors.append(result)
        else:
            # Filter by market cap — fetch via fast_info if not present
            mc = result.get("market_cap")
            if mc is None:
                try:
                    tk = yf.Ticker(ticker)
                    mc = getattr(tk.fast_info, "market_cap", None)
                except Exception:
                    mc = None
            if mc is not None and mc < args.min_market_cap:
                errors.append({**result, "error": f"Market cap too small ({mc:.0f})"})
            else:
                results.append(result)
        time.sleep(0.25)

    # Step 5: sort and bucket results
    results.sort(key=lambda x: x["score"], reverse=True)

    strong_buy_results = [r for r in results if r["score"] >= 6]
    buy_results = [r for r in results if 3 <= r["score"] < 6]
    other_qualified_results = [r for r in results if args.min_score <= r["score"] < 3]

    # Always include all BUY / STRONG BUY results; only lower-score qualified
    # results are subject to the generic --top cap.
    remaining_slots = max(0, args.top - len(strong_buy_results) - len(buy_results))
    top_results = strong_buy_results + buy_results + other_qualified_results[:remaining_slots]

    scan_date = pd.Timestamp.now().strftime("%Y-%m-%d")

    # ── History tracking ────────────────────────────────────────────────────────────
    history_kwargs = {}
    if args.history_path:
        history_kwargs["history_path"] = args.history_path

    if not args.no_history:
        # Annotate results with prior recommendation history BEFORE recording
        top_results = annotate_results(top_results, **history_kwargs)

        # Record all BUY / STRONG BUY results into history, regardless of --top
        qualified = [r for r in results if r["score"] >= 3]
        record_recommendations(qualified, scan_date, **history_kwargs)
        print(f"Recorded {len(qualified)} recommendations to history", file=sys.stderr)

    # ── News enrichment ───────────────────────────────────────────────────────────
    do_news = args.enrich_news and not args.no_enrich_news
    news_data = {}

    # Enrich all STRONG BUY picks (score >= 6) with news
    enriched_picks = [r for r in top_results if r["score"] >= 6]

    if do_news and HAS_NEWS_ENRICHMENT and enriched_picks:
        print(f"\nEnriching {len(enriched_picks)} STRONG BUY picks with recent news...", file=sys.stderr)
        try:
            news_data = enrich_from_scan_results(
                enriched_picks,
                max_articles_per_ticker=args.max_news_articles,
            )
            # Attach news articles to enriched results
            for r in enriched_picks:
                ticker = r["ticker"]
                if ticker in news_data:
                    r["recent_news"] = news_data[ticker].get("articles", [])
            print(f"News enrichment complete for {len(news_data)} tickers", file=sys.stderr)

            # Summarize news using the dedicated summarizer agent (Gemini 3 Flash)
            if HAS_LLM_SUMMARIZE:
                print("\nSummarizing news via OpenClaw summarizer agent (Gemini 3 Flash)...", file=sys.stderr)
                for r in enriched_picks:
                    ticker = r["ticker"]
                    articles = r.get("recent_news", [])
                    if articles:
                        name = r.get("name") or ticker
                        summary = summarize_news_for_ticker(
                            ticker, name, articles,
                            language="zh-TW",
                        )
                        r["news_summary"] = summary
                    else:
                        r["news_summary"] = ""
                print("News summarization complete", file=sys.stderr)
            else:
                print("Warning: llm_summarize not available, skipping news summarization", file=sys.stderr)

        except Exception as e:
            print(f"Warning: News enrichment failed: {e}", file=sys.stderr)
    elif do_news and not HAS_NEWS_ENRICHMENT:
        print("Warning: --enrich-news requested but news_enrichment module not available", file=sys.stderr)

    output = {
        "scan_date": scan_date,
        "candidates_analyzed": len(results),
        "candidates_skipped_errors": len(errors),
        "watchlist_excluded": len(skipped),
        "top": args.top,
        "min_score_filter": args.min_score,
        "results": top_results,
        "all_results_summary": [
            {"ticker": r["ticker"], "name": r.get("name"), "score": r["score"], "label": r["label"], "source": r["source"]}
            for r in results
        ],
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
