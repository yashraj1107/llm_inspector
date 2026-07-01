import os
import sqlite3
import time
from dotenv import load_dotenv
import llm_inspector
import openai

load_dotenv()
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
if not API_KEY:
    print("[SKIP] DEEPSEEK_API_KEY is not set.")
    raise SystemExit(0)

# Clear the traces database of span/llm_call to have a clean slate for verification
db = llm_inspector.db_path()
print(f"Using DB at: {db}")
conn = sqlite3.connect(str(db))
conn.execute("DELETE FROM traces WHERE provider = 'span' OR model = 'deepseek-chat'")
conn.commit()
conn.close()

# Start llm_inspector patches + worker
llm_inspector.auto()

client = openai.OpenAI(
    api_key=API_KEY,
    base_url="https://api.deepseek.com",
)

# Test 1: LLM Call INSIDE a span() block
print("\n--- Running Test 1: Inside Span Block ---")
with llm_inspector.span("handle_request", type="custom") as outer:
    span_id = outer.span_id
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "Say: linked"}],
    )
    print(f"DeepSeek response (inside span): {response.choices[0].message.content}")

# Test 2: LLM Call OUTSIDE any span block
print("\n--- Running Test 2: Outside Span Block ---")
response_outside = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "Say: standalone"}],
)
print(f"DeepSeek response (outside span): {response_outside.choices[0].message.content}")

# Wait for background queue worker to flush to DB
print("\nSleeping 2 seconds to let the queue worker flush...")
time.sleep(2)

# Query traces from SQLite
conn = sqlite3.connect(str(db))
conn.row_factory = sqlite3.Row

# Get the last 3 traces (the outer span, the inside call, and the outside call)
rows = conn.execute(
    "SELECT id, model, provider, span_type, parent_trace_id, root_trace_id FROM traces ORDER BY timestamp DESC LIMIT 3"
).fetchall()

print("\n--- Raw Trace Queries from traces.db ---")
for r in rows:
    print(dict(r))

# Let's map them by model
span_row = None
inside_call_row = None
outside_call_row = None

for r in rows:
    if r["provider"] == "span" and r["model"] == "handle_request":
        span_row = r
    elif r["provider"] == "deepseek" and r["span_type"] == "llm_call":
        if r["parent_trace_id"] is not None:
            inside_call_row = r
        else:
            outside_call_row = r

print("\n=== Verification assertions ===")
assert span_row is not None, "Span row not found in database!"
assert inside_call_row is not None, "Inside LLM call row not found in database!"
assert outside_call_row is not None, "Outside LLM call row not found in database!"

# 1. Inside span asserts
print(f"Span Row ID: {span_row['id']}")
print(f"Span Row span_type: {span_row['span_type']}")
print(f"Inside LLM Call parent_trace_id: {inside_call_row['parent_trace_id']}")
print(f"Inside LLM Call root_trace_id: {inside_call_row['root_trace_id']}")
print(f"Inside LLM Call span_type: {inside_call_row['span_type']}")

assert span_row["span_type"] == "custom"
assert span_row["parent_trace_id"] is None
assert inside_call_row["span_type"] == "llm_call"
assert inside_call_row["parent_trace_id"] == span_row["id"], f"Expected parent to be {span_row['id']}, got {inside_call_row['parent_trace_id']}"
assert inside_call_row["root_trace_id"] == span_row["id"], f"Expected root to be {span_row['id']}, got {inside_call_row['root_trace_id']}"
print("PASS: Inside-span linkage verified successfully!")

# 2. Outside span asserts
print(f"Outside LLM Call parent_trace_id: {outside_call_row['parent_trace_id']}")
print(f"Outside LLM Call root_trace_id: {outside_call_row['root_trace_id']}")
print(f"Outside LLM Call span_type: {outside_call_row['span_type']}")

assert outside_call_row["span_type"] == "llm_call"
assert outside_call_row["parent_trace_id"] is None, f"Expected None parent for outside call, got {outside_call_row['parent_trace_id']}"
assert outside_call_row["root_trace_id"] is None, f"Expected None root for outside call, got {outside_call_row['root_trace_id']}"
print("PASS: Outside-span standalone execution verified successfully!")

conn.close()
print("\nAll auto-linking tests passed successfully.")
