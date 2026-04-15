#!/usr/bin/env python3
"""
Recommendation History Tracker for Market Scanner.

Tracks which stocks have been recommended previously, when, how often,
and with what scores. Provides lookup and annotation utilities so the
scanner can flag repeat recommendations and show score trends.

Storage: a SQLite database.
Default: ./data/scanner-history.sqlite3, relative to this project.
Override with MARKET_SCANNER_HISTORY_PATH or the CLI --history-path flag.
"""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_HISTORY_ENV_VAR = "MARKET_SCANNER_HISTORY_PATH"
DEFAULT_HISTORY_PATH = os.path.join(PROJECT_ROOT, "data", "scanner-history.sqlite3")

CURRENT_SCHEMA_VERSION = 1


def _resolve_history_path(path: Optional[str] = None) -> str:
    """Return the configured SQLite database path."""
    return path or os.environ.get(DEFAULT_HISTORY_ENV_VAR) or DEFAULT_HISTORY_PATH


def _connect(path: Optional[str] = None) -> sqlite3.Connection:
    """Open the history database and ensure the schema exists."""
    resolved_path = _resolve_history_path(path)
    directory = os.path.dirname(resolved_path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    conn = sqlite3.connect(resolved_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _init_schema(conn)
    return conn


@contextmanager
def _open_history(path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    conn = _connect(path)
    try:
        yield conn
    finally:
        conn.close()


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tickers (
            ticker TEXT PRIMARY KEY,
            name TEXT
        );

        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            scan_date TEXT NOT NULL,
            score INTEGER NOT NULL,
            label TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (ticker) REFERENCES tickers(ticker),
            UNIQUE (ticker, scan_date)
        );

        CREATE INDEX IF NOT EXISTS idx_recommendations_ticker_date
        ON recommendations (ticker, scan_date);

        CREATE INDEX IF NOT EXISTS idx_recommendations_scan_date
        ON recommendations (scan_date);
        """
    )
    conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
    conn.commit()


def _row_to_recommendation(row: sqlite3.Row) -> dict:
    return {
        "date": row["scan_date"],
        "score": row["score"],
        "label": row["label"],
        "source": row["source"],
    }


def _lookup_with_connection(conn: sqlite3.Connection, ticker: str) -> Optional[dict]:
    ticker_row = conn.execute(
        "SELECT ticker, name FROM tickers WHERE ticker = ?",
        (ticker,),
    ).fetchone()
    if ticker_row is None:
        return None

    rows = conn.execute(
        """
        SELECT scan_date, score, label, source
        FROM recommendations
        WHERE ticker = ?
        ORDER BY scan_date
        """,
        (ticker,),
    ).fetchall()
    if not rows:
        return None

    recs = [_row_to_recommendation(row) for row in rows]
    return {
        "name": ticker_row["name"],
        "times_recommended": len(recs),
        "first_seen": recs[0]["date"],
        "last_seen": recs[-1]["date"],
        "last_score": recs[-1]["score"],
        "last_label": recs[-1]["label"],
        "score_trend": [rec["score"] for rec in recs],
        "recommendations": recs,
    }


def record_recommendations(
    results: list[dict],
    scan_date: str,
    history_path: Optional[str] = None,
) -> dict:
    """
    Record a batch of scan results into history.

    Duplicate ticker/date entries are ignored so same-day re-runs are idempotent.
    Returns the full history dict for compatibility with the prior JSON backend.
    """
    with _open_history(history_path) as conn:
        for r in results:
            ticker = r["ticker"]
            name = r.get("name")

            conn.execute(
                """
                INSERT INTO tickers (ticker, name)
                VALUES (?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    name = COALESCE(tickers.name, excluded.name)
                """,
                (ticker, name),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO recommendations (
                    ticker, scan_date, score, label, source
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    ticker,
                    scan_date,
                    r["score"],
                    r["label"],
                    r.get("source", "unknown"),
                ),
            )

        conn.commit()

    return get_all_history(history_path)


def lookup(
    ticker: str,
    history_path: Optional[str] = None,
) -> Optional[dict]:
    """
    Look up a single ticker's recommendation history.

    Returns None if never recommended, otherwise a summary with score trend
    and recommendation rows ordered by scan date.
    """
    with _open_history(history_path) as conn:
        return _lookup_with_connection(conn, ticker)


def annotate_results(
    results: list[dict],
    history_path: Optional[str] = None,
) -> list[dict]:
    """
    Annotate a list of scan results with history info.

    Adds to each result dict:
        - "previously_recommended": bool
        - "times_recommended": int
        - "first_seen": date str or None
        - "last_seen": date str or None
        - "score_trend": list of prior scores
    """
    with _open_history(history_path) as conn:
        for r in results:
            history = _lookup_with_connection(conn, r["ticker"])
            if history:
                r["previously_recommended"] = True
                r["times_recommended"] = history["times_recommended"]
                r["first_seen"] = history["first_seen"]
                r["last_seen"] = history["last_seen"]
                r["score_trend"] = history["score_trend"]
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
    """Return the full history dict in the legacy JSON-compatible shape."""
    with _open_history(history_path) as conn:
        ticker_rows = conn.execute(
            "SELECT ticker, name FROM tickers ORDER BY ticker"
        ).fetchall()

        data = {"version": CURRENT_SCHEMA_VERSION, "tickers": {}}
        for ticker_row in ticker_rows:
            rec_rows = conn.execute(
                """
                SELECT scan_date, score, label, source
                FROM recommendations
                WHERE ticker = ?
                ORDER BY scan_date
                """,
                (ticker_row["ticker"],),
            ).fetchall()
            if not rec_rows:
                continue

            data["tickers"][ticker_row["ticker"]] = {
                "name": ticker_row["name"],
                "recommendations": [_row_to_recommendation(row) for row in rec_rows],
            }

        return data


def get_repeat_tickers(
    min_times: int = 2,
    history_path: Optional[str] = None,
) -> list[dict]:
    """
    Get tickers that have been recommended at least `min_times` times.
    Returns a list sorted by recommendation count descending.
    """
    with _open_history(history_path) as conn:
        ticker_rows = conn.execute(
            """
            SELECT
                t.ticker,
                t.name,
                COUNT(r.id) AS times_recommended,
                MIN(r.scan_date) AS first_seen,
                MAX(r.scan_date) AS last_seen
            FROM tickers t
            JOIN recommendations r ON r.ticker = t.ticker
            GROUP BY t.ticker, t.name
            HAVING COUNT(r.id) >= ?
            ORDER BY times_recommended DESC, t.ticker
            """,
            (min_times,),
        ).fetchall()

        repeats = []
        for ticker_row in ticker_rows:
            rec_rows = conn.execute(
                """
                SELECT score
                FROM recommendations
                WHERE ticker = ?
                ORDER BY scan_date
                """,
                (ticker_row["ticker"],),
            ).fetchall()
            last_row = conn.execute(
                """
                SELECT score
                FROM recommendations
                WHERE ticker = ?
                ORDER BY scan_date DESC
                LIMIT 1
                """,
                (ticker_row["ticker"],),
            ).fetchone()

            repeats.append({
                "ticker": ticker_row["ticker"],
                "name": ticker_row["name"],
                "times_recommended": ticker_row["times_recommended"],
                "first_seen": ticker_row["first_seen"],
                "last_seen": ticker_row["last_seen"],
                "last_score": last_row["score"],
                "score_trend": [row["score"] for row in rec_rows],
            })

        return repeats
