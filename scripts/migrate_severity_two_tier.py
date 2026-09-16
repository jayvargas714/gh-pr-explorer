#!/usr/bin/env python3
"""Fold stored review severities into the two-tier model (blocking / non_blocking).

The application runs this migration itself on the first start after the
upgrade (Database._init_db, guarded by the `migrations` table). This script runs
the same code on demand so the change can be rehearsed on a copy and applied
explicitly — with a printed report — before the live instance is restarted.

Usage:
    python scripts/migrate_severity_two_tier.py --db /abs/path/pr_explorer.db --dry-run
    python scripts/migrate_severity_two_tier.py --db /abs/path/pr_explorer.db

--dry-run runs every step inside a transaction, prints the report, and rolls
back. Without it the changes are committed and the migration is recorded, so
the application's own startup guard finds it already done.

Never run this against a database that an OLDER version of the application
will still serve: old code does not recognise the two-tier section types and
would tally every migrated review as having zero issues.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# Add project root to path so we can import backend modules
sys.path.insert(0, str(Path(__file__).parent.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, type=Path, help="Path to the SQLite database file")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change, then roll back")
    args = parser.parse_args()

    if not args.db.is_file():
        print(f"error: {args.db} is not a file", file=sys.stderr)
        return 2

    from backend.database import severity_migration as mig

    conn = sqlite3.connect(args.db)
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN")
        if mig.is_applied(cursor):
            print(f"{mig.MIGRATION_NAME} already applied to {args.db}; nothing to do.")
            conn.rollback()
            return 0
        mig.ensure_columns(cursor)
        report = mig.apply_severity_two_tier(cursor)
        if args.dry_run:
            conn.rollback()
            print(f"DRY RUN — no changes written to {args.db}")
        else:
            mig.mark_applied(cursor)
            conn.commit()
            print(f"Applied {mig.MIGRATION_NAME} to {args.db}")
        print(json.dumps(report, indent=2))
        return 0
    except Exception as e:  # noqa: BLE001 — report and leave the file untouched
        conn.rollback()
        print(f"error: migration failed, rolled back: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
