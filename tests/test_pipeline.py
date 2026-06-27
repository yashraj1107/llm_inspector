"""
test_pipeline.py — End-to-end smoke test for llm_inspector Step 1.

Run from the repo root:
    python test_pipeline.py

Expected output:
    - Row count: 50
    - First 3 rows printed as dicts
"""

import json
import random
import sqlite3
import time
import uuid

from llm_inspector import db_path, enqueue_event, start_worker

# ---------------------------------------------------------------------------
# Fake data configuration
# ---------------------------------------------------------------------------

PROVIDERS = ["openai", "anthropic", "google", "cohere", "mistral"]
MODELS = {
    "openai":    ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
    "anthropic": ["claude-3-5-sonnet-20241022", "claude-3-haiku-20240307"],
    "google":    ["gemini-1.5-pro", "gemini-1.5-flash"],
    "cohere":    ["command-r-plus", "command-r"],
    "mistral":   ["mistral-large-latest", "mistral-small-latest"],
}

FAKE_USERS = [f"user_{i:04d}" for i in range(1, 11)]


def make_fake_event(index: int) -> dict:
    provider = random.choice(PROVIDERS)
    model    = random.choice(MODELS[provider])
    status   = "ok" if index % 2 == 0 else "error"

    event: dict = {
        "id":        str(uuid.uuid4()),
        "timestamp": int(time.time()),
        "provider":  provider,
        "model":     model,
        "request_json": json.dumps({
            "messages": [{"role": "user", "content": f"Test prompt #{index}"}],
            "temperature": round(random.uniform(0.0, 1.0), 2),
        }),
        "latency_ms":        random.randint(50, 3000),
        "prompt_tokens":     random.randint(10, 500),
        "completion_tokens": random.randint(5, 300) if status == "ok" else None,
        "status":            status,
        "user_id":           random.choice(FAKE_USERS),
    }

    if status == "ok":
        event["response_json"] = json.dumps({
            "choices": [{"message": {"content": f"Fake response for prompt #{index}"}}],
        })
        event["error_message"] = None
    else:
        event["response_json"] = None
        event["error_message"] = random.choice([
            "RateLimitError: Too many requests",
            "TimeoutError: upstream timed out after 30 s",
            "AuthenticationError: invalid API key",
            "ServiceUnavailableError: the model is overloaded",
        ])

    return event


# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print(" llm_inspector — pipeline smoke test")
    print("=" * 60)

    # 1. Start the worker (idempotent — safe to call twice)
    start_worker()
    start_worker()   # second call must be a no-op
    print("[1] Worker started (called twice — should still be one thread).")

    # 2. Enqueue 50 fake events in a tight loop
    N = 50
    for i in range(N):
        event = make_fake_event(i)
        enqueue_event(event)

    print(f"[2] Enqueued {N} fake events.")

    # 3. Give the worker time to flush everything
    SLEEP_S = 2
    print(f"[3] Sleeping {SLEEP_S} s to let the worker flush …", flush=True)
    time.sleep(SLEEP_S)

    # 4. Query the SQLite file directly
    db = db_path()
    print(f"[4] Opening DB at: {db.resolve()}")

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row

    row_count = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
    print(f"\n{'─'*60}")
    print(f"  Row count in traces table: {row_count}")

    if row_count != N:
        print(f"  ⚠  Expected {N} rows but found {row_count}.")
    else:
        print(f"  ✓  All {N} events persisted successfully.")

    print(f"\n  First 3 rows:")
    print(f"{'─'*60}")
    rows = conn.execute(
        "SELECT * FROM traces ORDER BY timestamp ASC LIMIT 3"
    ).fetchall()

    for i, row in enumerate(rows, 1):
        d = dict(row)
        print(f"\n  Row {i}:")
        for k, v in d.items():
            # Truncate long JSON blobs for readability
            val = v
            if isinstance(v, str) and len(v) > 80:
                val = v[:77] + "…"
            print(f"    {k:<22} = {val!r}")

    conn.close()
    print(f"\n{'='*60}")
    print(" Test complete.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
