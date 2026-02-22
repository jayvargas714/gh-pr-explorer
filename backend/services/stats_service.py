"""Developer stats aggregation from 3 sources (contributors, PRs, reviews)."""

import logging

from backend.services.github_service import (
    run_gh_command, parse_json_output, fetch_github_stats_api,
)

logger = logging.getLogger(__name__)


def fetch_contributor_stats(owner, repo):
    """Fetch contributor commit statistics from GitHub API."""
    return fetch_github_stats_api(
        owner, repo,
        "stats/contributors",
        jq_query=(
            "[.[] | select(.author) | "
            "{login: .author.login, avatar_url: .author.avatar_url, "
            "commits: .total, "
            "lines_added: ([.weeks[].a] | add), "
            "lines_deleted: ([.weeks[].d] | add)}]"
        ),
        max_retries=5,
        retry_delay=3,
    )


def fetch_pr_stats(owner, repo):
    """Fetch all PRs and aggregate statistics by author."""
    try:
        output = run_gh_command([
            "pr", "list", "-R", f"{owner}/{repo}",
            "--state", "all",
            "--limit", "500",
            "--json", "author,state,mergedAt",
        ])
        prs = parse_json_output(output)

        stats = {}
        for pr in prs:
            author = pr.get("author", {})
            if not author:
                continue
            login = author.get("login", "")
            if not login:
                continue

            if login not in stats:
                stats[login] = {
                    "avatar_url": author.get("avatarUrl", ""),
                    "authored": 0,
                    "merged": 0,
                    "closed": 0,
                    "open": 0,
                }

            stats[login]["authored"] += 1
            state = pr.get("state", "").upper()
            if state == "MERGED":
                stats[login]["merged"] += 1
            elif state == "CLOSED":
                stats[login]["closed"] += 1
            elif state == "OPEN":
                stats[login]["open"] += 1

        return stats
    except RuntimeError:
        return {}


def fetch_review_stats(owner, repo):
    """Fetch review statistics by reviewer."""
    try:
        output = run_gh_command([
            "pr", "list", "-R", f"{owner}/{repo}",
            "--state", "all",
            "--limit", "100",
            "--json", "number",
        ])
        prs = parse_json_output(output)

        stats = {}
        for pr in prs[:100]:
            pr_number = pr.get("number")
            if not pr_number:
                continue

            try:
                reviews_output = run_gh_command([
                    "api",
                    f"repos/{owner}/{repo}/pulls/{pr_number}/reviews",
                    "--jq", "[.[] | {login: .user.login, avatar_url: .user.avatar_url, state: .state}]",
                ])
                reviews = parse_json_output(reviews_output)

                for review in reviews:
                    login = review.get("login", "")
                    if not login:
                        continue

                    if login not in stats:
                        stats[login] = {
                            "avatar_url": review.get("avatar_url", ""),
                            "total": 0,
                            "approved": 0,
                            "changes_requested": 0,
                            "commented": 0,
                        }

                    stats[login]["total"] += 1
                    state = review.get("state", "").upper()
                    if state == "APPROVED":
                        stats[login]["approved"] += 1
                    elif state == "CHANGES_REQUESTED":
                        stats[login]["changes_requested"] += 1
                    elif state == "COMMENTED":
                        stats[login]["commented"] += 1

            except RuntimeError:
                continue

        return stats
    except RuntimeError:
        return {}


def fetch_and_compute_stats(owner, repo):
    """Fetch fresh stats from GitHub and compute aggregated developer stats."""
    contributor_stats = fetch_contributor_stats(owner, repo)
    pr_stats = fetch_pr_stats(owner, repo)
    review_stats = fetch_review_stats(owner, repo)

    developers = {}

    _dev_template = lambda login, avatar_url="": {
        "login": login,
        "avatar_url": avatar_url,
        "commits": 0,
        "lines_added": 0,
        "lines_deleted": 0,
        "prs_authored": 0,
        "prs_merged": 0,
        "prs_closed": 0,
        "prs_open": 0,
        "reviews_given": 0,
        "approvals": 0,
        "changes_requested": 0,
        "comments": 0,
    }

    for contrib in contributor_stats:
        login = contrib.get("login", "")
        if not login:
            continue
        developers[login] = _dev_template(login, contrib.get("avatar_url", ""))
        developers[login]["commits"] = contrib.get("commits", 0)
        developers[login]["lines_added"] = contrib.get("lines_added", 0)
        developers[login]["lines_deleted"] = contrib.get("lines_deleted", 0)

    for login, stats in pr_stats.items():
        if login not in developers:
            developers[login] = _dev_template(login, stats.get("avatar_url", ""))
        developers[login]["prs_authored"] = stats.get("authored", 0)
        developers[login]["prs_merged"] = stats.get("merged", 0)
        developers[login]["prs_closed"] = stats.get("closed", 0)
        developers[login]["prs_open"] = stats.get("open", 0)
        if not developers[login]["avatar_url"]:
            developers[login]["avatar_url"] = stats.get("avatar_url", "")

    for login, stats in review_stats.items():
        if login not in developers:
            developers[login] = _dev_template(login, stats.get("avatar_url", ""))
        developers[login]["reviews_given"] = stats.get("total", 0)
        developers[login]["approvals"] = stats.get("approved", 0)
        developers[login]["changes_requested"] = stats.get("changes_requested", 0)
        developers[login]["comments"] = stats.get("commented", 0)
        if not developers[login]["avatar_url"]:
            developers[login]["avatar_url"] = stats.get("avatar_url", "")

    stats_list = list(developers.values())
    stats_list.sort(key=lambda x: x.get("commits", 0), reverse=True)

    return stats_list


def add_avg_pr_scores(stats_list, full_repo, reviews_db):
    """Add average PR scores from reviews database to stats list."""
    conn = reviews_db._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT pr_author, AVG(score) as avg_score, COUNT(*) as review_count
            FROM reviews
            WHERE repo = ? AND score IS NOT NULL AND pr_author IS NOT NULL
            GROUP BY pr_author
        """, (full_repo,))

        score_data = {row["pr_author"]: {
            "avg_score": round(row["avg_score"], 1) if row["avg_score"] else None,
            "review_count": row["review_count"]
        } for row in cursor.fetchall()}
    finally:
        conn.close()

    for stat in stats_list:
        login = stat.get("login") or stat.get("username")
        if login and login in score_data:
            stat["avg_pr_score"] = score_data[login]["avg_score"]
            stat["reviewed_pr_count"] = score_data[login]["review_count"]
        else:
            stat["avg_pr_score"] = None
            stat["reviewed_pr_count"] = 0

    return stats_list


def stats_to_cache_format(stats_list):
    """Convert API-format stats list to database cache format."""
    cache_data = []
    for stat in stats_list:
        cache_data.append({
            "username": stat.get("login", ""),
            "total_prs": stat.get("prs_authored", 0),
            "open_prs": stat.get("prs_open", 0),
            "merged_prs": stat.get("prs_merged", 0),
            "closed_prs": stat.get("prs_closed", 0),
            "total_additions": stat.get("lines_added", 0),
            "total_deletions": stat.get("lines_deleted", 0),
            "commits": stat.get("commits", 0),
            "avatar_url": stat.get("avatar_url"),
            "reviews_given": stat.get("reviews_given", 0),
            "approvals": stat.get("approvals", 0),
            "changes_requested": stat.get("changes_requested", 0),
        })
    return cache_data


def cached_stats_to_api_format(cached_stats):
    """Convert database cache format to API response format."""
    transformed = []
    for stat in cached_stats:
        transformed.append({
            "login": stat.get("username", ""),
            "avatar_url": stat.get("avatar_url"),
            "commits": stat.get("commits", 0),
            "prs_authored": stat.get("total_prs", 0),
            "prs_open": stat.get("open_prs", 0),
            "prs_merged": stat.get("merged_prs", 0),
            "prs_closed": stat.get("closed_prs", 0),
            "lines_added": stat.get("total_additions", 0),
            "lines_deleted": stat.get("total_deletions", 0),
            "reviews_given": stat.get("reviews_given", 0),
            "approvals": stat.get("approvals", 0),
            "changes_requested": stat.get("changes_requested", 0),
            "avg_pr_score": stat.get("avg_pr_score"),
            "reviewed_pr_count": stat.get("reviewed_pr_count", 0),
        })
    return transformed
