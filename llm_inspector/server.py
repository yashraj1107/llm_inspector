"""
server.py — FastAPI dashboard backend for llm_inspector.

Endpoints
---------
  GET /                          → serves index.html
  GET /api/traces                → trace list (summary fields only)
  GET /api/traces/{trace_id}     → single trace with parsed JSON blobs

Reads traces.db via get_connection() from storage.py — no schema or
connection logic is duplicated here.
"""

import datetime
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import llm_inspector
from llm_inspector.storage import get_connection
from llm_inspector.pricing import PRICING

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

# Patch SDKs and start queue worker so replay calls are captured automatically
llm_inspector.auto()

app = FastAPI(
    title="llm_inspector",
    description="Local observability dashboard for LLM traces.",
    version="0.3.0",
    docs_url="/api/docs",
    redoc_url=None,
)

_STATIC_DIR = Path(__file__).parent / "static"

# Mount static assets at /static (CSS, JS, etc.)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_conn():
    """
    Wraps storage.get_connection(), adding row_factory so rows can be
    accessed by column name (row["id"] instead of row[0]).
    """
    import sqlite3 as _sqlite3
    conn = get_connection()
    conn.row_factory = _sqlite3.Row
    return conn


def _ts_to_iso(unix_ts) -> str | None:
    """Convert a unix integer timestamp to an ISO-8601 UTC string."""
    if unix_ts is None:
        return None
    return datetime.datetime.fromtimestamp(
        unix_ts, tz=datetime.timezone.utc
    ).isoformat()


def _safe_parse_json(raw: str | None):
    """
    Parse a JSON string into a Python object.
    Returns the raw string on failure (never raises).
    Returns None if raw is None.
    """
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw

def _classify_failure(error_msg: str | None) -> str | None:
    if not error_msg:
        return None
    msg = error_msg.lower()
    if "rate limit" in msg or "429" in msg: return "rate_limit"
    if "timeout" in msg or "timed out" in msg: return "timeout"
    if "authentication" in msg or "401" in msg or "invalid api key" in msg: return "auth_error"
    if "invalid_request" in msg or "400" in msg: return "invalid_request"
    return "unknown_error"

def _compute_cost(model: str, p_tok: int | None, c_tok: int | None, pricing_map: dict) -> float | None:
    if model not in pricing_map or p_tok is None or c_tok is None:
        return None
    rates = pricing_map[model]
    return (p_tok / 1000.0 * rates["prompt"]) + (c_tok / 1000.0 * rates["completion"])

# Helper to load pricing map from DB
def _get_pricing_map(conn) -> dict:
    rows = conn.execute("SELECT model, prompt_price_per_1k, completion_price_per_1k FROM model_pricing").fetchall()
    return {
        row["model"]: {
            "prompt": row["prompt_price_per_1k"],
            "completion": row["completion_price_per_1k"]
        }
        for row in rows
    }

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/providers/available")
def get_available_providers():
    from llm_inspector.config import get_provider_credentials
    return [
        {"provider": "openai", "available": bool(get_provider_credentials("openai")["api_key"])},
        {"provider": "anthropic", "available": bool(get_provider_credentials("anthropic")["api_key"])},
        {"provider": "deepseek", "available": bool(get_provider_credentials("deepseek")["api_key"])},
        {"provider": "gemini", "available": bool(get_provider_credentials("gemini")["api_key"])}
    ]

@app.get("/", include_in_schema=False)
def serve_index() -> FileResponse:
    """Serve the dashboard SPA."""
    return FileResponse(str(_STATIC_DIR / "index.html"))


@app.get("/api/traces")
def list_traces(
    limit: int = Query(default=50, ge=1, le=1000, description="Max rows to return"),
    provider: Optional[str] = Query(default=None, description="Filter by provider"),
    status: Optional[str] = Query(default=None, description="Filter by status (ok|error)"),
    search: Optional[str] = Query(default=None, description="Search request/response JSON text"),
    include_demo: bool = Query(default=False, description="Include demo traces"),
):
    """
    Return a JSON array of trace summaries, newest first.

    Deliberately excludes request_json / response_json blobs to keep
    the list payload small — use GET /api/traces/{id} for full detail.
    """
    conn = _get_conn()
    try:
        where_clauses, params = [], []
        if provider:
            where_clauses.append("provider = ?")
            params.append(provider)
        if status:
            where_clauses.append("status = ?")
            params.append(status)
        if search:
            where_clauses.append("(request_json LIKE ? OR response_json LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        if not include_demo:
            where_clauses.append("(tags IS NULL OR tags NOT LIKE '%demo%')")

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        params.append(limit)

        rows = conn.execute(
            f"""
            SELECT id, provider, model, status, latency_ms,
                   timestamp, prompt_tokens, completion_tokens, error_message, pinned, tags, parent_trace_id
            FROM traces
            {where_sql}
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        
        pricing_map = _get_pricing_map(conn)
        
        results = []
        for row in rows:
            results.append({
                "id":                row["id"],
                "provider":          row["provider"],
                "model":             row["model"],
                "status":            row["status"],
                "failure_type":      _classify_failure(row["error_message"]) if row["status"] == "error" else None,
                "latency_ms":        row["latency_ms"],
                "timestamp":         _ts_to_iso(row["timestamp"]),
                "prompt_tokens":     row["prompt_tokens"],
                "completion_tokens": row["completion_tokens"],
                "cost":              _compute_cost(row["model"], row["prompt_tokens"], row["completion_tokens"], pricing_map),
                "pinned":            row["pinned"],
                "tags":              row["tags"],
                "parent_trace_id":   row["parent_trace_id"]
            })
        return results

    finally:
        conn.close()


@app.get("/api/traces/{trace_id}")
def get_trace(trace_id: str):
    """
    Return the full row for a single trace, with request_json and
    response_json parsed into real nested JSON objects (not escaped strings).
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM traces WHERE id = ?", (trace_id,)
        ).fetchone()
        
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"No trace found with id {trace_id!r}",
            )

        d = dict(row)
        pricing_map = _get_pricing_map(conn)
        
        return {
            "id":                d["id"],
            "timestamp":         _ts_to_iso(d["timestamp"]),
            "provider":          d["provider"],
            "model":             d["model"],
            "status":            d["status"],
            "failure_type":      _classify_failure(d["error_message"]) if d["status"] == "error" else None,
            "latency_ms":        d["latency_ms"],
            "prompt_tokens":     d["prompt_tokens"],
            "completion_tokens": d["completion_tokens"],
            "cost":              _compute_cost(d["model"], d["prompt_tokens"], d["completion_tokens"], pricing_map),
            "error_message":     d["error_message"],
            "user_id":           d["user_id"],
            "parent_trace_id":   d["parent_trace_id"],
            "pinned":            d["pinned"],
            "tags":              d["tags"],
            "request_json":      _safe_parse_json(d["request_json"]),
            "response_json":     _safe_parse_json(d["response_json"]),
        }
    finally:
        conn.close()


class ReplayRequest(BaseModel):
    model: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    messages: Optional[List[Dict[str, Any]]] = None
    contents: Optional[Any] = None  # for Gemini


@app.post("/api/traces/{trace_id}/replay")
def replay_trace(trace_id: str, req: ReplayRequest):
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM traces WHERE id = ?", (trace_id,)).fetchone()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail=f"No trace found with id {trace_id!r}")

    d = dict(row)
    provider = req.provider or d["provider"]
    request_json_str = d["request_json"] or "{}"
    kwargs = _safe_parse_json(request_json_str) or {}
    
    # Force synchronous execution for replays. If we pass stream=True, the SDK returns a 
    # generator which we never consume, so the trace is never generated and the call hangs/drops.
    kwargs.pop("stream", None)
    kwargs.pop("stream_options", None)

    # Override model if provided
    if req.model:
        kwargs["model"] = req.model

    # Clean up kwargs if switching providers (e.g. anthropic max_tokens to openai max_completion_tokens)
    if req.provider and req.provider != d["provider"]:
        # Basic cleanup - advanced mapping could go here
        if req.provider == 'openai' and 'max_tokens' in kwargs:
             kwargs['max_completion_tokens'] = kwargs.pop('max_tokens')
        elif req.provider == 'anthropic' and 'max_completion_tokens' in kwargs:
             kwargs['max_tokens'] = kwargs.pop('max_completion_tokens')

    # Override messages/contents if provided
    if req.messages is not None:
        if provider == "openai" or provider == "anthropic" or provider == "deepseek":
            kwargs["messages"] = req.messages
            kwargs.pop("contents", None)
        elif provider == "gemini":
            kwargs["contents"] = req.messages  # Map frontend messages array back to contents
            kwargs.pop("messages", None)
            
    if req.contents is not None and provider == "gemini":
        kwargs["contents"] = req.contents
        kwargs.pop("messages", None)

    # Execute SDK call
    # Capture time BEFORE the call so we can identify the newly-created trace
    # regardless of which provider SDK actually records it under.
    call_ts = int(time.time())
    
    try:
        from llm_inspector.config import get_provider_credentials
        creds = get_provider_credentials(provider)

        if provider == "openai" or req.base_url:
            if req.base_url:
                compat_creds = get_provider_credentials("openai-compatible")
                api_key = compat_creds["api_key"]
                base_url = req.base_url
            else:
                api_key = creds["api_key"]
                base_url = None

            if not api_key and not req.base_url:
                raise HTTPException(status_code=400, detail="No OPENAI_API_KEY configured for openai — add it to .env or call configure() and restart the server.")

            import openai
            client_kwargs = {}
            client_kwargs["api_key"] = api_key or "custom"
            if base_url:
                client_kwargs["base_url"] = base_url

            client = openai.OpenAI(**client_kwargs)
            client.chat.completions.create(**kwargs)

        elif provider == "deepseek":
            deepseek_key = creds["api_key"]
            base_url = creds["base_url"] or "https://api.deepseek.com"
            if not deepseek_key:
                raise HTTPException(status_code=400, detail="No DEEPSEEK_API_KEY configured for deepseek — add it to .env or call configure() and restart the server.")
            import openai
            client = openai.OpenAI(api_key=deepseek_key, base_url=base_url)
            client.chat.completions.create(**kwargs)

        elif provider == "anthropic":
            api_key = creds["api_key"]
            if not api_key:
                raise HTTPException(status_code=400, detail="No ANTHROPIC_API_KEY configured for anthropic — add it to .env or call configure() and restart the server.")

            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            client.messages.create(**kwargs)

        elif provider == "gemini":
            api_key = creds["api_key"]
            if not api_key:
                raise HTTPException(status_code=400, detail="No GEMINI_API_KEY configured for gemini — add it to .env or call configure() and restart the server.")

            import google.genai
            client = google.genai.Client(api_key=api_key)
            client.models.generate_content(**kwargs)

        else:
            raise HTTPException(status_code=400, detail=f"Replay not supported for provider {provider}")

    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=502, content={"detail": f"Provider API Error: {str(e)}"})

    # Wait for queue worker to flush (batch flush is 1s, sleep 1.5s to be safe)
    time.sleep(1.5)

    conn = _get_conn()
    try:
        # Find the most recent trace written AFTER our call started that has no parent set yet.
        # We intentionally do NOT filter by provider here — deepseek replays go through the
        # openai SDK so they land as provider="openai" in the DB, not "deepseek".
        new_row = conn.execute(
            """SELECT id FROM traces
               WHERE timestamp >= ? AND parent_trace_id IS NULL
               ORDER BY timestamp DESC LIMIT 1""",
            (call_ts,)
        ).fetchone()
        if new_row:
            conn.execute("UPDATE traces SET parent_trace_id = ? WHERE id = ?", (trace_id, new_row["id"]))
            conn.commit()
    finally:
        conn.close()

    new_trace_id = new_row["id"] if new_row else None
    return {"success": True, "new_trace_id": new_trace_id}

@app.get("/api/traces/{trace_id}/history")
def get_trace_history(trace_id: str):
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            WITH RECURSIVE
            lineage AS (
                -- Base case: find the root by traversing UP
                SELECT * FROM traces WHERE id = ?
                UNION
                SELECT t.* FROM traces t
                JOIN lineage l ON l.parent_trace_id = t.id
            ),
            root AS (
                SELECT id FROM lineage WHERE parent_trace_id IS NULL LIMIT 1
            ),
            family AS (
                -- Now traverse DOWN from the root
                SELECT * FROM traces WHERE id = (SELECT id FROM root)
                UNION
                SELECT t.* FROM traces t
                JOIN family f ON t.parent_trace_id = f.id
            )
            SELECT id, timestamp, provider, model, status, latency_ms,
                   prompt_tokens, completion_tokens, error_message, parent_trace_id, response_json
            FROM family
            ORDER BY timestamp ASC
            """, (trace_id,)
        ).fetchall()
        
        # If the trace wasn't found at all, return 404
        if not rows and not conn.execute("SELECT 1 FROM traces WHERE id = ?", (trace_id,)).fetchone():
             raise HTTPException(status_code=404, detail="Trace not found")
             
    finally:
        conn.close()

    return [
        {
            "id": row["id"],
            "timestamp": _ts_to_iso(row["timestamp"]),
            "provider": row["provider"],
            "model": row["model"],
            "status": row["status"],
            "latency_ms": row["latency_ms"],
            "parent_trace_id": row["parent_trace_id"],
            "response_json": _safe_parse_json(row["response_json"]),
            "error_message": row["error_message"]
        } for row in rows
    ]

@app.post("/api/traces/{trace_id}/pin")
def toggle_pin(trace_id: str):
    conn = _get_conn()
    try:
        row = conn.execute("SELECT pinned FROM traces WHERE id = ?", (trace_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Trace not found")
        
        new_pinned = 0 if row["pinned"] == 1 else 1
        conn.execute("UPDATE traces SET pinned = ? WHERE id = ?", (new_pinned, trace_id))
        conn.commit()
        return {"id": trace_id, "pinned": new_pinned}
    finally:
        conn.close()

class TagsRequest(BaseModel):
    tags: str

@app.post("/api/traces/{trace_id}/tags")
def set_tags(trace_id: str, req: TagsRequest):
    conn = _get_conn()
    try:
        if not conn.execute("SELECT 1 FROM traces WHERE id = ?", (trace_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Trace not found")
            
        conn.execute("UPDATE traces SET tags = ? WHERE id = ?", (req.tags, trace_id))
        conn.commit()
        return {"id": trace_id, "tags": req.tags}
    finally:
        conn.close()

class CompareRequestModel(BaseModel):
    provider: str
    model: str
    
class CompareRequest(BaseModel):
    models: List[CompareRequestModel]
    messages: Optional[List[Dict[str, Any]]] = None
    base_url: Optional[str] = None

@app.post("/api/traces/{trace_id}/compare")
def compare_models(trace_id: str, req: CompareRequest):
    results = []
    for item in req.models:
        try:
            res = replay_trace(trace_id, ReplayRequest(model=item.model, provider=item.provider, base_url=req.base_url, messages=req.messages))
            results.append({
                "provider": item.provider,
                "model": item.model,
                "new_trace_id": res["new_trace_id"],
                "success": True,
                "error_message": None
            })
        except HTTPException as e:
            results.append({
                "provider": item.provider,
                "model": item.model,
                "new_trace_id": None,
                "success": False,
                "error_message": str(e.detail)
            })
        except Exception as e:
            results.append({
                "provider": item.provider,
                "model": item.model,
                "new_trace_id": None,
                "success": False,
                "error_message": str(e)
            })
    return results

@app.get("/api/stats/cost")
def get_cost_stats():
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT model, prompt_tokens, completion_tokens, timestamp FROM traces").fetchall()
        pricing_map = _get_pricing_map(conn)
    finally:
        conn.close()
        
    now = time.time()
    day_sec = 24 * 3600
    week_sec = 7 * day_sec
    
    cost_today = 0.0
    cost_week = 0.0
    cost_all = 0.0
    
    for row in rows:
        c = _compute_cost(row["model"], row["prompt_tokens"], row["completion_tokens"], pricing_map)
        if c is not None:
            cost_all += c
            if now - row["timestamp"] <= week_sec:
                cost_week += c
            if now - row["timestamp"] <= day_sec:
                cost_today += c
                
    return {
        "today": round(cost_today, 6),
        "week":  round(cost_week,  6),
        "all":   round(cost_all,   6),
    }

class PricingUpdate(BaseModel):
    prompt_price_per_1k: float
    completion_price_per_1k: float

@app.get("/api/pricing")
def get_pricing():
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT * FROM model_pricing ORDER BY provider, model").fetchall()
        import datetime
        now = datetime.datetime.utcnow()
        results = []
        for r in rows:
            lv = r["last_verified"]
            days = 0
            if lv:
                try:
                    dt = datetime.datetime.fromisoformat(lv)
                    days = (now - dt).days
                except Exception:
                    pass
            results.append({
                "model": r["model"],
                "provider": r["provider"],
                "prompt_price_per_1k": r["prompt_price_per_1k"],
                "completion_price_per_1k": r["completion_price_per_1k"],
                "last_verified": lv,
                "days_since_verified": days
            })
        return results
    finally:
        conn.close()

@app.post("/api/pricing/{model}")
def update_pricing(model: str, req: PricingUpdate):
    conn = _get_conn()
    try:
        import datetime
        now_iso = datetime.datetime.utcnow().isoformat()
        res = conn.execute(
            "UPDATE model_pricing SET prompt_price_per_1k=?, completion_price_per_1k=?, last_verified=? WHERE model=?",
            (req.prompt_price_per_1k, req.completion_price_per_1k, now_iso, model)
        )
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Model not found")
        conn.commit()
        return {"success": True, "last_verified": now_iso}
    finally:
        conn.close()

@app.get("/api/pricing/stale")
def get_stale_pricing():
    conn = _get_conn()
    try:
        # Get unique models used in traces
        used_models = {r["model"] for r in conn.execute("SELECT DISTINCT model FROM traces").fetchall()}
        
        # Get all pricing info
        rows = conn.execute("SELECT model, last_verified FROM model_pricing").fetchall()
        import datetime
        now = datetime.datetime.utcnow()
        stale_models = []
        
        for r in rows:
            model = r["model"]
            if model not in used_models:
                continue
            
            lv = r["last_verified"]
            if lv:
                try:
                    dt = datetime.datetime.fromisoformat(lv)
                    if (now - dt).days > 7:
                        stale_models.append(model)
                except Exception:
                    stale_models.append(model)
            else:
                stale_models.append(model)
                
        return stale_models
    finally:
        conn.close()
