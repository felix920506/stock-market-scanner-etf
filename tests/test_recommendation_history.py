import os
import tempfile
import unittest
from unittest.mock import patch

import recommendation_history as history


class RecommendationHistoryStorageTest(unittest.TestCase):
    def test_default_history_path_is_project_local(self):
        expected = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
            "scanner-history.sqlite3",
        )

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(history._resolve_history_path(), expected)

    def test_env_var_overrides_default_history_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            configured_path = os.path.join(tmpdir, "history.sqlite3")

            with patch.dict(os.environ, {history.DEFAULT_HISTORY_ENV_VAR: configured_path}):
                history.record_recommendations(
                    [
                        {
                            "ticker": "2330.TW",
                            "name": "台積電",
                            "score": 6,
                            "label": "STRONG BUY",
                            "source": "ETF:0050.TW",
                        }
                    ],
                    "2026-04-15",
                )

            self.assertTrue(os.path.isfile(configured_path))
            self.assertEqual(
                history.lookup("2330.TW", history_path=configured_path),
                {
                    "name": "台積電",
                    "times_recommended": 1,
                    "first_seen": "2026-04-15",
                    "last_seen": "2026-04-15",
                    "last_score": 6,
                    "last_label": "STRONG BUY",
                    "score_trend": [6],
                    "recommendations": [
                        {
                            "date": "2026-04-15",
                            "score": 6,
                            "label": "STRONG BUY",
                            "source": "ETF:0050.TW",
                        }
                    ],
                },
            )

    def test_explicit_history_path_overrides_env_var(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, "env-history.sqlite3")
            explicit_path = os.path.join(tmpdir, "explicit-history.sqlite3")

            with patch.dict(os.environ, {history.DEFAULT_HISTORY_ENV_VAR: env_path}):
                history.record_recommendations(
                    [
                        {
                            "ticker": "2317.TW",
                            "score": 4,
                            "label": "BUY",
                            "source": "ETF:0056.TW",
                        }
                    ],
                    "2026-04-15",
                    history_path=explicit_path,
                )

            self.assertTrue(os.path.isfile(explicit_path))
            self.assertFalse(os.path.exists(env_path))

    def test_record_recommendations_is_idempotent_by_ticker_and_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_path = os.path.join(tmpdir, "history.sqlite3")
            result = {
                "ticker": "2330.TW",
                "name": "台積電",
                "score": 6,
                "label": "STRONG BUY",
                "source": "ETF:0050.TW",
            }

            history.record_recommendations([result], "2026-04-15", history_path=history_path)
            history.record_recommendations([result], "2026-04-15", history_path=history_path)
            history.record_recommendations([{**result, "score": 7}], "2026-04-16", history_path=history_path)

            self.assertEqual(history.lookup("2330.TW", history_path=history_path)["score_trend"], [6, 7])

    def test_annotate_results_and_repeat_tickers_use_sqlite_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_path = os.path.join(tmpdir, "history.sqlite3")
            history.record_recommendations(
                [
                    {
                        "ticker": "2330.TW",
                        "name": "台積電",
                        "score": 6,
                        "label": "STRONG BUY",
                        "source": "ETF:0050.TW",
                    },
                    {
                        "ticker": "2317.TW",
                        "name": "鴻海",
                        "score": 4,
                        "label": "BUY",
                        "source": "ETF:0056.TW",
                    },
                ],
                "2026-04-15",
                history_path=history_path,
            )
            history.record_recommendations(
                [
                    {
                        "ticker": "2330.TW",
                        "name": "台積電",
                        "score": 7,
                        "label": "STRONG BUY",
                        "source": "ETF:006208.TW",
                    }
                ],
                "2026-04-16",
                history_path=history_path,
            )

            results = history.annotate_results(
                [{"ticker": "2330.TW"}, {"ticker": "2454.TW"}],
                history_path=history_path,
            )

            self.assertEqual(results[0]["times_recommended"], 2)
            self.assertEqual(results[0]["score_trend"], [6, 7])
            self.assertFalse(results[1]["previously_recommended"])
            self.assertEqual(
                history.get_repeat_tickers(min_times=2, history_path=history_path),
                [
                    {
                        "ticker": "2330.TW",
                        "name": "台積電",
                        "times_recommended": 2,
                        "first_seen": "2026-04-15",
                        "last_seen": "2026-04-16",
                        "last_score": 7,
                        "score_trend": [6, 7],
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
