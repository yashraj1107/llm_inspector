import contextvars
import uuid
import time
import functools
import inspect

_current_span_stack: contextvars.ContextVar = contextvars.ContextVar(
    "llm_inspector_span_stack", default=()
)

class span:
    def __init__(self, name: str, type: str = "custom"):
        self.name = name
        self.span_type = type
        self.span_id = str(uuid.uuid4())
        self.start_time = None
        self._token = None

    def __enter__(self):
        self.start_time = time.time()
        current_stack = _current_span_stack.get()
        self._token = _current_span_stack.set(current_stack + (self,))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = int((time.time() - self.start_time) * 1000)
        failure_type = None
        status = "ok"
        if exc_type is not None:
            status = "error"
            failure_type = exc_type.__name__
        
        try:
            event = {
                "id": self.span_id,
                "timestamp": int(self.start_time),
                "provider": "span",
                "model": self.name,
                "request_json": "{}",
                "response_json": None,
                "latency_ms": duration_ms,
                "status": status,
                "error_message": str(exc_val) if exc_val else None,
                "span_type": self.span_type,
                "parent_trace_id": self._get_parent_id(),
                "root_trace_id": self._get_root_id(),
                "failure_type": failure_type,
            }
            from llm_inspector.queue_worker import enqueue_event
            enqueue_event(event)
        except Exception:
            pass  # fail-open, same discipline as every other capture path
        
        _current_span_stack.reset(self._token)
        return False  # never suppress the caller's real exception

    def _get_parent_id(self):
        stack = _current_span_stack.get()
        # stack includes self at this point (set in __enter__), so parent 
        # is the second-to-last entry if it exists
        if len(stack) >= 2:
            return stack[-2].span_id
        return None

    def _get_root_id(self):
        stack = _current_span_stack.get()
        if len(stack) >= 1:
            return stack[0].span_id
        return self.span_id  # this span IS the root

    def __call__(self, func):
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                with span(self.name, self.span_type):
                    return await func(*args, **kwargs)
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                with span(self.name, self.span_type):
                    return func(*args, **kwargs)
            return sync_wrapper


def get_current_span_id():
    """Public helper the SDK patches will use to auto-link calls (step 3)."""
    stack = _current_span_stack.get()
    return stack[-1].span_id if stack else None


def get_current_root_id():
    stack = _current_span_stack.get()
    return stack[0].span_id if stack else None
