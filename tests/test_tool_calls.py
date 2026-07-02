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

print("Making tool-call request to DeepSeek...")
response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "What is the weather in Mumbai? Use the get_weather tool."}],
    tools=[{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a city",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"}
                },
                "required": ["city"]
            }
        }
    }],
    tool_choice="auto",
)

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

print("\n--- Test 1 Results ---")
print(f"Trace ID: {row['id']}")
print(f"Provider: {row['provider']}")
print(f"Model: {row['model']}")
print(f"Status: {row['status']}")
print(f"Span type: {row['span_type']}")

tool_calls_raw = row["tool_calls"]
if tool_calls_raw is None:
    choice = response.choices[0]
    if choice.finish_reason != "tool_calls":
         print("SKIP: Model chose not to invoke a tool — tool_calls column correctly NULL")
    else:
         print("FAIL: Model returned tool call finish_reason but database tool_calls is NULL")
         exit(1)
else:
    print(f"Tool calls raw: {tool_calls_raw}")
    try:
        data = json.loads(tool_calls_raw)
        assert isinstance(data, list), "tool_calls must be a list"
        assert len(data) > 0, "tool_calls list must not be empty"
        first_call = data[0]
        assert first_call["function"]["name"] == "get_weather", f"Expected name get_weather, got {first_call['function']['name']}"
        assert row["span_type"] == "llm_call", f"Expected span_type llm_call, got {row['span_type']}"
        print("PASS: Tool calls captured and verified successfully.")
    except Exception as e:
        print(f"FAIL: Assertions failed: {e}")
        exit(1)
