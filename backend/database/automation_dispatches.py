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
                "INSERT OR IGNORE INTO automation_dispatches (repo, pr_number) VALUES (?, ?)",
                (repo, pr_number),
            )
            return cursor.rowcount > 0

    def get_pending(self, limit: int) -> List[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM automation_dispatches WHERE status = 'pending' "
                "ORDER BY id ASC LIMIT ?",
                (limit,),
            )
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
            return row["attempts"] if row else 0
