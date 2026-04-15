import sys
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault("yfinance", types.SimpleNamespace(Ticker=None))
sys.modules.setdefault("pandas", types.SimpleNamespace(Timestamp=None))

import scan_market


class MarketSelectionTest(unittest.TestCase):
    def test_default_market_is_first_configured_market(self):
        config = {
            "markets": {
                "US": {"name": "United States", "etfs": []},
                "TW": {"name": "Taiwan", "etfs": []},
            }
        }

        with patch.object(scan_market, "ETF_SOURCES_CONFIG", config):
            self.assertEqual(scan_market.get_default_market(), "US")

    def test_get_market_config_rejects_unknown_market(self):
        config = {"markets": {"TW": {"name": "Taiwan", "etfs": []}}}

        with patch.object(scan_market, "ETF_SOURCES_CONFIG", config):
            with self.assertRaisesRegex(ValueError, "Unknown market 'US'"):
                scan_market.get_market_config("US")

    def test_ticker_allowed_for_market_uses_optional_suffixes(self):
        market = {"ticker_suffixes": [".TW", ".TWO"]}

        self.assertTrue(scan_market._ticker_allowed_for_market("2330.TW", market))
        self.assertTrue(scan_market._ticker_allowed_for_market("8069.TWO", market))
        self.assertFalse(scan_market._ticker_allowed_for_market("AAPL", market))
        self.assertFalse(scan_market._ticker_allowed_for_market("^TWII", market))

    def test_ticker_allowed_for_market_allows_any_plain_symbol_without_suffixes(self):
        self.assertTrue(scan_market._ticker_allowed_for_market("AAPL", {}))
        self.assertFalse(scan_market._ticker_allowed_for_market("USDTWD=X", {}))


if __name__ == "__main__":
    unittest.main()
