"""AutoVerdictArmingDB - Per-PR auto-verdict arming, independent of the merge queue.

One row per (repo, pr_number) that has ever been armed or given a criteria
override. Column names match the retired merge_queue.auto_verdict_* columns
so apply_override() and format_auto_verdict_state() consume a row unchanged.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class AutoVerdictArmingDB:
    """Database operations for auto-verdict arming rows."""

    def __init__(self, db):
        self.db = db

    def get(self, repo: str, pr_number: int) -> Optional[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM auto_verdict_arming WHERE repo = ? AND pr_number = ?",
                (repo, pr_number),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_armed(self) -> List[Dict[str, Any]]:
        """Every armed PR — the follow-up watcher's scan set."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM auto_verdict_arming WHERE auto_verdict_enabled = 1 "
                "ORDER BY repo ASC, pr_number ASC"
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_for_prs(self, repo_pr_pairs: List[Tuple[str, int]]) -> Dict[Tuple[str, int], Dict[str, Any]]:
        """Batch lookup keyed by (repo, pr_number). Pairs with no row are absent."""
        result: Dict[Tuple[str, int], Dict[str, Any]] = {}
        if not repo_pr_pairs:
            return result
        with self.db.connection() as conn:
            cursor = conn.cursor()
            # Chunked: each pair costs two SQL variables and SQLite caps them.
            for i in range(0, len(repo_pr_pairs), 400):
                chunk = repo_pr_pairs[i:i + 400]
                placeholders = " OR ".join(["(repo = ? AND pr_number = ?)"] * len(chunk))
                params = [v for pair in chunk for v in pair]
                cursor.execute(f"SELECT * FROM auto_verdict_arming WHERE {placeholders}", params)
                for row in cursor.fetchall():
                    result[(row["repo"], row["pr_number"])] = dict(row)
        return result

    def set_arming(
        self,
        repo: str,
        pr_number: int,
        enabled: bool,
        reviewer_type: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Arm or disarm a PR (upsert). Disarming keeps the row so a criteria
        override survives. Returns the row."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO auto_verdict_arming
                    (repo, pr_number, auto_verdict_enabled, auto_verdict_reviewer,
                     auto_verdict_mode, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(repo, pr_number) DO UPDATE SET
                    auto_verdict_enabled = excluded.auto_verdict_enabled,
                    auto_verdict_reviewer = excluded.auto_verdict_reviewer,
                    auto_verdict_mode = excluded.auto_verdict_mode,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (repo, pr_number, 1 if enabled else 0, reviewer_type, mode),
            )
            cursor.execute(
                "SELECT * FROM auto_verdict_arming WHERE repo = ? AND pr_number = ?",
                (repo, pr_number),
            )
            row = dict(cursor.fetchone())
        _mark_pipeline_dirty()
        return row

    def set_criteria(
        self,
        repo: str,
        pr_number: int,
        criteria: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Set or clear (None) a PR's criteria override (upsert). Returns the row."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO auto_verdict_arming (repo, pr_number, auto_verdict_criteria, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(repo, pr_number) DO UPDATE SET
                    auto_verdict_criteria = excluded.auto_verdict_criteria,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (repo, pr_number, json.dumps(criteria) if criteria is not None else None),
            )
            cursor.execute(
                "SELECT * FROM auto_verdict_arming WHERE repo = ? AND pr_number = ?",
                (repo, pr_number),
            )
            row = dict(cursor.fetchone())
        _mark_pipeline_dirty()
        return row

    def clear(self, repo: str, pr_number: int) -> bool:
        """Delete a PR's arming row. Returns True if a row was removed."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM auto_verdict_arming WHERE repo = ? AND pr_number = ?",
                (repo, pr_number),
            )
            deleted = cursor.rowcount > 0
        if deleted:
            _mark_pipeline_dirty()
        return deleted


def _mark_pipeline_dirty():
    # Imported lazily: services depend on the database package, not the reverse.
    from backend.services.pipeline_snapshot import mark_dirty
    mark_dirty()
