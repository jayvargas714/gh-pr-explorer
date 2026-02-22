"""Database base class - connection management, schema init, migrations."""

import sqlite3
import logging
from pathlib import Path
from typing import Optional

from backend.config import DB_PATH

logger = logging.getLogger(__name__)


class Database:
    """SQLite database manager for PR Explorer."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
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

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_queue_position
                ON merge_queue(position)
            """)

            # Create queue_notes table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS queue_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue_item_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (queue_item_id) REFERENCES merge_queue(id) ON DELETE CASCADE
                )
            """)

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

            # Create user_settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL UNIQUE,
                    value TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create developer_stats table
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

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_developer_stats_repo
                ON developer_stats(repo)
            """)

            # Create stats_metadata table
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

            # Create code_activity_cache table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS code_activity_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo TEXT NOT NULL UNIQUE,
                    data TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Migration: Add section-posted columns to reviews for existing databases
            cursor.execute("PRAGMA table_info(reviews)")
            reviews_columns = {row[1] for row in cursor.fetchall()}

            review_new_columns = [
                ("major_concerns_posted", "BOOLEAN DEFAULT FALSE"),
                ("minor_issues_posted", "BOOLEAN DEFAULT FALSE"),
            ]

            for col_name, col_type in review_new_columns:
                if col_name not in reviews_columns:
                    try:
                        cursor.execute(f"ALTER TABLE reviews ADD COLUMN {col_name} {col_type}")
                        logger.info(f"Added column {col_name} to reviews table")
                    except sqlite3.OperationalError:
                        pass

            # Migration: Add new columns to developer_stats for existing databases
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
                        pass

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
