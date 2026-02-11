"""Merge time distribution, stale PR detection, pr_table building."""

from datetime import datetime, timezone


def _median(lst):
    """Compute median of a sorted list."""
    if not lst:
        return None
    s = sorted(lst)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def compute_lifecycle_metrics(prs):
    """Compute PR lifecycle metrics from enriched PR data.

    Args:
        prs: list of PR dicts with createdAt, mergedAt, updatedAt,
             first_review_at, first_reviewer, state, author, etc.

    Returns:
        dict with median/avg merge/review times, stale_prs, distribution, pr_table
    """
    merge_times = []
    review_times = []
    stale_prs = []
    pr_table = []
    distribution = {"<1h": 0, "1-4h": 0, "4-24h": 0, "1-3d": 0, "3-7d": 0, ">7d": 0}

    now = datetime.now(timezone.utc)

    for pr in prs:
        created = pr.get("createdAt")
        merged = pr.get("mergedAt")
        first_review = pr.get("first_review_at")
        updated = pr.get("updatedAt")

        ttm_hours = None
        ttfr_hours = None

        if created:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))

            # Time to merge
            if merged:
                merged_dt = datetime.fromisoformat(merged.replace("Z", "+00:00"))
                ttm_hours = (merged_dt - created_dt).total_seconds() / 3600
                merge_times.append(ttm_hours)

                # Distribution
                if ttm_hours < 1:
                    distribution["<1h"] += 1
                elif ttm_hours < 4:
                    distribution["1-4h"] += 1
                elif ttm_hours < 24:
                    distribution["4-24h"] += 1
                elif ttm_hours < 72:
                    distribution["1-3d"] += 1
                elif ttm_hours < 168:
                    distribution["3-7d"] += 1
                else:
                    distribution[">7d"] += 1

            # Time to first review
            if first_review:
                review_dt = datetime.fromisoformat(first_review.replace("Z", "+00:00"))
                ttfr_hours = (review_dt - created_dt).total_seconds() / 3600
                review_times.append(ttfr_hours)

            # Stale detection (open PRs, no activity in 14+ days)
            if pr.get("state") == "OPEN" and updated:
                updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                age_days = (now - updated_dt).total_seconds() / 86400
                if age_days > 14:
                    stale_prs.append({
                        "number": pr.get("number"),
                        "title": pr.get("title"),
                        "author": pr.get("author", {}).get("login", "unknown"),
                        "age_days": round(age_days, 1)
                    })

        pr_table.append({
            "number": pr.get("number"),
            "title": pr.get("title"),
            "author": pr.get("author", {}).get("login", "unknown"),
            "created_at": created,
            "state": pr.get("state"),
            "time_to_first_review_hours": round(ttfr_hours, 2) if ttfr_hours is not None else None,
            "time_to_merge_hours": round(ttm_hours, 2) if ttm_hours is not None else None,
            "first_reviewer": pr.get("first_reviewer")
        })

    return {
        "median_time_to_merge": round(_median(merge_times), 2) if merge_times else None,
        "avg_time_to_merge": round(sum(merge_times) / len(merge_times), 2) if merge_times else None,
        "median_time_to_first_review": round(_median(review_times), 2) if review_times else None,
        "avg_time_to_first_review": round(sum(review_times) / len(review_times), 2) if review_times else None,
        "stale_prs": stale_prs,
        "stale_count": len(stale_prs),
        "distribution": distribution,
        "pr_table": pr_table
    }
