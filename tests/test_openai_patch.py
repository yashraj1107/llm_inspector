"""
test_openai_patch.py — Smoke test for the OpenAI SDK patch (Step 2),
running against DeepSeek's OpenAI-compatible API.

Run from the repo root:
    DEEPSEEK_API_KEY=sk-... python test_openai_patch.py

If DEEPSEEK_API_KEY is not set the script exits cleanly with an explanatory
message.  The openai_patch.py itself is NOT modified — this test confirms the
existing patch works unmodified against an OpenAI-compatible provider.

Expected output:
  - "Patch installed" confirmation
  - "API call succeeded" with the assistant's reply text
  - Most-recent row from traces.db showing:
      provider="openai", model="deepseek-chat", valid JSON in request_json /
      response_json, a plausible latency_ms, and non-null token counts
"""

import json
import os
import sqlite3
import time

# ---------------------------------------------------------------------------
# 0. Guard: require DEEPSEEK_API_KEY
# ---------------------------------------------------------------------------
from dotenv import load_dotenv
load_dotenv()
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
if not API_KEY:
    print(
        "\n[SKIP] DEEPSEEK_API_KEY environment variable is not set.\n"
        "       Export it and re-run:\n"
        "           export DEEPSEEK_API_KEY=sk-...\n"
        "           python test_openai_patch.py\n"
    )
    raise SystemExit(0)

# ---------------------------------------------------------------------------
# 1. Activate llm_inspector (starts worker + installs patch)
# ---------------------------------------------------------------------------

import llm_inspector

llm_inspector.auto()
print("[1] llm_inspector.auto() called — worker started, OpenAI patch installed.")
print(f"    DB will be written to: {llm_inspector.db_path().resolve()}")

# ---------------------------------------------------------------------------
# 2. Make a real chat completion call via DeepSeek's OpenAI-compatible API
# ---------------------------------------------------------------------------

import openai

client = openai.OpenAI(
    api_key=API_KEY,
    base_url="https://api.deepseek.com",
)

print("\n[2] Calling client.chat.completions.create (model=deepseek-chat) …")
try:
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user",   "content": "Reply with exactly one sentence: what is 2 + 2?"},
        ],
        max_tokens=64,
        temperature=0,
    )
    assistant_reply = response.choices[0].message.content
    print(f"    ✓ API call succeeded. Assistant replied: {assistant_reply!r}")
except openai.OpenAIError as exc:
    print(f"    ✗ API error (this is NOT a bug in llm_inspector): {exc}")
    raise SystemExit(1) from exc

# ---------------------------------------------------------------------------
# 3. Let the worker flush
# ---------------------------------------------------------------------------

SLEEP_S = 2
print(f"\n[3] Sleeping {SLEEP_S} s to let the worker flush …", flush=True)
time.sleep(SLEEP_S)

# ---------------------------------------------------------------------------
# 4. Inspect the DB directly
# ---------------------------------------------------------------------------

db = llm_inspector.db_path()
print(f"\n[4] Opening DB at: {db.resolve()}")

conn = sqlite3.connect(str(db))
conn.row_factory = sqlite3.Row

total_rows = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
print(f"    Total rows in traces: {total_rows}")

row = conn.execute(
    "SELECT * FROM traces ORDER BY timestamp DESC LIMIT 1"
).fetchone()

conn.close()

if row is None:
    print("    ✗ No rows found — the event was not persisted!")
    raise SystemExit(1)

print("\n" + "─" * 60)
print("  Most-recent row:")
print("─" * 60)

d = dict(row)
for k, v in d.items():
    display = v
    if isinstance(v, str) and len(v) > 80:
        display = v[:77] + "…"
    print(f"  {k:<22} = {display!r}")

# ---------------------------------------------------------------------------
# 5. Quick sanity checks
# ---------------------------------------------------------------------------


def _valid_json(s: str) -> bool:
    try:
        json.loads(s)
        return True
    except Exception:
        return False


print("\n" + "─" * 60)
print("  Sanity checks:")
checks = [
    ("provider == 'openai'",         d.get("provider") == "openai"),
    ("model == 'deepseek-chat'",     d.get("model") == "deepseek-chat"),
    ("request_json is valid JSON",   _valid_json(d.get("request_json", ""))),
    ("response_json is valid JSON",  _valid_json(d.get("response_json") or "null")),
    ("latency_ms > 0",               (d.get("latency_ms") or 0) > 0),
    ("prompt_tokens is not None",    d.get("prompt_tokens") is not None),
    ("completion_tokens is not None", d.get("completion_tokens") is not None),
    ("status == 'ok'",               d.get("status") == "ok"),
]

all_passed = True
for label, passed in checks:
    icon = "✓" if passed else "✗"
    print(f"  {icon}  {label}")
    if not passed:
        all_passed = False

print("─" * 60)
if all_passed:
    print("\n  All checks passed. Pipeline is working correctly. ✓")
else:
    print("\n  Some checks FAILED. See output above.")

print("=" * 60)
