"""
docker_test_script.py — Docker volume-persistence smoke test.

Enqueues ONE fake event with a recognisable marker (passed as sys.argv[1],
defaulting to "run_1"), flushes, then prints the total row count in traces.db.
No real API call is made — this test is purely about file survival across
container restarts.

Usage inside a container:
    python docker_test_script.py run_1
    python docker_test_script.py run_2
"""

import json
import sqlite3
import sys
import time
import uuid

import llm_inspector

# ---------------------------------------------------------------------------
# Marker from command-line (default: "run_1")
# ---------------------------------------------------------------------------

marker = sys.argv[1] if len(sys.argv) > 1 else "run_1"

print(f"[docker_test] Starting — marker={marker!r}")
print(f"[docker_test] DB path: {llm_inspector.db_path().resolve()}")

# ---------------------------------------------------------------------------
# Start worker + enqueue one fake event
# ---------------------------------------------------------------------------

llm_inspector.start_worker()

event = {
    "id":           str(uuid.uuid4()),
    "timestamp":    int(time.time()),
    "provider":     "docker_test",
    "model":        "test-run",
    "request_json": json.dumps({"marker": marker}),
    "response_json": None,
    "latency_ms":   0,
    "prompt_tokens": None,
    "completion_tokens": None,
    "status":       "ok",
    "error_message": None,
    "user_id":      None,
}

llm_inspector.enqueue_event(event)
print(f"[docker_test] Enqueued event with marker={marker!r}")

# ---------------------------------------------------------------------------
# Wait for the background worker to flush
# ---------------------------------------------------------------------------

time.sleep(2)

# ---------------------------------------------------------------------------
# Report row count
# ---------------------------------------------------------------------------

db = llm_inspector.db_path()
conn = sqlite3.connect(str(db))
count = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
conn.close()

print(f"[docker_test] Total rows in traces.db: {count}")
