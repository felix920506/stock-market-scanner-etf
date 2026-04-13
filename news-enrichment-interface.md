# News Enrichment — External Program Interface

The news search + LLM summarization features are candidates to be extracted into a
separate standalone program. This documents the data contract.

## Input

A list of stock picks, one object per ticker:

```json
[
  {"ticker": "2330.TW", "name": "台積電"},
  {"ticker": "2454.TW", "name": "聯發科"}
]
```

Only two fields are needed:

| Field    | Type   | Notes                                              |
|----------|--------|----------------------------------------------------|
| `ticker` | string | yfinance-style symbol (e.g. `2330.TW`, `2317.TW`) |
| `name`   | string | Company name — used for Chinese name lookup and LLM prompt |

Source: STRONG BUY picks from `scan_market.py` (score ≥ 6), fields `ticker` and `name`.

## Output

A dict keyed by ticker:

```json
{
  "2330.TW": {"news_summary": "台積電Q2法說會上調毛利率指引，AI需求強勁。"},
  "2454.TW": {"news_summary": "聯發科發布天璣9400晶片，市占率持續攀升。"}
}
```

| Field          | Type   | Notes                                                       |
|----------------|--------|-------------------------------------------------------------|
| `news_summary` | string | 1–2 line blurb in zh-TW; empty string if no meaningful news |

`recent_news` (the intermediate article list) is an internal detail of the external
program and does not need to cross the boundary.

## What the external program does internally

1. **Search** — for each ticker, run browser/web searches to collect article titles,
   URLs, and snippets (currently via OpenClaw `browser_search`)
2. **Filter** — drop generic stock-quote pages, keep actual news articles
3. **Summarize** — call an LLM with the articles and get a 1–2 line zh-TW blurb
   (currently via OpenClaw `summarizer` agent → Gemini 3 Flash)

## How `scan_market.py` consumes the output

```python
# After receiving {ticker: {"news_summary": "..."}} from external program:
for r in enriched_picks:
    r["news_summary"] = result.get(r["ticker"], {}).get("news_summary", "")
```

The `news_summary` string is rendered in the Discord report as:
```
📰 <news_summary>
```
