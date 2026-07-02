"""
gemini_patch.py — Monkey-patch google.genai.models.Models.generate_content
so every synchronous generate_content call is captured into the llm_inspector
pipeline.

SDK: google-genai (the newer SDK, package google.genai).
     google.generativeai is NOT available in this environment.

Class/method patched: google.genai.models.Models.generate_content

Gemini-specific field differences vs OpenAI:
- response.text           → simple string accessor (try first)
- response.usage_metadata.prompt_token_count    → prompt_tokens
- response.usage_metadata.candidates_token_count → completion_tokens
# NOTE: Asynchronous client support (google.genai.Client(....).aio) is currently
# a known gap and not yet patched.
"""

import json
import time
import uuid

from llm_inspector.queue_worker import enqueue_event
from llm_inspector.patches.registry import register_patcher

# ---------------------------------------------------------------------------
# Idempotency guard
# ---------------------------------------------------------------------------

_patched: bool = False

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def patch_gemini() -> None:
    """
    Replace ``google.genai.models.Models.generate_content`` with a thin
    wrapper that records every successful call into the llm_inspector pipeline.

    Safe to call multiple times — subsequent calls are no-ops.
    Does nothing if google.genai is not installed.
    """
    global _patched  # noqa: PLW0603

    if _patched:
        return

    # ---- lazy import (google.genai only — google.generativeai not present) -
    try:
        import google.genai.models as _models_mod
    except ImportError:
        return  # google-genai not installed — nothing to patch

    # ---- grab the real method and wrap it ----------------------------------
    _real_generate = _models_mod.Models.generate_content

    def _wrapped_generate_content(self, *args, **kwargs):  # noqa: ANN001, ANN202
        start_time = time.time()

        try:
            from llm_inspector.spans import get_current_span_id, get_current_root_id
            parent_trace_id = get_current_span_id()
            root_trace_id = get_current_root_id()
        except Exception:
            parent_trace_id = None
            root_trace_id = None

        # ----------------------------------------------------------------
        # Call the REAL method — exceptions propagate unchanged.
        # ----------------------------------------------------------------
        response = _real_generate(self, *args, **kwargs)

        # ----------------------------------------------------------------
        # Capture the successful call.
        # ----------------------------------------------------------------
        try:
            # -- model ---------------------------------------------------
            # In google.genai, model is a keyword-only arg named "model".
            try:
                model = kwargs.get("model", "unknown") or "unknown"
            except Exception:  # noqa: BLE001
                model = "unknown"

            # -- request_json --------------------------------------------
            # kwargs may contain complex types (Content, Part objects).
            # default=str handles non-serializable objects gracefully.
            try:
                request_json = json.dumps(kwargs, default=str)
            except Exception:  # noqa: BLE001
                request_json = "{}"

            # -- response_json -------------------------------------------
            # response.text is the simplest accessor for plain text responses.
            try:
                response_json: str | None = json.dumps(
                    {"text": response.text}, default=str
                )
            except Exception:  # noqa: BLE001
                response_json = None

            # -- token counts (Gemini naming) ----------------------------
            try:
                prompt_tokens: int | None = (
                    response.usage_metadata.prompt_token_count
                )
            except Exception:  # noqa: BLE001
                prompt_tokens = None

            try:
                completion_tokens: int | None = (
                    response.usage_metadata.candidates_token_count
                )
            except Exception:  # noqa: BLE001
                completion_tokens = None

            # -- latency -------------------------------------------------
            latency_ms = int((time.time() - start_time) * 1000)

            # -- tool calls ----------------------------------------------
            try:
                parts = response.candidates[0].content.parts
                fc_parts = [p for p in parts if hasattr(p, "function_call") 
                            and p.function_call]
                tool_calls_data = None
                if fc_parts:
                    tool_calls_data = json.dumps([
                        {
                            "name": p.function_call.name,
                            "args": dict(p.function_call.args),
                        }
                        for p in fc_parts
                    ], default=str)
            except Exception:
                tool_calls_data = None

            # -- assemble event ------------------------------------------
            event: dict = {
                "id":                str(uuid.uuid4()),
                "timestamp":         int(time.time()),
                "provider":          "gemini",
                "model":             model,
                "request_json":      request_json,
                "response_json":     response_json,
                "latency_ms":        latency_ms,
                "prompt_tokens":     prompt_tokens,
                "completion_tokens": completion_tokens,
                "status":            "ok",
                "error_message":     None,
                "parent_trace_id":   parent_trace_id,
                "root_trace_id":     root_trace_id,
                "span_type":         "llm_call",
                "tool_calls":        tool_calls_data,
            }

            enqueue_event(event)

        except Exception:  # noqa: BLE001
            # Capture must NEVER raise into the caller.
            pass

        return response

    # ---- install the wrapper -----------------------------------------------
    _models_mod.Models.generate_content = _wrapped_generate_content
    _patched = True


# ---------------------------------------------------------------------------
# Register with the central registry (runs at import time)
# ---------------------------------------------------------------------------

register_patcher("gemini", patch_gemini)
