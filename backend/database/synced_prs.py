"""SQLite store for the PR list sync: registered repos and full PR JSON rows."""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# SQLite has supported multiple path arguments to json_extract() since 3.9.0.
_MULTI_JSON_EXTRACT_MIN_VERSION = (3, 9, 0)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sqlite_supports_multi_json_extract() -> bool:
    try:
        version = tuple(int(p) for p in sqlite3.sqlite_version.split("."))
    except ValueError:
        return False
    return version >= _MULTI_JSON_EXTRACT_MIN_VERSION


def _parse_reviews(raw: Optional[str]) -> List[Dict[str, Any]]:
    """Parse the JSON `reviews` array column into the rollup shape."""
    if not raw:
        return []
    reviews = json.loads(raw)
    if not reviews:
        return []
    result = []
    for r in reviews:
        author = r.get("author") or {}
        result.append({
            "login": author.get("login"),
            "state": r.get("state"),
            "submitted_at": r.get("submittedAt"),
        })
    return result


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
        d["history_done"] = bool(d.get("history_done"))
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

    # -- inception-walk history state ---------------------------------------

    def set_repo_created_at(self, repo: str, iso: str) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE synced_repos SET repo_created_at = ? WHERE repo = ?",
                (iso, repo),
            )

    def get_history_state(self, repo: str) -> Dict[str, Any]:
        with self.db.connection() as conn:
            row = conn.execute(
                """SELECT repo_created_at, history_cursor, history_done, history_error
                   FROM synced_repos WHERE repo = ?""",
                (repo,),
            ).fetchone()
            if row is None:
                return {
                    "repo_created_at": None, "history_cursor": None,
                    "history_done": False, "history_error": None,
                }
            d = dict(row)
            d["history_done"] = bool(d["history_done"])
            return d

    def set_history_cursor(self, repo: str, day: str) -> None:
        """Advance the inception-walk cursor and clear any prior error."""
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE synced_repos SET history_cursor = ?, history_error = NULL WHERE repo = ?",
                (day, repo),
            )

    def mark_history_done(self, repo: str) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE synced_repos SET history_done = 1, history_error = NULL WHERE repo = ?",
                (repo,),
            )

    def set_history_error(self, repo: str, err: str) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE synced_repos SET history_error = ? WHERE repo = ?",
                (err, repo),
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
        pr["behindBy"] = row["behind_by"]
        return pr

    def get_prs(self, repo: str, states: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
        query = "SELECT data, fetched_at, behind_by FROM synced_prs WHERE repo = ?"
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
                f"SELECT pr_number, data, fetched_at, behind_by FROM synced_prs "
                f"WHERE repo = ? AND pr_number IN ({placeholders})",
                [repo] + list(numbers),
            ).fetchall()
            return {row["pr_number"]: self._pr_row(row) for row in rows}

    def set_draft(self, repo: str, pr_number: int, is_draft: bool) -> None:
        """Write a draft toggle through to the row (column + JSON) so views
        reflect it before the next sync re-hydrates the PR."""
        with self.db.connection() as conn:
            conn.execute(
                """UPDATE synced_prs SET is_draft = ?, data = json_set(data, '$.isDraft', json(?))
                   WHERE repo = ? AND pr_number = ?""",
                (1 if is_draft else 0, "true" if is_draft else "false", repo, pr_number),
            )

    def set_state(self, repo: str, pr_number: int, state: str) -> None:
        """Write a state change (e.g. MERGED after a merge) through to the row."""
        with self.db.connection() as conn:
            conn.execute(
                """UPDATE synced_prs SET state = ?, data = json_set(data, '$.state', ?)
                   WHERE repo = ? AND pr_number = ?""",
                (state, state, repo, pr_number),
            )

    # -- commits-behind cache ---------------------------------------------------

    def get_behind_state(self, repo: str) -> Dict[int, Dict[str, Any]]:
        """Cached behind count + the SHA pair it was computed against, per OPEN PR."""
        with self.db.connection() as conn:
            rows = conn.execute(
                """SELECT pr_number, behind_by, behind_base_sha, behind_head_sha
                   FROM synced_prs WHERE repo = ? AND state = 'OPEN'""",
                (repo,),
            ).fetchall()
            return {
                row["pr_number"]: {
                    "behind_by": row["behind_by"],
                    "behind_base_sha": row["behind_base_sha"],
                    "behind_head_sha": row["behind_head_sha"],
                }
                for row in rows
            }

    def get_behind_by(self, repo: str, pr_number: int) -> Optional[int]:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT behind_by FROM synced_prs WHERE repo = ? AND pr_number = ?",
                (repo, pr_number),
            ).fetchone()
            return row["behind_by"] if row else None

    def set_behind(self, repo: str, pr_number: int, behind_by: int,
                   base_sha: str, head_sha: str) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """UPDATE synced_prs SET behind_by = ?, behind_base_sha = ?, behind_head_sha = ?
                   WHERE repo = ? AND pr_number = ?""",
                (behind_by, base_sha, head_sha, repo, pr_number),
            )

    def get_states_by_numbers(self, repo: str, numbers: List[int]) -> Dict[int, str]:
        """Batch lookup of the scalar state column (no JSON parse). PRs the
        store doesn't know are absent from the result. Chunked at 500 to stay
        under SQLite's bound-variable limit."""
        if not numbers:
            return {}
        numbers = list(numbers)
        result: Dict[int, str] = {}
        with self.db.connection() as conn:
            for i in range(0, len(numbers), 500):
                chunk = numbers[i:i + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT pr_number, state FROM synced_prs "
                    f"WHERE repo = ? AND pr_number IN ({placeholders})",
                    [repo] + chunk,
                ).fetchall()
                result.update({row["pr_number"]: row["state"] for row in rows})
        return result

    def get_pr_rollup_rows(self, repo: str) -> List[Dict[str, Any]]:
        """One row per synced PR, shaped for the analytics rollup builder.

        Uses a single multi-path json_extract per query so each PR's JSON blob
        is parsed by SQLite once (falls back to four single-path extracts on
        SQLite builds that predate multi-path json_extract).
        """
        with self.db.connection() as conn:
            if _sqlite_supports_multi_json_extract():
                rows = conn.execute(
                    """SELECT pr_number, state, author, created_at, merged_at, closed_at,
                              json_extract(data, '$.baseRefName', '$.additions',
                                           '$.deletions', '$.author.is_bot') AS scalars,
                              json_extract(data, '$.reviews') AS reviews
                       FROM synced_prs WHERE repo = ?""",
                    (repo,),
                ).fetchall()
                result = []
                for row in rows:
                    scalars = json.loads(row["scalars"]) if row["scalars"] is not None else [None] * 4
                    base_ref, additions, deletions, is_bot = scalars
                    result.append(self._rollup_row(row, base_ref, additions, deletions, is_bot))
                return result

            rows = conn.execute(
                """SELECT pr_number, state, author, created_at, merged_at, closed_at,
                          json_extract(data, '$.baseRefName') AS base_ref,
                          json_extract(data, '$.additions') AS additions,
                          json_extract(data, '$.deletions') AS deletions,
                          json_extract(data, '$.author.is_bot') AS is_bot,
                          json_extract(data, '$.reviews') AS reviews
                   FROM synced_prs WHERE repo = ?""",
                (repo,),
            ).fetchall()
            return [
                self._rollup_row(row, row["base_ref"], row["additions"], row["deletions"], row["is_bot"])
                for row in rows
            ]

    @staticmethod
    def _rollup_row(row, base_ref, additions, deletions, is_bot) -> Dict[str, Any]:
        return {
            "number": row["pr_number"],
            "state": row["state"],
            "author": row["author"],
            "author_is_bot": bool(is_bot),
            "created_at": row["created_at"],
            "merged_at": row["merged_at"],
            "closed_at": row["closed_at"],
            "base_ref": base_ref,
            "additions": additions if additions is not None else 0,
            "deletions": deletions if deletions is not None else 0,
            "reviews": _parse_reviews(row["reviews"]),
        }

    def earliest_created_at(self, repo: str) -> Optional[str]:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT MIN(created_at) AS earliest FROM synced_prs WHERE repo = ?",
                (repo,),
            ).fetchone()
            return row["earliest"] if row else None

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
