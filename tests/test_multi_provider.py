"""
test_multi_provider.py - Multi-provider smoke test for llm_inspector Step 3.

Calls llm_inspector.auto() once, then makes one real call per provider
whose API key is present in the environment (or .env file).

Run from the repo root:
    python test_multi_provider.py

Missing API keys -> clear [SKIP] message, script continues to next provider.

Checks ANTHROPIC_API_KEY and GEMINI_API_KEY (also accepts GOOGLE_API_KEY
as an alias for Gemini).
"""

import json
import os
import sqlite3
import time

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_json(s: str) -> bool:
    try:
        json.loads(s)
        return True
    except Exception:
        return False


def _section(title: str) -> None:
    print(f"\n--- {title} ---")


def _sanity_checks(d: dict, expected_provider: str, expected_model: str) -> tuple[int, int]:
    checks = [
        (f"provider == {expected_provider!r}",  d.get("provider") == expected_provider),
        (f"model == {expected_model!r}",         d.get("model") == expected_model),
        ("request_json is valid JSON",           _valid_json(d.get("request_json", ""))),
        ("response_json is valid JSON",          _valid_json(d.get("response_json") or "null")),
        ("latency_ms > 0",                       (d.get("latency_ms") or 0) > 0),
        ("prompt_tokens is not None",            d.get("prompt_tokens") is not None),
        ("completion_tokens is not None",        d.get("completion_tokens") is not None),
        ("status == 'ok'",                       d.get("status") == "ok"),
    ]
    passed_count = 0
    for label, passed in checks:
        if passed:
            print(f"PASS: {label}")
            passed_count += 1
        else:
            print(f"FAIL: {label} - condition not met")
    return passed_count, len(checks)


# ---------------------------------------------------------------------------
# 0. Activate llm_inspector
# ---------------------------------------------------------------------------

import llm_inspector  # noqa: E402

print(f"llm_inspector v{llm_inspector.__version__} - multi-provider smoke test")

llm_inspector.auto()
print("\n[0] llm_inspector.auto() called - worker + all patches active.")
print(f"    DB: {llm_inspector.db_path().resolve()}")

db = llm_inspector.db_path()

# Snapshot row count before any calls
_snap = sqlite3.connect(str(db))
rows_start = _snap.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
_snap.close()
print(f"    Rows in traces at start: {rows_start}")

# Track which providers actually ran and their expected DB values
results: list[dict] = []   # {"provider": ..., "model": ..., "success": bool}

# ---------------------------------------------------------------------------
# 1. Anthropic
# ---------------------------------------------------------------------------

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()

_section("Provider: Anthropic")
if not ANTHROPIC_KEY:
    print("  [SKIP] ANTHROPIC_API_KEY not set - skipping.")
else:
    try:
        import anthropic

        _anth_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        _MODEL = "claude-3-haiku-20240307"
        print(f"  Calling Messages.create (model={_MODEL}) ...")

        _t0 = time.time()
        _resp = _anth_client.messages.create(
            model=_MODEL,
            max_tokens=64,
            messages=[{"role": "user", "content": "Reply with exactly one sentence: what is 2 + 2?"}],
        )
        _elapsed = int((time.time() - _t0) * 1000)
        _reply = _resp.content[0].text if _resp.content else "(empty)"
        print(f"  PASS: API call succeeded in {_elapsed} ms. Reply: {_reply!r}")
        results.append({"provider": "anthropic", "model": _MODEL, "success": True})

    except Exception as exc:
        print(f"  FAIL: Anthropic call failed - {exc}")
        results.append({"provider": "anthropic", "model": "claude-3-haiku-20240307", "success": False})

# ---------------------------------------------------------------------------
# 2. Gemini
# ---------------------------------------------------------------------------

GEMINI_KEY = (
    os.environ.get("GEMINI_API_KEY", "")
    or os.environ.get("GOOGLE_API_KEY", "")
).strip()

_section("Provider: Gemini")
if not GEMINI_KEY:
    print("  [SKIP] GEMINI_API_KEY (or GOOGLE_API_KEY) not set - skipping.")
else:
    try:
        import google.genai as genai

        _gem_client = genai.Client(api_key=GEMINI_KEY)
        _MODEL = "gemini-2.0-flash"
        print(f"  Calling models.generate_content (model={_MODEL}) ...")

        _t0 = time.time()
        _resp = _gem_client.models.generate_content(
            model=_MODEL,
            contents="Reply with exactly one sentence: what is 2 + 2?",
        )
        _elapsed = int((time.time() - _t0) * 1000)
        _reply = _resp.text
        print(f"  PASS: API call succeeded in {_elapsed} ms. Reply: {_reply!r}")
        results.append({"provider": "gemini", "model": _MODEL, "success": True})

    except Exception as exc:
        print(f"  FAIL: Gemini call failed - {exc}")
        results.append({"provider": "gemini", "model": "gemini-2.0-flash", "success": False})

# ---------------------------------------------------------------------------
# 3. Flush and inspect DB
# ---------------------------------------------------------------------------

if not results:
    print("\n[SKIP] No API keys were set - nothing to verify in the DB.")
    print("       Set at least one of: ANTHROPIC_API_KEY, GEMINI_API_KEY")
    raise SystemExit(0)

successful = [r for r in results if r["success"]]
if not successful:
    print("\n  All provider calls failed - check your API keys / network.")
    raise SystemExit(1)

SLEEP_S = 2
print(f"\n[flush] Sleeping {SLEEP_S} s to let the worker flush ...", flush=True)
time.sleep(SLEEP_S)

# ---------------------------------------------------------------------------
# 4. Per-provider DB verification
# ---------------------------------------------------------------------------

conn = sqlite3.connect(str(db))
conn.row_factory = sqlite3.Row

rows_now = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
print(f"\n[DB] Total rows: {rows_start} -> {rows_now}  (+{rows_now - rows_start})")

global_passed = 0
global_total = 0

for r in successful:
    prov  = r["provider"]
    model = r["model"]
    _section(f"DB row - provider={prov!r}")

    row = conn.execute(
        "SELECT * FROM traces WHERE provider = ? ORDER BY timestamp DESC LIMIT 1",
        (prov,),
    ).fetchone()

    if row is None:
        print(f"FAIL: Row existence - No row found for provider={prov!r}")
        global_total += 1
        continue
    else:
        print(f"PASS: Row existence - Found row for provider={prov!r}")
        global_passed += 1
        global_total += 1

    d = dict(row)
    for k, v in d.items():
        display = v
        if isinstance(v, str) and len(v) > 80:
            display = v[:77] + "..."
        print(f"  {k:<22} = {display!r}")

    print()
    passed_count, total_count = _sanity_checks(d, expected_provider=prov, expected_model=model)
    global_passed += passed_count
    global_total += total_count

conn.close()

# ---------------------------------------------------------------------------
# 5. Final verdict
# ---------------------------------------------------------------------------

print(f"\nSUMMARY: {global_total} checks total, {global_passed} passed, {global_total - global_passed} failed.")
if global_passed < global_total:
    raise SystemExit(1)
