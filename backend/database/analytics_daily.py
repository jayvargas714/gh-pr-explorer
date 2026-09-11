"""SQLite store for the precomputed per-developer, per-day analytics rollup."""

from typing import Any, Dict, List, Optional

_METRIC_COLUMNS = [
    "prs_created", "prs_merged", "prs_closed", "reviews", "approvals",
    "changes_requested", "comments", "additions", "deletions", "commits",
    "merge_hours_sum", "merge_hours_count",
    "review_rounds_sum", "review_rounds_count",
]

# Non-key row columns a rollup row dict carries (repo and the day/login/base_ref
# primary-key columns are handled separately by replace_repo).
_ROW_COLUMNS = ["day", "login", "base_ref", "is_bot"] + _METRIC_COLUMNS


class AnalyticsDailyDB:
    """Storage for the analytics_daily rollup and its per-repo build metadata."""

    def __init__(self, db):
        self.db = db

    def replace_repo(self, repo: str, rows: List[Dict[str, Any]], meta: Dict[str, Any]) -> None:
        """Replace a repo's rollup rows and metadata in one transaction."""
        with self.db.connection() as conn:
            conn.execute("DELETE FROM analytics_daily WHERE repo = ?", (repo,))
            if rows:
                col_list = ",".join(["repo"] + _ROW_COLUMNS)
                placeholders = ",".join("?" for _ in range(len(_ROW_COLUMNS) + 1))
                values = [
                    (repo,) + tuple(r.get(c) for c in _ROW_COLUMNS)
                    for r in rows
                ]
                conn.executemany(
                    f"INSERT INTO analytics_daily ({col_list}) VALUES ({placeholders})",
                    values,
                )
            conn.execute(
                """INSERT INTO analytics_daily_meta
                   (repo, built_at, schema_version, pr_count, review_count, commit_count,
                    earliest_pr_day, earliest_commit_day)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(repo) DO UPDATE SET
                     built_at = excluded.built_at, schema_version = excluded.schema_version,
                     pr_count = excluded.pr_count, review_count = excluded.review_count,
                     commit_count = excluded.commit_count,
                     earliest_pr_day = excluded.earliest_pr_day,
                     earliest_commit_day = excluded.earliest_commit_day""",
                (
                    repo, meta["built_at"], meta["schema_version"],
                    meta.get("pr_count"), meta.get("review_count"), meta.get("commit_count"),
                    meta.get("earliest_pr_day"), meta.get("earliest_commit_day"),
                ),
            )

    def get_meta(self, repo: str) -> Optional[Dict[str, Any]]:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM analytics_daily_meta WHERE repo = ?", (repo,)
            ).fetchone()
            return dict(row) if row else None

    def query(self, repo: str, day_from: str, day_to: str,
              base_ref: Optional[str] = None) -> List[Dict[str, Any]]:
        """Rows for a repo within [day_from, day_to] (inclusive).

        With `base_ref` given, returns the raw per-(day, login, base_ref) rows.
        Without it, rows are summed across base refs and grouped by (day, login);
        `is_bot` becomes MAX(is_bot) across the group.
        """
        with self.db.connection() as conn:
            if base_ref is not None:
                rows = conn.execute(
                    """SELECT * FROM analytics_daily
                       WHERE repo = ? AND day BETWEEN ? AND ? AND base_ref = ?
                       ORDER BY day, login""",
                    (repo, day_from, day_to, base_ref),
                ).fetchall()
                return [dict(r) for r in rows]

            metric_sums = ", ".join(f"SUM({c}) AS {c}" for c in _METRIC_COLUMNS)
            rows = conn.execute(
                f"""SELECT day, login, MAX(is_bot) AS is_bot, {metric_sums}
                    FROM analytics_daily
                    WHERE repo = ? AND day BETWEEN ? AND ?
                    GROUP BY day, login
                    ORDER BY day, login""",
                (repo, day_from, day_to),
            ).fetchall()
            return [dict(r) for r in rows]

    def earliest_day(self, repo: str, base_ref: Optional[str] = None) -> Optional[str]:
        query = "SELECT MIN(day) AS earliest FROM analytics_daily WHERE repo = ?"
        params: List[Any] = [repo]
        if base_ref is not None:
            query += " AND base_ref = ?"
            params.append(base_ref)
        with self.db.connection() as conn:
            row = conn.execute(query, params).fetchone()
            return row["earliest"] if row else None

    def base_refs(self, repo: str) -> List[str]:
        """Base refs for a repo, most-rows-first."""
        with self.db.connection() as conn:
            rows = conn.execute(
                """SELECT base_ref, COUNT(*) AS n FROM analytics_daily
                   WHERE repo = ? GROUP BY base_ref ORDER BY n DESC""",
                (repo,),
            ).fetchall()
            return [r["base_ref"] for r in rows]

    def clear(self, repo: Optional[str] = None) -> None:
        with self.db.connection() as conn:
            if repo is None:
                conn.execute("DELETE FROM analytics_daily")
                conn.execute("DELETE FROM analytics_daily_meta")
            else:
                conn.execute("DELETE FROM analytics_daily WHERE repo = ?", (repo,))
                conn.execute("DELETE FROM analytics_daily_meta WHERE repo = ?", (repo,))
