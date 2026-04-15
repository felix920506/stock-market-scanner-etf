#!/usr/bin/env python3
"""
Recommendation History Tracker for Market Scanner.

Tracks which stocks have been recommended previously, when, how often,
and with what scores. Provides lookup and annotation utilities so the
scanner can flag repeat recommendations and show score trends.

Storage: a single JSON file.
Default: ./data/scanner-history.json, relative to this project.
Override with MARKET_SCANNER_HISTORY_PATH or the CLI --history-path flag.

Schema:
{
  "version": 1,
  "tickers": {
    "2330.TW": {
      "name": "台積電",
      "recommendations": [
        {
          "date": "2026-04-06",
          "score": 6,
          "label": "STRONG BUY",
          "source": "ETF:0050.TW"
        },
        ...
      ]
    },
    ...
  }
}
"""

import json
import os
from datetime import datetime
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_HISTORY_ENV_VAR = "MARKET_SCANNER_HISTORY_PATH"
DEFAULT_HISTORY_PATH = os.path.join(PROJECT_ROOT, "data", "scanner-history.json")

CURRENT_VERSION = 1


def _resolve_history_path(path: Optional[str] = None) -> str:
    """Return the configured history file path."""
    return path or os.environ.get(DEFAULT_HISTORY_ENV_VAR) or DEFAULT_HISTORY_PATH


def _load(path: Optional[str] = None) -> dict:
    """Load history from disk, creating a fresh structure if absent or empty."""
    path = _resolve_history_path(path)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "r") as f:
            data = json.load(f)
        # Future-proof: migrate if version changes
        if data.get("version", 0) < CURRENT_VERSION:
            data["version"] = CURRENT_VERSION
        return data
    return {"version": CURRENT_VERSION, "tickers": {}}


def _save(data: dict, path: Optional[str] = None) -> None:
    """Atomically write history to disk."""
    path = _resolve_history_path(path)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def record_recommendations(
    results: list[dict],
    scan_date: str,
    history_path: Optional[str] = None,
) -> dict:
    """
    Record a batch of scan results into history.

    Args:
        results: list of result dicts from scan_market.py (must have ticker, score, label, source)
        scan_date: ISO date string e.g. "2026-04-06"
        history_path: path to the JSON history file

    Returns:
        The updated history dict.
    """
    data = _load(history_path)

    for r in results:
        ticker = r["ticker"]
        entry = {
            "date": scan_date,
            "score": r["score"],
            "label": r["label"],
            "source": r.get("source", "unknown"),
        }

        if ticker not in data["tickers"]:
            data["tickers"][ticker] = {
                "name": r.get("name"),
                "recommendations": [],
            }
        elif r.get("name") and not data["tickers"][ticker].get("name"):
            # backfill name if we didn't have it before
            data["tickers"][ticker]["name"] = r.get("name")

        # Avoid duplicate entries for the same date (idempotent re-runs)
        existing_dates = {rec["date"] for rec in data["tickers"][ticker]["recommendations"]}
        if scan_date not in existing_dates:
            data["tickers"][ticker]["recommendations"].append(entry)

    _save(data, history_path)
    return data


def lookup(
    ticker: str,
    history_path: Optional[str] = None,
) -> Optional[dict]:
    """
    Look up a single ticker's recommendation history.

    Returns None if never recommended, otherwise:
    {
        "name": "台積電",
        "times_recommended": 5,
        "first_seen": "2026-01-15",
        "last_seen": "2026-04-01",
        "last_score": 6,
        "last_label": "STRONG BUY",
        "score_trend": [4, 5, 6, 5, 6],
        "recommendations": [...]
    }
    """
    data = _load(history_path)
    if ticker not in data["tickers"]:
        return None

    info = data["tickers"][ticker]
    recs = sorted(info["recommendations"], key=lambda r: r["date"])

    if not recs:
        return None

    return {
        "name": info.get("name"),
        "times_recommended": len(recs),
        "first_seen": recs[0]["date"],
        "last_seen": recs[-1]["date"],
        "last_score": recs[-1]["score"],
        "last_label": recs[-1]["label"],
        "score_trend": [r["score"] for r in recs],
        "recommendations": recs,
    }


def annotate_results(
    results: list[dict],
    history_path: Optional[str] = None,
) -> list[dict]:
    """
    Annotate a list of scan results with history info.

    Adds to each result dict:
        - "previously_recommended": bool
        - "times_recommended": int (including this run, if already recorded)
        - "first_seen": date str or None
        - "last_seen": date str or None (prior to this run)
        - "score_trend": list of prior scores
    """
    data = _load(history_path)

    for r in results:
        ticker = r["ticker"]
        if ticker in data["tickers"]:
            recs = sorted(data["tickers"][ticker]["recommendations"], key=lambda x: x["date"])
            r["previously_recommended"] = True
            r["times_recommended"] = len(recs)
            r["first_seen"] = recs[0]["date"] if recs else None
            r["last_seen"] = recs[-1]["date"] if recs else None
            r["score_trend"] = [rec["score"] for rec in recs]
        else:
            r["previously_recommended"] = False
            r["times_recommended"] = 0
            r["first_seen"] = None
            r["last_seen"] = None
            r["score_trend"] = []

    return results


def get_all_history(
    history_path: Optional[str] = None,
) -> dict:
    """Return the full history dict."""
    return _load(history_path)


def get_repeat_tickers(
    min_times: int = 2,
    history_path: Optional[str] = None,
) -> list[dict]:
    """
    Get tickers that have been recommended at least `min_times` times.
    Returns a list sorted by recommendation count descending.
    """
    data = _load(history_path)
    repeats = []

    for ticker, info in data["tickers"].items():
        recs = info["recommendations"]
        if len(recs) >= min_times:
            sorted_recs = sorted(recs, key=lambda r: r["date"])
            repeats.append({
                "ticker": ticker,
                "name": info.get("name"),
                "times_recommended": len(recs),
                "first_seen": sorted_recs[0]["date"],
                "last_seen": sorted_recs[-1]["date"],
                "last_score": sorted_recs[-1]["score"],
                "score_trend": [r["score"] for r in sorted_recs],
            })

    repeats.sort(key=lambda x: x["times_recommended"], reverse=True)
    return repeats


def prune_old(
    days: int = 180,
    history_path: Optional[str] = None,
) -> int:
    """
    Remove recommendation entries older than `days` days.
    Removes ticker keys entirely if they have no remaining entries.
    Returns the number of entries pruned.
    """
    data = _load(history_path)
    cutoff = datetime.now().strftime("%Y-%m-%d")
    from datetime import timedelta
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    pruned = 0
    empty_tickers = []

    for ticker, info in data["tickers"].items():
        before = len(info["recommendations"])
        info["recommendations"] = [r for r in info["recommendations"] if r["date"] >= cutoff_date]
        pruned += before - len(info["recommendations"])
        if not info["recommendations"]:
            empty_tickers.append(ticker)

    for t in empty_tickers:
        del data["tickers"][t]

    if pruned > 0:
        _save(data, history_path)

    return pruned
