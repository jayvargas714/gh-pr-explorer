#!/usr/bin/env python3
"""Migrate reviews from markdown content to structured JSON format.

Creates a new database with the updated schema (content_json instead of content),
migrates all reviews by parsing markdown->JSON, copies all non-review tables verbatim.

Usage:
    python migrate_reviews_to_json.py              # run migration
    python migrate_reviews_to_json.py --dry-run    # preview without writing
"""

import argparse
import json
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.services.review_schema import markdown_to_json, validate_review_json


DB_PATH = Path(__file__).parent / "pr_explorer.db"


def backup_db(db_path: Path) -> Path:
    """Create a timestamped backup of the database."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = db_path.parent / f"{db_path.stem}.db.bak-pre-json-{timestamp}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def create_new_db(new_path: Path, old_conn: sqlite3.Connection):
    """Create new database with updated schema and copy non-review tables."""
    new_conn = sqlite3.connect(new_path)
    new_conn.execute("PRAGMA foreign_keys = ON")

    # Get all table creation SQL from old database
    old_cursor = old_conn.cursor()
    old_cursor.execute("""
        SELECT name, sql FROM sqlite_master
        WHERE type='table' AND name != 'sqlite_sequence'
        ORDER BY name
    """)
    tables = old_cursor.fetchall()

    # Tables that should be copied verbatim (everything except reviews)
    copy_tables = []
    for name, sql in tables:
        if name == "reviews":
            # Create the new reviews table with content_json
            new_conn.execute("""
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
                    major_concerns_posted BOOLEAN DEFAULT FALSE,
                    minor_issues_posted BOOLEAN DEFAULT FALSE,
                    critical_posted_count INTEGER,
                    critical_found_count INTEGER,
                    major_posted_count INTEGER,
                    major_found_count INTEGER,
                    minor_posted_count INTEGER,
                    minor_found_count INTEGER,
                    FOREIGN KEY (parent_review_id) REFERENCES reviews(id)
                )
            """)
        else:
            # Create table using the original SQL
            new_conn.execute(sql)
            copy_tables.append(name)

    # Copy indexes from old database
    old_cursor.execute("""
        SELECT sql FROM sqlite_master
        WHERE type='index' AND sql IS NOT NULL
    """)
    for (idx_sql,) in old_cursor.fetchall():
        try:
            new_conn.execute(idx_sql)
        except sqlite3.OperationalError:
            pass  # Index already exists or was auto-created

    new_conn.commit()

    # Copy data from non-review tables
    for table_name in copy_tables:
        old_cursor.execute(f"SELECT * FROM {table_name}")
        rows = old_cursor.fetchall()
        if not rows:
            continue

        # Get column names
        old_cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [col[1] for col in old_cursor.fetchall()]
        placeholders = ", ".join("?" * len(columns))
        cols_str = ", ".join(columns)

        for row in rows:
            try:
                new_conn.execute(
                    f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders})",
                    row
                )
            except sqlite3.IntegrityError:
                pass  # Skip duplicate entries

    new_conn.commit()
    return new_conn


def migrate_reviews(old_conn: sqlite3.Connection, new_conn: sqlite3.Connection, dry_run: bool = False):
    """Migrate reviews from old DB (content) to new DB (content_json)."""
    old_cursor = old_conn.cursor()
    old_cursor.execute("SELECT * FROM reviews ORDER BY id")
    old_reviews = old_cursor.fetchall()

    # Get column names from old table
    old_cursor.execute("PRAGMA table_info(reviews)")
    old_columns = [col[1] for col in old_cursor.fetchall()]

    total = len(old_reviews)
    migrated = 0
    warnings = 0
    errors = 0

    print(f"\nMigrating {total} reviews...")

    for row in old_reviews:
        row_dict = dict(zip(old_columns, row))
        review_id = row_dict["id"]
        pr_number = row_dict["pr_number"]
        repo = row_dict.get("repo", "")
        content = row_dict.get("content", "")

        try:
            # Build metadata from DB fields
            metadata = {
                "pr_number": pr_number,
                "repo": repo,
                "pr_url": row_dict.get("pr_url"),
                "pr_title": row_dict.get("pr_title"),
                "pr_author": row_dict.get("pr_author"),
                "is_followup": bool(row_dict.get("is_followup")),
                "parent_review_id": row_dict.get("parent_review_id"),
            }

            # Parse markdown to JSON
            if content:
                review_json = markdown_to_json(content, metadata)
            else:
                review_json = {
                    "schema_version": "1.0.0",
                    "metadata": {
                        "pr_number": pr_number,
                        "repository": repo,
                    },
                    "summary": "",
                    "sections": [
                        {"type": "critical", "display_name": "Critical Issues", "issues": []},
                        {"type": "major", "display_name": "Major Concerns", "issues": []},
                        {"type": "minor", "display_name": "Minor Issues", "issues": []},
                    ],
                    "highlights": [],
                    "recommendations": [],
                    "score": {"overall": 0},
                }

            # Validate
            valid, errs = validate_review_json(review_json)
            if not valid:
                print(f"  WARNING review {review_id} (PR #{pr_number} in {repo}): {len(errs)} validation issues")
                for e in errs[:3]:
                    print(f"    - {e}")
                warnings += 1

            # Extract score from JSON
            json_score = review_json.get("score", {}).get("overall")
            old_score = row_dict.get("score")

            # Use JSON score if available, fall back to old DB score
            score = json_score if json_score and json_score > 0 else old_score

            content_json_str = json.dumps(review_json, ensure_ascii=False)

            if not dry_run:
                new_conn.execute("""
                    INSERT INTO reviews (
                        id, pr_number, repo, pr_title, pr_author, pr_url,
                        review_timestamp, status, review_file_path, score,
                        content_json, is_followup, parent_review_id,
                        created_at, head_commit_sha, inline_comments_posted,
                        pr_state_at_review, major_concerns_posted, minor_issues_posted,
                        critical_posted_count, critical_found_count,
                        major_posted_count, major_found_count,
                        minor_posted_count, minor_found_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    review_id,
                    pr_number, repo, row_dict.get("pr_title"), row_dict.get("pr_author"),
                    row_dict.get("pr_url"), row_dict.get("review_timestamp"),
                    row_dict.get("status", "completed"), row_dict.get("review_file_path"),
                    score, content_json_str,
                    row_dict.get("is_followup", False), row_dict.get("parent_review_id"),
                    row_dict.get("created_at"), row_dict.get("head_commit_sha"),
                    row_dict.get("inline_comments_posted", False),
                    row_dict.get("pr_state_at_review"),
                    row_dict.get("major_concerns_posted", False),
                    row_dict.get("minor_issues_posted", False),
                    row_dict.get("critical_posted_count"),
                    row_dict.get("critical_found_count"),
                    row_dict.get("major_posted_count"),
                    row_dict.get("major_found_count"),
                    row_dict.get("minor_posted_count"),
                    row_dict.get("minor_found_count"),
                ))

            migrated += 1

        except Exception as e:
            print(f"  ERROR review {review_id} (PR #{pr_number} in {repo}): {e}")
            errors += 1

    if not dry_run:
        new_conn.commit()

    return total, migrated, warnings, errors


def main():
    parser = argparse.ArgumentParser(description="Migrate reviews to JSON format")
    parser.add_argument("--dry-run", action="store_true", help="Preview migration without writing")
    parser.add_argument("--db", type=str, default=str(DB_PATH), help="Path to database file")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        sys.exit(1)

    print(f"Database: {db_path}")
    if args.dry_run:
        print("DRY RUN MODE - no changes will be written")

    # Backup
    if not args.dry_run:
        backup_path = backup_db(db_path)
        print(f"Backed up to: {backup_path}")

    # Open old database
    old_conn = sqlite3.connect(db_path)
    old_conn.row_factory = None

    # Create new database
    new_path = db_path.parent / f"{db_path.stem}_v2.db"
    if args.dry_run:
        new_path = db_path.parent / f"{db_path.stem}_v2_dryrun.db"

    print(f"Creating new database: {new_path}")
    new_conn = create_new_db(new_path, old_conn)

    # Migrate reviews
    total, migrated, warnings, errors = migrate_reviews(old_conn, new_conn, dry_run=args.dry_run)

    print(f"\n{'DRY RUN ' if args.dry_run else ''}Migration complete:")
    print(f"  Total reviews: {total}")
    print(f"  Migrated:      {migrated}")
    print(f"  Warnings:      {warnings}")
    print(f"  Errors:        {errors}")

    old_conn.close()
    new_conn.close()

    if args.dry_run:
        # Clean up dry run database
        new_path.unlink(missing_ok=True)
        print("\nDry run database removed.")
    else:
        # Swap databases
        old_path = db_path.parent / f"{db_path.stem}.db.old"
        print(f"\nSwapping databases:")
        print(f"  {db_path.name} -> {old_path.name}")
        print(f"  {new_path.name} -> {db_path.name}")
        db_path.rename(old_path)
        new_path.rename(db_path)
        print("\nDone! The old database is preserved at:", old_path)

    # Score verification
    if not args.dry_run and errors == 0:
        print("\nVerifying scores...")
        new_conn2 = sqlite3.connect(db_path)
        cursor = new_conn2.cursor()
        cursor.execute("SELECT COUNT(*) FROM reviews WHERE score IS NOT NULL AND score > 0")
        scored = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM reviews")
        total_new = cursor.fetchone()[0]
        print(f"  {scored}/{total_new} reviews have scores")
        new_conn2.close()


if __name__ == "__main__":
    main()
