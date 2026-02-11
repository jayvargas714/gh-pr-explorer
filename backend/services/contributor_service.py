"""Contributor time series transform."""

import logging
from datetime import datetime, timezone

from backend.services.github_service import fetch_github_stats_api

logger = logging.getLogger(__name__)


def fetch_contributor_timeseries(owner, repo):
    """Fetch and transform per-contributor weekly time series from GitHub stats/contributors API.

    Returns list of contributor objects sorted by total commits descending.
    """
    raw = fetch_github_stats_api(owner, repo, "stats/contributors")
    if not raw or not isinstance(raw, list):
        return []

    contributors = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue

        author = entry.get("author") or {}
        weeks_raw = entry.get("weeks", [])
        total = entry.get("total", 0)

        weeks = []
        for w in weeks_raw:
            if not isinstance(w, dict):
                continue
            ts = w.get("w", 0)
            date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            weeks.append({
                "week": date_str,
                "commits": w.get("c", 0),
                "additions": w.get("a", 0),
                "deletions": w.get("d", 0),
            })

        contributors.append({
            "login": author.get("login", "unknown"),
            "avatar_url": author.get("avatar_url", ""),
            "total": total,
            "weeks": weeks,
        })

    contributors.sort(key=lambda c: c["total"], reverse=True)
    return contributors
