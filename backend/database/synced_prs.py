"""SQLite store for the PR list sync: registered repos and full PR JSON rows."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SyncedPRsDB:
    """Storage for synced PR list data, keyed by "owner/name" repo strings."""

    def __init__(self, db):
        self.db = db

    # -- repos ------------------------------------------------------------

    def register_repo(self, repo: str) -> None:
        """Idempotently register a repo and bump its last-visited stamp."""
        with self.db.connection() as conn:
            conn.execute(
                """INSERT INTO synced_repos (repo, last_visited_at)
                   VALUES (?, CURRENT_TIMESTAMP)
                   ON CONFLICT(repo) DO UPDATE SET last_visited_at = CURRENT_TIMESTAMP""",
                (repo,),
            )

    def get_repo(self, repo: str) -> Optional[Dict[str, Any]]:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM synced_repos WHERE repo = ?", (repo,)
            ).fetchone()
            return self._repo_row(row) if row else None

    def list_repos(self) -> List[Dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM synced_repos ORDER BY last_visited_at DESC"
            ).fetchall()
            return [self._repo_row(r) for r in rows]

    @staticmethod
    def _repo_row(row) -> Dict[str, Any]:
        d = dict(row)
        d["backfill_done"] = bool(d.get("backfill_done"))
        return d

    def mark_backfill_done(self, repo: str) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE synced_repos SET backfill_done = 1, backfill_error = NULL WHERE repo = ?",
                (repo,),
            )

    def set_backfill_error(self, repo: str, error: str) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE synced_repos SET backfill_error = ? WHERE repo = ?",
                (error, repo),
            )

    def update_last_synced(self, repo: str) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE synced_repos SET last_synced_at = CURRENT_TIMESTAMP WHERE repo = ?",
                (repo,),
            )

    # -- PRs ---------------------------------------------------------------

    def upsert_pr(self, repo: str, pr: Dict[str, Any]) -> None:
        """Insert or replace one PR row, extracting scalar columns from the JSON."""
        author = (pr.get("author") or {}).get("login")
        with self.db.connection() as conn:
            conn.execute(
                """INSERT INTO synced_prs
                   (repo, pr_number, state, is_draft, author,
                    created_at, updated_at, closed_at, merged_at, data, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(repo, pr_number) DO UPDATE SET
                     state = excluded.state, is_draft = excluded.is_draft,
                     author = excluded.author, created_at = excluded.created_at,
                     updated_at = excluded.updated_at, closed_at = excluded.closed_at,
                     merged_at = excluded.merged_at, data = excluded.data,
                     fetched_at = excluded.fetched_at""",
                (
                    repo, pr.get("number"), (pr.get("state") or "").upper(),
                    1 if pr.get("isDraft") else 0, author,
                    pr.get("createdAt"), pr.get("updatedAt"),
                    pr.get("closedAt"), pr.get("mergedAt"),
                    json.dumps(pr), _utc_now_iso(),
                ),
            )

    @staticmethod
    def _pr_row(row) -> Dict[str, Any]:
        pr = json.loads(row["data"])
        pr["fetchedAt"] = row["fetched_at"]
        return pr

    def get_prs(self, repo: str, states: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
        query = "SELECT data, fetched_at FROM synced_prs WHERE repo = ?"
        params: List[Any] = [repo]
        if states:
            placeholders = ",".join("?" for _ in states)
            query += f" AND state IN ({placeholders})"
            params.extend(sorted(states))
        with self.db.connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._pr_row(r) for r in rows]

    def get_prs_by_numbers(self, repo: str, numbers: List[int]) -> Dict[int, Dict[str, Any]]:
        if not numbers:
            return {}
        placeholders = ",".join("?" for _ in numbers)
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT pr_number, data, fetched_at FROM synced_prs "
                f"WHERE repo = ? AND pr_number IN ({placeholders})",
                [repo] + list(numbers),
            ).fetchall()
            return {row["pr_number"]: self._pr_row(row) for row in rows}

    def get_states_by_numbers(self, repo: str, numbers: List[int]) -> Dict[int, str]:
        """Batch lookup of the scalar state column (no JSON parse). PRs the
        store doesn't know are absent from the result."""
        if not numbers:
            return {}
        placeholders = ",".join("?" for _ in numbers)
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT pr_number, state FROM synced_prs "
                f"WHERE repo = ? AND pr_number IN ({placeholders})",
                [repo] + list(numbers),
            ).fetchall()
            return {row["pr_number"]: row["state"] for row in rows}

    def delete_pr(self, repo: str, pr_number: int) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "DELETE FROM synced_prs WHERE repo = ? AND pr_number = ?",
                (repo, pr_number),
            )

    def prune_old(self, repo: str, cutoff_iso: str) -> int:
        """Delete CLOSED/MERGED rows whose updated_at is older than the cutoff."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                """DELETE FROM synced_prs
                   WHERE repo = ? AND state IN ('CLOSED', 'MERGED') AND updated_at < ?""",
                (repo, cutoff_iso),
            )
            return cursor.rowcount

    def count_prs(self, repo: str) -> int:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM synced_prs WHERE repo = ?", (repo,)
            ).fetchone()
            return row["n"]
