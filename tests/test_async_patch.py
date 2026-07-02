import os
import asyncio
import sqlite3
import time
import json
from unittest import mock
import openai
import anthropic
from dotenv import load_dotenv
import llm_inspector

load_dotenv()
llm_inspector.auto()

async def run_deepseek_test():
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        print("SKIP: DEEPSEEK_API_KEY not found in env")
        return

    print("Making real AsyncOpenAI DeepSeek call...")
    client = openai.AsyncOpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    
    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "Say: async works"}]
    )
    print("Response content:", response.choices[0].message.content)

    # Wait for queue worker to flush
    await asyncio.sleep(2)

    db = llm_inspector.db_path()
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM traces WHERE provider = 'deepseek' AND span_type = 'llm_call' ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    conn.close()

    assert row is not None, "FAIL: DeepSeek async trace not found"
    assert row["status"] == "ok", f"Expected ok status, got {row['status']}"
    resp_obj = json.loads(row["response_json"])
    assert "content" in resp_obj, "response_json content missing"
    print("PASS: AsyncOpenAI DeepSeek call trace verified successfully.")

async def run_span_test():
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        print("SKIP: DEEPSEEK_API_KEY not found in env for span test")
        return

    print("Making real AsyncOpenAI call nested in a span block...")
    client = openai.AsyncOpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    # Capture span ID
    span_id = None
    with llm_inspector.span("async_request") as s:
        span_id = s.span_id
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "Say: context works"}]
        )
    print("Response content in span:", response.choices[0].message.content)

    # Wait for queue worker to flush
    await asyncio.sleep(2)

    db = llm_inspector.db_path()
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    
    # Verify both the span trace and the child completion trace
    span_row = conn.execute("SELECT * FROM traces WHERE id = ?", (span_id,)).fetchone()
    child_row = conn.execute(
        "SELECT * FROM traces WHERE parent_trace_id = ? ORDER BY timestamp DESC LIMIT 1",
        (span_id,)
    ).fetchone()
    conn.close()

    assert span_row is not None, "FAIL: Span trace not found"
    assert child_row is not None, "FAIL: Child trace linked to span not found"
    assert child_row["root_trace_id"] == span_row["root_trace_id"], "FAIL: root_trace_id mismatch"
    print(f"Span ID: {span_id}")
    print(f"Child Parent ID: {child_row['parent_trace_id']}")
    print(f"Child Root ID: {child_row['root_trace_id']}")
    print("PASS: Async contextvars span linkage verified successfully.")

async def run_anthropic_test():
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        print("Making real AsyncAnthropic call...")
        client = anthropic.AsyncAnthropic(api_key=api_key)
        try:
            response = await client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=10,
                messages=[{"role": "user", "content": "Say hello"}]
            )
            print("Anthropic real response:", response.content[0].text)
        except Exception as e:
            print("Anthropic real call failed (possibly network or billing):", e)
            print("Proceeding to run mocked Anthropic test.")
            await run_anthropic_mock_test()
            return
        
        await asyncio.sleep(2)
        db = llm_inspector.db_path()
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT provider, model, status FROM traces WHERE provider = 'anthropic' ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert row is not None, "FAIL: Anthropic async trace not found"
        print("PASS: Real AsyncAnthropic call trace verified successfully.")
    else:
        print("ANTHROPIC_API_KEY not found, running mock Anthropic test...")
        await run_anthropic_mock_test()

async def run_anthropic_mock_test():
    mock_resp = mock.MagicMock()
    mock_resp.content = [mock.MagicMock(type="text", text="hello mock")]
    mock_resp.usage = mock.MagicMock(input_tokens=4, output_tokens=5)

    mock_async_create = mock.AsyncMock(return_value=mock_resp)

    with mock.patch("llm_inspector.patches.anthropic_patch._real_async_create", mock_async_create):
        client = anthropic.AsyncAnthropic(api_key="fake")
        response = await client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=10,
            messages=[{"role": "user", "content": "Say hello"}]
        )
        print("Mock response:", response.content[0].text)

    await asyncio.sleep(2)
    db = llm_inspector.db_path()
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT provider, model, status FROM traces WHERE provider = 'anthropic' ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row is not None, "FAIL: Mock Anthropic trace not found"
    assert row[2] == "ok", f"Expected status ok, got {row[2]}"
    print("PASS: Mock AsyncAnthropic call trace verified successfully.")

async def main():
    await run_deepseek_test()
    print("-" * 40)
    await run_span_test()
    print("-" * 40)
    await run_anthropic_test()

if __name__ == "__main__":
    asyncio.run(main())
