"""Pure builder for the per-developer, per-day analytics rollup, plus the
rebuild orchestration (`needs_rebuild`/`rebuild_repo`) that Task 3's sync
worker and Task 4's route call. No Flask imports here."""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROLLUP_SCHEMA_VERSION = 1

METRIC_COLUMNS = (
    "prs_created", "prs_merged", "prs_closed", "reviews", "approvals",
    "changes_requested", "comments", "additions", "deletions", "commits",
    "merge_hours_sum", "merge_hours_count",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day(ts: Optional[str]) -> Optional[str]:
    return ts[:10] if ts else None


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _hours_between(start: Optional[str], end: str) -> Optional[float]:
    if not start:
        return None
    return (_parse_iso(end) - _parse_iso(start)).total_seconds() / 3600.0


def _parse_utc(ts: Optional[str]) -> Optional[datetime]:
    """Parse either synced_repos' SQLite timestamp ("YYYY-MM-DD HH:MM:SS", UTC)
    or analytics_daily_meta's ISO 'Z' timestamp into an aware UTC datetime."""
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            return _parse_iso(ts)
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def build_rows(pr_rows: List[dict], commit_rows: List[dict]) -> Tuple[List[dict], dict]:
    """Aggregate synced PR and commit rows into (day, login, base_ref) buckets.

    Pure function: no DB or config access. See task-2-brief.md for the
    bucketing rules.
    """
    buckets: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    bot_by_login: Dict[str, bool] = {}

    def bucket(day: str, login: str, base_ref: str) -> Dict[str, Any]:
        key = (day, login, base_ref)
        row = buckets.get(key)
        if row is None:
            row = {"day": day, "login": login, "base_ref": base_ref}
            row.update({c: 0 for c in METRIC_COLUMNS})
            buckets[key] = row
        return row

    review_count = 0
    commit_count = 0
    earliest_pr_day = None
    earliest_commit_day = None

    for pr in pr_rows:
        login = pr.get("author") or "unknown"
        base_ref = pr.get("base_ref") or "unknown"
        bot_by_login[login] = bot_by_login.get(login, False) or bool(pr.get("author_is_bot"))

        created_at = pr.get("created_at")
        if created_at:
            day = _day(created_at)
            if earliest_pr_day is None or day < earliest_pr_day:
                earliest_pr_day = day
            bucket(day, login, base_ref)["prs_created"] += 1

        state = pr.get("state")
        if state == "MERGED" and pr.get("merged_at"):
            row = bucket(_day(pr["merged_at"]), login, base_ref)
            row["prs_merged"] += 1
            row["additions"] += pr.get("additions") or 0
            row["deletions"] += pr.get("deletions") or 0
            hours = _hours_between(created_at, pr["merged_at"])
            if hours is not None:
                row["merge_hours_sum"] += hours
                row["merge_hours_count"] += 1
        elif state == "CLOSED" and pr.get("closed_at"):
            bucket(_day(pr["closed_at"]), login, base_ref)["prs_closed"] += 1

        for review in pr.get("reviews") or []:
            submitted_at = review.get("submitted_at")
            if not submitted_at:
                continue
            review_count += 1
            row = bucket(_day(submitted_at), review.get("login") or "unknown", base_ref)
            row["reviews"] += 1
            review_state = review.get("state")
            if review_state == "APPROVED":
                row["approvals"] += 1
            elif review_state == "CHANGES_REQUESTED":
                row["changes_requested"] += 1
            elif review_state == "COMMENTED":
                row["comments"] += 1

    for commit in commit_rows:
        if (commit.get("parent_count") or 1) > 1:
            continue
        committed_at = commit["committed_at"]
        commit_count += 1
        day = _day(committed_at)
        if earliest_commit_day is None or day < earliest_commit_day:
            earliest_commit_day = day
        bucket(day, commit["login"], commit["branch"])["commits"] += 1

    rows = list(buckets.values())
    for row in rows:
        row["is_bot"] = 1 if bot_by_login.get(row["login"]) else 0
    rows.sort(key=lambda r: (r["day"], r["login"], r["base_ref"]))

    counters = {
        "pr_count": len(pr_rows),
        "review_count": review_count,
        "commit_count": commit_count,
        "earliest_pr_day": earliest_pr_day,
        "earliest_commit_day": earliest_commit_day,
    }
    return rows, counters


def needs_rebuild(repo: str) -> bool:
    """True when the repo's rollup is missing, stale-schema, or older than
    the repo's last sync."""
    from backend.database import get_analytics_daily_db, get_synced_prs_db

    meta = get_analytics_daily_db().get_meta(repo)
    if meta is None:
        return True
    if meta.get("schema_version") != ROLLUP_SCHEMA_VERSION:
        return True

    repo_row = get_synced_prs_db().get_repo(repo)
    last_synced_at = _parse_utc(repo_row["last_synced_at"]) if repo_row else None
    built_at = _parse_utc(meta.get("built_at"))
    if last_synced_at is None or built_at is None:
        return False
    return last_synced_at > built_at


def rebuild_repo(repo: str) -> dict:
    """Recompute and persist the rollup for one repo. Returns the meta written."""
    from backend.database import get_analytics_daily_db, get_synced_commits_db, get_synced_prs_db

    start = time.monotonic()
    pr_rows = get_synced_prs_db().get_pr_rollup_rows(repo)
    commit_rows = get_synced_commits_db().get_rollup_rows(repo)
    rows, counters = build_rows(pr_rows, commit_rows)

    meta = {
        "built_at": _utc_now_iso(),
        "schema_version": ROLLUP_SCHEMA_VERSION,
        **counters,
    }
    get_analytics_daily_db().replace_repo(repo, rows, meta)

    elapsed_ms = (time.monotonic() - start) * 1000
    logger.info("analytics_rollup: rebuilt %s (%d rows) in %.0fms", repo, len(rows), elapsed_ms)
    return meta
