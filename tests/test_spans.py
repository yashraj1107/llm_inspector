import asyncio
import sqlite3
import time
import llm_inspector

# Clear the DB at the start
db = llm_inspector.db_path()
print(f"Using DB at: {db}")
conn = sqlite3.connect(str(db))
conn.execute("DELETE FROM traces WHERE provider = 'span'")
conn.commit()
conn.close()

# Start the worker
llm_inspector.start_worker()

# --- 1. SYNC NESTING TEST ---
print("\n--- Running SYNC Nesting Test ---")
with llm_inspector.span("sync_outer") as outer:
    outer_id = outer.span_id
    with llm_inspector.span("sync_inner") as inner:
        inner_id = inner.span_id
        pass

# --- 2. ASYNC CONCURRENT GATHER TEST ---
print("\n--- Running ASYNC Nesting Test ---")
task_ids = {}

async def task(name):
    with llm_inspector.span(f"async_outer_{name}") as outer:
        task_ids[f"outer_{name}"] = outer.span_id
        await asyncio.sleep(0.1)
        with llm_inspector.span(f"async_inner_{name}") as inner:
            task_ids[f"inner_{name}"] = inner.span_id
            await asyncio.sleep(0.1)

async def run_tasks():
    await asyncio.gather(task("a"), task("b"))

asyncio.run(run_tasks())

# --- 3. EXCEPTION HANDLING TEST ---
print("\n--- Running Exception Handling Test ---")
exception_span_id = None
try:
    with llm_inspector.span("exc_span") as exc_span:
        exception_span_id = exc_span.span_id
        raise ValueError("Something went wrong!")
except ValueError as e:
    print(f"Exception successfully propagated to caller: {e}")

# --- 4. DECORATOR USAGE TEST ---
print("\n--- Running Decorator Usage Test ---")

@llm_inspector.span("decorator_sync")
def sync_func():
    return "sync_func_result"

@llm_inspector.span("decorator_async")
async def async_func():
    return "async_func_result"

sync_func()
asyncio.run(async_func())

# Give worker time to flush
print("\nSleeping to allow worker to flush to DB...")
time.sleep(2)

# --- VERIFICATION FROM DATABASE ---
conn = sqlite3.connect(str(db))
conn.row_factory = sqlite3.Row

# Verification 1: Sync Nesting
outer_row = conn.execute("SELECT * FROM traces WHERE id = ?", (outer_id,)).fetchone()
inner_row = conn.execute("SELECT * FROM traces WHERE id = ?", (inner_id,)).fetchone()

print("\n=== Verification 1: SYNC Nesting ===")
if outer_row and inner_row:
    p_id = inner_row["parent_trace_id"]
    r_id = inner_row["root_trace_id"]
    print(f"Outer Span ID: {outer_id}")
    print(f"Inner Span ID: {inner_id}")
    print(f"Inner Parent ID: {p_id}")
    print(f"Inner Root ID: {r_id}")
    
    assert p_id == outer_id, f"Expected parent to be {outer_id}, got {p_id}"
    assert r_id == outer_id, f"Expected root to be {outer_id}, got {r_id}"
    print("PASS: Sync nesting parent/root linkage matches perfectly.")
else:
    print("FAIL: Sync traces not found in database.")

# Verification 2: Async Gathering
print("\n=== Verification 2: ASYNC Nesting (Concurrent Task 'a' and 'b') ===")
outer_a_id = task_ids["outer_a"]
inner_a_id = task_ids["inner_a"]
outer_b_id = task_ids["outer_b"]
inner_b_id = task_ids["inner_b"]

outer_a_row = conn.execute("SELECT * FROM traces WHERE id = ?", (outer_a_id,)).fetchone()
inner_a_row = conn.execute("SELECT * FROM traces WHERE id = ?", (inner_a_id,)).fetchone()
outer_b_row = conn.execute("SELECT * FROM traces WHERE id = ?", (outer_b_id,)).fetchone()
inner_b_row = conn.execute("SELECT * FROM traces WHERE id = ?", (inner_b_id,)).fetchone()

if all([outer_a_row, inner_a_row, outer_b_row, inner_b_row]):
    # Task A Check
    p_a = inner_a_row["parent_trace_id"]
    r_a = inner_a_row["root_trace_id"]
    print(f"Task A - Outer ID: {outer_a_id}, Inner Parent: {p_a}, Inner Root: {r_a}")
    assert p_a == outer_a_id, f"Expected task A parent to be {outer_a_id}, got {p_a}"
    assert r_a == outer_a_id, f"Expected task A root to be {outer_a_id}, got {r_a}"
    
    # Task B Check
    p_b = inner_b_row["parent_trace_id"]
    r_b = inner_b_row["root_trace_id"]
    print(f"Task B - Outer ID: {outer_b_id}, Inner Parent: {p_b}, Inner Root: {r_b}")
    assert p_b == outer_b_id, f"Expected task B parent to be {outer_b_id}, got {p_b}"
    assert r_b == outer_b_id, f"Expected task B root to be {outer_b_id}, got {r_b}"
    
    # Verification of no cross-contamination
    assert p_a != outer_b_id, "Cross-contamination detected! Task A inner points to Task B outer."
    assert p_b != outer_a_id, "Cross-contamination detected! Task B inner points to Task A outer."
    print("PASS: Async concurrent nesting parent/root linkage matches perfectly without contamination.")
else:
    print("FAIL: Async traces not found in database.")

# Verification 3: Exception Handling
print("\n=== Verification 3: Exception Handling ===")
exc_row = conn.execute("SELECT * FROM traces WHERE id = ?", (exception_span_id,)).fetchone()
if exc_row:
    print(f"Status: {exc_row['status']}")
    print(f"Error Message: {exc_row['error_message']}")
    print(f"Failure Type: {exc_row['failure_type']}")
    assert exc_row["status"] == "error"
    assert exc_row["failure_type"] == "ValueError"
    assert exc_row["error_message"] == "Something went wrong!"
    print("PASS: Exception handling captured status='error', failure_type='ValueError', and error_message.")
else:
    print("FAIL: Exception trace not found.")

# Verification 4: Decorators
print("\n=== Verification 4: Decorator Usage ===")
sync_dec_row = conn.execute("SELECT * FROM traces WHERE model = 'decorator_sync'").fetchone()
async_dec_row = conn.execute("SELECT * FROM traces WHERE model = 'decorator_async'").fetchone()

if sync_dec_row and async_dec_row:
    print(f"Sync decorator span ID: {sync_dec_row['id']}")
    print(f"Async decorator span ID: {async_dec_row['id']}")
    assert sync_dec_row["status"] == "ok"
    assert async_dec_row["status"] == "ok"
    print("PASS: Both sync and async decorators created and stored ok traces.")
else:
    print("FAIL: Decorator traces not found in database.")

conn.close()
print("\nAll tests completed.")
