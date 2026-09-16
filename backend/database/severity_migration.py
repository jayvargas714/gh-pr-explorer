"""One-shot data migration to the two-tier (blocking / non_blocking) severity model.

Schema 1.0.0 reviews carried critical / major / minor sections and the
auto-verdict criteria carried one threshold per tier. This module folds every
stored artefact into the two-tier shape:

- ``reviews.content_json``          -> normalize_legacy_sections (2.0.0)
- ``auto_verdicts.*_count``         -> blocking_count = critical + major, non_blocking_count = minor
- ``reviews.*_posted/found_count``  -> the same sums for the inline-posting counters
- ``user_settings.auto_verdict_config``, ``auto_verdict_arming.auto_verdict_criteria``
  and ``auto_verdicts.criteria_json`` -> upgrade_legacy_criteria

``apply_severity_two_tier`` never commits: the caller owns the transaction so
schema and data change atomically. ``Database._init_db`` runs it once under the
``migrations`` guard; ``scripts/migrate_severity_two_tier.py`` runs the same
function for a rehearsal (``--dry-run``) or an explicit pre-restart run.
Every step is idempotent, so re-running on a migrated database is a no-op.
"""

import json
import logging
import sqlite3
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

MIGRATION_NAME = "severity_two_tier_v1"
CHUNK_SIZE = 200

# New columns, added PRAGMA-guarded on every init so fresh databases get them
# without the legacy columns and existing ones gain them in place.
AUTO_VERDICT_COLUMNS = (("blocking_count", "INTEGER"), ("non_blocking_count", "INTEGER"))
REVIEW_COLUMNS = (
    ("blocking_posted_count", "INTEGER"),
    ("blocking_found_count", "INTEGER"),
    ("non_blocking_posted_count", "INTEGER"),
    ("non_blocking_found_count", "INTEGER"),
    ("non_blocking_posted", "BOOLEAN DEFAULT FALSE"),
)


def _columns(cursor: sqlite3.Cursor, table: str) -> set:
    cursor.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def ensure_columns(cursor: sqlite3.Cursor) -> None:
    """Add the two-tier columns to auto_verdicts and reviews if missing."""
    for table, columns in (("auto_verdicts", AUTO_VERDICT_COLUMNS), ("reviews", REVIEW_COLUMNS)):
        existing = _columns(cursor, table)
        for name, col_type in columns:
            if name not in existing:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}")
                logger.info(f"Added column {name} to {table} table")


def is_applied(cursor: sqlite3.Cursor) -> bool:
    cursor.execute("SELECT 1 FROM migrations WHERE name = ?", (MIGRATION_NAME,))
    return cursor.fetchone() is not None


def mark_applied(cursor: sqlite3.Cursor) -> None:
    cursor.execute("INSERT OR IGNORE INTO migrations (name) VALUES (?)", (MIGRATION_NAME,))


def apply_severity_two_tier(cursor: sqlite3.Cursor,
                            display_names: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Run every data step on an open cursor and return a report of what changed.

    Requires ``ensure_columns`` to have run (``_init_db`` and the CLI both do).
    Does not commit and does not record the migration; the caller does both.
    """
    from backend.services.auto_verdict_config import upgrade_legacy_criteria
    from backend.services.review_schema import DEFAULT_SECTION_NAMES, normalize_legacy_sections

    names = dict(DEFAULT_SECTION_NAMES)
    names.update(display_names or {})

    report: Dict[str, Any] = {
        "reviews_seen": 0, "reviews_rewritten": 0, "stubs_bumped": 0, "unparseable": 0,
        "sections_merged": 0, "disposition_severities_remapped": 0,
        "auto_verdict_counts_backfilled": 0, "review_counters_backfilled": 0,
        "criteria_snapshots_upgraded": 0, "settings_upgraded": False, "arming_overrides_upgraded": 0,
    }

    _backfill_auto_verdict_counts(cursor, report)
    _backfill_review_counters(cursor, report)
    _rewrite_review_content(cursor, report, names, normalize_legacy_sections)
    _upgrade_settings(cursor, report, upgrade_legacy_criteria)
    _upgrade_arming_overrides(cursor, report, upgrade_legacy_criteria)
    _upgrade_criteria_snapshots(cursor, report, upgrade_legacy_criteria)
    return report


# --- steps -----------------------------------------------------------------------

def _backfill_auto_verdict_counts(cursor, report):
    if not {"critical_count", "major_count", "minor_count"} <= _columns(cursor, "auto_verdicts"):
        return  # fresh database: nothing to fold
    cursor.execute("""
        UPDATE auto_verdicts
        SET blocking_count = COALESCE(critical_count, 0) + COALESCE(major_count, 0),
            non_blocking_count = minor_count
        WHERE blocking_count IS NULL
          AND (critical_count IS NOT NULL OR major_count IS NOT NULL)
    """)
    report["auto_verdict_counts_backfilled"] = cursor.rowcount


def _backfill_review_counters(cursor, report):
    legacy = {"critical_posted_count", "critical_found_count", "major_posted_count",
              "major_found_count", "minor_posted_count", "minor_found_count",
              "major_concerns_posted", "minor_issues_posted"}
    if not legacy <= _columns(cursor, "reviews"):
        return
    # The blocking flag is the pre-existing generic inline_comments_posted; a
    # review whose major concerns were posted also had blocking issues posted.
    cursor.execute("""
        UPDATE reviews
        SET blocking_posted_count = COALESCE(critical_posted_count, 0) + COALESCE(major_posted_count, 0),
            blocking_found_count = COALESCE(critical_found_count, 0) + COALESCE(major_found_count, 0),
            non_blocking_posted_count = minor_posted_count,
            non_blocking_found_count = minor_found_count,
            inline_comments_posted = COALESCE(inline_comments_posted, 0) OR COALESCE(major_concerns_posted, 0),
            non_blocking_posted = COALESCE(minor_issues_posted, 0)
        WHERE blocking_found_count IS NULL
          AND (critical_found_count IS NOT NULL OR major_found_count IS NOT NULL)
    """)
    report["review_counters_backfilled"] = cursor.rowcount


def _rewrite_review_content(cursor, report, names, normalize):
    last_id = 0
    while True:
        cursor.execute(
            "SELECT id, content_json FROM reviews WHERE id > ? ORDER BY id LIMIT ?",
            (last_id, CHUNK_SIZE),
        )
        rows = cursor.fetchall()
        if not rows:
            break
        for row in rows:
            review_id, raw = row[0], row[1]
            last_id = review_id
            report["reviews_seen"] += 1
            try:
                data = json.loads(raw) if raw else None
            except (json.JSONDecodeError, TypeError):
                data = None
            if not isinstance(data, dict):
                report["unparseable"] += 1
                continue
            upgraded = normalize(data, names)
            if upgraded is data:
                continue
            sections = [s for s in (data.get("sections") or []) if isinstance(s, dict)]
            report["sections_merged"] += sum(
                1 for s in sections if s.get("type") in ("critical", "major", "minor"))
            report["disposition_severities_remapped"] += sum(
                1 for s in sections if s.get("type") in ("disputed", "deferred")
                for issue in (s.get("issues") or []) if isinstance(issue, dict)
                and str(issue.get("severity", "")).lower() in ("critical", "major", "minor"))
            if not sections:
                report["stubs_bumped"] += 1
            cursor.execute(
                "UPDATE reviews SET content_json = ? WHERE id = ?",
                (json.dumps(upgraded, ensure_ascii=False), review_id),
            )
            report["reviews_rewritten"] += 1


def _upgrade_json_column(cursor, table: str, key_column: str, value_column: str,
                         rows: Iterable, upgrade) -> int:
    changed = 0
    for key, raw in rows:
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(parsed, dict):
            continue
        upgraded = upgrade(parsed)
        if upgraded is parsed:
            continue
        cursor.execute(f"UPDATE {table} SET {value_column} = ? WHERE {key_column} = ?",
                       (json.dumps(upgraded), key))
        changed += 1
    return changed


def _upgrade_settings(cursor, report, upgrade):
    cursor.execute("SELECT id, value FROM user_settings WHERE key = 'auto_verdict_config'")
    rows = cursor.fetchall()
    report["settings_upgraded"] = bool(
        _upgrade_json_column(cursor, "user_settings", "id", "value", rows, upgrade))


def _upgrade_arming_overrides(cursor, report, upgrade):
    cursor.execute("SELECT rowid, auto_verdict_criteria FROM auto_verdict_arming "
                   "WHERE auto_verdict_criteria IS NOT NULL")
    rows = cursor.fetchall()
    report["arming_overrides_upgraded"] = _upgrade_json_column(
        cursor, "auto_verdict_arming", "rowid", "auto_verdict_criteria", rows, upgrade)


def _upgrade_criteria_snapshots(cursor, report, upgrade):
    cursor.execute("SELECT id, criteria_json FROM auto_verdicts WHERE criteria_json IS NOT NULL")
    rows = cursor.fetchall()
    report["criteria_snapshots_upgraded"] = _upgrade_json_column(
        cursor, "auto_verdicts", "id", "criteria_json", rows, upgrade)
