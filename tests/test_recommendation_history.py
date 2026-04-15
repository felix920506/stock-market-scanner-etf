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
            "scanner-history.json",
        )

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(history._resolve_history_path(), expected)

    def test_env_var_overrides_default_history_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            configured_path = os.path.join(tmpdir, "history.json")

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

    def test_explicit_history_path_overrides_env_var(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, "env-history.json")
            explicit_path = os.path.join(tmpdir, "explicit-history.json")

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


if __name__ == "__main__":
    unittest.main()
