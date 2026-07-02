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
_real_create = None
_real_async_create = None

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _detect_provider(client) -> str:
    """
    Inspect the client's base_url to determine which real provider this 
    call is actually going to. Falls back to 'openai' if base_url is 
    unset or points at OpenAI's own domain.
    """
    try:
        client_obj = getattr(client, "_client", client)
        base = str(getattr(client_obj, "base_url", "") or "").lower()
    except Exception:
        return "openai"
    
    if "deepseek.com" in base:
        return "deepseek"
    if "openai.com" in base or base == "":
        return "openai"
    if "groq.com" in base:
        return "groq"
    if "mistral.ai" in base:
        return "mistral"
    if "perplexity.ai" in base:
        return "perplexity"
    if "together.ai" in base or "togetherai" in base or "together.xyz" in base:
        return "together"
    if "openrouter.ai" in base:
        return "openrouter"
    if "fireworks.ai" in base:
        return "fireworks"
    if "localhost" in base or "127.0.0.1" in base:
        return "ollama"
    if "azure" in base or "openai.azure.com" in base:
        return "azure_openai"
    return "openai-compatible"



def patch_openai() -> None:
    """
    Replace ``openai.resources.chat.completions.Completions.create`` with a
    thin wrapper that records every successful call into the llm_inspector
    pipeline.

    Safe to call multiple times — subsequent calls are no-ops.
    Does nothing if the ``openai`` package is not installed.
    """
    global _patched, _real_create, _real_async_create  # noqa: PLW0603

    if _patched:
        return

    # ---- lazy import -------------------------------------------------------
    try:
        import openai.resources.chat.completions as _completions_mod
    except ImportError:
        return  # openai not installed — nothing to patch

    _real_create = _completions_mod.Completions.create

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
        # Call the REAL method.
        # Any exception propagates to the caller EXACTLY as-is.
        # We do NOT catch API errors here — that is the caller's concern.
        # ----------------------------------------------------------------
        response = _real_create(self, *args, **kwargs)

        is_stream = kwargs.get("stream") is True
        if is_stream:
            def _stream_generator(original_generator, start_t, client_ref):
                accumulated_content = []
                prompt_tokens, completion_tokens = None, None
                _first_token_time = None
                model = kwargs.get("model", "unknown") or "unknown"
                request_json = "{}"
                try:
                    request_json = json.dumps(kwargs, default=str)
                except Exception:
                    pass

                try:
                    for chunk in original_generator:
                        yield chunk
                        try:
                            if _first_token_time is None and hasattr(chunk, 'choices') and chunk.choices:
                                delta = getattr(chunk.choices[0], 'delta', None)
                                if delta:
                                    content = getattr(delta, 'content', None)
                                    if content:
                                        _first_token_time = time.time()
                        except Exception:
                            pass
                        try:
                            if hasattr(chunk, 'choices') and chunk.choices:
                                delta = getattr(chunk.choices[0], 'delta', None)
                                if delta:
                                    content = getattr(delta, 'content', None)
                                    if content:
                                        accumulated_content.append(content)
                            if hasattr(chunk, 'usage') and chunk.usage:
                                prompt_tokens = getattr(chunk.usage, 'prompt_tokens', None)
                                completion_tokens = getattr(chunk.usage, 'completion_tokens', None)
                        except Exception:
                            pass
                    
                    try:
                        # Latency is time until stream fully consumed
                        latency_ms = int((time.time() - start_t) * 1000)
                        
                        ttft_ms = (
                            int((_first_token_time - start_t) * 1000)
                            if _first_token_time is not None
                            else None
                        )

                        event = {
                            "id":                str(uuid.uuid4()),
                            "timestamp":         int(time.time()),
                            "provider":          _detect_provider(client_ref),
                            "model":             model,
                            "request_json":      request_json,
                            "response_json":     json.dumps({"content": "".join(accumulated_content)}, default=str),
                            "latency_ms":        latency_ms,
                            "prompt_tokens":     prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "status":            "ok",
                            "error_message":     None,
                            "parent_trace_id":   parent_trace_id,
                            "root_trace_id":     root_trace_id,
                            "span_type":         "llm_call",
                            "ttft_ms":           ttft_ms,
                        }
                        enqueue_event(event)
                    except Exception:
                        pass
                except Exception:
                    raise

            return _stream_generator(response, start_time, self)

        # ----------------------------------------------------------------
        # Capture the successful synchronous call — all field extraction is wrapped
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

            # -- tool calls ----------------------------------------------
            try:
                choice = response.choices[0]
                msg = choice.message
                tool_calls_data = None
                
                if getattr(msg, "tool_calls", None):
                    tool_calls_data = json.dumps([
                        {
                            "id":       tc.id,
                            "type":     tc.type,
                            "function": {
                                "name":      tc.function.name,
                                "arguments": tc.function.arguments,
                            }
                        }
                        for tc in msg.tool_calls
                    ], default=str)
                elif getattr(msg, "function_call", None):
                    # legacy function_call format (older OpenAI API style)
                    tool_calls_data = json.dumps([{
                        "type": "function",
                        "function": {
                            "name":      msg.function_call.name,
                            "arguments": msg.function_call.arguments,
                        }
                    }], default=str)
            except Exception:
                tool_calls_data = None

            # -- assemble event ------------------------------------------
            event: dict = {
                "id":                str(uuid.uuid4()),
                "timestamp":         int(time.time()),
                "provider":          _detect_provider(self),
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

        return response  # return the real response object unchanged

    _real_async_create = _completions_mod.AsyncCompletions.create

    import functools

    @functools.wraps(_real_async_create)
    async def _wrapped_async_create(self, *args, **kwargs):
        try:
            from llm_inspector.spans import get_current_span_id, get_current_root_id
            parent_trace_id = get_current_span_id()
            root_trace_id = get_current_root_id()
        except Exception:
            parent_trace_id = None
            root_trace_id = None

        start_time = time.time()
        response = await _real_async_create(self, *args, **kwargs)

        try:
            is_stream = kwargs.get("stream") is True
            if is_stream:
                async def _async_stream_generator(original_generator, start_t, client_ref):
                    accumulated_content = []
                    prompt_tokens, completion_tokens = None, None
                    _first_token_time = None
                    model = kwargs.get("model", "unknown") or "unknown"
                    request_json = "{}"
                    try:
                        request_json = json.dumps(kwargs, default=str)
                    except Exception:
                        pass

                    try:
                        async for chunk in original_generator:
                            yield chunk
                            try:
                                if _first_token_time is None and hasattr(chunk, 'choices') and chunk.choices:
                                    delta = getattr(chunk.choices[0], 'delta', None)
                                    if delta:
                                        content = getattr(delta, 'content', None)
                                        if content:
                                            _first_token_time = time.time()
                            except Exception:
                                pass
                            try:
                                if hasattr(chunk, 'choices') and chunk.choices:
                                    delta = getattr(chunk.choices[0], 'delta', None)
                                    if delta:
                                        content = getattr(delta, 'content', None)
                                        if content:
                                            accumulated_content.append(content)
                                if hasattr(chunk, 'usage') and chunk.usage:
                                    prompt_tokens = getattr(chunk.usage, 'prompt_tokens', None)
                                    completion_tokens = getattr(chunk.usage, 'completion_tokens', None)
                            except Exception:
                                pass
                        
                        try:
                            latency_ms = int((time.time() - start_t) * 1000)
                            ttft_ms = (
                                int((_first_token_time - start_t) * 1000)
                                if _first_token_time is not None
                                else None
                            )
                            event = {
                                "id":                str(uuid.uuid4()),
                                "timestamp":         int(time.time()),
                                "provider":          _detect_provider(client_ref),
                                "model":             model,
                                "request_json":      request_json,
                                "response_json":     json.dumps({"content": "".join(accumulated_content)}, default=str),
                                "latency_ms":        latency_ms,
                                "prompt_tokens":     prompt_tokens,
                                "completion_tokens": completion_tokens,
                                "status":            "ok",
                                "error_message":     None,
                                "parent_trace_id":   parent_trace_id,
                                "root_trace_id":     root_trace_id,
                                "span_type":         "llm_call",
                                "ttft_ms":           ttft_ms,
                            }
                            enqueue_event(event)
                        except Exception:
                            pass
                    except Exception:
                        raise
                
                return _async_stream_generator(response, start_time, self)

            # ---- non-streaming capture -------------------------------------
            try:
                model = kwargs.get("model", "unknown") or "unknown"
            except Exception:
                model = "unknown"

            try:
                request_json = json.dumps(kwargs, default=str)
            except Exception:
                request_json = "{}"

            try:
                choice = response.choices[0]
                msg = choice.message
                resp_dict: dict = {"content": msg.content}
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
            except Exception:
                response_json = None

            try:
                choice = response.choices[0]
                msg = choice.message
                tool_calls_data = None
                
                if getattr(msg, "tool_calls", None):
                    tool_calls_data = json.dumps([
                        {
                            "id":       tc.id,
                            "type":     tc.type,
                            "function": {
                                "name":      tc.function.name,
                                "arguments": tc.function.arguments,
                            }
                        }
                        for tc in msg.tool_calls
                    ], default=str)
                elif getattr(msg, "function_call", None):
                    tool_calls_data = json.dumps([{
                        "type": "function",
                        "function": {
                            "name":      msg.function_call.name,
                            "arguments": msg.function_call.arguments,
                        }
                    }], default=str)
            except Exception:
                tool_calls_data = None

            try:
                prompt_tokens = response.usage.prompt_tokens
            except Exception:
                prompt_tokens = None

            try:
                completion_tokens = response.usage.completion_tokens
            except Exception:
                completion_tokens = None

            latency_ms = int((time.time() - start_time) * 1000)

            event = {
                "id":                str(uuid.uuid4()),
                "timestamp":         int(time.time()),
                "provider":          _detect_provider(self),
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

        except Exception:
            pass

        return response

    # ---- install the wrappers -----------------------------------------------
    _completions_mod.Completions.create = _wrapped_create
    _completions_mod.AsyncCompletions.create = _wrapped_async_create
    _patched = True


# ---------------------------------------------------------------------------
# Register with the central registry (runs at import time)
# ---------------------------------------------------------------------------

register_patcher("openai", patch_openai)
