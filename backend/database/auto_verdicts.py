"""AutoVerdictsDB - Database operations for auto-generated PR review verdicts."""

import json
import logging
import sqlite3
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# "deferred" = the post was rate-limited and will be retried; "mediation" = the
# disputed critical/major count reached the threshold, the review was posted as
# a COMMENT and the PR was disarmed pending a human.
VALID_OUTCOMES = ("pending", "posted", "suppressed", "skipped", "error", "deferred", "mediation")


class AutoVerdictsDB:
    """Database operations for auto verdicts.

    One row per review the evaluator handled. ``claim()`` inserts the row in the
    ``pending`` state *before* GitHub is contacted, so the UNIQUE constraint on
    review_id is what prevents a double post when both the watcher thread and a
    frontend poll notice the same review completing.
    """

    def __init__(self, db):
        self.db = db

    def claim(
        self,
        repo: str,
        pr_number: int,
        review_id: int,
        head_commit_sha: Optional[str] = None,
    ) -> bool:
        """Reserve the auto verdict for a review.

        Returns True if this caller won the claim and should proceed, False if
        the review was already claimed by someone else.
        """
        try:
            with self.db.connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO auto_verdicts (repo, pr_number, review_id, outcome, head_commit_sha)
                    VALUES (?, ?, ?, 'pending', ?)
                """, (repo, pr_number, review_id, head_commit_sha))
            _mark_pipeline_dirty()
            return True
        except sqlite3.IntegrityError as e:
            # Distinguish a lost race (the UNIQUE review_id) from a genuine
            # constraint failure such as the foreign key to reviews(id) — both
            # raise IntegrityError, but only the former is a normal outcome.
            if self._is_claimed(review_id):
                logger.info(f"Auto verdict for review {review_id} already claimed — skipping")
            else:
                logger.error(f"Could not claim auto verdict for review {review_id}: {e}")
            return False

    def _is_claimed(self, review_id: int) -> bool:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM auto_verdicts WHERE review_id = ?", (review_id,))
            return cursor.fetchone() is not None

    def finalize(
        self,
        review_id: int,
        outcome: str,
        event: Optional[str] = None,
        reason: Optional[str] = None,
        tallies: Optional[Dict[str, int]] = None,
        criteria: Optional[Dict[str, Any]] = None,
        error_detail: Optional[str] = None,
    ) -> None:
        """Record the decision on a previously claimed row."""
        if outcome not in VALID_OUTCOMES:
            raise ValueError(f"Invalid outcome: {outcome}")
        tallies = tallies or {}
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE auto_verdicts SET
                    outcome = ?, event = ?, reason = ?,
                    critical_count = ?, major_count = ?, minor_count = ?,
                    disputed_count = ?, deferred_count = ?,
                    criteria_json = ?, error_detail = ?
                WHERE review_id = ?
            """, (
                outcome, event, reason,
                tallies.get("critical"), tallies.get("major"), tallies.get("minor"),
                tallies.get("disputed"), tallies.get("deferred"),
                json.dumps(criteria) if criteria is not None else None,
                error_detail, review_id,
            ))
        _mark_pipeline_dirty()
        logger.info(f"Auto verdict for review {review_id}: outcome={outcome} event={event} — {reason}")

    def get_deferred(self) -> List[Dict[str, Any]]:
        """All verdicts deferred by a rate limit, oldest first — the retry queue."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM auto_verdicts
                WHERE outcome = 'deferred'
                ORDER BY created_at ASC, id ASC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_latest_for_pr(self, repo: str, pr_number: int) -> Optional[Dict[str, Any]]:
        """Most recent auto verdict for a PR, or None."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM auto_verdicts
                WHERE repo = ? AND pr_number = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
            """, (repo, pr_number))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_latest_for_review_ids(self, review_ids) -> Dict[int, Dict[str, Any]]:
        """Batch lookup: newest auto-verdict row per review_id. Ids with no
        verdict row are absent from the result."""
        result: Dict[int, Dict[str, Any]] = {}
        ids = sorted({i for i in review_ids if i is not None})
        if not ids:
            return result
        with self.db.connection() as conn:
            cursor = conn.cursor()
            for i in range(0, len(ids), 800):
                chunk = ids[i:i + 800]
                # Ascending order so the newest row overwrites older ones.
                cursor.execute(
                    f"SELECT * FROM auto_verdicts WHERE review_id IN ({','.join('?' * len(chunk))}) "
                    "ORDER BY created_at ASC, id ASC",
                    chunk,
                )
                for row in cursor.fetchall():
                    result[row["review_id"]] = dict(row)
        return result

    def get_for_pr(self, repo: str, pr_number: int) -> List[Dict[str, Any]]:
        """All auto verdicts for a PR, newest first."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM auto_verdicts
                WHERE repo = ? AND pr_number = ?
                ORDER BY created_at DESC, id DESC
            """, (repo, pr_number))
            return [dict(row) for row in cursor.fetchall()]

    def get_for_prs(
        self, repo_pr_pairs: List[Tuple[str, int]]
    ) -> Dict[Tuple[str, int], List[Dict[str, Any]]]:
        """Batch lookup: every auto verdict per (repo, pr_number), newest first.
        Pairs with no verdict are absent from the result."""
        result: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
        if not repo_pr_pairs:
            return result
        with self.db.connection() as conn:
            cursor = conn.cursor()
            # Chunked: each pair costs two SQL variables and SQLite caps them.
            for i in range(0, len(repo_pr_pairs), 400):
                chunk = repo_pr_pairs[i:i + 400]
                placeholders = " OR ".join(["(repo = ? AND pr_number = ?)"] * len(chunk))
                params = [v for pair in chunk for v in pair]
                cursor.execute(
                    f"SELECT * FROM auto_verdicts WHERE {placeholders} "
                    "ORDER BY created_at DESC, id DESC",
                    params,
                )
                for row in cursor.fetchall():
                    result.setdefault((row["repo"], row["pr_number"]), []).append(dict(row))
        return result


def _mark_pipeline_dirty():
    # Imported lazily: services depend on the database package, not the reverse.
    from backend.services.pipeline_snapshot import mark_dirty
    mark_dirty()
