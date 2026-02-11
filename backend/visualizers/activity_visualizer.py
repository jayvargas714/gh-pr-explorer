"""Slice 52-week data by timeframe, compute summary stats."""


def compute_activity_summary(weekly_commits, code_changes, owner_commits, community_commits):
    """Compute summary stats from sliced activity data."""
    total_commits = sum(w.get("total", 0) for w in weekly_commits)
    total_additions = sum(c.get("additions", 0) for c in code_changes)
    total_deletions = sum(c.get("deletions", 0) for c in code_changes)
    avg_weekly = round(total_commits / len(weekly_commits), 1) if weekly_commits else 0

    peak_week = None
    peak_commits = 0
    for w in weekly_commits:
        if w.get("total", 0) > peak_commits:
            peak_commits = w["total"]
            peak_week = w["week"]

    owner_total = sum(owner_commits) if owner_commits else 0
    all_total = sum(owner_commits) + sum(community_commits) if owner_commits else 0
    owner_pct = round(owner_total / all_total * 100, 1) if all_total > 0 else 0

    return {
        "total_commits": total_commits,
        "avg_weekly_commits": avg_weekly,
        "total_additions": total_additions,
        "total_deletions": total_deletions,
        "peak_week": peak_week,
        "peak_commits": peak_commits,
        "owner_percentage": owner_pct,
    }


def slice_and_summarize(data, weeks):
    """Slice cached 52-week data by timeframe and add summary stats.

    Args:
        data: dict with weekly_commits, code_changes, owner_commits, community_commits
        weeks: number of weeks to slice (1-52)

    Returns:
        dict with sliced data + summary key
    """
    sliced = {
        "weekly_commits": data.get("weekly_commits", [])[-weeks:],
        "code_changes": data.get("code_changes", [])[-weeks:],
        "owner_commits": data.get("owner_commits", [])[-weeks:],
        "community_commits": data.get("community_commits", [])[-weeks:],
    }
    sliced["summary"] = compute_activity_summary(
        sliced["weekly_commits"], sliced["code_changes"],
        sliced["owner_commits"], sliced["community_commits"]
    )
    return sliced
