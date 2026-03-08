"""Persists active agent PIDs to SQLite so orphan recovery can kill them.

Every agent subprocess registers its PID on start and unregisters on
cleanup/cancel.  On server startup, `kill_all_tracked` terminates any
leftover processes before the DB rows are cleared.
"""
from __future__ import annotations

import logging
import os
import signal

logger = logging.getLogger(__name__)


def _get_conn():
    from backend.database import get_workflow_db
    return get_workflow_db().db.connection()


def register_pid(pid: int, *, instance_id: int | None = None,
                 step_id: str | None = None, agent_name: str | None = None,
                 domain: str | None = None) -> None:
    """Record an active agent PID in the database."""
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO active_agent_pids "
                "(instance_id, step_id, pid, agent_name, domain) "
                "VALUES (?, ?, ?, ?, ?)",
                (instance_id, step_id, pid, agent_name, domain),
            )
    except Exception as e:
        logger.warning(f"pid_tracker: failed to register PID {pid}: {e}")


def unregister_pid(pid: int) -> None:
    """Remove a PID from the tracker (agent completed or was cleaned up)."""
    try:
        with _get_conn() as conn:
            conn.execute("DELETE FROM active_agent_pids WHERE pid = ?", (pid,))
    except Exception as e:
        logger.warning(f"pid_tracker: failed to unregister PID {pid}: {e}")


def kill_all_tracked() -> int:
    """Kill every tracked PID and clear the table.  Returns count killed."""
    killed = 0
    try:
        with _get_conn() as conn:
            rows = conn.execute("SELECT pid FROM active_agent_pids").fetchall()
            for (pid,) in rows:
                try:
                    os.kill(pid, signal.SIGTERM)
                    killed += 1
                    logger.info(f"pid_tracker: sent SIGTERM to orphaned PID {pid}")
                except ProcessLookupError:
                    pass
                except PermissionError:
                    logger.warning(f"pid_tracker: no permission to kill PID {pid}")
            conn.execute("DELETE FROM active_agent_pids")
    except Exception as e:
        logger.error(f"pid_tracker: kill_all_tracked failed: {e}")
    return killed
