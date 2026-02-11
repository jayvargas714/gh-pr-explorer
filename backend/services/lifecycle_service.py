"""PR review times fetch (ThreadPoolExecutor) with SQLite cache."""

import logging
from concurrent.futures import ThreadPoolExecutor

from backend.services.github_service import run_gh_command, parse_json_output

logger = logging.getLogger(__name__)


def fetch_pr_review_times(owner, repo, lifecycle_cache_db, limit=50):
    """Fetch PRs with review timing data. Uses SQLite cache with 2-hour TTL."""
    repo_key = f"{owner}/{repo}"

    if not lifecycle_cache_db.is_stale(repo_key):
        cached = lifecycle_cache_db.get_cached(repo_key)
        if cached:
            return cached["data"]

    try:
        pr_output = run_gh_command([
            "pr", "list", "-R", f"{owner}/{repo}",
            "--state", "all", "--limit", str(limit),
            "--json", "number,title,createdAt,mergedAt,closedAt,updatedAt,author,state"
        ])
        prs = parse_json_output(pr_output) or []
    except RuntimeError:
        prs = []

    if not prs:
        return []

    def fetch_reviews_for_pr(pr):
        number = pr.get("number")
        try:
            output = run_gh_command([
                "api", f"repos/{owner}/{repo}/pulls/{number}/reviews",
                "--jq", '[.[] | {login: .user.login, submitted_at: .submitted_at, state: .state}]'
            ])
            reviews = parse_json_output(output) or []
        except RuntimeError:
            reviews = []

        pr["all_reviews"] = reviews
        if reviews:
            pr["first_review_at"] = reviews[0].get("submitted_at")
            pr["first_reviewer"] = reviews[0].get("login")
        else:
            pr["first_review_at"] = None
            pr["first_reviewer"] = None
        return pr

    with ThreadPoolExecutor(max_workers=5) as executor:
        enriched = list(executor.map(fetch_reviews_for_pr, prs))

    lifecycle_cache_db.save_cache(repo_key, enriched)
    return enriched
