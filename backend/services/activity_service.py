"""Code activity data from 3 stats APIs."""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from backend.services.github_service import fetch_github_stats_api

logger = logging.getLogger(__name__)


def fetch_code_activity_data(owner, repo):
    """Fetch and process all 52 weeks of code activity data from GitHub stats APIs.

    Returns a dict with weekly_commits, code_changes, owner_commits, community_commits,
    or None if all data sources are empty.
    """
    with ThreadPoolExecutor(max_workers=3) as executor:
        freq_future = executor.submit(fetch_github_stats_api, owner, repo, "stats/code_frequency")
        commit_future = executor.submit(fetch_github_stats_api, owner, repo, "stats/commit_activity")
        participation_future = executor.submit(fetch_github_stats_api, owner, repo, "stats/participation")

        code_freq = freq_future.result()
        commit_activity = commit_future.result()
        participation = participation_future.result()

    code_changes = []
    if isinstance(code_freq, list):
        for entry in code_freq:
            if isinstance(entry, list) and len(entry) >= 3:
                ts = entry[0]
                date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                code_changes.append({
                    "week": date_str,
                    "additions": entry[1],
                    "deletions": abs(entry[2])
                })

    weekly_commits = []
    if isinstance(commit_activity, list):
        for entry in commit_activity:
            if isinstance(entry, dict):
                ts = entry.get("week", 0)
                date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                weekly_commits.append({
                    "week": date_str,
                    "total": entry.get("total", 0),
                    "days": entry.get("days", [0]*7)
                })

    owner_commits = []
    community_commits = []
    if isinstance(participation, dict):
        all_p = participation.get("all", [])
        owner_p = participation.get("owner", [])
        owner_commits = owner_p if owner_p else []
        community_commits = [
            (all_p[i] if i < len(all_p) else 0) - (owner_p[i] if i < len(owner_p) else 0)
            for i in range(len(all_p))
        ]

    if not weekly_commits and not code_changes and not owner_commits and not community_commits:
        return None

    return {
        "weekly_commits": weekly_commits,
        "code_changes": code_changes,
        "owner_commits": owner_commits,
        "community_commits": community_commits,
    }
