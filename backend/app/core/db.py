"""
SQLite persistence layer.

Uses stdlib sqlite3 directly (no ORM) -- keeps dependencies minimal and
avoids version-conflict risk. Three tables:

- sessions:        one row per research session (inputs + status)
- reports:         final structured report JSON, one per completed session
- chat_messages:   follow-up chat history per session
- progress_events: workflow SSE trace per session (survives reconnect)

This stores session metadata and completed reports. In-progress workflow
state is checkpointed separately by LangGraph's SqliteSaver (see
workflow.py / checkpoint.py).
"""

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class SessionAlreadyExistsError(Exception):
    """Raised when create_session hits the unique inputs constraint."""

    def __init__(self, session_id: str, status: str):
        self.session_id = session_id
        self.status = status
        super().__init__(session_id)


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    website TEXT NOT NULL DEFAULT '',
    objective TEXT NOT NULL,
    company_key TEXT NOT NULL DEFAULT '',
    website_key TEXT NOT NULL DEFAULT '',
    objective_key TEXT NOT NULL DEFAULT '',
    research_mode TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (company_key, website_key, objective_key)
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

CREATE TABLE IF NOT EXISTS progress_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    node TEXT NOT NULL,
    status TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    error TEXT,
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
        _migrate_sessions(conn)


def normalize_session_inputs(
    company_name: str, website: str, objective: str
) -> tuple[str, str, str]:
    """Normalize session inputs for storage."""
    return (
        company_name.strip(),
        website.strip().rstrip("/").lower(),
        objective.strip(),
    )


def session_input_keys(
    company_name: str, website: str, objective: str
) -> tuple[str, str, str]:
    """Canonical keys used for uniqueness checks and the DB constraint."""
    company, site, objective_text = normalize_session_inputs(
        company_name, website, objective
    )
    return company.lower(), site, objective_text.lower()


def _migrate_sessions(conn: sqlite3.Connection):
    """Backfill normalized keys and enforce uniqueness on existing databases."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}

    if "company_key" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN company_key TEXT")
        conn.execute("ALTER TABLE sessions ADD COLUMN website_key TEXT")
        conn.execute("ALTER TABLE sessions ADD COLUMN objective_key TEXT")

    conn.execute(
        "UPDATE sessions SET website = '' WHERE website IS NULL"
    )

    rows = conn.execute(
        "SELECT id, company_name, website, objective FROM sessions"
    ).fetchall()
    for row in rows:
        company, site, objective = normalize_session_inputs(
            row["company_name"],
            row["website"] or "",
            row["objective"],
        )
        company_key, website_key, objective_key = session_input_keys(
            row["company_name"],
            row["website"] or "",
            row["objective"],
        )
        conn.execute(
            """UPDATE sessions
               SET company_name = ?,
                   website = ?,
                   objective = ?,
                   company_key = ?,
                   website_key = ?,
                   objective_key = ?
               WHERE id = ?""",
            (
                company,
                site,
                objective,
                company_key,
                website_key,
                objective_key,
                row["id"],
            ),
        )

    removed = _dedupe_sessions(conn)
    if removed:
        logger.warning(
            "Removed %d duplicate session(s) while applying uniqueness migration",
            removed,
        )

    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_unique_inputs
           ON sessions (company_key, website_key, objective_key)"""
    )


def _dedupe_sessions(conn: sqlite3.Connection) -> int:
    """Keep one canonical row per input triple; delete the rest."""
    groups = conn.execute(
        """SELECT company_key, website_key, objective_key
           FROM sessions
           GROUP BY company_key, website_key, objective_key
           HAVING COUNT(*) > 1"""
    ).fetchall()

    removed = 0
    for group in groups:
        rows = conn.execute(
            """SELECT * FROM sessions
               WHERE company_key = ? AND website_key = ? AND objective_key = ?
               ORDER BY created_at ASC""",
            (group["company_key"], group["website_key"], group["objective_key"]),
        ).fetchall()
        keeper = _pick_canonical_session(conn, rows)
        for row in rows:
            if row["id"] != keeper["id"]:
                _delete_session(conn, row["id"])
                removed += 1
    return removed


def _pick_canonical_session(
    conn: sqlite3.Connection, rows: list[sqlite3.Row]
) -> sqlite3.Row:
    """Prefer the most complete session when deduplicating legacy rows."""
    status_rank = {
        "completed": 4,
        "running": 3,
        "failed": 2,
        "pending": 1,
    }
    scored = []
    for row in rows:
        report = conn.execute(
            "SELECT 1 FROM reports WHERE session_id = ? LIMIT 1",
            (row["id"],),
        ).fetchone()
        scored.append(
            (
                1 if report else 0,
                status_rank.get(row["status"], 0),
                row["updated_at"],
                row["created_at"],
                row,
            )
        )
    scored.sort(reverse=True)
    return scored[0][4]


def _delete_session(conn: sqlite3.Connection, session_id: str):
    conn.execute("DELETE FROM progress_events WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM reports WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def find_session_by_inputs(
    company_name: str, website: str, objective: str
) -> dict | None:
    company_key, website_key, objective_key = session_input_keys(
        company_name, website, objective
    )
    with get_conn() as conn:
        row = conn.execute(
            """SELECT * FROM sessions
               WHERE company_key = ? AND website_key = ? AND objective_key = ?
               LIMIT 1""",
            (company_key, website_key, objective_key),
        ).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def create_session(session_id: str, company_name: str, website: str, objective: str):
    company, site, objective_text = normalize_session_inputs(
        company_name, website, objective
    )
    company_key, website_key, objective_key = session_input_keys(
        company_name, website, objective
    )
    now = _now()
    with get_conn() as conn:
        try:
            conn.execute(
                """INSERT INTO sessions
                   (id, company_name, website, objective,
                    company_key, website_key, objective_key,
                    status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    session_id,
                    company,
                    site,
                    objective_text,
                    company_key,
                    website_key,
                    objective_key,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            row = conn.execute(
                """SELECT id, status FROM sessions
                   WHERE company_key = ? AND website_key = ? AND objective_key = ?
                   LIMIT 1""",
                (company_key, website_key, objective_key),
            ).fetchone()
            if row:
                raise SessionAlreadyExistsError(row["id"], row["status"]) from exc
            raise


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


def reset_session(session_id: str):
    """Clear outputs and reset a session so research can run again from scratch."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE sessions
               SET status = 'pending',
                   research_mode = NULL,
                   error = NULL,
                   updated_at = ?
               WHERE id = ?""",
            (_now(), session_id),
        )
        conn.execute("DELETE FROM reports WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM progress_events WHERE session_id = ?", (session_id,))


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


# ---------------------------------------------------------------------------
# Workflow progress events
# ---------------------------------------------------------------------------


def add_progress_event(session_id: str, event: dict):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO progress_events
               (session_id, node, status, done, error, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                event["node"],
                event.get("status", ""),
                1 if event.get("done") else 0,
                event.get("error"),
                _now(),
            ),
        )


def get_progress_events(session_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT node, status, done, error FROM progress_events
               WHERE session_id = ? ORDER BY id ASC""",
            (session_id,),
        ).fetchall()
        events = []
        for row in rows:
            event = {
                "node": row["node"],
                "status": row["status"],
                "done": bool(row["done"]),
            }
            if row["error"]:
                event["error"] = row["error"]
            events.append(event)
        return events


def clear_progress_events(session_id: str):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM progress_events WHERE session_id = ?",
            (session_id,),
        )