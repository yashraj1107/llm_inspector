"""
openai_patch.py — Monkey-patch openai.resources.chat.completions.Completions.create
so every synchronous chat completion is captured into the llm_inspector pipeline.

Design constraints (all enforced here):
- The original exception propagates to the caller UNCHANGED on API failure.
- Capture logic is wrapped in a bare try/except so it can NEVER raise into
  the caller, even if every field extraction somehow fails.
- patch_openai() is idempotent — safe to call multiple times.
- openai is imported lazily; if it's not installed the function returns silently.
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


def patch_openai() -> None:
    """
    Replace ``openai.resources.chat.completions.Completions.create`` with a
    thin wrapper that records every successful call into the llm_inspector
    pipeline.

    Safe to call multiple times — subsequent calls are no-ops.
    Does nothing if the ``openai`` package is not installed.
    """
    global _patched  # noqa: PLW0603

    if _patched:
        return

    # ---- lazy import -------------------------------------------------------
    try:
        import openai.resources.chat.completions as _completions_mod
    except ImportError:
        return  # openai not installed — nothing to patch

    # ---- grab the real method and wrap it ----------------------------------
    _real_create = _completions_mod.Completions.create

    def _wrapped_create(self, *args, **kwargs):  # noqa: ANN001, ANN202
        start_time = time.time()

        # ----------------------------------------------------------------
        # Call the REAL method.
        # Any exception propagates to the caller EXACTLY as-is.
        # We do NOT catch API errors here — that is the caller's concern.
        # ----------------------------------------------------------------
        response = _real_create(self, *args, **kwargs)

        # ----------------------------------------------------------------
        # Capture the successful call — all field extraction is wrapped
        # so that even a completely broken response object cannot raise
        # into the caller.
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
            try:
                choice = response.choices[0]
                msg = choice.message
                resp_dict: dict = {"content": msg.content}
                # Include tool_calls if present
                if getattr(msg, "tool_calls", None):
                    resp_dict["tool_calls"] = [
                        {
                            "id":       tc.id,
                            "type":     tc.type,
                            "function": {
                                "name":      tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                response_json: str | None = json.dumps(resp_dict, default=str)
            except Exception:  # noqa: BLE001
                response_json = None

            # -- token counts --------------------------------------------
            try:
                prompt_tokens: int | None = response.usage.prompt_tokens
            except Exception:  # noqa: BLE001
                prompt_tokens = None

            try:
                completion_tokens: int | None = response.usage.completion_tokens
            except Exception:  # noqa: BLE001
                completion_tokens = None

            # -- latency -------------------------------------------------
            latency_ms = int((time.time() - start_time) * 1000)

            # -- assemble event ------------------------------------------
            event: dict = {
                "id":                str(uuid.uuid4()),
                "timestamp":         int(time.time()),
                "provider":          "openai",
                "model":             model,
                "request_json":      request_json,
                "response_json":     response_json,
                "latency_ms":        latency_ms,
                "prompt_tokens":     prompt_tokens,
                "completion_tokens": completion_tokens,
                "status":            "ok",
                "error_message":     None,
            }

            enqueue_event(event)

        except Exception:  # noqa: BLE001
            # Capture must NEVER raise into the caller.
            pass

        return response  # return the real response object unchanged

    # ---- install the wrapper -----------------------------------------------
    _completions_mod.Completions.create = _wrapped_create
    _patched = True


# ---------------------------------------------------------------------------
# Register with the central registry (runs at import time)
# ---------------------------------------------------------------------------

register_patcher("openai", patch_openai)
