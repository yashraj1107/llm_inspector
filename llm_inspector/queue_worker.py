"""
queue_worker.py — In-memory queue, background worker thread, and public API
for llm_inspector.

Public surface:
    start_worker()      — idempotent; starts the daemon thread once
    enqueue_event(dict) — non-blocking put with a 0.1 s timeout; drops if full
"""

import queue
import sys
import threading
import time

from llm_inspector.storage import get_connection, write_batch

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_QUEUE_MAX_SIZE = 10_000   # bound the in-memory queue
_PUT_TIMEOUT    = 0.1      # seconds caller may block on enqueue_event
_BATCH_SIZE     = 20       # max rows per SQLite transaction
_BATCH_WINDOW   = 1.0      # max seconds to wait before flushing a partial batch
_POLL_TIMEOUT   = 0.05     # how long worker blocks on each queue.get call

# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_event_queue: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX_SIZE)
_worker_thread: threading.Thread | None = None
_worker_lock = threading.Lock()   # protects start_worker idempotency check

# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------


def _worker_loop() -> None:
    """
    Drain the queue continuously, batching events for efficient SQLite writes.

    Strategy
    --------
    - Accumulate up to _BATCH_SIZE items *or* wait at most _BATCH_WINDOW seconds
      before flushing, whichever comes first.
    - If a write fails, log a warning and carry on — never crash.
    - The thread owns a single, long-lived SQLite connection.
    """
    conn = get_connection()
    batch: list[dict] = []
    deadline = time.monotonic() + _BATCH_WINDOW

    while True:
        time_remaining = deadline - time.monotonic()

        # ---- collect one item (or notice the deadline has passed) ----------
        if time_remaining <= 0:
            # Flush whatever we have collected so far, then reset the window.
            _flush(conn, batch)
            batch = []
            deadline = time.monotonic() + _BATCH_WINDOW
            continue

        try:
            event = _event_queue.get(block=True, timeout=min(_POLL_TIMEOUT, time_remaining))
            batch.append(event)
            _event_queue.task_done()
        except queue.Empty:
            # Nothing arrived within the poll window — just loop back and
            # re-evaluate the deadline.
            pass

        # ---- flush when the batch is full ----------------------------------
        if len(batch) >= _BATCH_SIZE:
            _flush(conn, batch)
            batch = []
            deadline = time.monotonic() + _BATCH_WINDOW


def _flush(conn, batch: list[dict]) -> None:
    """Write *batch* to SQLite; swallow and log any exception."""
    if not batch:
        return
    try:
        write_batch(conn, batch)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[llm_inspector] WARNING: SQLite write failed for {len(batch)} event(s): {exc}",
            file=sys.stderr,
        )

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_worker() -> None:
    """
    Start the background worker thread.

    Idempotent — safe to call multiple times; only one thread is ever created.
    The thread is a daemon so it exits automatically when the main process ends.
    """
    global _worker_thread  # noqa: PLW0603

    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return  # already running

        _worker_thread = threading.Thread(
            target=_worker_loop,
            name="llm_inspector_worker",
            daemon=True,
        )
        _worker_thread.start()


def enqueue_event(event: dict) -> None:
    """
    Place *event* on the internal queue for async persistence.

    - Blocks the caller for at most _PUT_TIMEOUT seconds.
    - If the queue is full, the event is silently dropped with a stderr warning.
    - Never raises.
    """
    try:
        _event_queue.put(event, block=True, timeout=_PUT_TIMEOUT)
    except queue.Full:
        print(
            "[llm_inspector] WARNING: event queue is full — dropping event silently.",
            file=sys.stderr,
        )
