"""
test_import_order.py — Verifies that the OpenAI patch works correctly even when
`openai` is imported and the client is constructed BEFORE llm_inspector.auto()
is called.

This tests a critical property of the patch: because it replaces the method on
the CLASS (Completions.create), not on any particular instance, calling auto()
after client construction still intercepts subsequent calls on that same client.

Import / call order:
  1. load_dotenv + check DEEPSEEK_API_KEY
  2. import openai
  3. construct client  ← BEFORE auto()
  4. import llm_inspector + call auto()
  5. call client.chat.completions.create(...)  ← same client from step 3

Run from the repo root:
    DEEPSEEK_API_KEY=sk-... python test_import_order.py
    # or with a .env file containing DEEPSEEK_API_KEY=sk-...
    python test_import_order.py
"""

import json
import os
import sqlite3
import time

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 0. Load env + guard: require DEEPSEEK_API_KEY
# ---------------------------------------------------------------------------

load_dotenv()

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
if not API_KEY:
    print(
        "\n[SKIP] DEEPSEEK_API_KEY environment variable is not set.\n"
        "       Export it or add it to a .env file, then re-run:\n"
        "           export DEEPSEEK_API_KEY=sk-...\n"
        "           python test_import_order.py\n"
    )
    raise SystemExit(0)

# ---------------------------------------------------------------------------
# 1. import openai + construct client  ← intentionally BEFORE auto()
# ---------------------------------------------------------------------------

import openai  # noqa: E402

client = openai.OpenAI(
    api_key=API_KEY,
    base_url="https://api.deepseek.com",
)

print("[1] openai imported and client constructed — llm_inspector NOT yet active.")

# ---------------------------------------------------------------------------
# 2. NOW activate llm_inspector
# ---------------------------------------------------------------------------

import llm_inspector  # noqa: E402

llm_inspector.auto()
print("[2] llm_inspector.auto() called — worker started, patch installed.")
print(f"    DB will be written to: {llm_inspector.db_path().resolve()}")

# Snapshot the row count before this test run so we can confirm exactly 1 new
# row was added by the call below.
db = llm_inspector.db_path()
_conn = sqlite3.connect(str(db))
rows_before = _conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
_conn.close()
print(f"    Rows in traces BEFORE this call: {rows_before}")

# ---------------------------------------------------------------------------
# 3. Call create() on the client that was built BEFORE auto()
# ---------------------------------------------------------------------------

print("\n[3] Calling client.chat.completions.create (model=deepseek-chat) …")
print("    (client was constructed in step 1, BEFORE the patch was installed)")
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
# 4. Let the worker flush
# ---------------------------------------------------------------------------

SLEEP_S = 2
print(f"\n[4] Sleeping {SLEEP_S} s to let the worker flush …", flush=True)
time.sleep(SLEEP_S)

# ---------------------------------------------------------------------------
# 5. Inspect the DB directly
# ---------------------------------------------------------------------------

print(f"\n[5] Opening DB at: {db.resolve()}")

conn = sqlite3.connect(str(db))
conn.row_factory = sqlite3.Row

rows_after = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
print(f"    Rows BEFORE this call : {rows_before}")
print(f"    Rows AFTER  this call : {rows_after}")
new_rows = rows_after - rows_before
print(f"    New rows added        : {new_rows}  ← should be 1")

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
# 6. Sanity checks
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
    ("exactly 1 new row added",      new_rows == 1),
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
    print(
        "\n  All checks passed.\n"
        "  The patch intercepts calls even on clients constructed BEFORE auto(). ✓"
    )
else:
    print("\n  Some checks FAILED. See output above.")

print("=" * 60)
