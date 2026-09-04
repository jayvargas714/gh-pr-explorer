"""ReviewRequestsDB - Follow-up demand ledger for GitHub review requests.

One row per (repo, pr_number). A row is created when a human requests a review
from the authenticated user on a PR the pipeline has already dispatched; the
dispatch worker fulfils it with a follow-up review once the dispatch gates
hold. A later re-request revives a terminal row (fulfilled/skipped/failed) back
to pending with a fresh requested_at — the dispatch-window clock.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

VALID_STATUSES = ("pending", "fulfilled", "skipped", "failed")


class ReviewRequestsDB:
    """Database operations for review-request rows."""

    def __init__(self, db):
        self.db = db

    def record(self, repo: str, pr_number: int) -> bool:
        """Register a review request. Inserts a pending row, or revives a
        terminal one (attempts/detail cleared, clock restarted).
        Returns False when a pending row already exists (nothing changed)."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, status FROM review_requests WHERE repo = ? AND pr_number = ?",
                (repo, pr_number),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    "INSERT INTO review_requests (repo, pr_number, requested_at) "
                    "VALUES (?, ?, CURRENT_TIMESTAMP)",
                    (repo, pr_number),
                )
            elif row["status"] == "pending":
                return False
            else:
                cursor.execute(
                    "UPDATE review_requests "
                    "SET status = 'pending', attempts = 0, detail = NULL, "
                    "requested_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (row["id"],),
                )
        _mark_pipeline_dirty()
        return True

    def get_pending(self, limit: int) -> List[Dict[str, Any]]:
        """Pending rows, least recently evaluated first (set_status bumps
        updated_at, so waiters round-robin like dispatch rows)."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM review_requests WHERE status = 'pending' "
                "ORDER BY updated_at ASC, id ASC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def count_pending(self) -> int:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS n FROM review_requests WHERE status = 'pending'")
            return cursor.fetchone()["n"]

    def get_by_pr(self, repo: str, pr_number: int) -> Optional[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM review_requests WHERE repo = ? AND pr_number = ?",
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
            cursor.execute(f"SELECT * FROM review_requests WHERE {placeholders}", params)
            for row in cursor.fetchall():
                result[(row["repo"], row["pr_number"])] = dict(row)
        return result

    def set_status(self, request_id: int, status: str,
                   detail: Optional[str] = None) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid review request status: {status}")
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE review_requests
                SET status = ?,
                    detail = COALESCE(?, detail),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, detail, request_id),
            )
        _mark_pipeline_dirty()

    def reset_attempts(self, request_id: int) -> None:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE review_requests SET attempts = 0 WHERE id = ?", (request_id,))
        _mark_pipeline_dirty()

    def increment_attempts(self, request_id: int) -> int:
        """Bump the attempt counter; returns the new count."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE review_requests "
                "SET attempts = attempts + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (request_id,),
            )
            cursor.execute("SELECT attempts FROM review_requests WHERE id = ?", (request_id,))
            row = cursor.fetchone()
        _mark_pipeline_dirty()
        return row["attempts"] if row else 0


def _mark_pipeline_dirty():
    # Imported lazily: services depend on the database package, not the reverse.
    from backend.services.pipeline_snapshot import mark_dirty
    mark_dirty()
