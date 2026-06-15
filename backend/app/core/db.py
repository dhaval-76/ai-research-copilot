"""
SQLite persistence layer.

Uses stdlib sqlite3 directly (no ORM) -- keeps dependencies minimal and
avoids version-conflict risk. Three tables:

- sessions:      one row per research session (inputs + status)
- reports:       final structured report JSON, one per completed session
- chat_messages: follow-up chat history per session

This is the "Persistence Layer" required by the spec, separate from
the in-process LangGraph MemorySaver checkpointer (see workflow.py).
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from app.core.config import get_settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    website TEXT,
    objective TEXT NOT NULL,
    research_mode TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    session_id TEXT PRIMARY KEY,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions (id)
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions (id)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn():
    settings = get_settings()
    os.makedirs(os.path.dirname(settings.database_path) or ".", exist_ok=True)
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def create_session(session_id: str, company_name: str, website: str, objective: str):
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO sessions
               (id, company_name, website, objective, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
            (session_id, company_name, website, objective, now, now),
        )


def update_session_status(
    session_id: str,
    status: str,
    research_mode: str | None = None,
    error: str | None = None,
):
    with get_conn() as conn:
        conn.execute(
            """UPDATE sessions
               SET status = ?,
                   research_mode = COALESCE(?, research_mode),
                   error = ?,
                   updated_at = ?
               WHERE id = ?""",
            (status, research_mode, error, _now(), session_id),
        )


def get_session(session_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None


def list_sessions() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def save_report(session_id: str, report: dict):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO reports (session_id, report_json, created_at)
               VALUES (?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                   report_json = excluded.report_json,
                   created_at = excluded.created_at""",
            (session_id, json.dumps(report), _now()),
        )


def get_report(session_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT report_json FROM reports WHERE session_id = ?", (session_id,)
        ).fetchone()
        return json.loads(row["report_json"]) if row else None


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


def add_chat_message(session_id: str, role: str, content: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO chat_messages (session_id, role, content, created_at)
               VALUES (?, ?, ?, ?)""",
            (session_id, role, content, _now()),
        )


def get_chat_history(session_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT role, content, created_at FROM chat_messages
               WHERE session_id = ? ORDER BY id ASC""",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]