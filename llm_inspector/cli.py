"""
cli.py — CLI for llm_inspector's traces.db.

Commands
--------
  llm-inspector list  [--limit N] [--provider NAME] [--status STATUS]
  llm-inspector show  <id_or_prefix> | --last
  llm-inspector clear [--status STATUS] [--before DAYS] [--yes]

Never imports queue_worker or any patches — standalone SQLite reader/writer.
"""

import argparse
import datetime
import json
import sqlite3
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# DB helpers (standalone — does not import the rest of the package so the
# CLI works even if the optional SDKs are not installed)
# ---------------------------------------------------------------------------

_DB_PATH = Path("llm_inspector_data") / "traces.db"


def _connect() -> sqlite3.Connection:
    if not _DB_PATH.exists():
        print(
            f"[llm-inspector] No database found at {_DB_PATH.resolve()}\n"
            "Run the package first to create it.",
            file=sys.stderr,
        )
        sys.exit(1)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _fmt_ts(unix_ts: int | None) -> str:
    """Unix timestamp → human-readable local time string."""
    if unix_ts is None:
        return "—"
    return datetime.datetime.fromtimestamp(unix_ts).strftime("%Y-%m-%d %H:%M:%S")


def _trunc(s: str | None, width: int) -> str:
    if s is None:
        return "—"
    return s if len(s) <= width else s[: width - 1] + "…"


def _pretty_json(raw: str | None) -> str:
    if raw is None:
        return "(no response captured — see error_message)"
    try:
        return json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return raw  # return as-is if it won't parse


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

# ANSI colours — gracefully disabled when stdout is not a tty
_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_RED    = "\033[91m"
_GREEN  = "\033[92m"
_YELLOW = "\033[93m"
_CYAN   = "\033[96m"
_DIM    = "\033[2m"

def _c(text: str, *codes: str) -> str:
    if not sys.stdout.isatty():
        return text
    return "".join(codes) + text + _RESET


def _status_colored(status: str) -> str:
    if status == "ok":
        return _c(status, _GREEN, _BOLD)
    return _c(status, _RED, _BOLD)


# ---------------------------------------------------------------------------
# Command: list
# ---------------------------------------------------------------------------

def _col_widths(error_mode: bool) -> tuple:
    """Return (short_id, provider, model, status, metric, timestamp)."""
    if error_mode:
        return (8, 12, 22, 7, 52, 19)
    return (8, 12, 22, 7, 10, 19)


def cmd_list(args: argparse.Namespace) -> None:
    conn = _connect()
    error_mode = (getattr(args, "status", None) == "error")

    where_clauses, params = [], []
    if args.provider:
        where_clauses.append("provider = ?")
        params.append(args.provider)
    if args.status:
        where_clauses.append("status = ?")
        params.append(args.status)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    query = f"""
        SELECT id, provider, model, status, latency_ms,
               timestamp, error_message
        FROM traces
        {where_sql}
        ORDER BY timestamp DESC
        LIMIT ?
    """
    params.append(args.limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        print("No traces found.")
        return

    # Header
    w = _col_widths(error_mode)
    metric_label = "error_message" if error_mode else "latency_ms"
    header = (
        f"{'ID':>{w[0]}}  "
        f"{'PROVIDER':<{w[1]}}  "
        f"{'MODEL':<{w[2]}}  "
        f"{'STATUS':<{w[3]}}  "
        f"{metric_label:<{w[4]}}  "
        f"{'TIMESTAMP':<{w[5]}}"
    )
    sep = "─" * len(header)
    print(_c(sep, _DIM))
    print(_c(header, _BOLD))
    print(_c(sep, _DIM))

    for row in rows:
        short_id = row["id"][:8]
        provider = _trunc(row["provider"], w[1])
        model    = _trunc(row["model"], w[2])
        ts       = _fmt_ts(row["timestamp"])

        raw_status  = row["status"]
        colored_status = _status_colored(raw_status)
        # Pad using raw length so ANSI codes don't eat into next column
        status_col  = colored_status + " " * max(0, w[3] - len(raw_status))

        colored_id  = _c(short_id, _CYAN)
        id_col      = colored_id + " " * max(0, w[0] - len(short_id))

        if error_mode:
            metric = _trunc(row["error_message"], w[4])
            metric = _c(metric, _RED) if metric != "—" else metric
        else:
            lms = row["latency_ms"]
            metric = f"{lms} ms" if lms is not None else "—"

        print(
            f"{id_col}  "
            f"{provider:<{w[1]}}  "
            f"{model:<{w[2]}}  "
            f"{status_col}  "
            f"{metric:<{w[4]}}  "
            f"{ts}"
        )

    print(_c(sep, _DIM))
    print(f"{len(rows)} row(s) shown  (--limit {args.limit})")


# ---------------------------------------------------------------------------
# Command: show
# ---------------------------------------------------------------------------

_FIELD_W = 18   # label column width in detail view


def _print_detail(row: sqlite3.Row) -> None:
    d = dict(row)
    sep  = "─" * 64
    sep2 = "╌" * 64

    print()
    print(_c(sep, _DIM))
    print(_c(f"  Trace  {d['id']}", _BOLD))
    print(_c(sep, _DIM))

    # Core metadata
    fields = [
        ("provider",          d["provider"]),
        ("model",             d["model"]),
        ("status",            _status_colored(d["status"])),
        ("timestamp",         _fmt_ts(d["timestamp"])),
        ("latency_ms",        f"{d['latency_ms']} ms" if d["latency_ms"] is not None else "—"),
        ("prompt_tokens",     str(d["prompt_tokens"])    if d["prompt_tokens"]    is not None else "—"),
        ("completion_tokens", str(d["completion_tokens"]) if d["completion_tokens"] is not None else "—"),
        ("user_id",           d["user_id"] or "—"),
    ]
    for label, value in fields:
        print(f"  {_c(label + ':', _BOLD):<{_FIELD_W + 9}}  {value}")

    # Error message (prominent if present)
    if d["status"] == "error" and d["error_message"]:
        print()
        print(f"  {_c('error_message:', _RED + _BOLD)}")
        print(f"  {_c(d['error_message'], _RED)}")

    # Request JSON
    print()
    print(_c(sep2, _DIM))
    print(_c("  request_json", _BOLD))
    print(_c(sep2, _DIM))
    print(_pretty_json(d["request_json"]))

    # Response JSON
    print()
    print(_c(sep2, _DIM))
    print(_c("  response_json", _BOLD))
    print(_c(sep2, _DIM))
    if d["response_json"] is None:
        print(_c("  (no response captured — see error_message)", _DIM))
    else:
        print(_pretty_json(d["response_json"]))

    print(_c(sep, _DIM))
    print()


def cmd_show(args: argparse.Namespace) -> None:
    conn = _connect()

    # --last shortcut (or no id given)
    id_or_prefix = getattr(args, "id_or_prefix", None)
    if args.last or not id_or_prefix:
        row = conn.execute(
            "SELECT * FROM traces ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row is None:
            print("No traces in database.", file=sys.stderr)
            sys.exit(1)
        _print_detail(row)
        return

    # Prefix / full-id lookup
    matches = conn.execute(
        "SELECT * FROM traces WHERE id LIKE ? ORDER BY timestamp DESC",
        (id_or_prefix + "%",),
    ).fetchall()
    conn.close()

    if len(matches) == 0:
        print(
            f"No trace found matching prefix {id_or_prefix!r}.",
            file=sys.stderr,
        )
        sys.exit(1)

    if len(matches) > 1:
        print(
            f"{len(matches)} traces match prefix {id_or_prefix!r}. "
            "Be more specific:",
            file=sys.stderr,
        )
        for m in matches:
            print(f"  {m['id'][:8]}  {_fmt_ts(m['timestamp'])}  {m['provider']}/{m['model']}",
                  file=sys.stderr)
        sys.exit(1)

    _print_detail(matches[0])


# ---------------------------------------------------------------------------
# Command: clear  (destructive — requires explicit confirmation)
# ---------------------------------------------------------------------------


def cmd_clear(args: argparse.Namespace) -> None:
    import time as _time  # local import to keep top-level imports minimal

    conn = _connect()

    # ---- build WHERE clause ------------------------------------------------
    where_clauses: list[str] = []
    params: list = []
    desc_parts: list[str] = []

    if args.status:
        where_clauses.append("status = ?")
        params.append(args.status)
        desc_parts.append(f"{args.status} ")

    if args.before is not None:
        if args.before <= 0:
            print("--before must be a positive number of days.", file=sys.stderr)
            conn.close()
            sys.exit(1)
        cutoff = int(_time.time()) - int(args.before * 86400)
        where_clauses.append("timestamp < ?")
        params.append(cutoff)
        desc_parts.append(f"older-than-{args.before}d ")

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    qualifier  = "".join(desc_parts).strip()   # e.g. "error older-than-7d"

    # ---- count what would be deleted ---------------------------------------
    count = conn.execute(
        f"SELECT COUNT(*) FROM traces {where_sql}", params
    ).fetchone()[0]

    if count == 0:
        noun = f"{qualifier} trace(s)" if qualifier else "trace(s)"
        print(f"No {noun} matched — nothing to delete.")
        conn.close()
        return

    # ---- confirmation ------------------------------------------------------
    noun       = f"{qualifier} trace(s)" if qualifier else "trace(s)"
    db_display = _DB_PATH.resolve()

    if not args.yes:
        try:
            answer = input(
                f"This will permanently delete {count} {noun} "
                f"from {db_display}.\nType 'yes' to confirm: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled, no rows deleted.")
            conn.close()
            sys.exit(0)

        if answer != "yes":
            print("Cancelled, no rows deleted.")
            conn.close()
            sys.exit(0)

    # ---- delete ------------------------------------------------------------
    conn.execute(f"DELETE FROM traces {where_sql}", params)
    conn.commit()

    remaining = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
    conn.close()

    print(
        _c(f"Deleted {count} {noun}. ", _RED, _BOLD)
        + f"{remaining} trace(s) remaining."
    )


# ---------------------------------------------------------------------------
# Command: ui  (starts the FastAPI dashboard)
# ---------------------------------------------------------------------------


def cmd_ui(args: argparse.Namespace) -> None:
    try:
        import uvicorn
    except ImportError:
        print(
            "uvicorn is required to run the dashboard.\n"
            "Install it with:  pip install uvicorn",
            file=sys.stderr,
        )
        sys.exit(1)

    port = args.port
    url  = f"http://localhost:{port}"

    print(f"[llm-inspector] Starting dashboard at {url}")
    print(f"[llm-inspector] Press Ctrl+C to stop.\n")

    if not args.no_browser:
        import threading
        import time
        import webbrowser

        def _open_browser() -> None:
            time.sleep(1.5)
            webbrowser.open(url)

        threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(
        "llm_inspector.server:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
    )


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-inspector",
        description="CLI for llm_inspector traces (list, inspect, clear, ui).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- list --------------------------------------------------------------
    p_list = sub.add_parser("list", help="Print a compact table of recent traces.")
    p_list.add_argument("--limit",    type=int, default=20,  metavar="N",
                        help="Max rows to show (default: 20)")
    p_list.add_argument("--provider", type=str, default=None, metavar="NAME",
                        help="Filter by provider (e.g. openai, anthropic, gemini)")
    p_list.add_argument("--status",   type=str, default=None,
                        choices=["ok", "error"],
                        help="Filter by status (ok or error)")

    # ---- show --------------------------------------------------------------
    p_show = sub.add_parser("show", help="Show full detail for one trace.")
    p_show.add_argument("id_or_prefix", nargs="?", default=None,
                        metavar="ID",
                        help="Full trace id or unique prefix (≥8 chars). "
                             "Omit to show the most recent trace.")
    p_show.add_argument("--last", action="store_true",
                        help="Show the most recent trace (same as omitting ID).")

    # ---- clear -------------------------------------------------------------
    p_clear = sub.add_parser(
        "clear",
        help="Delete traces from the database (destructive — requires confirmation).",
    )
    p_clear.add_argument(
        "--status", type=str, default=None,
        choices=["ok", "error"],
        help="Only delete traces with this status.",
    )
    p_clear.add_argument(
        "--before", type=float, default=None, metavar="DAYS",
        help="Only delete traces older than DAYS days.",
    )
    p_clear.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation prompt (for scripting/CI).",
    )

    # ---- ui ----------------------------------------------------------------
    p_ui = sub.add_parser(
        "ui",
        help="Start the web dashboard (FastAPI + uvicorn) and open a browser.",
    )
    p_ui.add_argument(
        "--port", type=int, default=8765, metavar="PORT",
        help="Port to listen on (default: 8765).",
    )
    p_ui.add_argument(
        "--no-browser", action="store_true",
        help="Don't open the browser automatically.",
    )

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "show":
        cmd_show(args)
    elif args.command == "clear":
        cmd_clear(args)
    elif args.command == "ui":
        cmd_ui(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
