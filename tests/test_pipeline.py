"""
test_pipeline.py - End-to-end smoke test for llm_inspector Step 1.

Run from the repo root:
    python tests/test_pipeline.py

Expected output:
    - Row count: 50
    - First 3 rows printed as dicts
"""

import sqlite3
import time

from llm_inspector import db_path, enqueue_event, start_worker
from demo_data import generate_demo_events

# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------

def main() -> None:
    print("llm_inspector - pipeline smoke test")

    # 1. Start the worker (idempotent - safe to call twice)
    start_worker()
    start_worker()   # second call must be a no-op
    print("[1] Worker started (called twice - should still be one thread).")
    
    db = db_path()
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    
    # Store demo row count BEFORE
    demo_count_before = conn.execute("SELECT COUNT(*) FROM traces WHERE tags LIKE '%demo%'").fetchone()[0]

    # 2. Enqueue 50 fake events in a tight loop
    N = 50
    demo_events = generate_demo_events(N)
    for event in demo_events:
        enqueue_event(event)

    print(f"[2] Enqueued {N} fake events.")

    # 3. Give the worker time to flush everything
    SLEEP_S = 2
    print(f"[3] Sleeping {SLEEP_S} s to let the worker flush ...", flush=True)
    time.sleep(SLEEP_S)

    # 4. Query the SQLite file directly
    print(f"[4] Opening DB at: {db.resolve()}")

    demo_count_after = conn.execute("SELECT COUNT(*) FROM traces WHERE tags LIKE '%demo%'").fetchone()[0]

    total_checks = 1
    passed_checks = 0

    inserted_demo = demo_count_after - demo_count_before

    if inserted_demo != N:
        print(f"FAIL: Row count - Expected {N} new demo rows but found {inserted_demo}.")
    else:
        print(f"PASS: Row count - All {N} events persisted successfully.")
        passed_checks += 1

    print(f"\n  First 3 newly inserted demo rows:")
    rows = conn.execute(
        "SELECT * FROM traces WHERE tags LIKE '%demo%' ORDER BY timestamp DESC LIMIT 3"
    ).fetchall()

    for i, row in enumerate(rows, 1):
        d = dict(row)
        print(f"\n  Row {i}:")
        for k, v in d.items():
            # Truncate long JSON blobs for readability
            val = v
            if isinstance(v, str) and len(v) > 80:
                val = v[:77] + "..."
            print(f"    {k:<22} = {val!r}")

    conn.close()
    
    print(f"\nSUMMARY: {total_checks} checks total, {passed_checks} passed, {total_checks - passed_checks} failed.")
    if passed_checks < total_checks:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
