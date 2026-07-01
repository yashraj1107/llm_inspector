import os
import sqlite3
import time
import json
from fastapi.testclient import TestClient
from dotenv import load_dotenv

# Load env variables first to get real keys
load_dotenv()
backup_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()

if not backup_key:
    print("[SKIP] DEEPSEEK_API_KEY not found in env.")
    raise SystemExit(0)

# Unset DEEPSEEK_API_KEY from environment to prove programmatic config is used
os.environ.pop("DEEPSEEK_API_KEY", None)

import llm_inspector
from llm_inspector.server import app

# Programmatically configure DeepSeek credentials
llm_inspector.configure(
    deepseek_api_key=backup_key,
    deepseek_base_url="https://api.deepseek.com"
)

# Start background worker and hooks
llm_inspector.auto()

# Create a mock trace in the SQLite database to run replay against
db = llm_inspector.db_path()
conn = sqlite3.connect(str(db))
conn.execute("DELETE FROM traces WHERE id = 'test-deepseek-configure-trace-id'")
conn.execute("""
INSERT INTO traces (
    id, timestamp, provider, model, request_json, status, error_message, tags
) VALUES (
    'test-deepseek-configure-trace-id',
    ?,
    'deepseek',
    'deepseek-chat',
    ?,
    'ok',
    NULL,
    'test-config'
);
""", (
    int(time.time()),
    json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "Say: hello configure test"}]
    })
))
conn.commit()
conn.close()

client = TestClient(app)

print("\n--- Verification 1: Availability Endpoint ---")
resp = client.get("/api/providers/available")
assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
providers = resp.json()
print("Available providers returned:")
for p in providers:
    print(p)

ds_prov = next((p for p in providers if p["provider"] == "deepseek"), None)
assert ds_prov is not None, "DeepSeek provider was not returned in list"
assert ds_prov["available"] is True, f"Expected deepseek to be available: True, got {ds_prov}"
print("PASS: Programmatic config correctly marked deepseek as available.")

print("\n--- Verification 2: Replay Endpoint ---")
# Post to replay endpoint with empty body
resp = client.post(
    "/api/traces/test-deepseek-configure-trace-id/replay",
    json={}
)
print(f"Replay response status: {resp.status_code}")
print(f"Replay response body: {resp.json()}")

assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
data = resp.json()
assert data.get("success") is True, f"Expected success: True, got {data}"
assert "new_trace_id" in data, "Expected new_trace_id in response"
assert data["new_trace_id"] is not None, "Expected new_trace_id to be non-None"

# Restore env variable just in case other tests need it
os.environ["DEEPSEEK_API_KEY"] = backup_key

print("\nAll programmatic configuration tests passed successfully.")
