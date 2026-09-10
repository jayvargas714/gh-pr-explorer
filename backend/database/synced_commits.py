"""SQLite store for the commit sync: per-branch backfill state and commit rows."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SyncedCommitsDB:
    """Storage for synced commit data, keyed by "owner/name" repo + branch."""

    def __init__(self, db):
        self.db = db

    # -- branch state ---------------------------------------------------------

    def get_branch_state(self, repo: str, branch: str) -> Optional[Dict[str, Any]]:
        with self.db.connection() as conn:
            row = conn.execute(
                """SELECT backfill_until, backfill_done, last_committed_at, last_synced_at, error
                   FROM synced_commit_branches WHERE repo = ? AND branch = ?""",
                (repo, branch),
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            d["backfill_done"] = bool(d["backfill_done"])
            return d

    def upsert_branch_state(self, repo: str, branch: str, touch: bool = True, **fields) -> None:
        """Insert or update a branch state row, touching only the given fields.

        `touch=True` (default) also stamps `last_synced_at` with the current
        UTC time.
        """
        if touch:
            fields = dict(fields)
            fields["last_synced_at"] = _utc_now_iso()

        columns = ["repo", "branch"] + list(fields.keys())
        values = [repo, branch] + list(fields.values())
        placeholders = ",".join("?" for _ in columns)
        col_list = ",".join(columns)

        with self.db.connection() as conn:
            if fields:
                set_clause = ", ".join(f"{k} = excluded.{k}" for k in fields)
                conn.execute(
                    f"""INSERT INTO synced_commit_branches ({col_list})
                        VALUES ({placeholders})
                        ON CONFLICT(repo, branch) DO UPDATE SET {set_clause}""",
                    values,
                )
            else:
                conn.execute(
                    f"""INSERT INTO synced_commit_branches ({col_list})
                        VALUES ({placeholders})
                        ON CONFLICT(repo, branch) DO NOTHING""",
                    values,
                )

    # -- commits ----------------------------------------------------------------

    def upsert_commits(self, repo: str, branch: str, rows: List[Dict[str, Any]]) -> int:
        """Insert or update commit rows. Returns the number of rows passed in."""
        if not rows:
            return 0
        fetched_at = _utc_now_iso()
        values = [
            (
                repo, branch, r["sha"], r.get("login"), r.get("name"), r.get("email"),
                r.get("authored_at"), r["committed_at"], r.get("parents", 1), fetched_at,
            )
            for r in rows
        ]
        with self.db.connection() as conn:
            conn.executemany(
                """INSERT INTO synced_commits
                   (repo, branch, sha, author_login, author_name, author_email,
                    authored_at, committed_at, parent_count, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(repo, branch, sha) DO UPDATE SET
                     author_login = excluded.author_login,
                     author_name = excluded.author_name,
                     author_email = excluded.author_email,
                     authored_at = excluded.authored_at,
                     committed_at = excluded.committed_at,
                     parent_count = excluded.parent_count,
                     fetched_at = excluded.fetched_at""",
                values,
            )
        return len(rows)

    def count(self, repo: str, branch: Optional[str] = None) -> int:
        query = "SELECT COUNT(*) AS n FROM synced_commits WHERE repo = ?"
        params: List[Any] = [repo]
        if branch is not None:
            query += " AND branch = ?"
            params.append(branch)
        with self.db.connection() as conn:
            row = conn.execute(query, params).fetchone()
            return row["n"]

    def get_rollup_rows(self, repo: str) -> List[Dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """SELECT branch, COALESCE(author_login, author_name, 'unknown') AS login,
                          committed_at, parent_count
                   FROM synced_commits WHERE repo = ?""",
                (repo,),
            ).fetchall()
            return [dict(r) for r in rows]

    def earliest_committed_at(self, repo: str) -> Optional[str]:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT MIN(committed_at) AS earliest FROM synced_commits WHERE repo = ?",
                (repo,),
            ).fetchone()
            return row["earliest"] if row else None
