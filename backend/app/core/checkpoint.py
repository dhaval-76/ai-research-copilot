"""
Durable LangGraph checkpoint store (SQLite).

Persists per-node workflow state to disk so sessions can be resumed after
a server restart or client reconnect. Uses a single long-lived sqlite3
connection for the process lifetime (see SqliteSaver docs).
"""

import os
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver

from app.core.config import get_settings

_checkpointer: SqliteSaver | None = None
_conn: sqlite3.Connection | None = None


def get_checkpointer() -> SqliteSaver:
    """Return the process-wide SqliteSaver, creating it on first use."""
    global _checkpointer, _conn
    if _checkpointer is None:
        settings = get_settings()
        db_dir = os.path.dirname(settings.checkpoint_db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        _conn = sqlite3.connect(
            settings.checkpoint_db_path,
            check_same_thread=False,
        )
        _checkpointer = SqliteSaver(_conn)
        _checkpointer.setup()
    return _checkpointer
