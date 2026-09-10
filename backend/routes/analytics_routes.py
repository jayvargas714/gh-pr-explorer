"""Analytics routes: the precomputed per-developer, per-day rollup."""

import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from backend.config import get_analytics_config, get_pr_sync_config
from backend.database import get_analytics_daily_db, get_synced_commits_db, get_synced_prs_db
from backend.routes import error_response
from backend.services.analytics_rollup import needs_rebuild, rebuild_repo
from backend.services.bot_filter import is_bot_login

logger = logging.getLogger(__name__)

analytics_bp = Blueprint("analytics", __name__)

METRIC_COLUMNS = (
    "prs_created", "prs_merged", "prs_closed", "reviews", "approvals",
    "changes_requested", "comments", "additions", "deletions", "commits",
    "merge_hours_sum", "merge_hours_count",
)

# Upper bound on the requested window (~5 years), so a huge explicit range
# (or an ancient repo's all-time default) can't force an O(days x people x
# METRIC_COLUMNS) zero-fill that pins the server.
MAX_RANGE_DAYS = 1830


def _normalize_timestamp(ts):
    """Normalize SQLite CURRENT_TIMESTAMP ('YYYY-MM-DD HH:MM:SS') to ISO 8601 with Z suffix."""
    if ts is None:
        return None
    s = str(ts)
    if "T" not in s:
        s = s.replace(" ", "T")
    if not s.endswith("Z"):
        s += "Z"
    return s


def _parse_day(value):
    """Parse a 'YYYY-MM-DD' string. Returns None on bad format."""
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return value
    except (TypeError, ValueError):
        return None


def _range_days(day_from, day_to):
    """Inclusive day count between two 'YYYY-MM-DD' strings."""
    start = datetime.strptime(day_from, "%Y-%m-%d")
    end = datetime.strptime(day_to, "%Y-%m-%d")
    return (end - start).days + 1


def _day_range(day_from, day_to):
    start = datetime.strptime(day_from, "%Y-%m-%d")
    end = datetime.strptime(day_to, "%Y-%m-%d")
    days = []
    d = start
    while d <= end:
        days.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return days


def _empty_series(n_days):
    return {c: [0] * n_days for c in METRIC_COLUMNS}


def _totals_from_series(series):
    totals = {c: sum(series[c]) for c in METRIC_COLUMNS}
    denom = totals["prs_merged"] + totals["prs_closed"]
    totals["merge_rate"] = (totals["prs_merged"] / denom) if denom else None
    count = totals["merge_hours_count"]
    totals["avg_merge_hours"] = (totals["merge_hours_sum"] / count) if count else None
    return totals


def build_daily_shape(rows, days):
    """Pure: bot-filtered rollup rows + the day list -> (people, team).

    `rows` are dicts with `day`, `login`, plus the metric columns (already
    summed/filtered by the caller). Rows whose day falls outside `days` are
    dropped.
    """
    day_index = {d: i for i, d in enumerate(days)}
    n_days = len(days)
    people_series = {}

    for row in rows:
        idx = day_index.get(row["day"])
        if idx is None:
            continue
        series = people_series.setdefault(row["login"], _empty_series(n_days))
        for c in METRIC_COLUMNS:
            series[c][idx] += row.get(c) or 0

    people = []
    team_series = _empty_series(n_days)
    for login, series in people_series.items():
        for c in METRIC_COLUMNS:
            for i in range(n_days):
                team_series[c][i] += series[c][i]
        person = {"login": login, "series": series, "totals": _totals_from_series(series)}
        if login and login != "unknown" and " " not in login:
            person["avatar_url"] = f"https://github.com/{login}.png"
        people.append(person)

    people.sort(key=lambda p: (-(p["totals"]["prs_merged"] + p["totals"]["reviews"]), p["login"]))

    team = {"series": team_series, "totals": _totals_from_series(team_series)}
    return people, team


@analytics_bp.route("/api/repos/<owner>/<repo>/analytics/daily")
def get_analytics_daily(owner, repo):
    """The precomputed per-developer, per-day rollup for a repo/window/base.

    Never calls GitHub: rebuilds (when stale) are DB-only, driven by rows the
    sync worker already wrote.
    """
    repo_key = f"{owner}/{repo}"
    base = request.args.get("base") or None

    to_param = request.args.get("to")
    if to_param:
        day_to = _parse_day(to_param)
        if day_to is None:
            return error_response("Invalid 'to' date, expected YYYY-MM-DD", 400)
    else:
        day_to = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    from_param = request.args.get("from")
    day_from = None
    if from_param:
        day_from = _parse_day(from_param)
        if day_from is None:
            return error_response("Invalid 'from' date, expected YYYY-MM-DD", 400)
        # Explicit params: validate ordering and the range cap up front, before
        # registration/rebuild, so a malformed request never triggers a rebuild.
        if day_from > day_to:
            return error_response("'from' must not be after 'to'", 400)
        if _range_days(day_from, day_to) > MAX_RANGE_DAYS:
            return error_response(
                f"Date range too large (max {MAX_RANGE_DAYS} days)", 400
            )

    synced_prs_db = get_synced_prs_db()
    synced_commits_db = get_synced_commits_db()
    analytics_db = get_analytics_daily_db()

    repo_row = synced_prs_db.get_repo(repo_key)
    if repo_row is None:
        synced_prs_db.register_repo(repo_key)
        repo_row = synced_prs_db.get_repo(repo_key)

    if needs_rebuild(repo_key):
        try:
            rebuild_repo(repo_key)
        except Exception:
            logger.exception("Rollup rebuild failed for %s; serving existing rollup", repo_key)

    if day_from is None:
        # All-time default: the earliest known day may push the range past
        # the cap on an old repo — clamp rather than error, so "All time"
        # still works instead of 400ing on the user.
        day_from = analytics_db.earliest_day(repo_key, base)
        if day_from is None:
            day_from = day_to
        elif _range_days(day_from, day_to) > MAX_RANGE_DAYS:
            day_from = (
                datetime.strptime(day_to, "%Y-%m-%d") - timedelta(days=MAX_RANGE_DAYS - 1)
            ).strftime("%Y-%m-%d")

        if day_from > day_to:
            return error_response("'from' must not be after 'to'", 400)

    rows = analytics_db.query(repo_key, day_from, day_to, base_ref=base)
    bot_logins = get_analytics_config()["bot_logins"]
    rows = [r for r in rows if not is_bot_login(r["login"], bool(r.get("is_bot")), bot_logins)]

    days = _day_range(day_from, day_to)
    people, team = build_daily_shape(rows, days)

    meta = analytics_db.get_meta(repo_key)
    sync_cfg = get_pr_sync_config()
    stale = False
    if meta and meta.get("built_at"):
        built_at = datetime.fromisoformat(meta["built_at"].replace("Z", "+00:00"))
        age_seconds = (datetime.now(timezone.utc) - built_at).total_seconds()
        stale = age_seconds > 3 * sync_cfg["poll_interval_seconds"]

    history_state = synced_prs_db.get_history_state(repo_key)
    commit_branches = sync_cfg["commit_branches"]

    def _branch_done(b):
        # A branch counts as done once it backfilled or hit a persistent
        # error (e.g. a 404 on a branch that doesn't exist) -- the worker
        # retries an errored branch forever, so treating it as pending would
        # latch `syncing` true forever.
        state = synced_commits_db.get_branch_state(repo_key, b) or {}
        return bool(state.get("backfill_done")) or state.get("error") is not None

    commit_history_done = all(_branch_done(b) for b in commit_branches) if commit_branches else True

    backfill_done = bool(repo_row and repo_row.get("backfill_done"))
    history_done = bool(history_state.get("history_done"))
    syncing = sync_cfg["enabled"] and not (backfill_done and history_done and commit_history_done)

    return jsonify({
        "from": day_from,
        "to": day_to,
        "base": base,
        "days": days,
        "people": people,
        "team": team,
        "base_branches": analytics_db.base_refs(repo_key),
        "last_updated": _normalize_timestamp(meta["built_at"]) if meta else None,
        "stale": stale,
        "syncing": syncing,
        "coverage": {
            "earliest_pr_day": meta.get("earliest_pr_day") if meta else None,
            "earliest_commit_day": meta.get("earliest_commit_day") if meta else None,
            "pr_count": (meta.get("pr_count") if meta else None) or 0,
            "review_count": (meta.get("review_count") if meta else None) or 0,
            "commit_count": (meta.get("commit_count") if meta else None) or 0,
            "backfill_done": backfill_done,
            "history_done": history_done,
            "commit_history_done": commit_history_done,
        },
    })
