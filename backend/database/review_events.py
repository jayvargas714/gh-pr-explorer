"""ReviewEventsDB - append-only operational log of review lifecycle events.

One row per event. Every attempt of a single review shares a ``run_id``, so the
UI can group a run's attempts without inferring the grouping from timestamps.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

VALID_EVENTS = ("started", "completed", "failed", "retry_scheduled", "gave_up", "cancelled")
VALID_REASONS = ("no_output", "nonzero_exit", "spawn_failed", "attempts_exhausted", "cancelled")

# Columns callers may set through log_event(**fields), in insert order.
_OPTIONAL_COLUMNS = (
    "reviewer_agent",
    "is_followup",
    "auto_started",
    "attempt",
    "max_attempts",
    "exit_code",
    "reason",
    "detail",
    "review_file",
    "review_id",
    "score",
    "pid",
)


class ReviewEventsDB:
    """Database operations for the review event log."""

    def __init__(self, db):
        self.db = db

    def log_event(
        self,
        event: str,
        repo: str,
        pr_number: int,
        run_id: str,
        **fields: Any,
    ) -> Optional[int]:
        """Append one lifecycle event.

        Raises:
            ValueError: if ``event`` or ``reason`` is outside its vocabulary, or
            an unknown column is passed. These are programming errors, not
            runtime conditions — the recorders in review_event_log.py are what
            keep them from ever reaching a running review.
        """
        if event not in VALID_EVENTS:
            raise ValueError(f"Unknown review event '{event}'; expected one of {VALID_EVENTS}")

        reason = fields.get("reason")
        if reason is not None and reason not in VALID_REASONS:
            raise ValueError(f"Unknown failure reason '{reason}'; expected one of {VALID_REASONS}")

        unknown = set(fields) - set(_OPTIONAL_COLUMNS)
        if unknown:
            raise ValueError(f"Unknown review event columns: {sorted(unknown)}")

        columns = ["created_at", "run_id", "event", "repo", "pr_number"]
        values: List[Any] = [
            datetime.now(timezone.utc).isoformat(),
            run_id,
            event,
            repo,
            pr_number,
        ]
        for column in _OPTIONAL_COLUMNS:
            if column in fields:
                columns.append(column)
                values.append(fields[column])

        placeholders = ", ".join("?" for _ in columns)
        sql = f"INSERT INTO review_events ({', '.join(columns)}) VALUES ({placeholders})"

        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, values)
            return cursor.lastrowid

    def list_events(
        self,
        repo: Optional[str] = None,
        pr_number: Optional[int] = None,
        event: Optional[str] = None,
        reason: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Return (events newest-first, total matching rows before paging)."""
        clause, params = self._where(
            repo=repo, pr_number=pr_number, event=event, reason=reason, since=since
        )

        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM review_events{clause}", params)
            total = cursor.fetchone()[0]

            cursor.execute(
                f"SELECT * FROM review_events{clause} "
                "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            )
            events = [dict(row) for row in cursor.fetchall()]

        return events, total

    def get_stats(
        self,
        repo: Optional[str] = None,
        since: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Aggregate counts for the Review Logs summary strip.

        ``failed`` counts runs that hit a ``gave_up`` event, not ``failed``
        events: a run that failed one attempt and then succeeded is not a failed
        run, and counting attempts would report every retry as a failure.

        ``rescued_by_retry`` counts runs that completed on an attempt after their
        first — the direct measure of whether the retry loop is earning its keep.
        """
        clause, params = self._where(repo=repo, since=since)
        joiner = " AND" if clause else " WHERE"

        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(f"SELECT COUNT(DISTINCT run_id) FROM review_events{clause}", params)
            runs = cursor.fetchone()[0]

            cursor.execute(
                f"SELECT event, COUNT(DISTINCT run_id) FROM review_events{clause} GROUP BY event",
                params,
            )
            by_event = {row[0]: row[1] for row in cursor.fetchall()}

            cursor.execute(
                f"SELECT COUNT(DISTINCT run_id) FROM review_events{clause}"
                f"{joiner} event = 'completed' AND attempt > 1",
                params,
            )
            rescued = cursor.fetchone()[0]

            cursor.execute(
                f"SELECT reason, COUNT(*) FROM review_events{clause}"
                f"{joiner} reason IS NOT NULL GROUP BY reason",
                params,
            )
            by_reason = {row[0]: row[1] for row in cursor.fetchall()}

        return {
            "runs": runs,
            "completed": by_event.get("completed", 0),
            "failed": by_event.get("gave_up", 0),
            "rescued_by_retry": rescued,
            "by_reason": by_reason,
        }

    def purge_older_than(self, days: int) -> int:
        """Delete events older than ``days``. A non-positive value is a no-op.

        Returns:
            int: number of rows deleted.
        """
        if not days or days <= 0:
            return 0

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM review_events WHERE created_at < ?", (cutoff,))
            deleted = cursor.rowcount

        if deleted:
            logger.info(f"Purged {deleted} review event(s) older than {days} days")
        return deleted

    @staticmethod
    def _where(**filters: Any) -> Tuple[str, List[Any]]:
        """Build a WHERE clause from the non-empty filters, plus its params."""
        columns = {
            "repo": "repo = ?",
            "pr_number": "pr_number = ?",
            "event": "event = ?",
            "reason": "reason = ?",
            "since": "created_at >= ?",
        }
        conditions: List[str] = []
        params: List[Any] = []
        for name, condition in columns.items():
            value = filters.get(name)
            if value is not None and value != "":
                conditions.append(condition)
                params.append(value)

        clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        return clause, params
