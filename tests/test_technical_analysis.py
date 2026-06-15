import unittest
from unittest.mock import patch

import pandas as pd

import technical_analysis


class LocalTechnicalAnalysisTest(unittest.TestCase):
    def test_score_signals_strong_buy_with_volume_bonus(self):
        score, label, signals = technical_analysis._score_signals(
            {
                "price_now": 110,
                "ema50": 105,
                "ema200": 100,
                "macd": 2.0,
                "macd_signal": 1.5,
                "macd_hist": 0.5,
                "rsi14": 55,
                "stoch_k": 70,
                "stoch_d": 50,
                "bb_pct": 0.5,
                "obv_rising": True,
                "volume_ratio": 2.0,
            }
        )

        self.assertEqual(score, 9)
        self.assertEqual(label, "STRONG BUY")
        self.assertIn("Volume surge with positive MACD", signals["bullish"])
        self.assertEqual(signals["bearish"], [])

    def test_score_signals_strong_sell(self):
        score, label, signals = technical_analysis._score_signals(
            {
                "price_now": 90,
                "ema50": 95,
                "ema200": 100,
                "macd": -1.0,
                "macd_signal": 0.0,
                "macd_hist": -0.5,
                "rsi14": 80,
                "stoch_k": 30,
                "stoch_d": 60,
                "bb_pct": 0.95,
                "obv_rising": False,
                "volume_ratio": 1.0,
            }
        )

        self.assertEqual(score, -8)
        self.assertEqual(label, "STRONG SELL")
        self.assertEqual(len(signals["bearish"]), 8)

    def test_score_signals_treats_missing_indicators_as_neutral(self):
        score, label, signals = technical_analysis._score_signals({})

        self.assertEqual(score, 0)
        self.assertEqual(label, "HOLD")
        self.assertEqual(len(signals["neutral"]), 8)

    def test_analyze_computes_local_result_shape(self):
        index = pd.date_range("2025-01-01", periods=240, freq="D")
        close = pd.Series([100 + i * 0.2 for i in range(240)], index=index)
        history = pd.DataFrame(
            {
                "Open": close - 0.1,
                "High": close + 1.0,
                "Low": close - 1.0,
                "Close": close,
                "Volume": [1_000_000 + i * 1_000 for i in range(240)],
            },
            index=index,
        )

        class FakeTicker:
            fast_info = {"market_cap": 123456789}

            def history(self, period, interval):
                self.period = period
                self.interval = interval
                return history

        with patch.object(technical_analysis.yf, "Ticker", return_value=FakeTicker()):
            result = technical_analysis.analyze("demo", period="1y", interval="1d")

        self.assertNotIn("error", result)
        self.assertEqual(result["ticker"], "DEMO")
        self.assertEqual(result["bars"], 240)
        self.assertEqual(result["market_cap"], 123456789)
        self.assertIn(result["label"], {"STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"})
        self.assertIn("current", result["price"])
        self.assertIn("macd_hist", result["trend"])
        self.assertIn("rsi14", result["momentum"])
        self.assertIn("ratio", result["volume"])
        self.assertIn("S1", result["levels"])


if __name__ == "__main__":
    unittest.main()
