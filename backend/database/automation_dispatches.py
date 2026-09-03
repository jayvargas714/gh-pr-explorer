"""AutomationDispatchesDB - Durable ledger of automation pipeline decisions.

One row per (repo, pr_number) the pipeline has ever seen. The UNIQUE
constraint makes record_candidate the idempotence guard: a PR is
auto-dispatched at most once, surviving restarts.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

VALID_STATUSES = ("pending", "dispatched", "unidentified", "skipped", "failed")


class AutomationDispatchesDB:
    """Database operations for automation dispatch rows."""

    def __init__(self, db):
        self.db = db

    def record_candidate(self, repo: str, pr_number: int) -> bool:
        """Insert a pending row. Returns True if inserted, False if already known."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO automation_dispatches (repo, pr_number, enrolled_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP)",
                (repo, pr_number),
            )
            inserted = cursor.rowcount > 0
        if inserted:
            _mark_pipeline_dirty()
        return inserted

    def get_pending(self, limit: int) -> List[Dict[str, Any]]:
        """Pending rows, least recently evaluated first.

        Evaluation bumps updated_at (set_status / increment_attempts), so this
        round-robins the pipeline: rows waiting on conditions indefinitely
        cannot starve rows behind them out of the per-cycle window.
        """
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM automation_dispatches WHERE status = 'pending' "
                "ORDER BY updated_at ASC, id ASC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def count_pending(self) -> int:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS n FROM automation_dispatches WHERE status = 'pending'")
            return cursor.fetchone()["n"]

    def list_dispatches(self, statuses: Optional[List[str]] = None,
                        limit: Optional[int] = 200) -> List[Dict[str, Any]]:
        """Rows for the pipeline view, most recently updated first. limit=None
        returns every row (the snapshot builder wants the whole ledger)."""
        query = "SELECT * FROM automation_dispatches"
        params: List[Any] = []
        if statuses:
            for status in statuses:
                if status not in VALID_STATUSES:
                    raise ValueError(f"Invalid dispatch status: {status}")
            query += f" WHERE status IN ({','.join('?' * len(statuses))})"
            params.extend(statuses)
        query += " ORDER BY updated_at DESC, id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_by_pr(self, repo: str, pr_number: int) -> Optional[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM automation_dispatches WHERE repo = ? AND pr_number = ?",
                (repo, pr_number),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_for_prs(self, repo_pr_pairs: List[Tuple[str, int]]) -> Dict[Tuple[str, int], Dict[str, Any]]:
        """Batch lookup keyed by (repo, pr_number). Missing pairs are absent."""
        result: Dict[Tuple[str, int], Dict[str, Any]] = {}
        if not repo_pr_pairs:
            return result
        with self.db.connection() as conn:
            cursor = conn.cursor()
            placeholders = " OR ".join(["(repo = ? AND pr_number = ?)"] * len(repo_pr_pairs))
            params = [v for pair in repo_pr_pairs for v in pair]
            cursor.execute(
                f"SELECT * FROM automation_dispatches WHERE {placeholders}", params
            )
            for row in cursor.fetchall():
                result[(row["repo"], row["pr_number"])] = dict(row)
        return result

    def set_status(self, dispatch_id: int, status: str,
                   outcome_json: Optional[str] = None,
                   reviewer_key: Optional[str] = None,
                   detail: Optional[str] = None) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid dispatch status: {status}")
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE automation_dispatches
                SET status = ?,
                    outcome_json = COALESCE(?, outcome_json),
                    reviewer_key = COALESCE(?, reviewer_key),
                    detail = COALESCE(?, detail),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, outcome_json, reviewer_key, detail, dispatch_id),
            )
        _mark_pipeline_dirty()

    def requeue(self, dispatch_id: int, detail: Optional[str] = None) -> None:
        """Put a terminal row back into the pipeline: pending, attempts cleared,
        detail replaced (not COALESCEd — the old failure text must not linger),
        and the dispatch-window clock (enrolled_at) restarted."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE automation_dispatches "
                "SET status = 'pending', attempts = 0, detail = ?, "
                "updated_at = CURRENT_TIMESTAMP, enrolled_at = CURRENT_TIMESTAMP WHERE id = ?",
                (detail, dispatch_id),
            )
        _mark_pipeline_dirty()

    def reset_attempts(self, dispatch_id: int) -> None:
        """Clear the attempt counter after a clean evaluation, so transient
        errors spread over a long wait never add up to a permanent failure."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE automation_dispatches SET attempts = 0 WHERE id = ?",
                (dispatch_id,),
            )
        _mark_pipeline_dirty()

    def increment_attempts(self, dispatch_id: int) -> int:
        """Bump the attempt counter; returns the new count."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE automation_dispatches "
                "SET attempts = attempts + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (dispatch_id,),
            )
            cursor.execute(
                "SELECT attempts FROM automation_dispatches WHERE id = ?", (dispatch_id,)
            )
            row = cursor.fetchone()
        _mark_pipeline_dirty()
        return row["attempts"] if row else 0


def _mark_pipeline_dirty():
    # Imported lazily: services depend on the database package, not the reverse.
    from backend.services.pipeline_snapshot import mark_dirty
    mark_dirty()
