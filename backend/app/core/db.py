"""
PostgreSQL persistence layer.

Uses psycopg3 directly (no ORM) -- keeps the dependency surface small
and the SQL explicit. A single process-wide connection pool is created
on first use and reused across requests (FastAPI is multi-request,
single-process by default with uvicorn; the pool handles concurrent
requests safely).

Four tables:

- sessions:        one row per research session (inputs + status)
- reports:         final structured report JSON, one per completed session
- chat_messages:   follow-up chat history per session
- progress_events: workflow SSE trace per session (survives reconnect)

This stores session metadata and completed reports. In-progress workflow
state is checkpointed separately by LangGraph's SqliteSaver (see
workflow.py / checkpoint.py).

Migrated from SQLite (see git history) for deployment readiness:
SQLite's single-writer model and file-based storage don't suit a
deployed, possibly multi-instance backend. Postgres also gives us real
types instead of SQLite's TEXT-everything affinity system:

- created_at / updated_at: TIMESTAMPTZ (was: TEXT, then INTEGER epoch
  in the SQLite version). Native timestamp type -- no manual epoch
  conversion needed, comparisons/ordering work directly, timezone-aware.
- status / research_mode / role: TEXT + CHECK constraint (Postgres has
  a real ENUM type too, but CHECK is simpler to evolve without a
  migration when new values are added).
- done (progress_events): BOOLEAN (was: INTEGER 0/1 in SQLite, which
  has no boolean type).
- id (sessions): TEXT (UUID). Could use Postgres's native UUID type;
  kept as TEXT for now since session IDs are generated app-side as
  str(uuid.uuid4()) and read/written as plain strings throughout the
  API layer -- revisit if this needs DB-level UUID validation.
- report_json: JSONB (was: TEXT in SQLite). Native JSON type with
  indexing/query support if ever needed; psycopg adapts dict<->JSONB
  automatically.
"""

import logging
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

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
    id               TEXT        PRIMARY KEY,
    company_name     TEXT        NOT NULL,
    website          TEXT        NOT NULL DEFAULT '',
    objective        TEXT        NOT NULL,
    company_key      TEXT        NOT NULL DEFAULT '',
    website_key      TEXT        NOT NULL DEFAULT '',
    objective_key    TEXT        NOT NULL DEFAULT '',
    research_mode    TEXT        CHECK (research_mode IN ('sales','investment','competitive','general')),
    status           TEXT        NOT NULL DEFAULT 'pending'
                                  CHECK (status IN ('pending','running','completed','failed')),
    error            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (company_key, website_key, objective_key)
);

CREATE TABLE IF NOT EXISTS reports (
    session_id   TEXT        PRIMARY KEY REFERENCES sessions (id),
    report_json  JSONB       NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id           SERIAL      PRIMARY KEY,
    session_id   TEXT        NOT NULL REFERENCES sessions (id),
    role         TEXT        NOT NULL CHECK (role IN ('user','assistant')),
    content      TEXT        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS progress_events (
    id           SERIAL      PRIMARY KEY,
    session_id   TEXT        NOT NULL REFERENCES sessions (id),
    node         TEXT        NOT NULL,
    status       TEXT        NOT NULL,
    done         BOOLEAN     NOT NULL DEFAULT false,
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row},
        )
    return _pool


@contextmanager
def get_conn():
    pool = _get_pool()
    with pool.connection() as conn:
        yield conn


def _iso(value) -> str | None:
    """Serialize a TIMESTAMPTZ value (datetime) to ISO-8601 string for
    API responses -- keeps the API contract unchanged regardless of
    backing DB."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _row_to_dict(row: dict | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for col in ("created_at", "updated_at"):
        if col in d:
            d[col] = _iso(d[col])
    return d


# ---------------------------------------------------------------------------
# Init + migrations
# ---------------------------------------------------------------------------


def init_db():
    with get_conn() as conn:
        print(conn.execute("""
            SELECT
                inet_server_addr(),
                inet_server_port(),
                version(),
                current_database()
        """).fetchone())
        print(conn.execute("""
            SELECT nspname
            FROM pg_namespace
            ORDER BY nspname
        """).fetchall())
        print(conn.execute("""
            SELECT
                n.nspname,
                pg_catalog.pg_get_userbyid(n.nspowner) AS owner
            FROM pg_namespace n
            WHERE n.nspname='app'
        """).fetchall())
        print(conn.execute("""
            SELECT current_user
        """).fetchone())
        print(conn.execute("SELECT current_database()").fetchone())
        print(conn.execute("SHOW search_path").fetchone())
        print(conn.execute("SELECT current_schema()").fetchone())
        print(conn.execute("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name='app'
        """).fetchone())
        conn.execute(SCHEMA)
        _migrate(conn)
        conn.commit()


def _migrate(conn: psycopg.Connection):
    """
    Idempotent migration: add any columns introduced after initial
    deploy, normalise+backfill session keys, dedupe, then ensure the
    unique index exists. Schema-level additions (CREATE TABLE IF NOT
    EXISTS, columns already in SCHEMA) are handled by executing SCHEMA
    directly; this only handles things SCHEMA can't (backfills, ALTERs
    for columns added in a later revision than the running DB).
    """
    existing_cols = {
        row["column_name"]
        for row in conn.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_name = 'sessions'"""
        ).fetchall()
    }
    for col, ddl in [
        ("company_key", "TEXT NOT NULL DEFAULT ''"),
        ("website_key", "TEXT NOT NULL DEFAULT ''"),
        ("objective_key", "TEXT NOT NULL DEFAULT ''"),
    ]:
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} {ddl}")

    conn.execute("UPDATE sessions SET website = '' WHERE website IS NULL")

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
               SET company_name=%s, website=%s, objective=%s,
                   company_key=%s, website_key=%s, objective_key=%s
               WHERE id=%s""",
            (company, site, obj, ck, wk, ok, row["id"]),
        )

    removed = _dedupe_sessions(conn)
    if removed:
        logger.warning("Removed %d duplicate session(s) during migration", removed)

    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_unique_inputs
           ON sessions (company_key, website_key, objective_key)"""
    )


def _dedupe_sessions(conn: psycopg.Connection) -> int:
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
               WHERE company_key=%s AND website_key=%s AND objective_key=%s
               ORDER BY created_at ASC""",
            (group["company_key"], group["website_key"], group["objective_key"]),
        ).fetchall()
        keeper = _pick_canonical_session(conn, rows)
        for row in rows:
            if row["id"] != keeper["id"]:
                _delete_session(conn, row["id"])
                removed += 1
    return removed


def _pick_canonical_session(conn: psycopg.Connection, rows: list[dict]) -> dict:
    """Prefer the most complete session when deduplicating legacy rows."""
    status_rank = {"completed": 4, "running": 3, "failed": 2, "pending": 1}
    scored = []
    for row in rows:
        has_report = conn.execute(
            "SELECT 1 FROM reports WHERE session_id=%s LIMIT 1", (row["id"],)
        ).fetchone()
        scored.append((
            1 if has_report else 0,
            status_rank.get(row["status"], 0),
            row["updated_at"],
            row["created_at"],
            row,
        ))
    scored.sort(reverse=True, key=lambda t: t[:4])
    return scored[0][4]


def _delete_session(conn: psycopg.Connection, session_id: str):
    for table in ("progress_events", "chat_messages", "reports", "sessions"):
        conn.execute(f"DELETE FROM {table} WHERE session_id=%s", (session_id,))


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
               WHERE company_key=%s AND website_key=%s AND objective_key=%s
               LIMIT 1""",
            (ck, wk, ok),
        ).fetchone()
        return _row_to_dict(row)


def create_session(session_id: str, company_name: str, website: str, objective: str):
    company, site, obj = normalize_session_inputs(company_name, website, objective)
    ck, wk, ok = session_input_keys(company_name, website, objective)
    with get_conn() as conn:
        try:
            conn.execute(
                """INSERT INTO sessions
                   (id, company_name, website, objective,
                    company_key, website_key, objective_key, status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'pending')""",
                (session_id, company, site, obj, ck, wk, ok),
            )
            conn.commit()
        except psycopg.errors.UniqueViolation:
            conn.rollback()
            row = conn.execute(
                """SELECT id, status FROM sessions
                   WHERE company_key=%s AND website_key=%s AND objective_key=%s
                   LIMIT 1""",
                (ck, wk, ok),
            ).fetchone()
            if row:
                raise SessionAlreadyExistsError(row["id"], row["status"])
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
               SET status=%s,
                   research_mode=COALESCE(%s, research_mode),
                   error=%s,
                   updated_at=now()
               WHERE id=%s""",
            (status, research_mode, error, session_id),
        )
        conn.commit()


def reset_session(session_id: str):
    """Clear outputs and reset a session so research can run again from scratch."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE sessions
               SET status='pending', research_mode=NULL,
                   error=NULL, updated_at=now()
               WHERE id=%s""",
            (session_id,),
        )
        for table in ("reports", "chat_messages", "progress_events"):
            conn.execute(f"DELETE FROM {table} WHERE session_id=%s", (session_id,))
        conn.commit()


def get_session(session_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id=%s", (session_id,)
        ).fetchone()
        return _row_to_dict(row)


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
            """INSERT INTO reports (session_id, report_json)
               VALUES (%s,%s)
               ON CONFLICT (session_id) DO UPDATE SET
                   report_json=excluded.report_json,
                   created_at=now()""",
            (session_id, psycopg.types.json.Json(report)),
        )
        conn.commit()


def get_report(session_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT report_json FROM reports WHERE session_id=%s", (session_id,)
        ).fetchone()
        return row["report_json"] if row else None


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


def add_chat_message(session_id: str, role: str, content: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO chat_messages (session_id, role, content)
               VALUES (%s,%s,%s)""",
            (session_id, role, content),
        )
        conn.commit()


def get_chat_history(session_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT role, content, created_at FROM chat_messages
               WHERE session_id=%s ORDER BY id ASC""",
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
               (session_id, node, status, done, error)
               VALUES (%s,%s,%s,%s,%s)""",
            (
                session_id,
                event["node"],
                event.get("status", ""),
                bool(event.get("done")),
                event.get("error"),
            ),
        )
        conn.commit()


def get_progress_events(session_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT node, status, done, error FROM progress_events
               WHERE session_id=%s ORDER BY id ASC""",
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
            "DELETE FROM progress_events WHERE session_id=%s", (session_id,)
        )
        conn.commit()