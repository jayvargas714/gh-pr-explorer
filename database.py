#!/usr/bin/env python3
"""Database module for GitHub PR Explorer.

Provides SQLite-backed persistence for code reviews and merge queue.
"""

import re
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Database file path (project root)
DB_PATH = Path(__file__).parent / "pr_explorer.db"


class Database:
    """SQLite database manager for PR Explorer."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize database connection.

        Args:
            db_path: Optional path to database file. Uses default if not provided.
        """
        self.db_path = db_path or DB_PATH
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initialize database schema."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Create reviews table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pr_number INTEGER NOT NULL,
                    repo TEXT NOT NULL,
                    pr_title TEXT,
                    pr_author TEXT,
                    pr_url TEXT,
                    review_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL DEFAULT 'completed',
                    review_file_path TEXT,
                    score INTEGER CHECK(score >= 0 AND score <= 10),
                    content TEXT,
                    is_followup BOOLEAN DEFAULT FALSE,
                    parent_review_id INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (parent_review_id) REFERENCES reviews(id)
                )
            """)

            # Create indexes for reviews
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_reviews_repo_pr
                ON reviews(repo, pr_number)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_reviews_timestamp
                ON reviews(review_timestamp DESC)
            """)

            # Create merge_queue table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS merge_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pr_number INTEGER NOT NULL,
                    repo TEXT NOT NULL,
                    pr_title TEXT,
                    pr_author TEXT,
                    pr_url TEXT,
                    additions INTEGER DEFAULT 0,
                    deletions INTEGER DEFAULT 0,
                    position INTEGER NOT NULL,
                    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(pr_number, repo)
                )
            """)

            # Create index for queue position
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_queue_position
                ON merge_queue(position)
            """)

            # Create migrations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS migrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    executed_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()
            logger.info(f"Database initialized at {self.db_path}")
        finally:
            conn.close()

    def is_migration_done(self, name: str) -> bool:
        """Check if a migration has been executed."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM migrations WHERE name = ?", (name,))
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def mark_migration_done(self, name: str):
        """Mark a migration as completed."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO migrations (name) VALUES (?)",
                (name,)
            )
            conn.commit()
        finally:
            conn.close()


class ReviewsDB:
    """Database operations for code reviews."""

    def __init__(self, db: Optional[Database] = None):
        """Initialize reviews database.

        Args:
            db: Optional Database instance. Creates new one if not provided.
        """
        self.db = db or Database()

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        return self.db._get_connection()

    def save_review(
        self,
        pr_number: int,
        repo: str,
        pr_title: Optional[str] = None,
        pr_author: Optional[str] = None,
        pr_url: Optional[str] = None,
        status: str = "completed",
        review_file_path: Optional[str] = None,
        score: Optional[int] = None,
        content: Optional[str] = None,
        is_followup: bool = False,
        parent_review_id: Optional[int] = None,
        review_timestamp: Optional[datetime] = None
    ) -> int:
        """Save a review to the database.

        Returns:
            The ID of the saved review.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Extract score from content if not provided
            if score is None and content:
                score = self._extract_score(content)

            timestamp = review_timestamp or datetime.now()

            cursor.execute("""
                INSERT INTO reviews (
                    pr_number, repo, pr_title, pr_author, pr_url,
                    status, review_file_path, score, content,
                    is_followup, parent_review_id, review_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pr_number, repo, pr_title, pr_author, pr_url,
                status, review_file_path, score, content,
                is_followup, parent_review_id, timestamp
            ))

            conn.commit()
            review_id = cursor.lastrowid
            logger.info(f"Saved review {review_id} for PR #{pr_number} in {repo}")
            return review_id
        finally:
            conn.close()

    def update_review(
        self,
        review_id: int,
        status: Optional[str] = None,
        score: Optional[int] = None,
        content: Optional[str] = None
    ):
        """Update an existing review."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            updates = []
            params = []

            if status is not None:
                updates.append("status = ?")
                params.append(status)

            if content is not None:
                updates.append("content = ?")
                params.append(content)
                # Extract score from content if not explicitly provided
                if score is None:
                    score = self._extract_score(content)

            if score is not None:
                updates.append("score = ?")
                params.append(score)

            if not updates:
                return

            params.append(review_id)
            query = f"UPDATE reviews SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, params)
            conn.commit()
            logger.info(f"Updated review {review_id}")
        finally:
            conn.close()

    def _extract_score(self, content: str) -> Optional[int]:
        """Extract score from review content.

        Looks for patterns like:
        - Score: 7/10
        - Rating: 8/10
        - Overall Score: 6/10
        - **Score:** 9/10
        """
        if not content:
            return None

        patterns = [
            r'(?:\*\*)?(?:Overall\s+)?(?:Score|Rating)(?:\*\*)?[:\s]*(\d+)\s*/?\s*10',
            r'(\d+)\s*/\s*10\s*(?:score|rating)',
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                score = int(match.group(1))
                if 0 <= score <= 10:
                    return score

        return None

    def get_review(self, review_id: int) -> Optional[Dict[str, Any]]:
        """Get a single review by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM reviews WHERE id = ?", (review_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_reviews_for_pr(self, repo: str, pr_number: int) -> List[Dict[str, Any]]:
        """Get all reviews for a specific PR (review chain)."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM reviews
                WHERE repo = ? AND pr_number = ?
                ORDER BY review_timestamp DESC
            """, (repo, pr_number))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_latest_review_for_pr(self, repo: str, pr_number: int) -> Optional[Dict[str, Any]]:
        """Get the most recent review for a PR."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM reviews
                WHERE repo = ? AND pr_number = ?
                ORDER BY review_timestamp DESC
                LIMIT 1
            """, (repo, pr_number))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_reviews(
        self,
        repo: Optional[str] = None,
        author: Optional[str] = None,
        pr_number: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List reviews with optional filtering."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            conditions = []
            params = []

            if repo:
                conditions.append("repo = ?")
                params.append(repo)

            if author:
                conditions.append("pr_author = ?")
                params.append(author)

            if pr_number:
                conditions.append("pr_number = ?")
                params.append(pr_number)

            if status:
                conditions.append("status = ?")
                params.append(status)

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            query = f"""
                SELECT * FROM reviews
                {where_clause}
                ORDER BY review_timestamp DESC
                LIMIT ? OFFSET ?
            """
            params.extend([limit, offset])

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_review_stats(self) -> Dict[str, Any]:
        """Get review statistics."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Total reviews
            cursor.execute("SELECT COUNT(*) as total FROM reviews")
            total = cursor.fetchone()["total"]

            # Reviews by status
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM reviews
                GROUP BY status
            """)
            by_status = {row["status"]: row["count"] for row in cursor.fetchall()}

            # Reviews by repo
            cursor.execute("""
                SELECT repo, COUNT(*) as count
                FROM reviews
                GROUP BY repo
                ORDER BY count DESC
                LIMIT 10
            """)
            by_repo = {row["repo"]: row["count"] for row in cursor.fetchall()}

            # Average score (excluding nulls)
            cursor.execute("""
                SELECT AVG(score) as avg_score
                FROM reviews
                WHERE score IS NOT NULL
            """)
            avg_score = cursor.fetchone()["avg_score"]

            # Follow-up count
            cursor.execute("SELECT COUNT(*) as count FROM reviews WHERE is_followup = 1")
            followup_count = cursor.fetchone()["count"]

            return {
                "total": total,
                "by_status": by_status,
                "by_repo": by_repo,
                "average_score": round(avg_score, 1) if avg_score else None,
                "followup_count": followup_count
            }
        finally:
            conn.close()

    def search_reviews(self, search_text: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search reviews by title or content."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            search_pattern = f"%{search_text}%"
            cursor.execute("""
                SELECT * FROM reviews
                WHERE pr_title LIKE ? OR content LIKE ?
                ORDER BY review_timestamp DESC
                LIMIT ?
            """, (search_pattern, search_pattern, limit))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()


class MergeQueueDB:
    """Database operations for merge queue."""

    def __init__(self, db: Optional[Database] = None):
        """Initialize merge queue database.

        Args:
            db: Optional Database instance. Creates new one if not provided.
        """
        self.db = db or Database()

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        return self.db._get_connection()

    def get_queue(self) -> List[Dict[str, Any]]:
        """Get all items in the merge queue, ordered by position."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM merge_queue
                ORDER BY position ASC
            """)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def add_to_queue(
        self,
        pr_number: int,
        repo: str,
        pr_title: Optional[str] = None,
        pr_author: Optional[str] = None,
        pr_url: Optional[str] = None,
        additions: int = 0,
        deletions: int = 0
    ) -> Dict[str, Any]:
        """Add a PR to the merge queue.

        Returns:
            The added queue item.

        Raises:
            ValueError: If PR is already in queue.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Check if already in queue
            cursor.execute(
                "SELECT id FROM merge_queue WHERE pr_number = ? AND repo = ?",
                (pr_number, repo)
            )
            if cursor.fetchone():
                raise ValueError("PR already in queue")

            # Get next position
            cursor.execute("SELECT COALESCE(MAX(position), 0) + 1 as next_pos FROM merge_queue")
            next_position = cursor.fetchone()["next_pos"]

            cursor.execute("""
                INSERT INTO merge_queue (
                    pr_number, repo, pr_title, pr_author, pr_url,
                    additions, deletions, position
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pr_number, repo, pr_title, pr_author, pr_url,
                additions, deletions, next_position
            ))

            conn.commit()

            # Return the inserted item
            cursor.execute(
                "SELECT * FROM merge_queue WHERE pr_number = ? AND repo = ?",
                (pr_number, repo)
            )
            return dict(cursor.fetchone())
        finally:
            conn.close()

    def remove_from_queue(self, pr_number: int, repo: Optional[str] = None) -> bool:
        """Remove a PR from the merge queue.

        Args:
            pr_number: The PR number to remove.
            repo: Optional repo filter. If None, removes matching PR from any repo.

        Returns:
            True if item was removed, False if not found.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            if repo:
                cursor.execute(
                    "DELETE FROM merge_queue WHERE pr_number = ? AND repo = ?",
                    (pr_number, repo)
                )
            else:
                cursor.execute(
                    "DELETE FROM merge_queue WHERE pr_number = ?",
                    (pr_number,)
                )

            deleted = cursor.rowcount > 0

            if deleted:
                # Reorder remaining items
                self._reorder_positions(cursor)
                conn.commit()

            return deleted
        finally:
            conn.close()

    def _reorder_positions(self, cursor: sqlite3.Cursor):
        """Reorder position values to be sequential starting from 1."""
        cursor.execute("""
            UPDATE merge_queue
            SET position = (
                SELECT COUNT(*)
                FROM merge_queue AS mq2
                WHERE mq2.position <= merge_queue.position
            )
        """)

    def reorder_queue(self, order: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Reorder the merge queue based on provided order.

        Args:
            order: List of dicts with 'number' and 'repo' keys in desired order.

        Returns:
            The reordered queue.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Update positions based on order
            for position, item in enumerate(order, start=1):
                cursor.execute("""
                    UPDATE merge_queue
                    SET position = ?
                    WHERE pr_number = ? AND repo = ?
                """, (position, item["number"], item["repo"]))

            conn.commit()

            # Return updated queue
            return self.get_queue()
        finally:
            conn.close()

    def clear_queue(self):
        """Remove all items from the merge queue."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM merge_queue")
            conn.commit()
        finally:
            conn.close()

    def is_in_queue(self, pr_number: int, repo: str) -> bool:
        """Check if a PR is in the merge queue."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM merge_queue WHERE pr_number = ? AND repo = ?",
                (pr_number, repo)
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()


# Singleton instances for convenience
_db_instance: Optional[Database] = None
_reviews_db: Optional[ReviewsDB] = None
_queue_db: Optional[MergeQueueDB] = None


def get_database() -> Database:
    """Get the singleton Database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance


def get_reviews_db() -> ReviewsDB:
    """Get the singleton ReviewsDB instance."""
    global _reviews_db
    if _reviews_db is None:
        _reviews_db = ReviewsDB(get_database())
    return _reviews_db


def get_queue_db() -> MergeQueueDB:
    """Get the singleton MergeQueueDB instance."""
    global _queue_db
    if _queue_db is None:
        _queue_db = MergeQueueDB(get_database())
    return _queue_db
