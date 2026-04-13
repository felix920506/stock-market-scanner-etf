# market-scanner

Scans the Taiwan stock market for technical analysis opportunities and posts a ranked report to a Discord channel.

Candidates are sourced from the holdings of 10 Taiwan ETFs covering large-cap, semiconductor, tech, mid/small-cap, and high-dividend names. Each candidate is scored by [stock-ta](../stock-ta) across 8 TA signals and ranked. The top picks are formatted into a report and delivered via Discord webhook.

## Requirements

- Python 3.12+
- A running [stock-ta](../stock-ta) server or CLI installation
- A Discord webhook URL

```bash
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

```env
# stock-ta backend — HTTP server or path to CLI script/binary
STOCK_TA=http://localhost:8000
# STOCK_TA=/path/to/stock-ta/analyze_stock.py
# STOCK_TA=/usr/local/bin/stock-ta

# Discord webhook URL
# To post into a thread, append ?thread_id=<id>
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
```

### stock-ta backend

`STOCK_TA` is auto-detected from the value:

| Value | Mode |
|---|---|
| `http://...` or `https://...` | HTTP server |
| Path ending in `.py` | Python script (run with current interpreter) |
| Any other path | Installed binary / entry-point |

To start the stock-ta HTTP server:

```bash
cd ../stock-ta
python server.py --port 8000
```

## Usage

### Post report to Discord

```bash
python3 main.py
```

### Print scan output as JSON (no Discord)

```bash
python3 main.py --json
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--top N` | 10 | Number of top picks in the report |
| `--min-score N` | 3 | Minimum TA score to include |
| `--max-candidates N` | 80 | Max tickers to analyse |
| `--min-market-cap N` | 10B TWD | Minimum market cap filter |
| `--period` | `6mo` | yfinance data period (`1mo` `3mo` `6mo` `1y` `2y`) |
| `--interval` | `1d` | Bar interval (`1d` `1wk` `1mo`) |
| `--watchlist PATH` | `market-watchlist.md` | Tickers to exclude from results |
| `--no-exclude-watchlist` | off | Include watchlist tickers instead of excluding them |
| `--no-history` | off | Disable recommendation history tracking |
| `--history-path PATH` | `~/.openclaw/workspace/data/scanner-history.json` | Custom history file path |
| `--enrich-news` | off | Fetch news summaries for STRONG BUY picks (not yet implemented) |
| `--json` | off | Print JSON to stdout and exit without posting to Discord |
| `--keep-temp` | off | Keep run artifact directory after success |
| `--reuse-temp-dir PATH` | — | Resume from an existing artifact directory, skipping completed stages |
| `--delivery-only` | off | Skip scan and re-post an already-generated report |
| `--temp-root PATH` | `/tmp` | Parent directory for run artifacts |

## Scoring

Each ticker is scored from -8 to +8 across 8 signals, plus up to +2 bonus:

| Signal | Bullish | Bearish |
|---|---|---|
| Price vs EMA200 | Above | Below |
| Golden/death cross | EMA50 > EMA200 | EMA50 < EMA200 |
| MACD vs signal | Above | Below |
| MACD histogram | Positive | Negative |
| RSI(14) | 40–70 | Outside range |
| Stochastic K vs D | K > D | K < D |
| Bollinger Band % | 0.2–0.8 | Outside range |
| OBV | Rising | Falling |

Bonus: +1 for oversold bounce (RSI < 35 and price > EMA50), +1 for volume surge (ratio > 1.5× with positive MACD).

| Label | Score |
|---|---|
| STRONG BUY | ≥ 6 |
| BUY | 3 – 5 |
| HOLD | -1 – 2 |
| SELL | -4 – -2 |
| STRONG SELL | ≤ -5 |

## Candidate sources

Holdings from 10 Taiwan ETFs, deduplicated and filtered to `.TW` / `.TWO` tickers only:

| ETF | Focus |
|---|---|
| 0050.TW | Large-cap top 50 |
| 0056.TW | High dividend |
| 00881.TW | 5G / tech / telecom |
| 00891.TW | Semiconductor supply chain |
| 00904.TW | Semiconductor 30 |
| 00929.TW | Tech + yield |
| 00912.TW | AI / smart tech |
| 00733.TW | Mid / small cap |
| 006208.TW | Large-cap (alternate) |
| 00900.TW | Value / dividend |

## Files

| File | Purpose |
|---|---|
| `main.py` | Entry point — CLI, Discord delivery, artifact staging |
| `scan_market.py` | Core scan logic (`scan()` function) |
| `recommendation_history.py` | Tracks prior recommendations to flag repeats |
| `scoring.md` | Detailed scoring methodology reference |
| `news-enrichment-interface.md` | Interface spec for the planned news enrichment service |
