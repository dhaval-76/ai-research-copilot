"""
SQLite persistence layer.

Uses stdlib sqlite3 directly (no ORM) -- keeps dependencies minimal and
avoids version-conflict risk. Four tables:

- sessions:        one row per research session (inputs + status)
- reports:         final structured report JSON, one per completed session
- chat_messages:   follow-up chat history per session
- progress_events: workflow SSE trace per session (survives reconnect)

This stores session metadata and completed reports. In-progress workflow
state is checkpointed separately by LangGraph's SqliteSaver (see
workflow.py / checkpoint.py).

Type decisions:
- Timestamps: INTEGER (Unix epoch / seconds UTC).
  Rationale: enables correct ORDER BY and range queries without string
  parsing; avoids ISO-format ambiguity across locales; consistent with
  how SQLite date functions work natively. Converted to/from
  datetime at the DB boundary (_now() / _to_ts() / _from_ts()).

- status / role / research_mode: TEXT with CHECK constraints.
  SQLite has no enum type; CHECK enforces the allowed set at the
  storage layer so bad values can't be inserted even if the
  application layer has a bug.

- done (progress_events): INTEGER (0/1 boolean). SQLite has no
  BOOLEAN type; INTEGER is the idiomatic representation.

- id (sessions): TEXT (UUID). No native UUID type in SQLite.

- report_json: TEXT (JSON blob). No native JSON column in SQLite
  (JSON1 functions work on TEXT); this is correct.
"""

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from app.core.config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class SessionAlreadyExistsError(Exception):
    """Raised when create_session hits the unique inputs constraint."""

    def __init__(self, session_id: str, status: str):
        self.session_id = session_id
        self.status = status
        super().__init__(session_id)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id               TEXT    PRIMARY KEY,
    company_name     TEXT    NOT NULL,
    website          TEXT    NOT NULL DEFAULT '',
    objective        TEXT    NOT NULL,
    company_key      TEXT    NOT NULL DEFAULT '',
    website_key      TEXT    NOT NULL DEFAULT '',
    objective_key    TEXT    NOT NULL DEFAULT '',
    research_mode    TEXT    CHECK (research_mode IN ('sales','investment','competitive','general')),
    status           TEXT    NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending','running','completed','failed')),
    error            TEXT,
    created_at       INTEGER NOT NULL,
    updated_at       INTEGER NOT NULL,
    UNIQUE (company_key, website_key, objective_key)
);

CREATE TABLE IF NOT EXISTS reports (
    session_id   TEXT    PRIMARY KEY,
    report_json  TEXT    NOT NULL,
    created_at   INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions (id)
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT    NOT NULL,
    role         TEXT    NOT NULL CHECK (role IN ('user','assistant')),
    content      TEXT    NOT NULL,
    created_at   INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions (id)
);

CREATE TABLE IF NOT EXISTS progress_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT    NOT NULL,
    node         TEXT    NOT NULL,
    status       TEXT    NOT NULL,
    done         INTEGER NOT NULL DEFAULT 0 CHECK (done IN (0,1)),
    error        TEXT,
    created_at   INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions (id)
);
"""


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def _now() -> int:
    """Current time as Unix epoch (seconds, UTC)."""
    return int(datetime.now(timezone.utc).timestamp())


def _from_ts(ts: int | None) -> str | None:
    """Convert stored epoch int to ISO-8601 string for API responses."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    """
    Convert a sqlite3.Row to a plain dict, serializing INTEGER timestamp
    columns (created_at, updated_at) to ISO-8601 strings so the rest of
    the app (and the API layer) keeps working with string timestamps
    exactly as before -- the conversion is transparent above this layer.
    """
    d = dict(row)
    for col in ("created_at", "updated_at"):
        if col in d and isinstance(d[col], int):
            d[col] = _from_ts(d[col])
    return d


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

@contextmanager
def get_conn():
    settings = get_settings()
    db_dir = os.path.dirname(settings.database_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    # Enforce foreign key constraints (off by default in SQLite)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Init + migrations
# ---------------------------------------------------------------------------

def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection):
    """
    Idempotent migration: add missing columns, backfill timestamps from
    ISO strings to INTEGER epoch, normalise session keys, dedupe, then
    create the unique index if missing.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}

    # --- add columns added after initial deploy ---
    for col, definition in [
        ("company_key", "TEXT NOT NULL DEFAULT ''"),
        ("website_key", "TEXT NOT NULL DEFAULT ''"),
        ("objective_key", "TEXT NOT NULL DEFAULT ''"),
    ]:
        if col not in columns:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} {definition}")

    # --- backfill NULL websites ---
    conn.execute("UPDATE sessions SET website = '' WHERE website IS NULL")

    # --- migrate TEXT timestamps -> INTEGER epoch in sessions ---
    _migrate_timestamps(conn, "sessions", ["created_at", "updated_at"])

    # --- migrate TEXT timestamps -> INTEGER epoch in other tables ---
    _migrate_timestamps(conn, "reports", ["created_at"])
    _migrate_timestamps(conn, "chat_messages", ["created_at"])
    _migrate_timestamps(conn, "progress_events", ["created_at"])

    # --- backfill normalised session keys ---
    rows = conn.execute(
        "SELECT id, company_name, website, objective FROM sessions"
    ).fetchall()
    for row in rows:
        company, site, obj = normalize_session_inputs(
            row["company_name"], row["website"] or "", row["objective"]
        )
        ck, wk, ok = session_input_keys(
            row["company_name"], row["website"] or "", row["objective"]
        )
        conn.execute(
            """UPDATE sessions
               SET company_name=?, website=?, objective=?,
                   company_key=?, website_key=?, objective_key=?
               WHERE id=?""",
            (company, site, obj, ck, wk, ok, row["id"]),
        )

    removed = _dedupe_sessions(conn)
    if removed:
        logger.warning("Removed %d duplicate session(s) during migration", removed)

    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_unique_inputs
           ON sessions (company_key, website_key, objective_key)"""
    )


def _migrate_timestamps(
    conn: sqlite3.Connection, table: str, cols: list[str]
) -> None:
    """
    For each column: if any row holds a TEXT value (ISO string from old
    schema), convert it to INTEGER epoch in-place. Rows already holding
    INTEGER are left untouched. NULL values are set to the current time.

    Uses each table's actual primary key (not SQLite's implicit `rowid`)
    to target the UPDATE -- `rowid` access via sqlite3.Row is unreliable
    across table layouts (e.g. tables with an explicit
    INTEGER PRIMARY KEY alias the rowid under that column's name, not
    under "rowid").
    """
    pk_column = _PRIMARY_KEY_COLUMN[table]
    table_cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}

    for col in cols:
        if col not in table_cols:
            continue
        rows = conn.execute(f"SELECT {pk_column}, {col} FROM {table}").fetchall()
        for row in rows:
            pk_value = row[pk_column]
            val = row[col]
            if val is None:
                conn.execute(
                    f"UPDATE {table} SET {col}=? WHERE {pk_column}=?",
                    (_now(), pk_value),
                )
            elif isinstance(val, str):
                try:
                    dt = datetime.fromisoformat(val)
                    epoch = int(dt.timestamp())
                except ValueError:
                    epoch = _now()
                conn.execute(
                    f"UPDATE {table} SET {col}=? WHERE {pk_column}=?",
                    (epoch, pk_value),
                )
            # already int -- no action needed


# Each table's actual primary key column, used by _migrate_timestamps
# to target updates without relying on SQLite's implicit rowid.
_PRIMARY_KEY_COLUMN = {
    "sessions": "id",
    "reports": "session_id",
    "chat_messages": "id",
    "progress_events": "id",
}


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
               WHERE company_key=? AND website_key=? AND objective_key=?
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
    status_rank = {"completed": 4, "running": 3, "failed": 2, "pending": 1}
    scored = []
    for row in rows:
        has_report = conn.execute(
            "SELECT 1 FROM reports WHERE session_id=? LIMIT 1", (row["id"],)
        ).fetchone()
        scored.append((
            1 if has_report else 0,
            status_rank.get(row["status"], 0),
            row["updated_at"],
            row["created_at"],
            row,
        ))
    scored.sort(reverse=True)
    return scored[0][4]


def _delete_session(conn: sqlite3.Connection, session_id: str):
    for table in ("progress_events", "chat_messages", "reports", "sessions"):
        conn.execute(f"DELETE FROM {table} WHERE session_id=?", (session_id,))


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

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
    company, site, obj = normalize_session_inputs(company_name, website, objective)
    return company.lower(), site, obj.lower()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def find_session_by_inputs(
    company_name: str, website: str, objective: str
) -> dict | None:
    """Canonical keys used for uniqueness checks and the DB constraint."""
    ck, wk, ok = session_input_keys(company_name, website, objective)
    with get_conn() as conn:
        row = conn.execute(
            """SELECT * FROM sessions
               WHERE company_key=? AND website_key=? AND objective_key=?
               LIMIT 1""",
            (ck, wk, ok),
        ).fetchone()
        return _row_to_dict(row) if row else None


def create_session(
    session_id: str, company_name: str, website: str, objective: str
):
    company, site, obj = normalize_session_inputs(company_name, website, objective)
    ck, wk, ok = session_input_keys(company_name, website, objective)
    now = _now()
    with get_conn() as conn:
        try:
            conn.execute(
                """INSERT INTO sessions
                   (id, company_name, website, objective,
                    company_key, website_key, objective_key,
                    status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,'pending',?,?)""",
                (session_id, company, site, obj, ck, wk, ok, now, now),
            )
        except sqlite3.IntegrityError as exc:
            row = conn.execute(
                """SELECT id, status FROM sessions
                   WHERE company_key=? AND website_key=? AND objective_key=?
                   LIMIT 1""",
                (ck, wk, ok),
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
               SET status=?,
                   research_mode=COALESCE(?, research_mode),
                   error=?,
                   updated_at=?
               WHERE id=?""",
            (status, research_mode, error, _now(), session_id),
        )


def reset_session(session_id: str):
    """Clear outputs and reset a session so research can run again from scratch."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE sessions
               SET status='pending', research_mode=NULL,
                   error=NULL, updated_at=?
               WHERE id=?""",
            (_now(), session_id),
        )
        for table in ("reports", "chat_messages", "progress_events"):
            conn.execute(
                f"DELETE FROM {table} WHERE session_id=?", (session_id,)
            )


def get_session(session_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        return _row_to_dict(row) if row else None


def list_sessions() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def save_report(session_id: str, report: dict):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO reports (session_id, report_json, created_at)
               VALUES (?,?,?)
               ON CONFLICT(session_id) DO UPDATE SET
                   report_json=excluded.report_json,
                   created_at=excluded.created_at""",
            (session_id, json.dumps(report), _now()),
        )


def get_report(session_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT report_json FROM reports WHERE session_id=?", (session_id,)
        ).fetchone()
        return json.loads(row["report_json"]) if row else None


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

def add_chat_message(session_id: str, role: str, content: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO chat_messages (session_id, role, content, created_at)
               VALUES (?,?,?,?)""",
            (session_id, role, content, _now()),
        )


def get_chat_history(session_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT role, content, created_at FROM chat_messages
               WHERE session_id=? ORDER BY id ASC""",
            (session_id,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Workflow progress events
# ---------------------------------------------------------------------------

def add_progress_event(session_id: str, event: dict):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO progress_events
               (session_id, node, status, done, error, created_at)
               VALUES (?,?,?,?,?,?)""",
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
               WHERE session_id=? ORDER BY id ASC""",
            (session_id,),
        ).fetchall()
        events = []
        for row in rows:
            event: dict = {
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
            "DELETE FROM progress_events WHERE session_id=?", (session_id,)
        )