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

    # Extract score
    patterns = [
        r'(?:\*\*)?(?:Overall\s+)?(?:Score|Rating)(?:\*\*)?[:\s]*(\d+)\s*/?\s*10',
        r'(\d+)\s*/\s*10\s*(?:score|rating)',
    ]
    for pattern in patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            score = int(match.group(1))
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

    # Check if migration already done
    migration_name = "initial_data_migration_v1"
    if db.is_migration_done(migration_name):
        logger.info("Migration already completed. Use --force to re-run.")
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

    args = parser.parse_args()

    # Handle force flag
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
