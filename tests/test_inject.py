"""
test_inject.py - Manually inserts a synthetic trace into traces.db for diff testing.

Run from the repo root:
    python tests/test_inject.py
"""
import sqlite3
import uuid
import time
import json
from pathlib import Path

# Resolve DB path relative to repo root (parent of tests/ directory)
REPO_ROOT = Path(__file__).parent.parent
DB_PATH = REPO_ROOT / 'llm_inspector_data' / 'traces.db'

conn = sqlite3.connect(str(DB_PATH))
trace_id = "france-germany-test"
req = {
    "model": "deepseek-chat",
    "messages": [
        {"role": "system", "content": "You are a concise assistant."},
        {"role": "user", "content": "What is the capital of France?"}
    ]
}
resp = {"content": "The capital of France is Paris."}

try:
    conn.execute('''
    INSERT INTO traces (id, timestamp, provider, model, request_json, response_json, latency_ms, prompt_tokens, completion_tokens, status, error_message, user_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        trace_id, int(time.time()), 'openai', 'deepseek-chat', json.dumps(req), json.dumps(resp),
        1000, 10, 10, 'ok', None, None
    ))
    conn.commit()
    print(f"PASS: Injected trace '{trace_id}' into {DB_PATH}")
except Exception as e:
    print(f"FAIL: Failed to inject trace - {e}")
finally:
    conn.close()
