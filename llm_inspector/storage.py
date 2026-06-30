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
    user_id           TEXT,
    tags               TEXT,
    root_trace_id     TEXT,
    span_type         TEXT,
    tool_calls        TEXT,
    ttft_ms           INTEGER
);

CREATE TABLE IF NOT EXISTS model_pricing (
    model              TEXT PRIMARY KEY,
    provider           TEXT NOT NULL,
    prompt_price_per_1k     REAL,
    completion_price_per_1k REAL,
    last_verified      TEXT
);
"""

_INSERT_SQL = """
INSERT OR IGNORE INTO traces (
    id, timestamp, provider, model,
    request_json, response_json,
    latency_ms, prompt_tokens, completion_tokens,
    status, error_message, user_id,
    parent_trace_id, failure_type, pinned, tags,
    root_trace_id, span_type, tool_calls, ttft_ms
) VALUES (
    :id, :timestamp, :provider, :model,
    :request_json, :response_json,
    :latency_ms, :prompt_tokens, :completion_tokens,
    :status, :error_message, :user_id,
    :parent_trace_id, :failure_type, :pinned, :tags,
    :root_trace_id, :span_type, :tool_calls, :ttft_ms
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
    conn.executescript(_CREATE_TABLE_SQL)
    
    # Feature 0: Schema Upgrades
    for alter_sql in [
        "ALTER TABLE traces ADD COLUMN parent_trace_id TEXT;",
        "ALTER TABLE traces ADD COLUMN failure_type TEXT;",
        "ALTER TABLE traces ADD COLUMN pinned INTEGER DEFAULT 0;",
        "ALTER TABLE traces ADD COLUMN tags TEXT;",
        "ALTER TABLE traces ADD COLUMN user_id TEXT;",
        "ALTER TABLE traces ADD COLUMN root_trace_id TEXT;",
        "ALTER TABLE traces ADD COLUMN span_type TEXT;",
        "ALTER TABLE traces ADD COLUMN tool_calls TEXT;",
        "ALTER TABLE traces ADD COLUMN ttft_ms INTEGER;"
    ]:
        try:
            conn.execute(alter_sql)
        except sqlite3.OperationalError:
            pass  # Ignore if column already exists

    _ensure_pricing_seeded(conn)
    conn.commit()
    return conn

def _ensure_pricing_seeded(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) FROM model_pricing").fetchone()[0]
    if count > 0:
        return
        
    import datetime
    from llm_inspector.pricing import PRICING
    
    now_iso = datetime.datetime.utcnow().isoformat()
    
    for model, costs in PRICING.items():
        provider = "unknown"
        if "gpt" in model or "o1" in model:
            provider = "openai"
        elif "claude" in model:
            provider = "anthropic"
        elif "gemini" in model:
            provider = "gemini"
        elif "deepseek" in model:
            provider = "deepseek"
            
        conn.execute(
            '''INSERT INTO model_pricing 
               (model, provider, prompt_price_per_1k, completion_price_per_1k, last_verified)
               VALUES (?, ?, ?, ?, ?)''',
            (model, provider, costs["prompt"], costs["completion"], now_iso)
        )


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
    "root_trace_id", "span_type", "tool_calls", "ttft_ms",
)


def _coerce(event: dict) -> dict:
    """Return a dict that contains exactly the keys the INSERT statement needs."""
    d = {col: event.get(col) for col in _COLUMNS}
    if d.get("pinned") is None:
        d["pinned"] = 0
    return d


def db_path() -> Path:
    """Return the resolved path to the SQLite file (useful for tests)."""
    return _DB_PATH
