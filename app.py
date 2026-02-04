#!/usr/bin/env python3
"""GitHub PR Explorer - Flask Backend

A lightweight web application to browse, filter, and explore GitHub Pull Requests
using the GitHub CLI (gh) for authentication and data fetching.
"""

import json
import logging
import re
import subprocess
import time
import threading
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from flask import Flask, jsonify, render_template, request

from database import get_database, get_reviews_db, get_queue_db, get_settings_db, get_dev_stats_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Load configuration
config_path = Path(__file__).parent / "config.json"
with open(config_path) as f:
    config = json.load(f)

# Code reviews directory
REVIEWS_DIR = Path("/Users/jvargas714/Documents/code-reviews")

# In-memory tracking of active review processes
# key: "owner/repo/pr_number", value: {"process": Popen, "status": str, "started_at": str, "pr_url": str}
active_reviews = {}
reviews_lock = threading.Lock()


# Initialize database
db = get_database()
reviews_db = get_reviews_db()
queue_db = get_queue_db()
settings_db = get_settings_db()
dev_stats_db = get_dev_stats_db()

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


def fetch_pr_state(owner, repo, pr_number):
    """Fetch the current state of a PR from GitHub.

    Returns:
        str: PR state (OPEN, CLOSED, or MERGED), or None on error.
    """
    try:
        output = run_gh_command([
            "pr", "view", str(pr_number),
            "-R", f"{owner}/{repo}",
            "--json", "state",
            "--jq", ".state"
        ])
        return output.strip().upper() if output else None
    except RuntimeError as e:
        logger.warning(f"Failed to fetch PR state for {owner}/{repo}#{pr_number}: {e}")
        return None


def fetch_pr_head_sha(owner, repo, pr_number):
    """Fetch the current head commit SHA of a PR from GitHub.

    Returns:
        str: The head commit SHA, or None on error.
    """
    try:
        output = run_gh_command([
            "pr", "view", str(pr_number),
            "-R", f"{owner}/{repo}",
            "--json", "headRefOid",
            "--jq", ".headRefOid"
        ])
        return output.strip() if output else None
    except RuntimeError as e:
        logger.warning(f"Failed to fetch PR head SHA for {owner}/{repo}#{pr_number}: {e}")
        return None


def parse_critical_issues(content):
    """Parse critical issues from review markdown content.

    Expected format:
    **Critical Issues**
    **1. Issue Title**
    - Location: path/to/file.py:123-456 or path/to/file.py:123
    - Problem: Description
    - Fix: Solution

    Returns:
        List of dicts: [{ title, path, start_line, end_line, body }]
    """
    issues = []
    if not content:
        return issues

    # Find the Critical Issues section
    critical_match = re.search(
        r'\*\*Critical Issues\*\*\s*(.*?)(?=\n---|\n\*\*[A-Z]|\Z)',
        content,
        re.DOTALL | re.IGNORECASE
    )

    if not critical_match:
        return issues

    critical_section = critical_match.group(1)

    # Find individual issues
    # Pattern: **N. Title** followed by Location, Problem, Fix
    issue_pattern = re.compile(
        r'\*\*(\d+)\.\s*(.+?)\*\*\s*'
        r'(?:-\s*Location:\s*([^\n]+))?'
        r'(?:-\s*Problem:\s*([^\n]+(?:\n(?!-).*?)*))?'
        r'(?:-\s*Fix:\s*([^\n]+(?:\n(?!-).*?)*))?',
        re.DOTALL
    )

    for match in issue_pattern.finditer(critical_section):
        issue_num = match.group(1)
        title = match.group(2).strip()
        location = match.group(3).strip() if match.group(3) else None
        problem = match.group(4).strip() if match.group(4) else None
        fix = match.group(5).strip() if match.group(5) else None

        if not location:
            continue

        # Parse location: file.py:123-456 or file.py:123
        loc_match = re.match(r'([^:]+):(\d+)(?:-(\d+))?', location)
        if not loc_match:
            continue

        file_path = loc_match.group(1).strip()
        start_line = int(loc_match.group(2))
        end_line = int(loc_match.group(3)) if loc_match.group(3) else start_line

        # Build the comment body
        body_parts = [f"**{title}**"]
        if problem:
            body_parts.append(f"\n**Problem:** {problem}")
        if fix:
            body_parts.append(f"\n**Fix:** {fix}")

        issues.append({
            "title": title,
            "path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "body": "\n".join(body_parts)
        })

    return issues


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
            "milestone,statusCheckRollup"
        ])

        output = run_gh_command(args)
        prs = parse_json_output(output)

        # Post-process: add review status and CI status summaries
        for pr in prs:
            pr["reviewStatus"] = get_review_status(pr.get("reviewDecision"))
            pr["ciStatus"] = get_ci_status(pr.get("statusCheckRollup"))

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


def get_ci_status(status_check_rollup):
    """Determine CI status from statusCheckRollup field.

    Returns: 'success', 'failure', 'pending', 'neutral', or None if no checks
    """
    if not status_check_rollup:
        return None

    # Handle both list format and object with contexts key
    if isinstance(status_check_rollup, list):
        contexts = status_check_rollup
    else:
        contexts = status_check_rollup.get("contexts", [])

    if not contexts:
        return None

    # Count statuses
    has_failure = False
    has_pending = False
    has_success = False

    for check in contexts:
        # Handle both check runs and status contexts
        state = check.get("state", "").upper()
        conclusion = check.get("conclusion", "").upper() if check.get("conclusion") else None
        status = check.get("status", "").upper()

        # Check runs use conclusion, status contexts use state
        if conclusion:
            if conclusion in ("FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED"):
                has_failure = True
            elif conclusion == "SUCCESS":
                has_success = True
            elif conclusion in ("NEUTRAL", "SKIPPED"):
                pass  # Neutral/skipped don't affect overall status
            else:
                has_pending = True
        elif state:
            if state == "FAILURE" or state == "ERROR":
                has_failure = True
            elif state == "SUCCESS":
                has_success = True
            elif state == "PENDING":
                has_pending = True
        elif status:
            if status in ("IN_PROGRESS", "QUEUED", "WAITING", "PENDING"):
                has_pending = True

    # Determine overall status (failure takes priority, then pending)
    if has_failure:
        return "failure"
    if has_pending:
        return "pending"
    if has_success:
        return "success"
    return "neutral"


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


# Track which repos are currently being refreshed in background
_stats_refresh_in_progress = set()
_stats_refresh_lock = threading.Lock()


def _background_refresh_stats(owner, repo, full_repo):
    """Background task to refresh stats for a repository."""
    try:
        logger.info(f"Background refresh started for {full_repo}")
        stats_list = _fetch_and_compute_stats(owner, repo)

        # Cache the stats
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
            })
        dev_stats_db.save_stats(full_repo, cache_data)
        logger.info(f"Background refresh completed for {full_repo}")
    except Exception as e:
        logger.error(f"Background refresh failed for {full_repo}: {e}")
    finally:
        with _stats_refresh_lock:
            _stats_refresh_in_progress.discard(full_repo)


@app.route("/api/repos/<owner>/<repo>/stats")
def get_developer_stats(owner, repo):
    """Get aggregated developer statistics for a repository.

    Stats are cached in the database and refreshed every 4 hours.
    - If cached stats exist (even if stale), return them immediately
    - If stale, trigger a background refresh for next time
    - If no cached data exists, fetch synchronously
    - Use ?refresh=true to force synchronous refresh
    """
    full_repo = f"{owner}/{repo}"
    force_refresh = request.args.get("refresh", "").lower() == "true"

    try:
        is_stale = dev_stats_db.is_stale(full_repo)
        last_updated = dev_stats_db.get_last_updated(full_repo)
        cached_stats = dev_stats_db.get_stats(full_repo)

        # Check if background refresh is in progress
        with _stats_refresh_lock:
            refreshing = full_repo in _stats_refresh_in_progress

        # Force refresh: fetch synchronously and wait
        if force_refresh:
            stats_list = _fetch_and_compute_stats(owner, repo)
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
                })
            dev_stats_db.save_stats(full_repo, cache_data)
            last_updated = dev_stats_db.get_last_updated(full_repo)
            stats_with_scores = _add_avg_pr_scores(stats_list, full_repo)
            return jsonify({
                "stats": stats_with_scores,
                "last_updated": last_updated.isoformat() if last_updated else None,
                "cached": False,
                "refreshing": False
            })

        # If we have cached data, return it immediately
        if cached_stats:
            # If stale and not already refreshing, trigger background refresh
            if is_stale and not refreshing:
                with _stats_refresh_lock:
                    if full_repo not in _stats_refresh_in_progress:
                        _stats_refresh_in_progress.add(full_repo)
                        thread = threading.Thread(
                            target=_background_refresh_stats,
                            args=(owner, repo, full_repo),
                            daemon=True
                        )
                        thread.start()
                        refreshing = True

            stats_with_scores = _add_avg_pr_scores(cached_stats, full_repo)
            return jsonify({
                "stats": stats_with_scores,
                "last_updated": last_updated.isoformat() if last_updated else None,
                "cached": True,
                "stale": is_stale,
                "refreshing": refreshing
            })

        # No cached data: fetch synchronously (first time)
        stats_list = _fetch_and_compute_stats(owner, repo)
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
            })
        dev_stats_db.save_stats(full_repo, cache_data)
        last_updated = dev_stats_db.get_last_updated(full_repo)
        stats_with_scores = _add_avg_pr_scores(stats_list, full_repo)

        return jsonify({
            "stats": stats_with_scores,
            "last_updated": last_updated.isoformat() if last_updated else None,
            "cached": False,
            "refreshing": False
        })

    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


def _add_avg_pr_scores(stats_list, full_repo):
    """Add average PR scores from reviews database to stats list."""
    # Get average scores per author from reviews
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

    # Add scores to stats
    for stat in stats_list:
        login = stat.get("login") or stat.get("username")
        if login and login in score_data:
            stat["avg_pr_score"] = score_data[login]["avg_score"]
            stat["reviewed_pr_count"] = score_data[login]["review_count"]
        else:
            stat["avg_pr_score"] = None
            stat["reviewed_pr_count"] = 0

    return stats_list


def _fetch_and_compute_stats(owner, repo):
    """Fetch fresh stats from GitHub and compute aggregated developer stats."""
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

    return stats_list


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


@app.route("/api/merge-queue", methods=["GET"])
def get_merge_queue():
    """Get all items in the merge queue with fresh PR states and new commits info."""
    try:
        queue_items = queue_db.get_queue()
        # Convert to expected format
        queue = []
        for item in queue_items:
            # Get note count for this item
            notes_count = queue_db.get_notes_count(item["id"])

            # Fetch fresh PR state from GitHub
            repo_parts = item["repo"].split("/")
            pr_state = None
            has_new_commits = False
            last_reviewed_sha = None
            current_sha = None
            review_score = None
            has_review = False

            review_id = None
            inline_comments_posted = False

            if len(repo_parts) == 2:
                owner, repo = repo_parts
                pr_state = fetch_pr_state(owner, repo, item["pr_number"])

                # Check for new commits since last review and get review score
                latest_review = reviews_db.get_latest_review_for_pr(item["repo"], item["pr_number"])
                if latest_review:
                    has_review = True
                    review_score = latest_review.get("score")
                    review_id = latest_review.get("id")
                    inline_comments_posted = latest_review.get("inline_comments_posted", False)
                    if latest_review.get("head_commit_sha"):
                        last_reviewed_sha = latest_review["head_commit_sha"]
                        current_sha = fetch_pr_head_sha(owner, repo, item["pr_number"])
                        if current_sha and last_reviewed_sha:
                            has_new_commits = current_sha != last_reviewed_sha
            else:
                pr_state = item.get("pr_state")  # Fall back to stored state

            queue.append({
                "id": item["id"],
                "number": item["pr_number"],
                "title": item["pr_title"],
                "url": item["pr_url"],
                "author": item["pr_author"],
                "additions": item["additions"],
                "deletions": item["deletions"],
                "repo": item["repo"],
                "addedAt": item["added_at"],
                "notesCount": notes_count,
                "prState": pr_state or item.get("pr_state"),
                "hasNewCommits": has_new_commits,
                "lastReviewedSha": last_reviewed_sha,
                "currentSha": current_sha,
                "hasReview": has_review,
                "reviewScore": review_score,
                "reviewId": review_id,
                "inlineCommentsPosted": inline_comments_posted
            })
        return jsonify({"queue": queue})
    except Exception as e:
        logger.error(f"Error getting merge queue: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/merge-queue", methods=["POST"])
def add_to_merge_queue():
    """Add a PR to the merge queue."""
    try:
        pr_data = request.get_json()
        if not pr_data:
            return jsonify({"error": "No data provided"}), 400

        required_fields = ["number", "title", "url", "author", "repo"]
        for field in required_fields:
            if field not in pr_data:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        # Fetch current PR state
        repo_parts = pr_data["repo"].split("/")
        pr_state = None
        if len(repo_parts) == 2:
            pr_state = fetch_pr_state(repo_parts[0], repo_parts[1], pr_data["number"])

        # Add to database
        item = queue_db.add_to_queue(
            pr_number=pr_data["number"],
            repo=pr_data["repo"],
            pr_title=pr_data["title"],
            pr_author=pr_data["author"],
            pr_url=pr_data["url"],
            additions=pr_data.get("additions", 0),
            deletions=pr_data.get("deletions", 0),
            pr_state=pr_state
        )

        # Convert to expected format
        queue_item = {
            "id": item["id"],
            "number": item["pr_number"],
            "title": item["pr_title"],
            "url": item["pr_url"],
            "author": item["pr_author"],
            "additions": item["additions"],
            "deletions": item["deletions"],
            "repo": item["repo"],
            "addedAt": item["added_at"],
            "notesCount": 0,
            "prState": pr_state
        }

        return jsonify({"message": "PR added to queue", "item": queue_item}), 201

    except ValueError as e:
        # PR already in queue
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        logger.error(f"Error adding to merge queue: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/merge-queue/<int:pr_number>", methods=["DELETE"])
def remove_from_merge_queue(pr_number):
    """Remove a PR from the merge queue."""
    try:
        repo = request.args.get("repo")
        removed = queue_db.remove_from_queue(pr_number, repo)

        if not removed:
            return jsonify({"error": "PR not found in queue"}), 404

        return jsonify({"message": "PR removed from queue"})

    except Exception as e:
        logger.error(f"Error removing from merge queue: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/merge-queue/reorder", methods=["POST"])
def reorder_merge_queue():
    """Reorder items in the merge queue."""
    try:
        order_data = request.get_json()
        if not order_data or "order" not in order_data:
            return jsonify({"error": "No order provided"}), 400

        order = order_data["order"]  # List of {number, repo} objects
        queue_items = queue_db.reorder_queue(order)

        # Convert to expected format
        new_queue = []
        for item in queue_items:
            new_queue.append({
                "number": item["pr_number"],
                "title": item["pr_title"],
                "url": item["pr_url"],
                "author": item["pr_author"],
                "additions": item["additions"],
                "deletions": item["deletions"],
                "repo": item["repo"],
                "addedAt": item["added_at"]
            })

        return jsonify({"message": "Queue reordered", "queue": new_queue})

    except Exception as e:
        logger.error(f"Error reordering merge queue: {e}")
        return jsonify({"error": str(e)}), 500


# Merge Queue Notes Endpoints

@app.route("/api/merge-queue/<int:pr_number>/notes", methods=["GET"])
def get_queue_notes(pr_number):
    """Get all notes for a queue item."""
    try:
        repo = request.args.get("repo")
        if not repo:
            return jsonify({"error": "repo parameter required"}), 400

        # Get queue item ID
        queue_item_id = queue_db.get_queue_item_id(pr_number, repo)
        if not queue_item_id:
            return jsonify({"error": "PR not found in queue"}), 404

        notes = queue_db.get_notes(queue_item_id)

        # Format notes for response
        formatted_notes = []
        for note in notes:
            formatted_notes.append({
                "id": note["id"],
                "content": note["content"],
                "createdAt": note["created_at"]
            })

        return jsonify({"notes": formatted_notes})

    except Exception as e:
        logger.error(f"Error getting queue notes: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/merge-queue/<int:pr_number>/notes", methods=["POST"])
def add_queue_note(pr_number):
    """Add a note to a queue item."""
    try:
        repo = request.args.get("repo")
        if not repo:
            return jsonify({"error": "repo parameter required"}), 400

        data = request.get_json()
        if not data or "content" not in data:
            return jsonify({"error": "content is required"}), 400

        content = data["content"].strip()
        if not content:
            return jsonify({"error": "content cannot be empty"}), 400

        # Get queue item ID
        queue_item_id = queue_db.get_queue_item_id(pr_number, repo)
        if not queue_item_id:
            return jsonify({"error": "PR not found in queue"}), 404

        note = queue_db.add_note(queue_item_id, content)

        return jsonify({
            "message": "Note added",
            "note": {
                "id": note["id"],
                "content": note["content"],
                "createdAt": note["created_at"]
            }
        }), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(f"Error adding queue note: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/merge-queue/notes/<int:note_id>", methods=["DELETE"])
def delete_queue_note(note_id):
    """Delete a note from a queue item."""
    try:
        deleted = queue_db.delete_note(note_id)
        if not deleted:
            return jsonify({"error": "Note not found"}), 404

        return jsonify({"message": "Note deleted"})

    except Exception as e:
        logger.error(f"Error deleting queue note: {e}")
        return jsonify({"error": str(e)}), 500


# Review History Endpoints

@app.route("/api/review-history", methods=["GET"])
def get_review_history():
    """List reviews with optional filtering."""
    try:
        repo = request.args.get("repo")
        author = request.args.get("author")
        pr_number = request.args.get("pr_number", type=int)
        search = request.args.get("search")
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)

        if search:
            reviews = reviews_db.search_reviews(search, limit=limit)
        else:
            reviews = reviews_db.list_reviews(
                repo=repo,
                author=author,
                pr_number=pr_number,
                limit=limit,
                offset=offset
            )

        # Format for frontend - use stored pr_state_at_review to avoid slow API calls
        formatted = []
        for review in reviews:
            formatted.append({
                "id": review["id"],
                "pr_number": review["pr_number"],
                "repo": review["repo"],
                "pr_title": review["pr_title"],
                "pr_author": review["pr_author"],
                "pr_url": review["pr_url"],
                "review_timestamp": review["review_timestamp"],
                "status": review["status"],
                "score": review["score"],
                "is_followup": review["is_followup"],
                "parent_review_id": review["parent_review_id"],
                "head_commit_sha": review.get("head_commit_sha"),
                "inline_comments_posted": review.get("inline_comments_posted", False),
                "pr_state": review.get("pr_state_at_review")
            })

        return jsonify({"reviews": formatted})

    except Exception as e:
        logger.error(f"Error getting review history: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/review-history/<int:review_id>", methods=["GET"])
def get_review_detail(review_id):
    """Get a single review with full content."""
    try:
        review = reviews_db.get_review(review_id)
        if not review:
            return jsonify({"error": "Review not found"}), 404

        return jsonify({"review": dict(review)})

    except Exception as e:
        logger.error(f"Error getting review {review_id}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/review-history/pr/<owner>/<repo>/<int:pr_number>", methods=["GET"])
def get_pr_reviews(owner, repo, pr_number):
    """Get all reviews for a specific PR (review chain)."""
    try:
        full_repo = f"{owner}/{repo}"
        reviews = reviews_db.get_reviews_for_pr(full_repo, pr_number)

        # Format for frontend
        formatted = []
        for review in reviews:
            formatted.append({
                "id": review["id"],
                "pr_number": review["pr_number"],
                "repo": review["repo"],
                "pr_title": review["pr_title"],
                "pr_author": review["pr_author"],
                "pr_url": review["pr_url"],
                "review_timestamp": review["review_timestamp"],
                "status": review["status"],
                "score": review["score"],
                "content": review["content"],
                "is_followup": review["is_followup"],
                "parent_review_id": review["parent_review_id"]
            })

        return jsonify({"reviews": formatted})

    except Exception as e:
        logger.error(f"Error getting reviews for PR #{pr_number}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/review-history/stats", methods=["GET"])
def get_review_stats():
    """Get review statistics."""
    try:
        stats = reviews_db.get_review_stats()
        return jsonify({"stats": stats})

    except Exception as e:
        logger.error(f"Error getting review stats: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/review-history/check/<owner>/<repo>/<int:pr_number>", methods=["GET"])
def check_pr_review_exists(owner, repo, pr_number):
    """Check if a PR has been reviewed and get latest review info."""
    try:
        full_repo = f"{owner}/{repo}"
        latest_review = reviews_db.get_latest_review_for_pr(full_repo, pr_number)

        if latest_review:
            return jsonify({
                "has_review": True,
                "latest_review": {
                    "id": latest_review["id"],
                    "score": latest_review["score"],
                    "review_timestamp": latest_review["review_timestamp"],
                    "is_followup": latest_review["is_followup"],
                    "head_commit_sha": latest_review.get("head_commit_sha"),
                    "inline_comments_posted": latest_review.get("inline_comments_posted", False)
                }
            })
        else:
            return jsonify({"has_review": False})

    except Exception as e:
        logger.error(f"Error checking review for PR #{pr_number}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/reviews/check-new-commits/<owner>/<repo>/<int:pr_number>", methods=["GET"])
def check_new_commits(owner, repo, pr_number):
    """Check if a PR has new commits since the last review.

    Returns:
        has_new_commits: bool
        last_reviewed_sha: str (or null if no review found)
        current_sha: str (or null if PR not found)
    """
    try:
        full_repo = f"{owner}/{repo}"
        latest_review = reviews_db.get_latest_review_for_pr(full_repo, pr_number)

        last_reviewed_sha = None
        if latest_review:
            last_reviewed_sha = latest_review.get("head_commit_sha")

        # Fetch current PR head SHA
        current_sha = fetch_pr_head_sha(owner, repo, pr_number)

        # Determine if there are new commits
        has_new_commits = False
        if last_reviewed_sha and current_sha:
            has_new_commits = last_reviewed_sha != current_sha
        elif current_sha and not last_reviewed_sha:
            # No previous review or SHA not tracked - assume new
            has_new_commits = True if latest_review else False

        return jsonify({
            "has_new_commits": has_new_commits,
            "last_reviewed_sha": last_reviewed_sha,
            "current_sha": current_sha
        })

    except Exception as e:
        logger.error(f"Error checking new commits for PR #{pr_number}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/reviews/<int:review_id>/post-inline-comments", methods=["POST"])
def post_inline_comments(review_id):
    """Post critical issues from a review as inline PR comments.

    Parses critical issues from the review content and posts them as
    inline comments on the PR using the GitHub API.
    """
    try:
        # Get the review from database
        review = reviews_db.get_review(review_id)
        if not review:
            return jsonify({"error": "Review not found"}), 404

        # Check if already posted
        if review.get("inline_comments_posted"):
            return jsonify({"error": "Inline comments have already been posted for this review"}), 409

        content = review.get("content")
        if not content:
            return jsonify({"error": "Review has no content to parse"}), 400

        # Parse critical issues from content
        issues = parse_critical_issues(content)
        if not issues:
            return jsonify({"error": "No critical issues found in review content", "issues_found": 0}), 400

        # Get PR info
        repo = review.get("repo")
        pr_number = review.get("pr_number")

        if not repo or not pr_number:
            return jsonify({"error": "Review is missing repo or PR number"}), 400

        repo_parts = repo.split("/")
        if len(repo_parts) != 2:
            return jsonify({"error": f"Invalid repo format: {repo}"}), 400

        owner, repo_name = repo_parts

        # Fetch current PR head SHA (required for posting review)
        current_sha = fetch_pr_head_sha(owner, repo_name, pr_number)
        if not current_sha:
            return jsonify({"error": "Could not fetch PR head commit SHA"}), 500

        # Build the review comments
        comments = []
        for issue in issues:
            comment = {
                "path": issue["path"],
                "body": issue["body"]
            }
            # Use single line if start == end, otherwise use multi-line
            if issue["start_line"] == issue["end_line"]:
                comment["line"] = issue["end_line"]
            else:
                comment["start_line"] = issue["start_line"]
                comment["line"] = issue["end_line"]

            comments.append(comment)

        # Post the review with inline comments using gh api
        # Build the request body
        review_body = {
            "commit_id": current_sha,
            "event": "COMMENT",
            "body": f"**Code Review Critical Issues** ({len(issues)} issue(s) flagged)",
            "comments": comments
        }

        try:
            # Use gh api to post the review
            result = subprocess.run(
                [
                    "gh", "api",
                    f"repos/{owner}/{repo_name}/pulls/{pr_number}/reviews",
                    "--method", "POST",
                    "--input", "-"
                ],
                input=json.dumps(review_body),
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"Posted inline comments for review {review_id}: {result.stdout[:200]}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to post inline comments: {e.stderr}")
            return jsonify({
                "error": f"Failed to post comments to GitHub: {e.stderr}",
                "issues_parsed": len(issues)
            }), 500

        # Update the review in database
        reviews_db.update_inline_comments_posted(review_id, True)

        return jsonify({
            "message": "Inline comments posted successfully",
            "issues_posted": len(issues),
            "comments": [{"path": c["path"], "line": c.get("line")} for c in comments]
        })

    except Exception as e:
        logger.error(f"Error posting inline comments for review {review_id}: {e}")
        return jsonify({"error": str(e)}), 500


# User Settings Endpoints

@app.route("/api/settings", methods=["GET"])
def get_all_settings():
    """Get all user settings."""
    try:
        settings = settings_db.get_all_settings()
        return jsonify({"settings": settings})
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/settings/<key>", methods=["GET"])
def get_setting(key):
    """Get a specific setting by key."""
    try:
        value = settings_db.get_setting(key)
        if value is None:
            return jsonify({"error": "Setting not found"}), 404
        return jsonify({"key": key, "value": value})
    except Exception as e:
        logger.error(f"Error getting setting {key}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/settings/<key>", methods=["PUT", "POST"])
def set_setting(key):
    """Set a setting value."""
    try:
        data = request.get_json()
        if data is None or "value" not in data:
            return jsonify({"error": "Missing 'value' in request body"}), 400

        settings_db.set_setting(key, data["value"])
        return jsonify({"key": key, "value": data["value"], "message": "Setting saved"})
    except Exception as e:
        logger.error(f"Error setting {key}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/settings/<key>", methods=["DELETE"])
def delete_setting(key):
    """Delete a setting."""
    try:
        deleted = settings_db.delete_setting(key)
        if not deleted:
            return jsonify({"error": "Setting not found"}), 404
        return jsonify({"message": "Setting deleted"})
    except Exception as e:
        logger.error(f"Error deleting setting {key}: {e}")
        return jsonify({"error": str(e)}), 500


# Code Review Endpoints

def _save_review_to_db(key, review, status):
    """Save a completed/failed review to the database."""
    try:
        parts = key.split("/")
        if len(parts) >= 3:
            owner = parts[0]
            repo = parts[1]
            pr_number = int(parts[2])
            full_repo = f"{owner}/{repo}"

            # Read review content from file if completed
            content = None
            review_file = review.get("review_file")
            if status == "completed" and review_file:
                try:
                    review_path = Path(review_file)
                    if review_path.exists():
                        content = review_path.read_text(encoding='utf-8')
                except Exception as e:
                    logger.warning(f"Could not read review file {review_file}: {e}")

            # Get PR info from review data
            pr_url = review.get("pr_url", "")
            pr_title = review.get("pr_title")
            pr_author = review.get("pr_author")
            is_followup = review.get("is_followup", False)
            parent_review_id = review.get("parent_review_id")

            # Extract title from content H1 header if not already set
            if not pr_title and content:
                h1_match = re.search(r'^#\s+(.+?)$', content, re.MULTILINE)
                if h1_match:
                    pr_title = h1_match.group(1).strip()
                else:
                    # Fallback to generic title
                    pr_title = f"PR #{pr_number} Review"

            # Fetch current head commit SHA and PR state
            head_commit_sha = fetch_pr_head_sha(owner, repo, pr_number)
            pr_state_at_review = fetch_pr_state(owner, repo, pr_number)

            # Save to database
            reviews_db.save_review(
                pr_number=pr_number,
                repo=full_repo,
                pr_title=pr_title,
                pr_author=pr_author,
                pr_url=pr_url,
                status=status,
                review_file_path=review_file,
                content=content,
                is_followup=is_followup,
                parent_review_id=parent_review_id,
                head_commit_sha=head_commit_sha,
                pr_state_at_review=pr_state_at_review
            )
            logger.info(f"Saved review to database for {key}")
    except Exception as e:
        logger.error(f"Failed to save review to database for {key}: {e}")


def _check_review_status(key):
    """Check and update the status of a review process."""
    with reviews_lock:
        if key not in active_reviews:
            return None
        review = active_reviews[key]
        process = review.get("process")
        if process and review["status"] == "running":
            exit_code = process.poll()
            if exit_code is not None:
                # Capture any remaining output
                try:
                    stdout, stderr = process.communicate(timeout=1)
                    if stderr:
                        review["error_output"] = stderr.strip()[-2000:]  # Keep last 2000 chars
                    if stdout:
                        review["stdout"] = stdout.strip()[-500:]  # Keep last 500 chars
                except subprocess.TimeoutExpired:
                    pass
                except Exception as e:
                    logger.error(f"Error reading process output for {key}: {e}")

                status = "completed" if exit_code == 0 else "failed"
                review["status"] = status
                review["exit_code"] = exit_code
                review["completed_at"] = datetime.now(timezone.utc).isoformat()

                if exit_code == 0:
                    logger.info(f"Review completed successfully: {key}")
                else:
                    error_msg = review.get("error_output", "Unknown error")
                    logger.error(f"Review failed: {key} (exit code: {exit_code})\nError: {error_msg}")

                # Save to database
                _save_review_to_db(key, review, status)

        return review


def _start_review_process(pr_url, owner, repo, pr_number, is_followup=False, previous_review_content=None):
    """Start a Claude CLI review process in the background.

    Args:
        pr_url: URL of the pull request
        owner: Repository owner
        repo: Repository name
        pr_number: PR number
        is_followup: Whether this is a follow-up review
        previous_review_content: Content of previous review for follow-up context
    """
    # Ensure reviews directory exists
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)

    # Build review file path
    repo_safe = repo.replace("/", "-")
    suffix = "-followup" if is_followup else ""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S") if is_followup else ""
    if is_followup:
        review_file = REVIEWS_DIR / f"{owner}-{repo_safe}-pr-{pr_number}{suffix}-{timestamp}.md"
    else:
        review_file = REVIEWS_DIR / f"{owner}-{repo_safe}-pr-{pr_number}.md"

    # Build the prompt
    if is_followup and previous_review_content:
        prompt = (
            f"Review PR #{pr_number} at {pr_url}. "
            f"This is a FOLLOW-UP review. Here is the previous review for context:\n\n"
            f"---PREVIOUS REVIEW---\n{previous_review_content[:8000]}\n---END PREVIOUS REVIEW---\n\n"
            f"Focus on: changes since last review, whether previous issues were addressed. "
            f"Use the code-reviewer agent. "
            f"Write the review to {review_file} "
            f"IMPORTANT: Include a final score from 0-10 in the review."
        )
    else:
        prompt = (
            f"Review PR #{pr_number} at {pr_url}. "
            f"Use the code-reviewer agent. "
            f"Write the review to {review_file} "
            f"IMPORTANT: Include a final score from 0-10 in the review."
        )

    # Build the command
    cmd = [
        "claude",
        "-p", prompt,
        "--allowedTools", "Bash(git*),Bash(gh*),Read,Glob,Grep,Write,Task",
        "--dangerously-skip-permissions"
    ]

    review_type = "follow-up " if is_followup else ""
    logger.info(f"Starting {review_type}review for PR #{pr_number} ({owner}/{repo})")
    logger.debug(f"Review command: {' '.join(cmd)}")

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        logger.info(f"Review process started with PID {process.pid} for {owner}/{repo}/#{pr_number}")
        return process, str(review_file), is_followup
    except FileNotFoundError:
        error_msg = "Claude CLI not found. Please ensure 'claude' is installed and in PATH."
        logger.error(f"Failed to start review: {error_msg}")
        return None, error_msg, is_followup
    except Exception as e:
        logger.error(f"Failed to start review process: {e}")
        return None, str(e), is_followup


@app.route("/api/reviews", methods=["GET"])
def get_reviews():
    """Get all active/recent reviews with updated statuses."""
    reviews_list = []
    with reviews_lock:
        for key, review in active_reviews.items():
            # Check process status
            process = review.get("process")
            if process and review["status"] == "running":
                exit_code = process.poll()
                if exit_code is not None:
                    # Capture any remaining output
                    try:
                        stdout, stderr = process.communicate(timeout=1)
                        if stderr:
                            review["error_output"] = stderr.strip()[-2000:]
                        if stdout:
                            review["stdout"] = stdout.strip()[-500:]
                    except subprocess.TimeoutExpired:
                        pass
                    except Exception as e:
                        logger.error(f"Error reading process output for {key}: {e}")

                    status = "completed" if exit_code == 0 else "failed"
                    review["status"] = status
                    review["exit_code"] = exit_code
                    review["completed_at"] = datetime.now(timezone.utc).isoformat()

                    if exit_code == 0:
                        logger.info(f"Review completed successfully: {key}")
                    else:
                        error_msg = review.get("error_output", "Unknown error")
                        logger.error(f"Review failed: {key} (exit code: {exit_code})\nError: {error_msg}")

                    # Save to database
                    _save_review_to_db(key, review, status)

            # Build response (exclude process object)
            parts = key.split("/")
            reviews_list.append({
                "key": key,
                "owner": parts[0] if len(parts) >= 1 else "",
                "repo": parts[1] if len(parts) >= 2 else "",
                "pr_number": int(parts[2]) if len(parts) >= 3 else 0,
                "status": review["status"],
                "started_at": review.get("started_at", ""),
                "completed_at": review.get("completed_at", ""),
                "pr_url": review.get("pr_url", ""),
                "review_file": review.get("review_file", ""),
                "exit_code": review.get("exit_code"),
                "error_output": review.get("error_output", ""),
                "is_followup": review.get("is_followup", False)
            })

    return jsonify({"reviews": reviews_list})


@app.route("/api/reviews", methods=["POST"])
def start_review():
    """Start a new code review for a PR.

    Supports follow-up reviews with context from previous reviews.
    Pass 'is_followup': true and optionally 'previous_review_id' to do a follow-up.
    """
    try:
        data = request.get_json()
        if not data:
            logger.warning("Review request received with no data")
            return jsonify({"error": "No data provided"}), 400

        required_fields = ["number", "url", "owner", "repo"]
        for field in required_fields:
            if field not in data:
                logger.warning(f"Review request missing required field: {field}")
                return jsonify({"error": f"Missing required field: {field}"}), 400

        pr_number = data["number"]
        pr_url = data["url"]
        owner = data["owner"]
        repo = data["repo"]
        key = f"{owner}/{repo}/{pr_number}"

        # Check for follow-up review
        is_followup = data.get("is_followup", False)
        previous_review_id = data.get("previous_review_id")
        pr_title = data.get("title")
        pr_author = data.get("author")

        logger.info(f"Received {'follow-up ' if is_followup else ''}review request for {key}")

        # Check if review is already running
        with reviews_lock:
            if key in active_reviews:
                existing = active_reviews[key]
                if existing["status"] == "running":
                    logger.warning(f"Review already in progress for {key}")
                    return jsonify({"error": "Review already in progress for this PR"}), 409

        # Get previous review content for follow-up
        previous_review_content = None
        parent_id = None
        if is_followup:
            full_repo = f"{owner}/{repo}"
            if previous_review_id:
                # Get specific review
                prev_review = reviews_db.get_review(previous_review_id)
                if prev_review:
                    previous_review_content = prev_review.get("content")
                    parent_id = previous_review_id
            else:
                # Get latest review for this PR
                prev_review = reviews_db.get_latest_review_for_pr(full_repo, pr_number)
                if prev_review:
                    previous_review_content = prev_review.get("content")
                    parent_id = prev_review.get("id")

            if not previous_review_content:
                logger.warning(f"No previous review found for follow-up, proceeding as normal review")
                is_followup = False

        # Start the review process
        process, result, is_followup = _start_review_process(
            pr_url, owner, repo, pr_number,
            is_followup=is_followup,
            previous_review_content=previous_review_content
        )

        if process is None:
            logger.error(f"Failed to start review for {key}: {result}")
            return jsonify({"error": result}), 500

        # Store the review
        with reviews_lock:
            active_reviews[key] = {
                "process": process,
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "pr_url": pr_url,
                "review_file": result,
                "is_followup": is_followup,
                "parent_review_id": parent_id,
                "pr_title": pr_title,
                "pr_author": pr_author
            }

        return jsonify({
            "message": "Review started",
            "key": key,
            "status": "running",
            "review_file": result,
            "is_followup": is_followup
        }), 201

    except Exception as e:
        logger.exception(f"Unexpected error starting review: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/reviews/<owner>/<repo>/<int:pr_number>", methods=["DELETE"])
def cancel_review(owner, repo, pr_number):
    """Cancel/terminate a running review."""
    key = f"{owner}/{repo}/{pr_number}"
    logger.info(f"Received cancel request for review: {key}")

    with reviews_lock:
        if key not in active_reviews:
            logger.warning(f"Cancel request for non-existent review: {key}")
            return jsonify({"error": "Review not found"}), 404

        review = active_reviews[key]
        process = review.get("process")

        if process and review["status"] == "running":
            try:
                logger.info(f"Terminating review process (PID {process.pid}) for {key}")
                process.terminate()
                # Give it a moment to terminate gracefully
                try:
                    process.wait(timeout=2)
                    logger.info(f"Review process terminated gracefully for {key}")
                except subprocess.TimeoutExpired:
                    process.kill()
                    logger.warning(f"Review process killed (did not terminate gracefully) for {key}")
                review["status"] = "cancelled"
            except Exception as e:
                logger.error(f"Failed to terminate review process for {key}: {e}")
                return jsonify({"error": f"Failed to terminate process: {e}"}), 500

        # Remove from active reviews
        del active_reviews[key]
        logger.info(f"Review cancelled and removed: {key}")

    return jsonify({"message": "Review cancelled", "key": key})


@app.route("/api/reviews/<owner>/<repo>/<int:pr_number>/status", methods=["GET"])
def get_review_status_endpoint(owner, repo, pr_number):
    """Get the status of a specific review."""
    key = f"{owner}/{repo}/{pr_number}"

    review = _check_review_status(key)
    if review is None:
        return jsonify({"error": "Review not found"}), 404

    return jsonify({
        "key": key,
        "status": review["status"],
        "started_at": review.get("started_at", ""),
        "completed_at": review.get("completed_at", ""),
        "pr_url": review.get("pr_url", ""),
        "review_file": review.get("review_file", ""),
        "exit_code": review.get("exit_code"),
        "error_output": review.get("error_output", "")
    })


if __name__ == "__main__":
    app.run(
        host=config.get("host", "127.0.0.1"),
        port=config.get("port", 5050),
        debug=config.get("debug", False),
    )
