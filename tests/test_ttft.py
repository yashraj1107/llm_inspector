import os
import time
import json
import sqlite3
import openai
from dotenv import load_dotenv
import llm_inspector

load_dotenv()
api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
if not api_key:
    print("FAIL: DEEPSEEK_API_KEY not found in env")
    exit(1)

# Auto-initialize inspector
llm_inspector.auto()

client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

print("Making streaming request to DeepSeek...")
response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "Count from 1 to 20, one number per line."}],
    stream=True,
    stream_options={"include_usage": True}
)

for chunk in response:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
print()

# Wait 2 seconds for worker to flush trace
time.sleep(2.0)

db = llm_inspector.db_path()
conn = sqlite3.connect(str(db))
conn.row_factory = sqlite3.Row
row = conn.execute("SELECT * FROM traces ORDER BY timestamp DESC LIMIT 1").fetchone()
conn.close()

if not row:
    print("FAIL: No traces found in traces.db")
    exit(1)

print("\n--- Test 2 Results ---")
print(f"Trace ID: {row['id']}")
print(f"Latency (ms): {row['latency_ms']}")
print(f"TTFT (ms): {row['ttft_ms']}")

try:
    assert row["ttft_ms"] is not None, "ttft_ms must not be None"
    assert row["latency_ms"] is not None, "latency_ms must not be None"
    assert row["ttft_ms"] < row["latency_ms"], f"ttft_ms ({row['ttft_ms']}) must be less than latency_ms ({row['latency_ms']})"
    assert row["ttft_ms"] > 0, "ttft_ms must be > 0"
    
    resp_obj = json.loads(row["response_json"])
    assert resp_obj.get("content"), "response_json content must not be null/empty"
    print(f"Response Content length: {len(resp_obj['content'])}")
    print("PASS: Streaming TTFT measurements captured and verified successfully.")
except Exception as e:
    print(f"FAIL: Assertions failed: {e}")
    exit(1)
