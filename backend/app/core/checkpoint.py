"""
Durable LangGraph checkpoint store (Postgres).

Persists per-node workflow state so sessions can be resumed after a
server restart or client reconnect. Backed by a psycopg ConnectionPool
(not a single bare connection) -- PostgresSaver.from_conn_string()'s
context-manager pattern was tried first and closed its connection
unexpectedly under FastAPI's request lifecycle (connection is closed
errors on later requests). A pool sidesteps that: PostgresSaver gets a
fresh, valid connection per operation, and the pool transparently
reconnects if Postgres drops a connection for any reason -- the same
pattern already used for the primary app DB (see db.py).

Uses settings.resolved_checkpoint_database_url, which is a distinct
Postgres connection string from the primary app DB (database_url) when
CHECKPOINT_DATABASE_URL is set -- lets checkpoint storage be scaled,
backed up, or hosted separately from session/report/chat data. Falls
back to database_url (same instance) if unset.
"""

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool

from app.core.config import get_settings

_checkpointer: PostgresSaver | None = None
_pool: ConnectionPool | None = None


def get_checkpointer() -> PostgresSaver:
    """Return the process-wide PostgresSaver, creating it on first use."""
    global _checkpointer, _pool
    if _checkpointer is None:
        settings = get_settings()
        _pool = ConnectionPool(
            conninfo=settings.resolved_checkpoint_database_url,
            min_size=1,
            max_size=10,
            kwargs={"autocommit": True, "prepare_threshold": 0},
            open=True,
        )
        _checkpointer = PostgresSaver(_pool)
        _checkpointer.setup()
    return _checkpointer