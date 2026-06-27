"""
storage.py — SQLite schema and batch write logic for llm_inspector.

The DB file lives at ./llm_inspector_data/traces.db relative to wherever
the process is started. The directory is created automatically on first use.
"""

import os
import sqlite3
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DB_DIR = Path("llm_inspector_data")
_DB_PATH = _DB_DIR / "traces.db"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS traces (
    id                TEXT    PRIMARY KEY,
    timestamp         INTEGER NOT NULL,
    provider          TEXT    NOT NULL,
    model             TEXT    NOT NULL,
    request_json      TEXT    NOT NULL,
    response_json     TEXT,
    latency_ms        INTEGER,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    status            TEXT    NOT NULL CHECK(status IN ('ok', 'error')),
    error_message     TEXT,
    user_id           TEXT
);
"""

_INSERT_SQL = """
INSERT OR IGNORE INTO traces (
    id, timestamp, provider, model,
    request_json, response_json,
    latency_ms, prompt_tokens, completion_tokens,
    status, error_message, user_id,
    parent_trace_id, failure_type, pinned, tags
) VALUES (
    :id, :timestamp, :provider, :model,
    :request_json, :response_json,
    :latency_ms, :prompt_tokens, :completion_tokens,
    :status, :error_message, :user_id,
    :parent_trace_id, :failure_type, :pinned, :tags
);
"""

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_connection() -> sqlite3.Connection:
    """
    Return a new SQLite connection, creating the directory and schema on
    first call.  WAL journal mode gives better concurrent read performance.
    """
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(_CREATE_TABLE_SQL)
    
    # Feature 0: Schema Upgrades
    for alter_sql in [
        "ALTER TABLE traces ADD COLUMN parent_trace_id TEXT;",
        "ALTER TABLE traces ADD COLUMN failure_type TEXT;",
        "ALTER TABLE traces ADD COLUMN pinned INTEGER DEFAULT 0;",
        "ALTER TABLE traces ADD COLUMN tags TEXT;"
    ]:
        try:
            conn.execute(alter_sql)
        except sqlite3.OperationalError:
            pass  # Ignore if column already exists

    conn.commit()
    return conn


def write_batch(conn: sqlite3.Connection, events: list[dict]) -> None:
    """
    Write *events* to the traces table in a single transaction.

    Missing keys in each event dict are silently coerced to None so that
    partially-formed events don't crash the worker.
    """
    rows = [_coerce(e) for e in events]
    with conn:
        conn.executemany(_INSERT_SQL, rows)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_COLUMNS = (
    "id", "timestamp", "provider", "model",
    "request_json", "response_json",
    "latency_ms", "prompt_tokens", "completion_tokens",
    "status", "error_message", "user_id",
    "parent_trace_id", "failure_type", "pinned", "tags",
)


def _coerce(event: dict) -> dict:
    """Return a dict that contains exactly the keys the INSERT statement needs."""
    return {col: event.get(col) for col in _COLUMNS}


def db_path() -> Path:
    """Return the resolved path to the SQLite file (useful for tests)."""
    return _DB_PATH
