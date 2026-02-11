"""Reviewer leaderboard, bottleneck detection."""

from datetime import datetime, timezone


def _safe_median(lst):
    """Compute median of a list."""
    if not lst:
        return None
    s = sorted(lst)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def compute_responsiveness_metrics(prs):
    """Compute per-reviewer responsiveness metrics and bottleneck detection.

    Args:
        prs: list of PR dicts with createdAt, all_reviews, state, author, etc.

    Returns:
        dict with leaderboard, bottlenecks, avg_team_response_hours,
              fastest_reviewer, prs_awaiting_review
    """
    reviewer_data = {}
    bottlenecks = []
    now = datetime.now(timezone.utc)

    for pr in prs:
        created = pr.get("createdAt")
        reviews = pr.get("all_reviews", [])

        if created and reviews:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))

            for review in reviews:
                reviewer = review.get("login", "unknown")
                submitted = review.get("submitted_at")
                state = review.get("state", "")

                if reviewer not in reviewer_data:
                    reviewer_data[reviewer] = {
                        "response_times": [],
                        "total_reviews": 0,
                        "approvals": 0,
                        "changes_requested": 0,
                        "comments": 0
                    }

                reviewer_data[reviewer]["total_reviews"] += 1
                if state == "APPROVED":
                    reviewer_data[reviewer]["approvals"] += 1
                elif state == "CHANGES_REQUESTED":
                    reviewer_data[reviewer]["changes_requested"] += 1
                elif state == "COMMENTED":
                    reviewer_data[reviewer]["comments"] += 1

                if submitted:
                    submitted_dt = datetime.fromisoformat(submitted.replace("Z", "+00:00"))
                    response_hours = (submitted_dt - created_dt).total_seconds() / 3600
                    if response_hours >= 0:
                        reviewer_data[reviewer]["response_times"].append(response_hours)

        # Bottleneck: open PRs with no reviews
        if pr.get("state") == "OPEN" and not reviews and created:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            wait_hours = (now - created_dt).total_seconds() / 3600
            bottlenecks.append({
                "number": pr.get("number"),
                "title": pr.get("title"),
                "author": pr.get("author", {}).get("login", "unknown"),
                "wait_hours": round(wait_hours, 1)
            })

    # Build leaderboard
    leaderboard = []
    for reviewer, data in reviewer_data.items():
        times = data["response_times"]
        total = data["total_reviews"]
        approvals = data["approvals"]
        leaderboard.append({
            "reviewer": reviewer,
            "avg_response_time_hours": round(sum(times) / len(times), 2) if times else None,
            "median_response_time_hours": round(_safe_median(times), 2) if times else None,
            "total_reviews": total,
            "approvals": approvals,
            "changes_requested": data["changes_requested"],
            "approval_rate": round(approvals / total * 100, 1) if total > 0 else 0
        })

    leaderboard.sort(key=lambda x: x.get("avg_response_time_hours") or float("inf"))
    bottlenecks.sort(key=lambda x: x.get("wait_hours", 0), reverse=True)

    # Team-level summary
    all_times = [t for d in reviewer_data.values() for t in d["response_times"]]
    avg_team_response = round(sum(all_times) / len(all_times), 2) if all_times else None
    fastest = leaderboard[0]["reviewer"] if leaderboard else None

    return {
        "leaderboard": leaderboard,
        "bottlenecks": bottlenecks[:10],
        "avg_team_response_hours": avg_team_response,
        "fastest_reviewer": fastest,
        "prs_awaiting_review": len(bottlenecks)
    }
