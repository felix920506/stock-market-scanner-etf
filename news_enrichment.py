#!/usr/bin/env python3
"""
News Enrichment for Market Scanner

Takes a list of tickers/names from scanner results and performs quick
browser-based news searches to gather recent context for each company.
Uses the company-research skill's browser tools.

Output: JSON dict mapping ticker → list of news snippets
{
  "2330.TW": {
    "name": "台積電",
    "articles": [
      {"title": "...", "url": "...", "snippet": "..."},
      ...
    ]
  },
  ...
}

Usage:
    python3 news_enrichment.py --tickers '{"2330.TW": "台積電", "2317.TW": "鴻海"}'
    python3 news_enrichment.py --results-json '<scan_market output JSON>'
    python3 news_enrichment.py --results-file /path/to/scan_results.json

Dependencies: Requires the company-research skill's browser_search.py
"""

import argparse
import json
import os
import sys
import time

# ── Import browser_search from company-research skill ──────────────────────────
_script_dir = os.path.dirname(os.path.abspath(__file__))
_market_research_dir = os.path.join(_script_dir, "..", "..", "company-research", "scripts")
_market_research_dir = os.path.normpath(_market_research_dir)
sys.path.insert(0, _market_research_dir)

try:
    from browser_search import search as browser_search
except ImportError as e:
    print(f"Error: Cannot import browser_search from {_market_research_dir}: {e}", file=sys.stderr)
    print("Ensure the company-research skill is installed at skills/company-research/", file=sys.stderr)
    sys.exit(1)

# ── TW ticker → Chinese company name mapping ──────────────────────────────────
# Common names that yfinance returns in English. This map lets us search
# in Chinese for much better results on local news sites.
TW_CHINESE_NAMES = {
    "2303.TW": "聯電", "2308.TW": "台達電", "2317.TW": "鴻海",
    "2324.TW": "仁寶", "2330.TW": "台積電", "2337.TW": "旺宏",
    "2344.TW": "華邦電", "2345.TW": "智邦", "2356.TW": "英業達",
    "2357.TW": "華碩", "2376.TW": "技嘉", "2379.TW": "瑞昱",
    "2382.TW": "廣達", "2383.TW": "台光電", "2404.TW": "漢唐",
    "2408.TW": "南亞科", "2409.TW": "友達", "2449.TW": "京元電子",
    "2454.TW": "聯發科", "2542.TW": "興富發", "2603.TW": "長榮海運",
    "2880.TW": "華南金", "2881.TW": "富邦金", "2882.TW": "國泰金",
    "2884.TW": "玉山金", "2887.TW": "台新金", "2890.TW": "永豐金",
    "2891.TW": "中信金", "3008.TW": "大立光", "3017.TW": "奇鋐",
    "3034.TW": "聯詠", "3036.TW": "文曄", "3044.TW": "健鼎",
    "3189.TW": "景碩", "3231.TW": "緯創", "3293.TWO": "鈊象電子",
    "3653.TW": "健策", "3661.TW": "世芯", "3711.TW": "日月光投控",
    "4938.TW": "和碩", "5269.TW": "祥碩", "5274.TWO": "信驊",
    "5871.TW": "中租控股", "6223.TWO": "旺矽", "6239.TW": "力成",
    "6446.TW": "藥華藥", "6669.TW": "緯穎", "6770.TW": "力積電",
    "7769.TW": "長聖", "8299.TWO": "群聯", "1216.TW": "統一",
    "1504.TW": "東元", "1605.TW": "華新", "2059.TW": "川湖",
    "2301.TW": "光寶科", "2912.TW": "統一超",
}


def _is_tw_ticker(ticker: str) -> bool:
    """Check if ticker is a Taiwan market stock."""
    return ticker.upper().endswith(".TW") or ticker.upper().endswith(".TWO")


def _resolve_chinese_name(ticker: str, english_name: str = None) -> str | None:
    """Try to get a Chinese name for a TW ticker."""
    # Check our hardcoded map first
    if ticker in TW_CHINESE_NAMES:
        return TW_CHINESE_NAMES[ticker]
    # If the English name contains CJK characters, it might already be Chinese
    if english_name:
        for ch in english_name:
            if '\u4e00' <= ch <= '\u9fff':
                return english_name
    return None


def _build_queries(ticker: str, name: str = None) -> list[str]:
    """
    Build 2-3 targeted search queries for a ticker.
    Uses Chinese company names for TW stocks and searches news sites
    with a ~2 month window.
    """
    queries = []
    clean_ticker = ticker.replace(".TW", "").replace(".TWO", "")

    if _is_tw_ticker(ticker):
        # Resolve Chinese name for much better search results
        zh_name = _resolve_chinese_name(ticker, name)
        search_term = zh_name or clean_ticker

        # Query 1: recent news from financial/tech sources
        queries.append(
            f'{search_term} 新聞 營收 法說會 site:cnyes.com OR site:technews.tw OR site:ctee.com.tw'
        )
        # Query 2: broader industry/product news
        queries.append(
            f'{search_term} 股票 產業 訂單 展望 近期'
        )
        # Query 3: PTT/social discussion for sentiment
        queries.append(
            f'{search_term} {clean_ticker} site:ptt.cc OR site:dcard.tw'
        )
    else:
        # US/global market: search in English
        search_name = name or ticker
        queries.append(f'"{search_name}" news earnings guidance 2026')
        queries.append(f'"{search_name}" product launch industry analysis recent')

    return queries


def _is_useful_article(article: dict) -> bool:
    """Filter out generic stock quote / portal pages that aren't real news."""
    title = article.get("title", "").lower()
    url = article.get("url", "").lower()
    snippet = article.get("snippet", "").lower()

    # Skip generic stock quote pages
    skip_patterns = [
        "走勢圖", "互動股市圖表", "比較股票", "stock chart",
        "股價、新聞、報價和記錄",  # Yahoo generic
        "股價、報價、新聞及事件",   # Yahoo generic
        "期權鏈", "options chain",
        "簡介|", "/company/profile",
    ]
    combined = title + " " + snippet + " " + url
    for pattern in skip_patterns:
        if pattern in combined:
            return False

    # Skip if title is just a ticker or company name with no actual news
    if len(title) < 15 and not any(kw in title for kw in ["營收", "獲利", "訂單", "法說", "新聞"]):
        return False

    return True


def enrich_tickers(
    tickers: dict[str, str],
    max_articles_per_ticker: int = 5,
    delay_between_searches: float = 2.0,
) -> dict:
    """
    Fetch recent news for a set of tickers.

    Args:
        tickers: dict of {ticker: company_name} (name can be None)
        max_articles_per_ticker: max articles to keep per company
        delay_between_searches: seconds to wait between browser searches

    Returns:
        dict of {ticker: {"name": str, "articles": [...]}}
    """
    results = {}

    for ticker, name in tickers.items():
        zh_name = _resolve_chinese_name(ticker, name) if _is_tw_ticker(ticker) else None
        display_name = zh_name or name or ticker
        print(f"  [News] Searching for {ticker} ({display_name})...", file=sys.stderr)

        articles = []
        seen_urls = set()

        queries = _build_queries(ticker, name)

        for q in queries:
            try:
                search_results = browser_search(q, max_results=5)
                for r in search_results:
                    url = r.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        article = {
                            "title": r.get("title", ""),
                            "url": url,
                            "snippet": r.get("snippet", ""),
                        }
                        # Only keep actual news, not stock quote pages
                        if _is_useful_article(article):
                            articles.append(article)
            except Exception as e:
                print(f"  [News] Search error for '{q}': {e}", file=sys.stderr)

            if delay_between_searches > 0:
                time.sleep(delay_between_searches)

        # Cap articles
        articles = articles[:max_articles_per_ticker]

        results[ticker] = {
            "name": display_name,
            "articles": articles,
        }
        print(f"  [News] {ticker}: found {len(articles)} useful articles", file=sys.stderr)

    return results


def enrich_from_scan_results(
    scan_results: list[dict],
    max_articles_per_ticker: int = 5,
    delay_between_searches: float = 2.0,
) -> dict:
    """
    Convenience wrapper: takes scanner result dicts and enriches them.

    Args:
        scan_results: list of result dicts from scan_market.py (need 'ticker' and optionally 'name')

    Returns:
        Same format as enrich_tickers()
    """
    tickers = {}
    for r in scan_results:
        ticker = r.get("ticker")
        name = r.get("name")
        if ticker:
            tickers[ticker] = name

    return enrich_tickers(tickers, max_articles_per_ticker, delay_between_searches)


def main():
    parser = argparse.ArgumentParser(description="News enrichment for market scanner results")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tickers", type=str,
                       help='JSON dict of {ticker: name}, e.g. \'{"2330.TW": "台積電"}\'')
    group.add_argument("--results-json", type=str,
                       help="Raw JSON string of scan_market.py output")
    group.add_argument("--results-file", type=str,
                       help="Path to a JSON file with scan_market.py output")

    parser.add_argument("--max-articles", type=int, default=5,
                        help="Max articles per ticker (default: 5)")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Delay between browser searches in seconds (default: 2.0)")
    args = parser.parse_args()

    if args.tickers:
        tickers = json.loads(args.tickers)
        result = enrich_tickers(tickers, args.max_articles, args.delay)
    else:
        if args.results_file:
            with open(args.results_file) as f:
                scan_output = json.load(f)
        else:
            scan_output = json.loads(args.results_json)

        scan_results = scan_output.get("results", [])
        result = enrich_from_scan_results(scan_results, args.max_articles, args.delay)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
