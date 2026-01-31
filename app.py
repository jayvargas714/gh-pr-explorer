#!/usr/bin/env python3
"""GitHub PR Explorer - Flask Backend

A lightweight web application to browse, filter, and explore GitHub Pull Requests
using the GitHub CLI (gh) for authentication and data fetching.
"""

import json
import subprocess
import time
from functools import wraps
from pathlib import Path
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# Load configuration
config_path = Path(__file__).parent / "config.json"
with open(config_path) as f:
    config = json.load(f)

# Simple in-memory cache
cache = {}


def cached(ttl_seconds=None):
    """Decorator for caching function results."""
    if ttl_seconds is None:
        ttl_seconds = config.get("cache_ttl_seconds", 300)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}:{args}:{sorted(kwargs.items())}"
            now = time.time()

            if cache_key in cache:
                result, timestamp = cache[cache_key]
                if now - timestamp < ttl_seconds:
                    return result

            result = func(*args, **kwargs)
            cache[cache_key] = (result, now)
            return result

        return wrapper

    return decorator


def run_gh_command(args, check=True):
    """Run a gh CLI command and return the output."""
    try:
        result = subprocess.run(
            ["gh"] + args,
            capture_output=True,
            text=True,
            check=check,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"gh command failed: {e.stderr}")
    except FileNotFoundError:
        raise RuntimeError("gh CLI not found. Please install GitHub CLI.")


def parse_json_output(output):
    """Parse JSON output from gh CLI."""
    if not output:
        return []
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return []


# Routes

@app.route("/")
def index():
    """Serve the main HTML page."""
    return render_template("index.html")


@app.route("/api/user")
def get_user():
    """Get the current authenticated user."""
    try:
        output = run_gh_command([
            "api", "user",
            "--jq", "{login: .login, name: .name, avatar_url: .avatar_url}"
        ])
        user = parse_json_output(output) if output else {}
        return jsonify({"user": user})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/orgs")
def get_orgs():
    """List organizations the user belongs to, plus their personal account."""
    try:
        # Get current user
        user_output = run_gh_command([
            "api", "user",
            "--jq", "{login: .login, name: .name, avatar_url: .avatar_url, type: \"user\"}"
        ])
        user = json.loads(user_output) if user_output else None

        # Get organizations
        orgs_output = run_gh_command([
            "api", "user/orgs",
            "--jq", "[.[] | {login: .login, name: .login, avatar_url: .avatar_url, type: \"org\"}]"
        ])
        orgs = parse_json_output(orgs_output)

        # Combine: personal account first, then orgs
        accounts = []
        if user:
            user["is_personal"] = True
            accounts.append(user)
        accounts.extend(orgs)

        return jsonify({"accounts": accounts})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/repos")
def get_repos():
    """List repositories for an organization or user."""
    try:
        limit = request.args.get("limit", 100, type=int)
        owner = request.args.get("owner")  # org or user login

        args = ["repo", "list"]
        if owner:
            args.append(owner)
        args.extend([
            "--json", "name,owner,description,isPrivate,updatedAt",
            "--limit", str(limit),
        ])

        output = run_gh_command(args)
        repos = parse_json_output(output)
        return jsonify({"repos": repos})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/repos/<owner>/<repo>/prs")
def get_prs(owner, repo):
    """Get PRs with advanced filtering support using GitHub search syntax."""
    try:
        # Build gh pr list command
        args = ["pr", "list", "-R", f"{owner}/{repo}"]

        # Build search query parts
        search_parts = []

        # State filter (use gh native flags for basic states)
        state = request.args.get("state", "open")
        if state == "all":
            args.extend(["--state", "all"])
        elif state == "merged":
            args.extend(["--state", "merged"])
        elif state == "closed":
            args.extend(["--state", "closed"])
        else:
            args.extend(["--state", "open"])

        # Author filter
        author = request.args.get("author")
        if author:
            args.extend(["--author", author])

        # Assignee filter
        assignee = request.args.get("assignee")
        if assignee:
            args.extend(["--assignee", assignee])

        # Label filter (supports multiple)
        labels = request.args.get("labels")
        if labels:
            for lbl in labels.split(","):
                lbl = lbl.strip()
                if lbl:
                    args.extend(["--label", lbl])

        # Base branch filter
        base = request.args.get("base")
        if base:
            args.extend(["--base", base])

        # Head branch filter
        head = request.args.get("head")
        if head:
            args.extend(["--head", head])

        # Draft filter
        draft = request.args.get("draft")
        if draft == "true":
            search_parts.append("draft:true")
        elif draft == "false":
            search_parts.append("draft:false")

        # Review status filter (supports multiple with OR logic)
        review = request.args.get("review")
        if review:
            review_values = [r.strip() for r in review.split(",") if r.strip()]
            if len(review_values) == 1:
                search_parts.append(f"review:{review_values[0]}")
            elif len(review_values) > 1:
                # OR logic: wrap in parentheses
                review_parts = [f"review:{r}" for r in review_values]
                search_parts.append(f"({' OR '.join(review_parts)})")

        # Reviewed by filter
        reviewed_by = request.args.get("reviewedBy")
        if reviewed_by:
            search_parts.append(f"reviewed-by:{reviewed_by}")

        # Review requested filter
        review_requested = request.args.get("reviewRequested")
        if review_requested:
            search_parts.append(f"review-requested:{review_requested}")

        # CI/Status filter (supports multiple with OR logic)
        status = request.args.get("status")
        if status:
            status_values = [s.strip() for s in status.split(",") if s.strip()]
            if len(status_values) == 1:
                search_parts.append(f"status:{status_values[0]}")
            elif len(status_values) > 1:
                # OR logic: wrap in parentheses
                status_parts = [f"status:{s}" for s in status_values]
                search_parts.append(f"({' OR '.join(status_parts)})")

        # Involves filter (author, assignee, mentions, commenter)
        involves = request.args.get("involves")
        if involves:
            search_parts.append(f"involves:{involves}")

        # Mentions filter
        mentions = request.args.get("mentions")
        if mentions:
            search_parts.append(f"mentions:{mentions}")

        # Commenter filter
        commenter = request.args.get("commenter")
        if commenter:
            search_parts.append(f"commenter:{commenter}")

        # Linked to issue filter
        linked = request.args.get("linked")
        if linked == "true":
            search_parts.append("linked:issue")
        elif linked == "false":
            search_parts.append("-linked:issue")

        # Comments count filter
        comments = request.args.get("comments")
        if comments:
            search_parts.append(f"comments:{comments}")

        # Date filters
        created_after = request.args.get("createdAfter")
        if created_after:
            search_parts.append(f"created:>={created_after}")

        created_before = request.args.get("createdBefore")
        if created_before:
            search_parts.append(f"created:<={created_before}")

        updated_after = request.args.get("updatedAfter")
        if updated_after:
            search_parts.append(f"updated:>={updated_after}")

        updated_before = request.args.get("updatedBefore")
        if updated_before:
            search_parts.append(f"updated:<={updated_before}")

        merged_after = request.args.get("mergedAfter")
        if merged_after:
            search_parts.append(f"merged:>={merged_after}")

        merged_before = request.args.get("mergedBefore")
        if merged_before:
            search_parts.append(f"merged:<={merged_before}")

        closed_after = request.args.get("closedAfter")
        if closed_after:
            search_parts.append(f"closed:>={closed_after}")

        closed_before = request.args.get("closedBefore")
        if closed_before:
            search_parts.append(f"closed:<={closed_before}")

        # Milestone filter
        milestone = request.args.get("milestone")
        if milestone:
            if milestone == "none":
                search_parts.append("no:milestone")
            else:
                search_parts.append(f'milestone:"{milestone}"')

        # No assignee filter
        no_assignee = request.args.get("noAssignee")
        if no_assignee == "true":
            search_parts.append("no:assignee")

        # No label filter
        no_label = request.args.get("noLabel")
        if no_label == "true":
            search_parts.append("no:label")

        # Search in specific fields
        search_in = request.args.get("searchIn", "")
        search_text = request.args.get("search", "")
        if search_text:
            if search_in:
                # Search in specific fields
                for field in search_in.split(","):
                    field = field.strip()
                    if field in ["title", "body", "comments"]:
                        search_parts.append(f"{search_text} in:{field}")
            else:
                # General search
                search_parts.append(search_text)

        # Advanced filters
        # Reactions count
        reactions = request.args.get("reactions")
        if reactions:
            search_parts.append(f"reactions:{reactions}")

        # Interactions count
        interactions = request.args.get("interactions")
        if interactions:
            search_parts.append(f"interactions:{interactions}")

        # Team review requested
        team_review = request.args.get("teamReviewRequested")
        if team_review:
            search_parts.append(f"team-review-requested:{team_review}")

        # Exclude labels (NOT logic)
        exclude_labels = request.args.get("excludeLabels")
        if exclude_labels:
            for lbl in exclude_labels.split(","):
                lbl = lbl.strip()
                if lbl:
                    search_parts.append(f'-label:"{lbl}"')

        # Exclude author
        exclude_author = request.args.get("excludeAuthor")
        if exclude_author:
            search_parts.append(f"-author:{exclude_author}")

        # Exclude milestone
        exclude_milestone = request.args.get("excludeMilestone")
        if exclude_milestone:
            search_parts.append(f'-milestone:"{exclude_milestone}"')

        # Sort options
        sort_by = request.args.get("sortBy")
        sort_direction = request.args.get("sortDirection", "desc")
        if sort_by:
            sort_map = {
                "created": "created",
                "updated": "updated",
                "comments": "comments",
                "reactions": "reactions",
                "interactions": "interactions"
            }
            if sort_by in sort_map:
                search_parts.append(f"sort:{sort_map[sort_by]}-{sort_direction}")

        # Combine all search parts
        if search_parts:
            search_query = " ".join(search_parts)
            args.extend(["--search", search_query])

        # Limit - cap at 100 to avoid GraphQL node limits
        limit = request.args.get("limit", config.get("default_per_page", 30), type=int)
        limit = min(limit, 100)  # Hard cap to prevent GraphQL errors
        args.extend(["--limit", str(limit)])

        # JSON output with fields
        # Note: Avoid heavy nested fields (commits, comments, reviews) to prevent
        # GraphQL "exceeds maximum limit of 500,000 nodes" errors
        args.extend([
            "--json",
            "number,title,author,state,isDraft,createdAt,updatedAt,closedAt,"
            "mergedAt,url,body,headRefName,baseRefName,labels,assignees,"
            "reviewRequests,reviewDecision,mergeable,additions,deletions,changedFiles,"
            "milestone"
        ])

        output = run_gh_command(args)
        prs = parse_json_output(output)

        # Post-process: add review status summary from reviewDecision field
        for pr in prs:
            pr["reviewStatus"] = get_review_status(pr.get("reviewDecision"))

        return jsonify({"prs": prs})

    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


def get_review_status(review_decision):
    """Determine review status from reviewDecision field."""
    if not review_decision:
        return "pending"

    decision = review_decision.upper()

    if decision == "CHANGES_REQUESTED":
        return "changes_requested"
    if decision == "APPROVED":
        return "approved"
    if decision == "REVIEW_REQUIRED":
        return "review_required"
    return "pending"


@app.route("/api/repos/<owner>/<repo>/contributors")
def get_contributors(owner, repo):
    """Get contributors for a repository (for filter dropdowns)."""
    try:
        # Use gh api to get contributors
        output = run_gh_command([
            "api",
            f"repos/{owner}/{repo}/contributors",
            "--jq", ".[].login",
        ])
        contributors = [c.strip() for c in output.split("\n") if c.strip()]
        return jsonify({"contributors": contributors})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/repos/<owner>/<repo>/labels")
def get_labels(owner, repo):
    """Get labels for a repository (for filter dropdowns)."""
    try:
        output = run_gh_command([
            "api",
            f"repos/{owner}/{repo}/labels",
            "--jq", ".[].name",
        ])
        labels = [l.strip() for l in output.split("\n") if l.strip()]
        return jsonify({"labels": labels})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/repos/<owner>/<repo>/branches")
def get_branches(owner, repo):
    """Get branches for a repository (for filter dropdowns)."""
    try:
        output = run_gh_command([
            "api",
            f"repos/{owner}/{repo}/branches",
            "--jq", ".[].name",
            "--paginate",
        ])
        branches = [b.strip() for b in output.split("\n") if b.strip()]
        return jsonify({"branches": branches})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/repos/<owner>/<repo>/milestones")
def get_milestones(owner, repo):
    """Get milestones for a repository (for filter dropdowns)."""
    try:
        output = run_gh_command([
            "api",
            f"repos/{owner}/{repo}/milestones",
            "--jq", "[.[] | {title: .title, state: .state, number: .number}]",
        ])
        milestones = parse_json_output(output)
        return jsonify({"milestones": milestones})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/repos/<owner>/<repo>/teams")
def get_teams(owner, repo):
    """Get teams with access to a repository (for filter dropdowns)."""
    try:
        output = run_gh_command([
            "api",
            f"repos/{owner}/{repo}/teams",
            "--jq", "[.[] | {slug: .slug, name: .name}]",
        ])
        teams = parse_json_output(output)
        return jsonify({"teams": teams})
    except RuntimeError as e:
        # Teams endpoint may fail for personal repos
        return jsonify({"teams": []})


@app.route("/api/repos/<owner>/<repo>/stats")
def get_developer_stats(owner, repo):
    """Get aggregated developer statistics for a repository."""
    try:
        # Fetch contributor commit stats
        contributor_stats = fetch_contributor_stats(owner, repo)

        # Fetch all PRs and aggregate by author
        pr_stats = fetch_pr_stats(owner, repo)

        # Fetch review stats
        review_stats = fetch_review_stats(owner, repo)

        # Combine all stats by developer
        developers = {}

        # Add contributor stats (commits, lines added/deleted)
        for contrib in contributor_stats:
            login = contrib.get("login", "")
            if not login:
                continue
            developers[login] = {
                "login": login,
                "avatar_url": contrib.get("avatar_url", ""),
                "commits": contrib.get("commits", 0),
                "lines_added": contrib.get("lines_added", 0),
                "lines_deleted": contrib.get("lines_deleted", 0),
                "prs_authored": 0,
                "prs_merged": 0,
                "prs_closed": 0,
                "prs_open": 0,
                "reviews_given": 0,
                "approvals": 0,
                "changes_requested": 0,
                "comments": 0,
            }

        # Add PR stats
        for login, stats in pr_stats.items():
            if login not in developers:
                developers[login] = {
                    "login": login,
                    "avatar_url": stats.get("avatar_url", ""),
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
            developers[login]["prs_authored"] = stats.get("authored", 0)
            developers[login]["prs_merged"] = stats.get("merged", 0)
            developers[login]["prs_closed"] = stats.get("closed", 0)
            developers[login]["prs_open"] = stats.get("open", 0)
            if not developers[login]["avatar_url"]:
                developers[login]["avatar_url"] = stats.get("avatar_url", "")

        # Add review stats
        for login, stats in review_stats.items():
            if login not in developers:
                developers[login] = {
                    "login": login,
                    "avatar_url": stats.get("avatar_url", ""),
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
            developers[login]["reviews_given"] = stats.get("total", 0)
            developers[login]["approvals"] = stats.get("approved", 0)
            developers[login]["changes_requested"] = stats.get("changes_requested", 0)
            developers[login]["comments"] = stats.get("commented", 0)
            if not developers[login]["avatar_url"]:
                developers[login]["avatar_url"] = stats.get("avatar_url", "")

        # Convert to list and sort by commits (descending)
        stats_list = list(developers.values())
        stats_list.sort(key=lambda x: x.get("commits", 0), reverse=True)

        return jsonify({"stats": stats_list})

    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


def fetch_contributor_stats(owner, repo):
    """Fetch contributor commit statistics from GitHub API.

    Note: GitHub's stats API returns 202 when computing stats for the first time.
    We retry a few times to wait for the computation to complete.
    """
    max_retries = 3
    retry_delay = 2  # seconds

    for attempt in range(max_retries):
        try:
            # First, make a raw request to check status
            result = subprocess.run(
                ["gh", "api", f"repos/{owner}/{repo}/stats/contributors", "-i"],
                capture_output=True,
                text=True,
                check=False,
            )

            # Check if we got a 202 (computing) response
            if "HTTP/2.0 202" in result.stdout or "202 Accepted" in result.stdout:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                else:
                    # Give up after max retries
                    return []

            # Now fetch with jq processing
            output = run_gh_command([
                "api",
                f"repos/{owner}/{repo}/stats/contributors",
                "--jq", "[.[] | select(.author) | {login: .author.login, avatar_url: .author.avatar_url, commits: .total, lines_added: ([.weeks[].a] | add), lines_deleted: ([.weeks[].d] | add)}]",
            ])

            result = parse_json_output(output)
            if result:
                return result

            # Empty result, might need retry
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue

        except RuntimeError:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            return []

    return []


def fetch_pr_stats(owner, repo):
    """Fetch all PRs and aggregate statistics by author."""
    try:
        # Fetch all PRs (state=all, limit high to get comprehensive stats)
        output = run_gh_command([
            "pr", "list", "-R", f"{owner}/{repo}",
            "--state", "all",
            "--limit", "500",
            "--json", "author,state,mergedAt",
        ])
        prs = parse_json_output(output)

        # Aggregate by author
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
        # First, get list of recent PRs to check for reviews
        output = run_gh_command([
            "pr", "list", "-R", f"{owner}/{repo}",
            "--state", "all",
            "--limit", "100",
            "--json", "number",
        ])
        prs = parse_json_output(output)

        # Aggregate review stats
        stats = {}

        # Fetch reviews for each PR (limit to first 100 PRs for performance)
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
                # Skip PRs where we can't fetch reviews
                continue

        return stats
    except RuntimeError:
        return {}


@app.route("/api/clear-cache", methods=["POST"])
def clear_cache():
    """Clear the in-memory cache."""
    global cache
    cache = {}
    return jsonify({"message": "Cache cleared"})


if __name__ == "__main__":
    app.run(
        host=config.get("host", "127.0.0.1"),
        port=config.get("port", 5050),
        debug=config.get("debug", False),
    )
