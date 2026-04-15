---
name: market-scanner
description: Discover stock opportunities by pulling candidates from market screeners and ETF holdings, running TA on them, and posting a ranked report to Discord. Use when the user wants to find stocks to look at (e.g. "scan the market for opportunities", "find new stocks to look at", "what's looking good?", "run the market scanner", "discover new opportunities").
---

# Market Discovery Scanner

Discovers investment opportunities by pulling candidates from live screeners and ETF holdings, running TA on each candidate, and delivering a ranked report to Discord.

## How It Works

```
Screeners (most_actives, growth_tech, day_gainers, undervalued_growth)
  +
ETF Holdings (SMH, SOXX, QQQ, XLK, IGV)
  ↓
Deduplicate → Filter penny stocks
  ↓
Run TA on ~50–80 candidates
  ↓
Score –8 to +8 → Rank → Top N opportunities
  ↓
Post report to Discord
```

## Prerequisites

- Discord webhook URL in `TOOLS.md` under `Market Research`
- Dependencies: `pip install yfinance pandas ta`

## Running the Scanner

Deterministic scheduled/manual run with verified webhook delivery:

```bash
python3 /home/user/.openclaw/workspace/skills/market-scanner/scripts/run_market_scanner_deterministic.py
```

Raw scanner only (JSON output, no delivery):

```bash
python3 /home/user/.openclaw/workspace/skills/market-scanner/scripts/scan_market.py \
  --top 10 \
  --min-score 3 \
  --min-market-cap 1000000000 \
  --enrich-news
```

**Key arguments:**

| Argument | Default | Description |
|---|---|---|
| `--top` | 10 | How many top picks to show in the report |
| `--min-score` | 2 | Minimum TA score to include |
| `--min-market-cap` | 1B | Filter out micro/penny stocks (in USD) |
| `--max-candidates` | 80 | Cap on total tickers to analyze |
| `--period` | `6mo` | yfinance data period |
| `--interval` | `1d` | Bar interval |
| `--enrich-news` | off | Run browser news searches on top picks for recent context |
| `--no-enrich-news` | — | Explicitly disable news enrichment |
| `--max-news-articles` | 5 | Max news articles to collect per ticker |


**If missing deps:**
```bash
pip install yfinance pandas ta --break-system-packages
```

## Candidate Sources (Taiwan Market)

No yfinance built-in screeners exist for TWSE/OTC, so candidates come entirely from TW ETF top holdings:

| ETF | Name | Focus |
|---|---|---|
| `0050.TW` | 元大台灣50 | Large-cap broad market |
| `0056.TW` | 元大高股息 | High dividend, different mix |
| `00881.TW` | 國泰台灣5G+ | Tech/telecom/semi |
| `00891.TW` | 中信關鍵半導體 | Semiconductor supply chain |
| `00904.TW` | 新光台灣半導體30 | Semiconductor 30 |
| `00929.TW` | 復華台灣科技優息 | Tech + yield |
| `00912.TW` | 中信台灣智慧50 | AI/smart tech |
| `00733.TW` | 富邦台灣中小 | Mid/small cap discovery |
| `006208.TW` | 富邦台灣50 | Alternative large-cap |
| `00900.TW` | 富邦特選高股息30 | Value/dividend names |

Only `.TW` and `.TWO` tickers pass the filter. All candidates are deduplicated before analysis.

## Scoring

See `references/scoring.md` for full signal table.

Score –8 to +8 (plus up to +2 bonus):
- +1 each: Price > EMA200, golden cross, MACD bullish, MACD hist positive, RSI 40–70, Stoch K > D, BB% 0.2–0.8, OBV rising
- Bonus: oversold bounce setup, volume surge conviction

Labels: `STRONG BUY` (≥6) · `BUY` (3–5) · `HOLD` (–1 to 2) · `SELL` (–4 to –2) · `STRONG SELL` (≤–5)

## Interpreting Results

The JSON output has:
- `results[]` — top opportunities sorted by score, filtered to `min_score`
- `all_results_summary[]` — every analyzed ticker with score + label (for reference)
- `candidates_analyzed` — how many tickers were fully analyzed

Focus on:
- **Tier 1 (score ≥ 5):** Strong buy signals — headline the report
- **Tier 2 (score 3–4):** Worth watching — include with full details
- Lower scores: omit unless there's a specific reason to mention

## Building the Discord Report

Format in **繁體中文 (zh-TW)**, plain text (no markdown tables).

```
📡 市場新機會掃描報告
{scan_date} · 分析 {candidates_analyzed} 檔候選股票

━━━━━━━━━━━━━━━━━━━━━━
🏆 強力機會
━━━━━━━━━━━━━━━━━━━━━━

[For each Tier 1 (score ≥ 5):]
🟢 {TICKER} {name} [{label}] 分數: {score}/8  ·  來源: {source}
現價: ${price}  ({change_1d_pct:+.1f}%)
RSI: {rsi14:.0f} | Stoch K{stoch_k:.0f}/D{stoch_d:.0f} | 成交量: {vol_ratio}×均量
✅ {top 2 bullish signals}
支撐: {S1}  阻力: {R1}
📰 {1-2 line news summary if --enrich-news was used}

━━━━━━━━━━━━━━━━━━━━━━
👀 值得關注
━━━━━━━━━━━━━━━━━━━━━━

[For each Tier 2 (score 3–4), condensed:]
🟡 {TICKER} {name} [{label}] 分數: {score}/8  ·  {price} ({change_1d_pct:+.1f}%)  RSI {rsi14:.0f}
{1-line TA summary}

━━━━━━━━━━━━━━━━━━━━━━
*本報告僅供參考，非投資建議。來源：市場篩選器 + ETF 持倉。*
```

- Icon by score: ≥5 = 🟢, 3–4 = 🟡, ≤2 = 🔴
- Keep total message **under 2000 characters**. Trim Tier 2 list if needed.
- Mention the source (screener name or ETF) so the user knows where the pick came from

## Posting to Discord

For scheduled or production runs, use the deterministic runner. It:
- runs the scanner
- builds the final plain-text report
- writes stage artifacts under `/tmp`
- can reuse an existing temp run directory to skip completed stages
- automatically splits reports into multiple Discord messages when they exceed the 2000-character limit
- sends the report through `skills/discord-webhook/scripts/send_webhook.sh`
- fails loudly if webhook delivery is not confirmed

Stage artifacts are written like:
- `00-meta.json`
- `01-scan-output.json`
- `01-scan-stderr.log`
- `02-report.txt`
- `03-webhook-stdout.log`
- `03-webhook-stderr.log`

Re-delivery without rerunning the scan is supported:

```bash
python3 /home/user/.openclaw/workspace/skills/market-scanner/scripts/resend_market_scanner_report.py /tmp/market-scanner-xxxxxx
```

```bash
python3 /home/user/.openclaw/workspace/skills/market-scanner/scripts/run_market_scanner_deterministic.py
```

Use raw `scan_market.py` only when you explicitly want JSON output without delivery.

## News Enrichment

When `--enrich-news` is passed, the scanner runs browser-based news searches on top picks after TA scoring. This uses the `company-research` skill's browser tools to Google recent news for each recommended stock.

**What it does:**
1. For each top result, builds 2 targeted search queries (financial news + industry news)
2. Searches via headed browser (avoids rate-limiting that hits programmatic search)
3. Collects article titles, URLs, and snippets
4. Attaches them as `recent_news` array on each result dict

**Requirements:**
- The `company-research` skill must be installed at `skills/company-research/`
- A headed browser must be available (`openclaw browser` commands)
- Adds ~2-4 minutes to scan time depending on number of top picks

**TW stocks** get Chinese-language queries; **US/global stocks** get English queries.

**News summarization:**
- After collecting articles, each ticker's news is summarized into a 1-2 line blurb by the dedicated **`summarizer` OpenClaw agent** (Gemini 3 Flash)
- The summary is stored as `news_summary` on each result dict — ready to use in the Discord report
- All LLM calls go through `openclaw agent --agent summarizer` — no direct API access
- To change the model, update the summarizer agent: `openclaw config set agents.list[1].model <new-model>`
- Summaries are in zh-TW by default, matching the report language

**Using news in reports:**
- After the TA signals, add the `news_summary` as a "📰" line
- If `news_summary` is empty, omit the news line for that stock
- This is context, not a full research report — keep it brief

**Standalone usage:**
```bash
python3 skills/market-scanner/scripts/news_enrichment.py \
  --tickers '{"2330.TW": "台積電", "2317.TW": "鴻海"}'
```

## Recommendation History

The scanner automatically tracks every stock it recommends across runs.

**Storage:** `./data/scanner-history.sqlite3` by default. Override with `MARKET_SCANNER_HISTORY_PATH` or `--history-path`.

Each scan:
1. **Annotates** top results with prior history before output (adds `previously_recommended`, `times_recommended`, `first_seen`, `last_seen`, `score_trend`)
2. **Records** all qualifying results (≥ min-score) into the history database
3. Deduplicates by date — re-running the same day won't create duplicate entries

**CLI flags:**

| Argument | Default | Description |
|---|---|---|
| `--history-path` | `data/scanner-history.sqlite3` | Custom path for the SQLite history database; overrides `MARKET_SCANNER_HISTORY_PATH` |
| `--no-history` | false | Skip history tracking entirely for this run |

**Programmatic API** (from `recommendation_history.py`):

```python
from recommendation_history import (
    record_recommendations,  # save a batch of results
    annotate_results,        # add history fields to result dicts
    lookup,                  # single ticker history lookup
    get_repeat_tickers,      # tickers recommended N+ times
)
```

**Using history in reports:**
- If a stock has `previously_recommended: true`, mention it in the Discord report (e.g. "已連續推薦 3 次" or "分數趨勢: 4→5→6")
- Use `score_trend` to show whether momentum is building or fading
- `get_repeat_tickers(min_times=3)` finds persistent signals worth deeper analysis

## Scheduling (Daily Discovery)

```bash
openclaw cron add "30 8 * * 1-5" "Run the deterministic Taiwan market scanner workflow and post the verified report to Discord using the webhook configured in TOOLS.md. Use the market-scanner skill and its deterministic runner script."
```

## Invocation Examples

- "scan the market for opportunities" → full run, top 10, min score 3
- "find new stocks to watch" → same
- "scan for tech opportunities" → hint to prioritize growth_technology and ETF sources
- "quick scan, top 5 strong buys only" → `--top 5 --min-score 5`
- "scan with tighter filter" → `--min-score 4 --min-market-cap 5000000000`

## Timing Notes

- Full scan (~80 candidates) takes 2–4 minutes
- Screener data is real-time market hours; outside hours uses last close
- Weekends use Friday's closing data
