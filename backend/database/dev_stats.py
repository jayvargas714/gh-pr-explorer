"""DeveloperStatsDB - Database operations for cached developer statistics."""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class DeveloperStatsDB:
    """Database operations for cached developer statistics."""

    CACHE_TTL_HOURS = 4

    def __init__(self, db):
        self.db = db

    def get_last_updated(self, repo: str) -> Optional[datetime]:
        """Get the last update timestamp for a repo's stats."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT last_updated FROM stats_metadata WHERE repo = ?",
                (repo,)
            )
            row = cursor.fetchone()
            if row and row["last_updated"]:
                return datetime.fromisoformat(row["last_updated"])
            return None

    def is_stale(self, repo: str) -> bool:
        """Check if stats for a repo are stale (older than TTL)."""
        last_updated = self.get_last_updated(repo)
        if last_updated is None:
            return True
        age = datetime.now() - last_updated
        return age.total_seconds() > (self.CACHE_TTL_HOURS * 3600)

    def get_stats(self, repo: str) -> List[Dict[str, Any]]:
        """Get cached stats for a repository."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT username, total_prs, open_prs, merged_prs, closed_prs,
                       total_additions, total_deletions, avg_pr_score,
                       reviewed_pr_count, commits, avatar_url, reviews_given,
                       approvals, changes_requested, updated_at
                FROM developer_stats
                WHERE repo = ?
                ORDER BY total_prs DESC
            """, (repo,))
            return [dict(row) for row in cursor.fetchall()]

    def get_all_repos(self) -> List[str]:
        """Return all repos that have cached stats."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT repo FROM stats_metadata")
            return [row["repo"] for row in cursor.fetchall()]

    def save_stats(self, repo: str, stats: List[Dict[str, Any]]) -> None:
        """Save developer stats for a repository. Skips save if stats list is empty."""
        if not stats:
            logger.warning(f"Skipping save_stats for {repo}: empty stats list")
            return

        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute("DELETE FROM developer_stats WHERE repo = ?", (repo,))

            for stat in stats:
                cursor.execute("""
                    INSERT INTO developer_stats
                    (repo, username, total_prs, open_prs, merged_prs, closed_prs,
                     total_additions, total_deletions, avg_pr_score, reviewed_pr_count,
                     commits, avatar_url, reviews_given, approvals, changes_requested,
                     updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    repo,
                    stat.get("username", ""),
                    stat.get("total_prs", 0),
                    stat.get("open_prs", 0),
                    stat.get("merged_prs", 0),
                    stat.get("closed_prs", 0),
                    stat.get("total_additions", 0),
                    stat.get("total_deletions", 0),
                    stat.get("avg_pr_score"),
                    stat.get("reviewed_pr_count", 0),
                    stat.get("commits", 0),
                    stat.get("avatar_url"),
                    stat.get("reviews_given", 0),
                    stat.get("approvals", 0),
                    stat.get("changes_requested", 0)
                ))

            cursor.execute("""
                INSERT INTO stats_metadata (repo, last_updated)
                VALUES (?, CURRENT_TIMESTAMP)
                ON CONFLICT(repo) DO UPDATE SET
                    last_updated = CURRENT_TIMESTAMP
            """, (repo,))

    def clear_stats(self, repo: str) -> None:
        """Clear cached stats for a repository."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM developer_stats WHERE repo = ?", (repo,))
            cursor.execute("DELETE FROM stats_metadata WHERE repo = ?", (repo,))
