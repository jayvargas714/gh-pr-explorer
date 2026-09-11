"""Tests for the analytics-daily schema additions to Database._init_db."""
import sqlite3

from backend.database.base import Database


def test_schema_init_is_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    Database(db_path)
    Database(db_path)  # re-init must not raise (idempotent ALTERs / CREATE IF NOT EXISTS)

    conn = sqlite3.connect(db_path)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert {"synced_commit_branches", "synced_commits", "analytics_daily", "analytics_daily_meta"} <= tables


def test_synced_repos_new_columns_present(tmp_path):
    db = Database(tmp_path / "test.db")
    conn = sqlite3.connect(db.db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(synced_repos)").fetchall()}
    conn.close()
    assert {"repo_created_at", "history_cursor", "history_done", "history_error"} <= cols


def test_drop_legacy_analytics_caches_migration(tmp_path):
    db_path = tmp_path / "test.db"

    # Pre-create a legacy table by hand, as if from an older DB version.
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE developer_stats (id INTEGER PRIMARY KEY, repo TEXT)")
    conn.commit()
    conn.close()

    db = Database(db_path)
    conn = sqlite3.connect(db_path)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "developer_stats" not in tables
    assert db.is_migration_done("drop_legacy_analytics_caches")

    # Re-init is a no-op (idempotent).
    Database(db_path)
    conn = sqlite3.connect(db_path)
    tables_again = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert tables_again == tables


def test_drop_legacy_analytics_caches_migration_fresh_db(tmp_path):
    """Safe on a fresh DB where the legacy tables never existed."""
    db = Database(tmp_path / "fresh.db")
    assert db.is_migration_done("drop_legacy_analytics_caches")


def test_analytics_daily_gains_review_rounds_columns_on_existing_db(tmp_path):
    """A DB created with the old analytics_daily DDL (no review_rounds_* columns)
    gains them via the PRAGMA-guarded ALTER on the next init."""
    db_path = tmp_path / "test.db"

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE analytics_daily (
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
            PRIMARY KEY (repo, day, login, base_ref)
        )
    """)
    conn.commit()
    conn.close()

    db = Database(db_path)
    conn = sqlite3.connect(db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(analytics_daily)").fetchall()}
    conn.close()
    assert {"review_rounds_sum", "review_rounds_count"} <= cols

    # Re-init is a no-op (idempotent).
    Database(db_path)
