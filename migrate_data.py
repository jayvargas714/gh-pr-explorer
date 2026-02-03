#!/usr/bin/env python3
"""Data migration script for GitHub PR Explorer.

Migrates existing data from:
1. Past reviews in /Users/jvargas714/Documents/code-reviews/past-reviews/
2. Merge queue from MQ/merge_queue.json

Run this script once to import existing data into the SQLite database.
"""

import json
import logging
import re
import os
import subprocess
from datetime import datetime
from pathlib import Path

from database import Database, ReviewsDB, MergeQueueDB

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Source paths
PAST_REVIEWS_DIR = Path("/Users/jvargas714/Documents/code-reviews/past-reviews")
MERGE_QUEUE_FILE = Path(__file__).parent / "MQ" / "merge_queue.json"


def parse_review_filename(filename: str) -> dict:
    """Parse review filename to extract PR info.

    Supported patterns:
    - PR-###-description.md -> PR number only
    - {owner}-{repo}-pr-###.md -> Full info
    - pr-###-description.md -> PR number only
    - scala-computing-scala-pr-###.md -> org/repo pattern

    Returns:
        Dict with 'pr_number', 'repo' (if found), 'is_followup'
    """
    result = {
        "pr_number": None,
        "repo": None,
        "is_followup": False
    }

    # Check for followup suffix
    if "-followup" in filename.lower():
        result["is_followup"] = True
        filename = filename.lower().replace("-followup", "")

    # Remove .md extension
    name = filename.replace(".md", "")

    # Pattern 1: scala-computing-scala-pr-###
    # Format: {org}-{repo}-pr-{number}
    match = re.match(r'^([a-zA-Z0-9-]+)-([a-zA-Z0-9-]+)-pr-(\d+)', name, re.IGNORECASE)
    if match:
        org = match.group(1)
        repo = match.group(2)
        result["pr_number"] = int(match.group(3))
        result["repo"] = f"{org}/{repo}"
        return result

    # Pattern 2: owner-repo-pr-###
    match = re.match(r'^(.+?)-pr-(\d+)', name, re.IGNORECASE)
    if match:
        # Try to split owner-repo from the prefix
        prefix = match.group(1)
        result["pr_number"] = int(match.group(2))
        # Default repo if can't determine
        result["repo"] = "scala-computing/scala"
        return result

    # Pattern 3: PR-###-description or pr-###-description
    match = re.match(r'^pr-?(\d+)', name, re.IGNORECASE)
    if match:
        result["pr_number"] = int(match.group(1))
        result["repo"] = "scala-computing/scala"  # Default
        return result

    # Pattern 4: Try to find any number that looks like a PR number
    match = re.search(r'(\d{2,4})', name)
    if match:
        result["pr_number"] = int(match.group(1))
        result["repo"] = "scala-computing/scala"  # Default

    return result


def parse_review_content(content: str) -> dict:
    """Parse review content to extract metadata.

    Looks for header patterns like:
    # Code Review: PR #XXX
    **Repository:** owner/repo
    **Author:** username
    **URL:** https://github.com/...

    Returns:
        Dict with 'pr_number', 'repo', 'author', 'title', 'url', 'score'
    """
    result = {
        "pr_number": None,
        "repo": None,
        "author": None,
        "title": None,
        "url": None,
        "score": None
    }

    # Extract PR number from header
    match = re.search(r'(?:Code Review|Review)[:\s]*(?:PR\s*)?#?(\d+)', content, re.IGNORECASE)
    if match:
        result["pr_number"] = int(match.group(1))

    # Extract repository
    match = re.search(r'\*\*Repository\*\*[:\s]*([^\s\n]+)', content, re.IGNORECASE)
    if match:
        result["repo"] = match.group(1).strip()

    # Extract author
    match = re.search(r'\*\*Author\*\*[:\s]*@?([^\s\n]+)', content, re.IGNORECASE)
    if match:
        result["author"] = match.group(1).strip()

    # Extract URL
    match = re.search(r'\*\*(?:URL|PR)\*\*[:\s]*(https?://[^\s\n]+)', content, re.IGNORECASE)
    if match:
        result["url"] = match.group(1).strip()
    else:
        # Try to find GitHub PR URL anywhere
        match = re.search(r'(https://github\.com/[^/]+/[^/]+/pull/\d+)', content)
        if match:
            result["url"] = match.group(1)

    # Extract title - first try H1 header, then **Title** field, then fallback
    h1_match = re.search(r'^#\s+(.+?)$', content, re.MULTILINE)
    if h1_match:
        result["title"] = h1_match.group(1).strip()
    else:
        match = re.search(r'\*\*Title\*\*[:\s]*(.+?)(?:\n|\*\*)', content, re.IGNORECASE)
        if match:
            result["title"] = match.group(1).strip()

    # Extract score (supports decimals like 8.5 or 7.25)
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
                result["score"] = score
                break

    return result


def migrate_reviews(db: Database, dry_run: bool = False) -> dict:
    """Migrate past reviews to the database.

    Args:
        db: Database instance
        dry_run: If True, don't actually write to database

    Returns:
        Migration statistics
    """
    stats = {
        "total_files": 0,
        "migrated": 0,
        "skipped": 0,
        "errors": 0,
        "followups": 0
    }

    if not PAST_REVIEWS_DIR.exists():
        logger.warning(f"Past reviews directory not found: {PAST_REVIEWS_DIR}")
        return stats

    reviews_db = ReviewsDB(db)

    # Track reviews for followup linking
    pr_to_review_id = {}

    # Get all .md files sorted by modification time
    review_files = sorted(
        PAST_REVIEWS_DIR.glob("*.md"),
        key=lambda p: p.stat().st_mtime
    )

    stats["total_files"] = len(review_files)
    logger.info(f"Found {len(review_files)} review files to migrate")

    for review_file in review_files:
        try:
            # Read content
            content = review_file.read_text(encoding='utf-8')

            # Parse filename
            file_info = parse_review_filename(review_file.name)

            # Parse content for metadata
            content_info = parse_review_content(content)

            # Merge info (content takes precedence)
            pr_number = content_info["pr_number"] or file_info["pr_number"]
            repo = content_info["repo"] or file_info["repo"] or "scala-computing/scala"
            is_followup = file_info["is_followup"]

            if pr_number is None:
                logger.warning(f"Could not determine PR number for {review_file.name}")
                stats["skipped"] += 1
                continue

            # Get file modification time as review timestamp
            review_timestamp = datetime.fromtimestamp(review_file.stat().st_mtime)

            # Determine parent review ID for followups
            parent_review_id = None
            if is_followup:
                key = f"{repo}/{pr_number}"
                parent_review_id = pr_to_review_id.get(key)
                stats["followups"] += 1

            if dry_run:
                logger.info(
                    f"[DRY RUN] Would migrate: PR #{pr_number} ({repo}) "
                    f"from {review_file.name} "
                    f"{'[FOLLOWUP]' if is_followup else ''}"
                )
            else:
                # Save to database
                review_id = reviews_db.save_review(
                    pr_number=pr_number,
                    repo=repo,
                    pr_title=content_info["title"],
                    pr_author=content_info["author"],
                    pr_url=content_info["url"],
                    status="completed",
                    review_file_path=str(review_file),
                    score=content_info["score"],
                    content=content,
                    is_followup=is_followup,
                    parent_review_id=parent_review_id,
                    review_timestamp=review_timestamp
                )

                # Track for followup linking
                key = f"{repo}/{pr_number}"
                if not is_followup:
                    pr_to_review_id[key] = review_id

                logger.info(
                    f"Migrated: PR #{pr_number} ({repo}) -> review ID {review_id}"
                )

            stats["migrated"] += 1

        except Exception as e:
            logger.error(f"Error migrating {review_file.name}: {e}")
            stats["errors"] += 1

    return stats


def migrate_merge_queue(db: Database, dry_run: bool = False) -> dict:
    """Migrate merge queue from JSON to database.

    Args:
        db: Database instance
        dry_run: If True, don't actually write to database

    Returns:
        Migration statistics
    """
    stats = {
        "total_items": 0,
        "migrated": 0,
        "errors": 0
    }

    if not MERGE_QUEUE_FILE.exists():
        logger.info("No merge queue file found, nothing to migrate")
        return stats

    queue_db = MergeQueueDB(db)

    try:
        with open(MERGE_QUEUE_FILE) as f:
            data = json.load(f)

        queue_items = data.get("queue", [])
        stats["total_items"] = len(queue_items)

        logger.info(f"Found {len(queue_items)} items in merge queue to migrate")

        for item in queue_items:
            try:
                if dry_run:
                    logger.info(
                        f"[DRY RUN] Would migrate queue item: "
                        f"PR #{item.get('number')} ({item.get('repo')})"
                    )
                else:
                    queue_db.add_to_queue(
                        pr_number=item["number"],
                        repo=item["repo"],
                        pr_title=item.get("title"),
                        pr_author=item.get("author"),
                        pr_url=item.get("url"),
                        additions=item.get("additions", 0),
                        deletions=item.get("deletions", 0)
                    )
                    logger.info(
                        f"Migrated queue item: PR #{item['number']} ({item['repo']})"
                    )

                stats["migrated"] += 1

            except ValueError as e:
                # PR already in queue
                logger.warning(f"Skipping duplicate: {e}")
            except Exception as e:
                logger.error(f"Error migrating queue item: {e}")
                stats["errors"] += 1

    except json.JSONDecodeError as e:
        logger.error(f"Error reading merge queue JSON: {e}")
        stats["errors"] += 1

    return stats


def run_schema_migration(db: Database, dry_run: bool = False):
    """Run schema migrations to add new columns.

    Args:
        db: Database instance
        dry_run: If True, don't actually modify schema
    """
    migration_name = "schema_v2_new_columns"

    if db.is_migration_done(migration_name):
        logger.info("Schema migration v2 already completed.")
        return

    logger.info("-" * 40)
    logger.info("Running Schema Migration v2")
    logger.info("-" * 40)

    conn = db._get_connection()
    try:
        cursor = conn.cursor()

        # Check existing columns in reviews table
        cursor.execute("PRAGMA table_info(reviews)")
        reviews_columns = {row['name'] for row in cursor.fetchall()}

        # Add new columns to reviews table if they don't exist
        new_reviews_columns = [
            ("head_commit_sha", "TEXT"),
            ("inline_comments_posted", "BOOLEAN DEFAULT FALSE"),
            ("pr_state_at_review", "TEXT")
        ]

        for col_name, col_type in new_reviews_columns:
            if col_name not in reviews_columns:
                if dry_run:
                    logger.info(f"[DRY RUN] Would add column {col_name} to reviews")
                else:
                    cursor.execute(f"ALTER TABLE reviews ADD COLUMN {col_name} {col_type}")
                    logger.info(f"Added column {col_name} to reviews table")

        # Check existing columns in merge_queue table
        cursor.execute("PRAGMA table_info(merge_queue)")
        queue_columns = {row['name'] for row in cursor.fetchall()}

        # Add new columns to merge_queue table if they don't exist
        new_queue_columns = [
            ("pr_state", "TEXT"),
            ("state_updated_at", "DATETIME")
        ]

        for col_name, col_type in new_queue_columns:
            if col_name not in queue_columns:
                if dry_run:
                    logger.info(f"[DRY RUN] Would add column {col_name} to merge_queue")
                else:
                    cursor.execute(f"ALTER TABLE merge_queue ADD COLUMN {col_name} {col_type}")
                    logger.info(f"Added column {col_name} to merge_queue table")

        if not dry_run:
            conn.commit()
            db.mark_migration_done(migration_name)
            logger.info("Schema migration v2 completed successfully")

    finally:
        conn.close()


def fetch_pr_head_sha(owner: str, repo: str, pr_number: int) -> str:
    """Fetch the current head commit SHA for a PR using gh CLI.

    Args:
        owner: Repository owner
        repo: Repository name
        pr_number: PR number

    Returns:
        The head commit SHA or None if fetch fails
    """
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number),
             "--repo", f"{owner}/{repo}",
             "--json", "headRefOid",
             "--jq", ".headRefOid"],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.warning(f"Timeout fetching head SHA for {owner}/{repo}#{pr_number}")
    except Exception as e:
        logger.warning(f"Error fetching head SHA for {owner}/{repo}#{pr_number}: {e}")
    return None


def backfill_head_commit_shas(db: Database, dry_run: bool = False) -> dict:
    """Backfill head_commit_sha for existing reviews that don't have one.

    This migration fetches the current head commit SHA for each PR that has
    been reviewed but doesn't have a stored head_commit_sha. This prevents
    all reviewed PRs from showing "New Commits" badges on first load.

    Args:
        db: Database instance
        dry_run: If True, don't actually write to database

    Returns:
        Migration statistics
    """
    migration_name = "backfill_head_commit_shas_v1"

    if db.is_migration_done(migration_name):
        logger.info("Head commit SHA backfill already completed.")
        return {"skipped": True}

    stats = {
        "total_reviews": 0,
        "unique_prs": 0,
        "updated": 0,
        "errors": 0,
        "skipped": 0
    }

    logger.info("-" * 40)
    logger.info("Backfilling head_commit_sha for existing reviews")
    logger.info("-" * 40)

    conn = db._get_connection()
    try:
        cursor = conn.cursor()

        # Find all reviews without head_commit_sha, grouped by unique PR
        cursor.execute("""
            SELECT DISTINCT repo, pr_number
            FROM reviews
            WHERE head_commit_sha IS NULL OR head_commit_sha = ''
        """)
        prs_to_update = cursor.fetchall()

        stats["unique_prs"] = len(prs_to_update)
        logger.info(f"Found {len(prs_to_update)} unique PRs needing head_commit_sha backfill")

        for pr in prs_to_update:
            repo_str = pr["repo"]
            pr_number = pr["pr_number"]

            if not repo_str or "/" not in repo_str:
                logger.warning(f"Invalid repo format for PR #{pr_number}: {repo_str}")
                stats["skipped"] += 1
                continue

            owner, repo = repo_str.split("/", 1)

            if dry_run:
                logger.info(f"[DRY RUN] Would fetch head SHA for {owner}/{repo}#{pr_number}")
                stats["updated"] += 1
                continue

            # Fetch current head SHA from GitHub
            head_sha = fetch_pr_head_sha(owner, repo, pr_number)

            if head_sha:
                # Update all reviews for this PR with the head SHA
                cursor.execute("""
                    UPDATE reviews
                    SET head_commit_sha = ?
                    WHERE repo = ? AND pr_number = ?
                    AND (head_commit_sha IS NULL OR head_commit_sha = '')
                """, (head_sha, repo_str, pr_number))

                rows_updated = cursor.rowcount
                stats["total_reviews"] += rows_updated
                stats["updated"] += 1
                logger.info(f"Updated {rows_updated} review(s) for {repo_str}#{pr_number} with SHA {head_sha[:8]}...")
            else:
                logger.warning(f"Could not fetch head SHA for {repo_str}#{pr_number} (PR may be closed/merged)")
                stats["errors"] += 1

        if not dry_run:
            conn.commit()
            db.mark_migration_done(migration_name)
            logger.info("Head commit SHA backfill completed successfully")

    finally:
        conn.close()

    return stats


def run_migration(dry_run: bool = False, backup: bool = True):
    """Run the full migration.

    Args:
        dry_run: If True, don't actually write to database
        backup: If True, rename JSON file to .bak after successful migration
    """
    logger.info("=" * 60)
    logger.info("Starting PR Explorer Data Migration")
    logger.info("=" * 60)

    if dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

    # Initialize database
    db = Database()

    # Run schema migration first (for existing databases)
    run_schema_migration(db, dry_run)

    # Check if data migration already done
    migration_name = "initial_data_migration_v1"
    if db.is_migration_done(migration_name):
        logger.info("Data migration already completed. Use --force to re-run.")
        return

    # Migrate reviews
    logger.info("")
    logger.info("-" * 40)
    logger.info("Migrating Reviews")
    logger.info("-" * 40)
    review_stats = migrate_reviews(db, dry_run)
    logger.info(f"Review migration stats: {review_stats}")

    # Migrate merge queue
    logger.info("")
    logger.info("-" * 40)
    logger.info("Migrating Merge Queue")
    logger.info("-" * 40)
    queue_stats = migrate_merge_queue(db, dry_run)
    logger.info(f"Merge queue migration stats: {queue_stats}")

    # Mark migration as done
    if not dry_run:
        db.mark_migration_done(migration_name)

        # Backup old merge queue file
        if backup and MERGE_QUEUE_FILE.exists():
            backup_path = MERGE_QUEUE_FILE.with_suffix('.json.bak')
            MERGE_QUEUE_FILE.rename(backup_path)
            logger.info(f"Backed up merge queue to {backup_path}")

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("Migration Complete!")
    logger.info("=" * 60)
    logger.info(f"Reviews: {review_stats['migrated']}/{review_stats['total_files']} migrated "
                f"({review_stats['followups']} follow-ups)")
    logger.info(f"Queue: {queue_stats['migrated']}/{queue_stats['total_items']} migrated")

    if review_stats['errors'] > 0 or queue_stats['errors'] > 0:
        logger.warning(f"Errors: {review_stats['errors']} review(s), "
                      f"{queue_stats['errors']} queue item(s)")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrate PR Explorer data to SQLite")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview migration without making changes"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-run even if migration was already done"
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Don't backup the old JSON file"
    )
    parser.add_argument(
        "--backfill-shas",
        action="store_true",
        help="Backfill head_commit_sha for existing reviews (run this to prevent false 'New Commits' badges)"
    )

    args = parser.parse_args()

    # Run backfill-shas migration if requested
    if args.backfill_shas:
        db = Database()

        # Handle force flag for backfill
        if args.force:
            conn = db._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM migrations WHERE name = 'backfill_head_commit_shas_v1'")
                conn.commit()
                logger.info("Cleared backfill migration marker")
            finally:
                conn.close()

        stats = backfill_head_commit_shas(db, dry_run=args.dry_run)
        if not stats.get("skipped"):
            logger.info("")
            logger.info("=" * 60)
            logger.info("Backfill Complete!")
            logger.info("=" * 60)
            logger.info(f"Unique PRs processed: {stats['unique_prs']}")
            logger.info(f"Reviews updated: {stats['total_reviews']}")
            logger.info(f"PRs updated: {stats['updated']}")
            if stats['errors'] > 0:
                logger.warning(f"Errors: {stats['errors']}")
            if stats['skipped'] > 0:
                logger.info(f"Skipped (invalid repo): {stats['skipped']}")
    else:
        # Handle force flag for main migration
        if args.force:
            db = Database()
            conn = db._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM migrations WHERE name = 'initial_data_migration_v1'")
                conn.commit()
                logger.info("Cleared previous migration marker")
            finally:
                conn.close()

        run_migration(
            dry_run=args.dry_run,
            backup=not args.no_backup
        )
