# Scoring Reference

## Composite Score (–8 to +8, +2 bonus possible)

Each signal contributes ±1 to the score:

| Signal            | +1 (Bullish)                        | –1 (Bearish)                         |
|-------------------|-------------------------------------|--------------------------------------|
| price_vs_ema200   | Price above EMA200                  | Price below EMA200                   |
| golden_cross      | EMA50 > EMA200                      | EMA50 < EMA200 (death cross)         |
| macd_bullish      | MACD line above signal              | MACD line below signal               |
| macd_hist         | Positive (momentum building)        | Negative (momentum fading)           |
| RSI14             | 40–70 (healthy zone)                | >70 (overbought) or <40 (oversold)   |
| stoch K vs D      | K > D (bullish crossover)           | K < D (bearish crossover)            |
| bb_pct_band       | 0.2–0.8 (healthy range)             | >1.0 (above upper) or <0 (below lower) |
| obv_trend         | Rising (volume confirms)            | Falling (volume diverges)            |

### Bonus signals (+1 each, not capped)
- **Oversold bounce setup**: RSI < 35 AND price still above EMA50 → contrarian long opportunity
- **Volume conviction**: vol_ratio > 1.5× AND MACD hist positive → strong breakout signal

## Label Mapping

| Score    | Label        |
|----------|--------------|
| ≥ 6      | STRONG BUY   |
| 3 to 5   | BUY          |
| –1 to 2  | HOLD         |
| –4 to –2 | SELL         |
| ≤ –5     | STRONG SELL  |

## Opportunity Tiers (for report formatting)

- **Tier 1 (Strong opportunities):** score ≥ 5 → lead the report, highlight in green
- **Tier 2 (Watch closely):** score 3–4 → include with full details
- **Tier 3 (Neutral/weak):** score ≤ 2 → summarize briefly or omit from top section

## Notes

- A score of 0 can still be interesting if specific signals (e.g. oversold + golden cross) are present
- Volume ratio > 2× on a bullish setup greatly increases conviction
- RSI < 35 with price above EMA50 = classic "dip within an uptrend" setup
- Avoid tickers with <100 bars of data; EMA200 will be unreliable
