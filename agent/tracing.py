"""Execution tracing — the "Execution Logs" deliverable.

Every Composio tool call and every agent decision is written here. The /logs
dashboard reads from this same store. Traces double as the demo-day backup:
if a live surface misbehaves, you narrate the trace instead.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from .config import settings

_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    trigger_source TEXT,
    error_title TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    summary TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    step TEXT NOT NULL,
    kind TEXT NOT NULL,            -- 'tool' | 'decision' | 'info' | 'error'
    tool_slug TEXT,
    request_json TEXT,
    response_json TEXT,
    ok INTEGER,
    note TEXT
);
"""


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success, and ALWAYS close it.

    `with sqlite3.connect(...)` only manages the transaction, not the handle —
    leaving connections open locks the DB file on Windows. This wrapper closes.
    """
    conn = sqlite3.connect(settings.trace_db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _LOCK, _connect() as conn:
        conn.executescript(_SCHEMA)


def start_incident(trigger_source: str, error_title: str) -> str:
    incident_id = uuid.uuid4().hex[:12]
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO incidents (id, created_at, trigger_source, error_title, status) "
            "VALUES (?, ?, ?, ?, 'running')",
            (incident_id, time.time(), trigger_source, error_title),
        )
    return incident_id


def finish_incident(incident_id: str, status: str, summary: str = "") -> None:
    with _LOCK, _connect() as conn:
        conn.execute(
            "UPDATE incidents SET status = ?, summary = ? WHERE id = ?",
            (status, summary, incident_id),
        )


def _safe(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str)[:20000]
    except Exception:
        return json.dumps(str(obj))


def log_event(
    incident_id: str,
    step: str,
    kind: str,
    *,
    tool_slug: str | None = None,
    request: Any = None,
    response: Any = None,
    ok: bool | None = None,
    note: str = "",
) -> None:
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO events "
            "(incident_id, created_at, step, kind, tool_slug, request_json, response_json, ok, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                incident_id,
                time.time(),
                step,
                kind,
                tool_slug,
                _safe(request) if request is not None else None,
                _safe(response) if response is not None else None,
                None if ok is None else int(ok),
                note,
            ),
        )


def list_incidents(limit: int = 50) -> list[dict]:
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM incidents ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_events(incident_id: str) -> list[dict]:
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE incident_id = ? ORDER BY id ASC", (incident_id,)
        ).fetchall()
    return [dict(r) for r in rows]


@contextmanager
def timed_step(incident_id: str, step: str) -> Iterator[None]:
    start = time.time()
    try:
        yield
    finally:
        log_event(
            incident_id,
            step,
            "info",
            note=f"step '{step}' took {time.time() - start:.2f}s",
        )
