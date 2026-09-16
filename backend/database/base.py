"""Database base class - connection management, schema init, migrations."""

import sqlite3
import logging
from contextlib import contextmanager
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

    @contextmanager
    def connection(self):
        """Context manager that yields a connection, commits on success, rollbacks on exception."""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        """Initialize database schema."""
        with self.connection() as conn:
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
                    content_json TEXT NOT NULL,
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

            # Create workflow_cache table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS workflow_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo TEXT NOT NULL UNIQUE,
                    data TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create repo_stats_cache table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS repo_stats_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo TEXT NOT NULL UNIQUE,
                    data TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create repo_loc_cache table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS repo_loc_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo TEXT NOT NULL UNIQUE,
                    data TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create pr_timeline_cache table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pr_timeline_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo TEXT NOT NULL,
                    pr_number INTEGER NOT NULL,
                    pr_state TEXT NOT NULL,
                    data TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(repo, pr_number)
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_pr_timeline_cache_key
                ON pr_timeline_cache(repo, pr_number)
            """)

            # Create swimlanes table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS swimlanes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    color TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    is_default INTEGER DEFAULT 0,
                    is_protected INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_swimlanes_position
                ON swimlanes(position)
            """)

            # Create swimlane_assignments table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS swimlane_assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue_item_id INTEGER NOT NULL UNIQUE,
                    swimlane_id INTEGER,
                    position_in_lane INTEGER NOT NULL,
                    is_pinned INTEGER NOT NULL DEFAULT 0,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (queue_item_id) REFERENCES merge_queue(id) ON DELETE CASCADE,
                    FOREIGN KEY (swimlane_id) REFERENCES swimlanes(id) ON DELETE SET NULL
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_swl_assign_lane
                ON swimlane_assignments(swimlane_id)
            """)

            # Review events table: append-only operational log of review attempts.
            # No FOREIGN KEY on review_id: events are written for attempts that
            # never produced a reviews row, and foreign_keys is ON for every
            # connection — a FK would reject exactly the failures this log exists
            # to record.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS review_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    repo TEXT NOT NULL,
                    pr_number INTEGER NOT NULL,
                    reviewer_agent TEXT,
                    is_followup BOOLEAN DEFAULT FALSE,
                    auto_started BOOLEAN DEFAULT FALSE,
                    attempt INTEGER,
                    max_attempts INTEGER,
                    exit_code INTEGER,
                    reason TEXT,
                    detail TEXT,
                    review_file TEXT,
                    review_id INTEGER,
                    score REAL,
                    pid INTEGER
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_review_events_repo_pr
                ON review_events(repo, pr_number)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_review_events_run
                ON review_events(run_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_review_events_created
                ON review_events(created_at DESC)
            """)

            # Create audits table (PB↔ED audits — parallel to reviews)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pr_number INTEGER NOT NULL,
                    repo TEXT NOT NULL,
                    pr_title TEXT,
                    pr_author TEXT,
                    pr_url TEXT,
                    head_ref TEXT,
                    base_ref TEXT,
                    audit_type TEXT NOT NULL DEFAULT 'pb_ed',
                    audit_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL DEFAULT 'completed',
                    content_json TEXT NOT NULL,
                    finding_count INTEGER DEFAULT 0,
                    blocking_count INTEGER DEFAULT 0,
                    inline_comments_posted BOOLEAN DEFAULT FALSE,
                    audit_file_path TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_audits_repo_pr
                ON audits(repo, pr_number)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_audits_timestamp
                ON audits(audit_timestamp DESC)
            """)

            # Create auto_verdicts table (one row per review the auto-verdict evaluator handled).
            # review_id is UNIQUE: the row is claimed before GitHub is contacted, so the
            # constraint is what makes double-posting impossible when the watcher thread and
            # the frontend poll notice the same completion.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS auto_verdicts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo TEXT NOT NULL,
                    pr_number INTEGER NOT NULL,
                    review_id INTEGER UNIQUE,
                    event TEXT,
                    outcome TEXT NOT NULL DEFAULT 'pending',
                    reason TEXT,
                    blocking_count INTEGER,
                    non_blocking_count INTEGER,
                    disputed_count INTEGER,
                    deferred_count INTEGER,
                    criteria_json TEXT,
                    head_commit_sha TEXT,
                    error_detail TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (review_id) REFERENCES reviews(id)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_auto_verdicts_repo_pr
                ON auto_verdicts(repo, pr_number)
            """)
            # Set-aside counts: findings the author disputed or deferred, which
            # never count toward the verdict thresholds but drive the mediation
            # outcome. NULL on rows recorded before the columns existed.
            cursor.execute("PRAGMA table_info(auto_verdicts)")
            auto_verdict_columns = {row[1] for row in cursor.fetchall()}
            for column in ("disputed_count", "deferred_count"):
                if column not in auto_verdict_columns:
                    cursor.execute(f"ALTER TABLE auto_verdicts ADD COLUMN {column} INTEGER")
                    logger.info(f"Added column {column} to auto_verdicts table")

            # Automation dispatches: one row per PR the automation pipeline has seen.
            # UNIQUE(repo, pr_number) is the restart-proof idempotence guard — a PR
            # is auto-dispatched at most once, ever.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS automation_dispatches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo TEXT NOT NULL,
                    pr_number INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    outcome_json TEXT,
                    reviewer_key TEXT,
                    detail TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    enrolled_at DATETIME,
                    UNIQUE(repo, pr_number)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_automation_dispatches_status
                ON automation_dispatches(status)
            """)

            # Migration: enrolled_at is the dispatch-window clock (reset on
            # requeue), distinct from created_at (first seen). Seed legacy rows
            # from created_at so their window is unchanged.
            cursor.execute("PRAGMA table_info(automation_dispatches)")
            dispatch_columns = {row[1] for row in cursor.fetchall()}
            if "enrolled_at" not in dispatch_columns:
                cursor.execute("ALTER TABLE automation_dispatches ADD COLUMN enrolled_at DATETIME")
                cursor.execute(
                    "UPDATE automation_dispatches SET enrolled_at = created_at "
                    "WHERE enrolled_at IS NULL"
                )
                logger.info("Added column enrolled_at to automation_dispatches table")

            # Review requests: follow-up demand created when a human requests a
            # review from the authenticated user on an already-dispatched PR.
            # One row per PR; re-requests reset the row to pending.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS review_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo TEXT NOT NULL,
                    pr_number INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    requested_at DATETIME NOT NULL,
                    detail TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(repo, pr_number)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_review_requests_status
                ON review_requests(status)
            """)

            # Reviewer registry: configurable reviewer agents (seeded by ReviewersDB.ensure_builtins)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reviewers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL UNIQUE,
                    label TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    prompt_context TEXT,
                    is_builtin INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # PR list sync: registered repos + full PR JSON rows (see docs/specs/2026-08-28-pr-sync-db-design.md)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS synced_repos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo TEXT NOT NULL UNIQUE,
                    registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_visited_at DATETIME,
                    last_synced_at DATETIME,
                    backfill_done INTEGER NOT NULL DEFAULT 0,
                    backfill_error TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS synced_prs (
                    repo TEXT NOT NULL,
                    pr_number INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    is_draft INTEGER NOT NULL DEFAULT 0,
                    author TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    closed_at TEXT,
                    merged_at TEXT,
                    data TEXT NOT NULL,
                    fetched_at DATETIME NOT NULL,
                    PRIMARY KEY (repo, pr_number)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_synced_prs_repo_state
                ON synced_prs(repo, state)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_synced_prs_repo_updated
                ON synced_prs(repo, updated_at DESC)
            """)

            # Migration: Add inception-walk history tracking columns to synced_repos
            cursor.execute("PRAGMA table_info(synced_repos)")
            synced_repos_columns = {row[1] for row in cursor.fetchall()}

            synced_repos_new_columns = [
                ("repo_created_at", "TEXT"),
                ("history_cursor", "TEXT"),
                ("history_done", "INTEGER NOT NULL DEFAULT 0"),
                ("history_error", "TEXT"),
            ]

            for col_name, col_type in synced_repos_new_columns:
                if col_name not in synced_repos_columns:
                    try:
                        cursor.execute(f"ALTER TABLE synced_repos ADD COLUMN {col_name} {col_type}")
                        logger.info(f"Added column {col_name} to synced_repos table")
                    except sqlite3.OperationalError:
                        pass

            # Commit sync: per-branch backfill/incremental state, and the commits themselves
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS synced_commit_branches (
                    repo TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    backfill_until TEXT,
                    backfill_done INTEGER NOT NULL DEFAULT 0,
                    last_committed_at TEXT,
                    last_synced_at TEXT,
                    error TEXT,
                    PRIMARY KEY (repo, branch)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS synced_commits (
                    repo TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    sha TEXT NOT NULL,
                    author_login TEXT,
                    author_name TEXT,
                    author_email TEXT,
                    authored_at TEXT,
                    committed_at TEXT NOT NULL,
                    parent_count INTEGER NOT NULL DEFAULT 1,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY (repo, branch, sha)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_synced_commits_repo_branch_day
                ON synced_commits(repo, branch, committed_at)
            """)

            # Analytics daily rollup: precomputed per-developer, per-day metrics
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS analytics_daily (
                    repo TEXT NOT NULL,
                    day TEXT NOT NULL,
                    login TEXT NOT NULL,
                    base_ref TEXT NOT NULL,
                    is_bot INTEGER NOT NULL DEFAULT 0,
                    prs_created INTEGER NOT NULL DEFAULT 0,
                    prs_merged INTEGER NOT NULL DEFAULT 0,
                    prs_closed INTEGER NOT NULL DEFAULT 0,
                    reviews INTEGER NOT NULL DEFAULT 0,
                    approvals INTEGER NOT NULL DEFAULT 0,
                    changes_requested INTEGER NOT NULL DEFAULT 0,
                    comments INTEGER NOT NULL DEFAULT 0,
                    additions INTEGER NOT NULL DEFAULT 0,
                    deletions INTEGER NOT NULL DEFAULT 0,
                    commits INTEGER NOT NULL DEFAULT 0,
                    merge_hours_sum REAL NOT NULL DEFAULT 0,
                    merge_hours_count INTEGER NOT NULL DEFAULT 0,
                    review_rounds_sum INTEGER NOT NULL DEFAULT 0,
                    review_rounds_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (repo, day, login, base_ref)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_analytics_daily_repo_day
                ON analytics_daily(repo, day)
            """)

            # Migration: Add review-rounds columns to analytics_daily for existing databases
            cursor.execute("PRAGMA table_info(analytics_daily)")
            analytics_daily_columns = {row[1] for row in cursor.fetchall()}
            analytics_daily_new_columns = [
                ("review_rounds_sum", "INTEGER NOT NULL DEFAULT 0"),
                ("review_rounds_count", "INTEGER NOT NULL DEFAULT 0"),
            ]
            for col_name, col_type in analytics_daily_new_columns:
                if col_name not in analytics_daily_columns:
                    try:
                        cursor.execute(f"ALTER TABLE analytics_daily ADD COLUMN {col_name} {col_type}")
                        logger.info(f"Added column {col_name} to analytics_daily table")
                    except sqlite3.OperationalError:
                        pass

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS analytics_daily_meta (
                    repo TEXT PRIMARY KEY,
                    built_at TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    pr_count INTEGER,
                    review_count INTEGER,
                    commit_count INTEGER,
                    earliest_pr_day TEXT,
                    earliest_commit_day TEXT
                )
            """)

            # Migration: Add auto-verdict arming columns to merge_queue for existing databases
            cursor.execute("PRAGMA table_info(merge_queue)")
            queue_columns = {row[1] for row in cursor.fetchall()}

            queue_new_columns = [
                ("auto_verdict_enabled", "INTEGER NOT NULL DEFAULT 0"),
                ("auto_verdict_reviewer", "TEXT"),
                ("auto_verdict_mode", "TEXT"),        # 'verdict' | 'comment'; NULL reads as 'verdict'
                ("auto_verdict_criteria", "TEXT"),    # per-PR criteria override (JSON), NULL = use global
            ]

            for col_name, col_type in queue_new_columns:
                if col_name not in queue_columns:
                    try:
                        cursor.execute(f"ALTER TABLE merge_queue ADD COLUMN {col_name} {col_type}")
                        logger.info(f"Added column {col_name} to merge_queue table")
                    except sqlite3.OperationalError:
                        pass

            # Per-PR auto-verdict arming, decoupled from the merge queue. Column
            # names match the (now unused) merge_queue.auto_verdict_* columns so
            # the row dict is consumed by the same helpers.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS auto_verdict_arming (
                    repo TEXT NOT NULL,
                    pr_number INTEGER NOT NULL,
                    auto_verdict_enabled INTEGER NOT NULL DEFAULT 0,
                    auto_verdict_reviewer TEXT,
                    auto_verdict_mode TEXT,
                    auto_verdict_criteria TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (repo, pr_number)
                )
            """)

            # Migration (once): copy arming state off merge_queue rows.
            cursor.execute(
                "SELECT 1 FROM migrations WHERE name = 'copy_arming_from_merge_queue'"
            )
            if cursor.fetchone() is None:
                cursor.execute("""
                    INSERT OR IGNORE INTO auto_verdict_arming
                        (repo, pr_number, auto_verdict_enabled, auto_verdict_reviewer,
                         auto_verdict_mode, auto_verdict_criteria)
                    SELECT repo, pr_number, auto_verdict_enabled, auto_verdict_reviewer,
                           auto_verdict_mode, auto_verdict_criteria
                    FROM merge_queue
                    WHERE auto_verdict_enabled = 1 OR auto_verdict_criteria IS NOT NULL
                """)
                if cursor.rowcount:
                    logger.info(f"Copied {cursor.rowcount} arming rows from merge_queue "
                                "to auto_verdict_arming")
                cursor.execute(
                    "INSERT OR IGNORE INTO migrations (name) VALUES ('copy_arming_from_merge_queue')"
                )

            # Migration: Add is_pinned column to swimlane_assignments for existing databases
            cursor.execute("PRAGMA table_info(swimlane_assignments)")
            swl_assign_columns = {row[1] for row in cursor.fetchall()}
            if "is_pinned" not in swl_assign_columns:
                try:
                    cursor.execute(
                        "ALTER TABLE swimlane_assignments "
                        "ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0"
                    )
                    logger.info("Added column is_pinned to swimlane_assignments table")
                except sqlite3.OperationalError:
                    pass

            # Migration: Add is_protected column to swimlanes for existing databases
            cursor.execute("PRAGMA table_info(swimlanes)")
            swimlane_columns = {row[1] for row in cursor.fetchall()}
            if "is_protected" not in swimlane_columns:
                try:
                    cursor.execute(
                        "ALTER TABLE swimlanes "
                        "ADD COLUMN is_protected INTEGER NOT NULL DEFAULT 0"
                    )
                    logger.info("Added column is_protected to swimlanes table")
                except sqlite3.OperationalError:
                    pass

            # Migration: Add reviewer/auto-start columns to reviews for existing
            # databases. (The pre-two-tier per-severity posting counters —
            # critical/major/minor_*_count, major_concerns_posted,
            # minor_issues_posted — are no longer created; existing databases
            # keep them as unread legacy columns.)
            cursor.execute("PRAGMA table_info(reviews)")
            reviews_columns = {row[1] for row in cursor.fetchall()}

            review_new_columns = [
                ("reviewer_agent", "TEXT"),
                ("auto_started", "BOOLEAN DEFAULT FALSE"),
            ]

            for col_name, col_type in review_new_columns:
                if col_name not in reviews_columns:
                    try:
                        cursor.execute(f"ALTER TABLE reviews ADD COLUMN {col_name} {col_type}")
                        logger.info(f"Added column {col_name} to reviews table")
                    except sqlite3.OperationalError:
                        pass

            # Migration (once): drop the legacy analytics cache tables now that
            # analytics reads from the analytics_daily rollup instead.
            cursor.execute(
                "SELECT 1 FROM migrations WHERE name = 'drop_legacy_analytics_caches'"
            )
            if cursor.fetchone() is None:
                for table in (
                    "developer_stats", "stats_metadata", "pr_lifecycle_cache",
                    "code_activity_cache", "contributor_timeseries_cache",
                ):
                    cursor.execute(f"DROP TABLE IF EXISTS {table}")
                cursor.execute(
                    "INSERT OR IGNORE INTO migrations (name) VALUES ('drop_legacy_analytics_caches')"
                )
                logger.info("Dropped legacy analytics cache tables")

            # Two-tier severity (blocking / non_blocking): columns on every init,
            # data folded once. Runs after copy_arming_from_merge_queue so a
            # copied legacy criteria override is upgraded in the same init.
            # Imported lazily: services depend on the database package, not the reverse.
            from backend.database import severity_migration

            severity_migration.ensure_columns(cursor)
            if not severity_migration.is_applied(cursor):
                report = severity_migration.apply_severity_two_tier(cursor)
                severity_migration.mark_applied(cursor)
                if report["reviews_seen"]:
                    logger.info(f"Migrated review severities to two tiers: {report}")

            logger.info(f"Database initialized at {self.db_path}")

    def is_migration_done(self, name: str) -> bool:
        """Check if a migration has been executed."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM migrations WHERE name = ?", (name,))
            return cursor.fetchone() is not None

    def mark_migration_done(self, name: str):
        """Mark a migration as completed."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO migrations (name) VALUES (?)",
                (name,)
            )
