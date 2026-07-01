"""
anthropic_patch.py — Monkey-patch anthropic.resources.messages.Messages.create
so every synchronous message call is captured into the llm_inspector pipeline.

Follows the exact same structure as openai_patch.py:
- Idempotent via module-level _patched bool.
- Lazy import: silently no-ops if anthropic is not installed.
- Real exceptions propagate to the caller completely unchanged.
- All capture logic wrapped in an outer try/except that can never raise.

Anthropic-specific field differences vs OpenAI:
- response.content  → list of content blocks (type "text" or "tool_use")
- usage.input_tokens  → maps to prompt_tokens in the trace
- usage.output_tokens → maps to completion_tokens in the trace
"""

import json
import sys
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


def patch_anthropic() -> None:
    """
    Replace ``anthropic.resources.messages.Messages.create`` with a thin
    wrapper that records every successful call into the llm_inspector pipeline.

    Safe to call multiple times — subsequent calls are no-ops.
    Does nothing if the ``anthropic`` package is not installed.
    """
    global _patched  # noqa: PLW0603

    if _patched:
        return

    # ---- lazy import -------------------------------------------------------
    try:
        import anthropic.resources.messages as _messages_mod
    except ImportError:
        return  # anthropic not installed — nothing to patch

    # ---- grab the real method and wrap it ----------------------------------
    _real_create = _messages_mod.Messages.create

    def _wrapped_create(self, *args, **kwargs):  # noqa: ANN001, ANN202
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
        response = _real_create(self, *args, **kwargs)

        # ----------------------------------------------------------------
        # Capture the successful call.
        # All field extraction is isolated so nothing can raise into caller.
        # ----------------------------------------------------------------
        try:
            # -- model ---------------------------------------------------
            try:
                model = kwargs.get("model", "unknown") or "unknown"
            except Exception:  # noqa: BLE001
                model = "unknown"

            # -- request_json --------------------------------------------
            try:
                request_json = json.dumps(kwargs, default=str)
            except Exception:  # noqa: BLE001
                request_json = "{}"

            # -- response_json -------------------------------------------
            # response.content is a list of content blocks.
            # Each block has .type == "text" (with .text)
            #                       or "tool_use" (with .id, .name, .input)
            try:
                content_blocks = []
                for block in response.content:
                    btype = getattr(block, "type", None)
                    if btype == "text":
                        content_blocks.append({
                            "type": "text",
                            "text": getattr(block, "text", None),
                        })
                    elif btype == "tool_use":
                        content_blocks.append({
                            "type":  "tool_use",
                            "id":    getattr(block, "id", None),
                            "name":  getattr(block, "name", None),
                            "input": getattr(block, "input", None),
                        })
                    else:
                        # Unknown block type — store type only, don't crash.
                        content_blocks.append({"type": btype})
                response_json: str | None = json.dumps(
                    {"content": content_blocks}, default=str
                )
            except Exception:  # noqa: BLE001
                response_json = None

            # -- token counts (Anthropic naming) -------------------------
            try:
                prompt_tokens: int | None = response.usage.input_tokens
            except Exception:  # noqa: BLE001
                prompt_tokens = None

            try:
                completion_tokens: int | None = response.usage.output_tokens
            except Exception:  # noqa: BLE001
                completion_tokens = None

            # -- latency -------------------------------------------------
            latency_ms = int((time.time() - start_time) * 1000)

            # -- assemble event ------------------------------------------
            event: dict = {
                "id":                str(uuid.uuid4()),
                "timestamp":         int(time.time()),
                "provider":          "anthropic",
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
            }

            enqueue_event(event)

        except Exception:  # noqa: BLE001
            # Capture must NEVER raise into the caller.
            pass

        return response

    # ---- install the wrapper -----------------------------------------------
    _messages_mod.Messages.create = _wrapped_create
    _patched = True


# ---------------------------------------------------------------------------
# Register with the central registry (runs at import time)
# ---------------------------------------------------------------------------

register_patcher("anthropic", patch_anthropic)
