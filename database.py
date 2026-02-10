#!/usr/bin/env python3
"""Database module for GitHub PR Explorer.

Provides SQLite-backed persistence for code reviews and merge queue.
"""

import json
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
        # Enable foreign keys for CASCADE support
        conn.execute("PRAGMA foreign_keys = ON")
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
                    score REAL CHECK(score >= 0 AND score <= 10),
                    content TEXT,
                    is_followup BOOLEAN DEFAULT FALSE,
                    parent_review_id INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    head_commit_sha TEXT,
                    inline_comments_posted BOOLEAN DEFAULT FALSE,
                    pr_state_at_review TEXT,
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
                    pr_state TEXT,
                    state_updated_at DATETIME,
                    UNIQUE(pr_number, repo)
                )
            """)

            # Create index for queue position
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_queue_position
                ON merge_queue(position)
            """)

            # Create queue_notes table for notes on merge queue items
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS queue_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue_item_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (queue_item_id) REFERENCES merge_queue(id) ON DELETE CASCADE
                )
            """)

            # Create index for queue_notes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_queue_notes_item
                ON queue_notes(queue_item_id)
            """)

            # Create migrations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS migrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    executed_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create user_settings table for persistent settings
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL UNIQUE,
                    value TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create developer_stats table for caching contributor statistics
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS developer_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo TEXT NOT NULL,
                    username TEXT NOT NULL,
                    total_prs INTEGER DEFAULT 0,
                    open_prs INTEGER DEFAULT 0,
                    merged_prs INTEGER DEFAULT 0,
                    closed_prs INTEGER DEFAULT 0,
                    total_additions INTEGER DEFAULT 0,
                    total_deletions INTEGER DEFAULT 0,
                    avg_pr_score REAL,
                    reviewed_pr_count INTEGER DEFAULT 0,
                    commits INTEGER DEFAULT 0,
                    avatar_url TEXT,
                    reviews_given INTEGER DEFAULT 0,
                    approvals INTEGER DEFAULT 0,
                    changes_requested INTEGER DEFAULT 0,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(repo, username)
                )
            """)

            # Create index for developer_stats
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_developer_stats_repo
                ON developer_stats(repo)
            """)

            # Create stats_metadata table for tracking last update times
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stats_metadata (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo TEXT NOT NULL UNIQUE,
                    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create pr_lifecycle_cache table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pr_lifecycle_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo TEXT NOT NULL UNIQUE,
                    data TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create workflow_cache table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS workflow_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo TEXT NOT NULL UNIQUE,
                    data TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create contributor_timeseries_cache table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS contributor_timeseries_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo TEXT NOT NULL UNIQUE,
                    data TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Migration: Add new columns to developer_stats for existing databases
            # Check if columns exist before adding them
            cursor.execute("PRAGMA table_info(developer_stats)")
            existing_columns = {row[1] for row in cursor.fetchall()}

            new_columns = [
                ("commits", "INTEGER DEFAULT 0"),
                ("avatar_url", "TEXT"),
                ("reviews_given", "INTEGER DEFAULT 0"),
                ("approvals", "INTEGER DEFAULT 0"),
                ("changes_requested", "INTEGER DEFAULT 0"),
            ]

            for col_name, col_type in new_columns:
                if col_name not in existing_columns:
                    try:
                        cursor.execute(f"ALTER TABLE developer_stats ADD COLUMN {col_name} {col_type}")
                        logger.info(f"Added column {col_name} to developer_stats table")
                    except sqlite3.OperationalError:
                        pass  # Column already exists

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
        score: Optional[float] = None,
        content: Optional[str] = None,
        is_followup: bool = False,
        parent_review_id: Optional[int] = None,
        review_timestamp: Optional[datetime] = None,
        head_commit_sha: Optional[str] = None,
        pr_state_at_review: Optional[str] = None
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
                    is_followup, parent_review_id, review_timestamp,
                    head_commit_sha, pr_state_at_review
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pr_number, repo, pr_title, pr_author, pr_url,
                status, review_file_path, score, content,
                is_followup, parent_review_id, timestamp,
                head_commit_sha, pr_state_at_review
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
        score: Optional[float] = None,
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

    def update_inline_comments_posted(self, review_id: int, posted: bool = True):
        """Update the inline_comments_posted flag for a review.

        Args:
            review_id: The ID of the review to update.
            posted: Whether inline comments have been posted.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE reviews SET inline_comments_posted = ? WHERE id = ?",
                (posted, review_id)
            )
            conn.commit()
            logger.info(f"Updated inline_comments_posted for review {review_id} to {posted}")
        finally:
            conn.close()

    def _extract_score(self, content: str) -> Optional[float]:
        """Extract score from review content.

        Looks for patterns like:
        - Score: 7/10
        - Rating: 8.5/10
        - Overall Score: 6.25/10
        - **Score:** 9/10
        """
        if not content:
            return None

        patterns = [
            # Matches: **Review Score: 8.5/10**, ## Overall Score: 7/10, Score: 8/10, etc.
            r'(?:#*\s*)?(?:\*\*)?(?:\w+\s+)?(?:Score|Rating)\s*[:\s]*(\d+(?:\.\d{1,2})?)\s*/?\s*10',
            r'(\d+(?:\.\d{1,2})?)\s*/\s*10\s*(?:score|rating)',
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                score = float(match.group(1))
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
        deletions: int = 0,
        pr_state: Optional[str] = None
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

            state_updated_at = datetime.now() if pr_state else None

            cursor.execute("""
                INSERT INTO merge_queue (
                    pr_number, repo, pr_title, pr_author, pr_url,
                    additions, deletions, position, pr_state, state_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pr_number, repo, pr_title, pr_author, pr_url,
                additions, deletions, next_position, pr_state, state_updated_at
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

    def update_pr_state(self, pr_number: int, repo: str, pr_state: str):
        """Update the PR state for a queue item.

        Args:
            pr_number: The PR number.
            repo: The repository (owner/repo format).
            pr_state: The new PR state (OPEN, CLOSED, MERGED).
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE merge_queue
                SET pr_state = ?, state_updated_at = ?
                WHERE pr_number = ? AND repo = ?
            """, (pr_state, datetime.now(), pr_number, repo))
            conn.commit()
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

    def get_queue_item_id(self, pr_number: int, repo: str) -> Optional[int]:
        """Get the queue item ID for a PR.

        Args:
            pr_number: The PR number.
            repo: The repository (owner/repo format).

        Returns:
            The queue item ID, or None if not found.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM merge_queue WHERE pr_number = ? AND repo = ?",
                (pr_number, repo)
            )
            row = cursor.fetchone()
            return row["id"] if row else None
        finally:
            conn.close()

    def add_note(self, queue_item_id: int, content: str) -> Dict[str, Any]:
        """Add a note to a queue item.

        Args:
            queue_item_id: The ID of the queue item.
            content: The markdown content of the note.

        Returns:
            The created note.

        Raises:
            ValueError: If the queue item doesn't exist.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Verify queue item exists
            cursor.execute("SELECT id FROM merge_queue WHERE id = ?", (queue_item_id,))
            if not cursor.fetchone():
                raise ValueError("Queue item not found")

            cursor.execute("""
                INSERT INTO queue_notes (queue_item_id, content)
                VALUES (?, ?)
            """, (queue_item_id, content))

            conn.commit()
            note_id = cursor.lastrowid

            # Return the created note
            cursor.execute("SELECT * FROM queue_notes WHERE id = ?", (note_id,))
            return dict(cursor.fetchone())
        finally:
            conn.close()

    def get_notes(self, queue_item_id: int) -> List[Dict[str, Any]]:
        """Get all notes for a queue item.

        Args:
            queue_item_id: The ID of the queue item.

        Returns:
            List of notes, ordered by creation date (newest first).
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM queue_notes
                WHERE queue_item_id = ?
                ORDER BY created_at DESC
            """, (queue_item_id,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def delete_note(self, note_id: int) -> bool:
        """Delete a note.

        Args:
            note_id: The ID of the note to delete.

        Returns:
            True if the note was deleted, False if not found.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM queue_notes WHERE id = ?", (note_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_notes_count(self, queue_item_id: int) -> int:
        """Get the count of notes for a queue item.

        Args:
            queue_item_id: The ID of the queue item.

        Returns:
            The number of notes.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as count FROM queue_notes WHERE queue_item_id = ?",
                (queue_item_id,)
            )
            return cursor.fetchone()["count"]
        finally:
            conn.close()


class SettingsDB:
    """Database operations for user settings."""

    def __init__(self, db: Optional[Database] = None):
        """Initialize settings database.

        Args:
            db: Optional Database instance. Creates new one if not provided.
        """
        self.db = db or Database()

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        return self.db._get_connection()

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a setting value.

        Args:
            key: The setting key.
            default: Default value if not found.

        Returns:
            The setting value (JSON parsed) or default.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM user_settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row and row["value"]:
                try:
                    return json.loads(row["value"])
                except json.JSONDecodeError:
                    return row["value"]
            return default
        finally:
            conn.close()

    def set_setting(self, key: str, value: Any) -> None:
        """Set a setting value.

        Args:
            key: The setting key.
            value: The value to store (will be JSON encoded).
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            json_value = json.dumps(value) if not isinstance(value, str) else value
            cursor.execute("""
                INSERT INTO user_settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, json_value))
            conn.commit()
        finally:
            conn.close()

    def delete_setting(self, key: str) -> bool:
        """Delete a setting.

        Args:
            key: The setting key.

        Returns:
            True if deleted, False if not found.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_settings WHERE key = ?", (key,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_all_settings(self) -> Dict[str, Any]:
        """Get all settings as a dictionary.

        Returns:
            Dictionary of all settings.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM user_settings")
            settings = {}
            for row in cursor.fetchall():
                try:
                    settings[row["key"]] = json.loads(row["value"])
                except json.JSONDecodeError:
                    settings[row["key"]] = row["value"]
            return settings
        finally:
            conn.close()


class DeveloperStatsDB:
    """Database operations for cached developer statistics."""

    CACHE_TTL_HOURS = 4  # Stats are considered stale after 4 hours

    def __init__(self, db: Optional[Database] = None):
        """Initialize developer stats database.

        Args:
            db: Optional Database instance. Creates new one if not provided.
        """
        self.db = db or Database()

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        return self.db._get_connection()

    def get_last_updated(self, repo: str) -> Optional[datetime]:
        """Get the last update timestamp for a repo's stats.

        Args:
            repo: Repository in owner/repo format.

        Returns:
            The last updated datetime or None if never updated.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT last_updated FROM stats_metadata WHERE repo = ?",
                (repo,)
            )
            row = cursor.fetchone()
            if row and row["last_updated"]:
                return datetime.fromisoformat(row["last_updated"])
            return None
        finally:
            conn.close()

    def is_stale(self, repo: str) -> bool:
        """Check if stats for a repo are stale (older than TTL).

        Args:
            repo: Repository in owner/repo format.

        Returns:
            True if stats are stale or don't exist.
        """
        last_updated = self.get_last_updated(repo)
        if last_updated is None:
            return True
        age = datetime.now() - last_updated
        return age.total_seconds() > (self.CACHE_TTL_HOURS * 3600)

    def get_stats(self, repo: str) -> List[Dict[str, Any]]:
        """Get cached stats for a repository.

        Args:
            repo: Repository in owner/repo format.

        Returns:
            List of developer stats dictionaries.
        """
        conn = self._get_connection()
        try:
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
        finally:
            conn.close()

    def save_stats(self, repo: str, stats: List[Dict[str, Any]]) -> None:
        """Save developer stats for a repository.

        Args:
            repo: Repository in owner/repo format.
            stats: List of stats dictionaries with keys:
                   username, total_prs, open_prs, merged_prs, closed_prs,
                   total_additions, total_deletions, avg_pr_score, reviewed_pr_count,
                   commits, avatar_url, reviews_given, approvals, changes_requested
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Clear existing stats for this repo
            cursor.execute("DELETE FROM developer_stats WHERE repo = ?", (repo,))

            # Insert new stats
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

            # Update metadata
            cursor.execute("""
                INSERT INTO stats_metadata (repo, last_updated)
                VALUES (?, CURRENT_TIMESTAMP)
                ON CONFLICT(repo) DO UPDATE SET
                    last_updated = CURRENT_TIMESTAMP
            """, (repo,))

            conn.commit()
        finally:
            conn.close()

    def clear_stats(self, repo: str) -> None:
        """Clear cached stats for a repository.

        Args:
            repo: Repository in owner/repo format.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM developer_stats WHERE repo = ?", (repo,))
            cursor.execute("DELETE FROM stats_metadata WHERE repo = ?", (repo,))
            conn.commit()
        finally:
            conn.close()


class LifecycleCacheDB:
    """Cache for PR lifecycle/review timing data in SQLite."""

    def __init__(self, db: Database):
        self.db = db
        self._get_connection = db._get_connection

    def get_cached(self, repo: str) -> Optional[Dict[str, Any]]:
        """Get cached lifecycle data for a repository."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT data, updated_at FROM pr_lifecycle_cache WHERE repo = ?",
                (repo,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "data": json.loads(row["data"]),
                    "updated_at": row["updated_at"]
                }
            return None
        finally:
            conn.close()

    def save_cache(self, repo: str, data: Any) -> None:
        """Save lifecycle data to cache."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO pr_lifecycle_cache (repo, data, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(repo) DO UPDATE SET
                   data = excluded.data, updated_at = CURRENT_TIMESTAMP""",
                (repo, json.dumps(data))
            )
            conn.commit()
        finally:
            conn.close()

    def is_stale(self, repo: str, ttl_hours: int = 2) -> bool:
        """Check if cached data is older than TTL."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT updated_at FROM pr_lifecycle_cache WHERE repo = ?",
                (repo,)
            )
            row = cursor.fetchone()
            if not row:
                return True
            updated = datetime.strptime(row["updated_at"], "%Y-%m-%d %H:%M:%S")
            age_hours = (datetime.now() - updated).total_seconds() / 3600
            return age_hours > ttl_hours
        finally:
            conn.close()


class WorkflowCacheDB:
    """Cache for workflow runs data in SQLite."""

    def __init__(self, db: Database):
        self.db = db
        self._get_connection = db._get_connection

    def get_cached(self, repo: str) -> Optional[Dict[str, Any]]:
        """Get cached workflow data for a repository."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT data, updated_at FROM workflow_cache WHERE repo = ?",
                (repo,)
            )
            row = cursor.fetchone()
            if row:
                try:
                    return {
                        "data": json.loads(row["data"]),
                        "updated_at": row["updated_at"]
                    }
                except json.JSONDecodeError:
                    logger.warning(f"Corrupt workflow cache for {repo}, treating as miss")
                    return None
            return None
        finally:
            conn.close()

    def save_cache(self, repo: str, data: Any) -> None:
        """Save workflow data to cache."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO workflow_cache (repo, data, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(repo) DO UPDATE SET
                   data = excluded.data, updated_at = CURRENT_TIMESTAMP""",
                (repo, json.dumps(data))
            )
            conn.commit()
        finally:
            conn.close()

    def is_stale(self, repo: str, ttl_minutes: int = 60) -> bool:
        """Check if cached data is older than TTL."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT updated_at FROM workflow_cache WHERE repo = ?",
                (repo,)
            )
            row = cursor.fetchone()
            if not row:
                return True
            updated = datetime.strptime(row["updated_at"], "%Y-%m-%d %H:%M:%S")
            age_minutes = (datetime.now() - updated).total_seconds() / 60
            return age_minutes > ttl_minutes
        finally:
            conn.close()

    def get_all_repos(self) -> List[str]:
        """Get all repos that have cached workflow data."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT repo FROM workflow_cache")
            return [row["repo"] for row in cursor.fetchall()]
        finally:
            conn.close()

    def clear(self) -> None:
        """Clear all workflow cache entries."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM workflow_cache")
            conn.commit()
        finally:
            conn.close()


class ContributorTimeSeriesCacheDB:
    """Cache for per-contributor weekly time series data in SQLite."""

    def __init__(self, db: Database):
        self.db = db
        self._get_connection = db._get_connection

    def get_cached(self, repo: str) -> Optional[Dict[str, Any]]:
        """Get cached contributor time series data for a repository."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT data, updated_at FROM contributor_timeseries_cache WHERE repo = ?",
                (repo,)
            )
            row = cursor.fetchone()
            if row:
                try:
                    return {
                        "data": json.loads(row["data"]),
                        "updated_at": row["updated_at"]
                    }
                except json.JSONDecodeError:
                    logger.warning(f"Corrupt contributor TS cache for {repo}, treating as miss")
                    return None
            return None
        finally:
            conn.close()

    def save_cache(self, repo: str, data: Any) -> None:
        """Save contributor time series data to cache."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO contributor_timeseries_cache (repo, data, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(repo) DO UPDATE SET
                   data = excluded.data, updated_at = CURRENT_TIMESTAMP""",
                (repo, json.dumps(data))
            )
            conn.commit()
        finally:
            conn.close()

    def is_stale(self, repo: str, ttl_hours: int = 24) -> bool:
        """Check if cached data is older than TTL (default 24 hours)."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT updated_at FROM contributor_timeseries_cache WHERE repo = ?",
                (repo,)
            )
            row = cursor.fetchone()
            if not row:
                return True
            updated = datetime.strptime(row["updated_at"], "%Y-%m-%d %H:%M:%S")
            age_hours = (datetime.now() - updated).total_seconds() / 3600
            return age_hours > ttl_hours
        finally:
            conn.close()

    def clear(self) -> None:
        """Clear all contributor time series cache entries."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM contributor_timeseries_cache")
            conn.commit()
        finally:
            conn.close()


# Singleton instances for convenience
_db_instance: Optional[Database] = None
_reviews_db: Optional[ReviewsDB] = None
_queue_db: Optional[MergeQueueDB] = None
_settings_db: Optional[SettingsDB] = None
_dev_stats_db: Optional[DeveloperStatsDB] = None
_lifecycle_cache_db: Optional[LifecycleCacheDB] = None
_workflow_cache_db: Optional[WorkflowCacheDB] = None
_contributor_ts_cache_db: Optional[ContributorTimeSeriesCacheDB] = None


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


def get_settings_db() -> SettingsDB:
    """Get the singleton SettingsDB instance."""
    global _settings_db
    if _settings_db is None:
        _settings_db = SettingsDB(get_database())
    return _settings_db


def get_dev_stats_db() -> DeveloperStatsDB:
    """Get the singleton DeveloperStatsDB instance."""
    global _dev_stats_db
    if _dev_stats_db is None:
        _dev_stats_db = DeveloperStatsDB(get_database())
    return _dev_stats_db


def get_lifecycle_cache_db() -> LifecycleCacheDB:
    """Get the singleton LifecycleCacheDB instance."""
    global _lifecycle_cache_db
    if _lifecycle_cache_db is None:
        _lifecycle_cache_db = LifecycleCacheDB(get_database())
    return _lifecycle_cache_db


def get_workflow_cache_db() -> WorkflowCacheDB:
    """Get the singleton WorkflowCacheDB instance."""
    global _workflow_cache_db
    if _workflow_cache_db is None:
        _workflow_cache_db = WorkflowCacheDB(get_database())
    return _workflow_cache_db


def get_contributor_ts_cache_db() -> ContributorTimeSeriesCacheDB:
    """Get the singleton ContributorTimeSeriesCacheDB instance."""
    global _contributor_ts_cache_db
    if _contributor_ts_cache_db is None:
        _contributor_ts_cache_db = ContributorTimeSeriesCacheDB(get_database())
    return _contributor_ts_cache_db
