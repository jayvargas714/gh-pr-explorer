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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory

from database import get_database, get_reviews_db, get_queue_db, get_settings_db, get_dev_stats_db, get_lifecycle_cache_db, get_workflow_cache_db, get_contributor_ts_cache_db, get_code_activity_cache_db

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
workflow_cache_db = get_workflow_cache_db()
contributor_ts_cache_db = get_contributor_ts_cache_db()
code_activity_cache_db = get_code_activity_cache_db()

# Workflow cache background refresh tracking
_workflow_refresh_in_progress = set()
_workflow_refresh_lock = threading.Lock()

# Contributor timeseries cache background refresh tracking
_contributor_ts_refresh_in_progress = set()
_contributor_ts_refresh_lock = threading.Lock()

# Code activity cache background refresh tracking
_activity_refresh_in_progress = set()
_activity_refresh_lock = threading.Lock()

# Simple in-memory cache
cache = {}


def cached(ttl_seconds=None):
    """Decorator for caching function results."""
    if ttl_seconds is None:
        ttl_seconds = config.get("cache_ttl_seconds", 300)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            qs = request.query_string.decode() if request else ''
            cache_key = f"{func.__name__}:{args}:{sorted(kwargs.items())}:{qs}"
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


def fetch_github_stats_api(owner, repo, endpoint, jq_query=None, max_retries=3, retry_delay=2):
    """Fetch data from GitHub's stats API with 202-retry logic.

    GitHub stats endpoints return 202 while computing results. This helper
    retries with a delay until data is ready or max retries are exhausted.

    Args:
        owner: Repository owner
        repo: Repository name
        endpoint: Stats endpoint path (e.g., 'stats/contributors')
        jq_query: Optional jq query for processing the response
        max_retries: Maximum number of retry attempts
        retry_delay: Seconds between retries

    Returns:
        Parsed JSON result, or empty list if unavailable.
    """
    for attempt in range(max_retries):
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{owner}/{repo}/{endpoint}", "-i"],
                capture_output=True,
                text=True,
                check=False,
            )

            if "HTTP/2.0 202" in result.stdout or "202 Accepted" in result.stdout:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                else:
                    return []

            args = ["api", f"repos/{owner}/{repo}/{endpoint}"]
            if jq_query:
                args.extend(["--jq", jq_query])

            output = run_gh_command(args)
            parsed = parse_json_output(output)
            if parsed:
                return parsed

            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue

        except RuntimeError:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            return []

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


def fetch_pr_state_and_sha(owner, repo, pr_number):
    """Fetch PR state and head SHA in a single gh call.

    Returns:
        tuple: (state, head_sha) — either may be None on error.
    """
    try:
        output = run_gh_command([
            "pr", "view", str(pr_number),
            "-R", f"{owner}/{repo}",
            "--json", "state,headRefOid",
        ])
        data = parse_json_output(output)
        if isinstance(data, dict):
            state = data.get("state", "").upper() or None
            sha = data.get("headRefOid") or None
            return state, sha
        return None, None
    except RuntimeError as e:
        logger.warning(f"Failed to fetch PR state/SHA for {owner}/{repo}#{pr_number}: {e}")
        return None, None


def _parse_location(location):
    """Parse a location string into (file_path, start_line, end_line) or None.

    Handles multiple formats produced by code reviews:
      - path/to/file.py:123-456
      - path/to/file.py:123
      - `path/to/file.py`:123-456
      - `path/to/file.py` (description, approximately line 123-456 ...)
      - `path/to/file.py`, function `foo` (approximately lines 123-456 ...)
    """
    if not location:
        return None

    # Strategy 1: Classic format - file.py:123-456 or `file.py`:123-456
    # Strip backticks from path portion
    loc_match = re.match(r'`?([^`:\s]+)`?\s*:\s*(\d+)(?:\s*-\s*(\d+))?', location)
    if loc_match:
        file_path = loc_match.group(1).strip()
        start_line = int(loc_match.group(2))
        end_line = int(loc_match.group(3)) if loc_match.group(3) else start_line
        return file_path, start_line, end_line

    # Strategy 2: `file.py` followed by "line(s) N-M" or "line N" somewhere in the string
    path_match = re.match(r'`([^`]+)`', location)
    if path_match:
        file_path = path_match.group(1).strip()
        # Look for line numbers: "line 123-456", "lines 123-456", "line 123"
        line_match = re.search(r'lines?\s+(\d+)\s*[-–]\s*(\d+)', location)
        if line_match:
            return file_path, int(line_match.group(1)), int(line_match.group(2))
        line_match = re.search(r'line\s+(\d+)', location)
        if line_match:
            line_num = int(line_match.group(1))
            return file_path, line_num, line_num

    return None


def _extract_issue_field(content, field_name):
    """Extract a field's full content from an issue block.

    Captures everything after '- FieldName: ' until the next '- FieldName:' line
    or end of content. This correctly handles multiline values including code blocks.
    """
    pattern = re.compile(
        rf'-\s*{field_name}:\s*(.*?)(?=\n-\s*(?:Location|Problem|Fix):|\Z)',
        re.DOTALL
    )
    match = pattern.search(content)
    if match:
        return match.group(1).strip()
    return None


def parse_critical_issues(content):
    """Parse critical issues from review markdown content.

    Expected format:
    **Critical Issues**
    **1. Issue Title**
    - Location: path/to/file.py:123-456 or `path/to/file.py` (approx line 123-456)
    - Problem: Description (may span multiple lines)
    - Fix: Solution (may span multiple lines with code blocks)

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

    # Split into individual issues by **N. Title** headers
    issue_headers = list(re.finditer(r'\*\*(\d+)\.\s*(.+?)\*\*', critical_section))

    for idx, header_match in enumerate(issue_headers):
        title = header_match.group(2).strip()

        # Get content between this header and the next (or end of section)
        start = header_match.end()
        end = issue_headers[idx + 1].start() if idx + 1 < len(issue_headers) else len(critical_section)
        issue_content = critical_section[start:end]

        # Extract fields - each captures everything until the next field or end
        location = _extract_issue_field(issue_content, 'Location')
        problem = _extract_issue_field(issue_content, 'Problem')
        fix = _extract_issue_field(issue_content, 'Fix')

        if not location:
            continue

        parsed = _parse_location(location)
        if not parsed:
            continue

        file_path, start_line, end_line = parsed

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
    """Serve the React frontend. Run 'npm run build' in frontend/ first."""
    return send_from_directory(Path(__file__).parent / "frontend" / "dist", "index.html")


@app.route("/assets/<path:filename>")
def serve_frontend_assets(filename):
    """Serve static assets from the React build."""
    return send_from_directory(Path(__file__).parent / "frontend" / "dist" / "assets", filename)


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

        # Post-filter by draft status (gh search qualifier draft: is unreliable)
        if draft == "true":
            prs = [pr for pr in prs if pr.get("isDraft", False)]
        elif draft == "false":
            prs = [pr for pr in prs if not pr.get("isDraft", False)]

        # Post-process: add review status and CI status summaries
        for pr in prs:
            pr["reviewStatus"] = get_review_status(pr.get("reviewDecision"))
            pr["ciStatus"] = get_ci_status(pr.get("statusCheckRollup"))

        return jsonify({"prs": prs})

    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/repos/<owner>/<repo>/prs/divergence", methods=["POST"])
def get_pr_divergence(owner, repo):
    """Batch fetch branch divergence (ahead/behind) for open PRs."""
    try:
        data = request.get_json()
        if not data or "prs" not in data:
            return jsonify({"error": "Missing 'prs' in request body"}), 400

        pr_list = data["prs"]

        def fetch_one(pr_info):
            number = pr_info["number"]
            base = pr_info["base"]
            head = pr_info["head"]
            try:
                output = run_gh_command([
                    "api", f"repos/{owner}/{repo}/compare/{base}...{head}",
                    "--jq", '{"status": .status, "ahead_by": .ahead_by, "behind_by": .behind_by}'
                ])
                result = parse_json_output(output)
                if result:
                    return (number, result)
            except RuntimeError:
                pass
            return (number, None)

        divergence = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(fetch_one, pr) for pr in pr_list]
            for future in futures:
                number, result = future.result()
                if result:
                    divergence[str(number)] = result

        return jsonify({"divergence": divergence})

    except Exception as e:
        logger.error(f"Failed to fetch divergence: {e}")
        return jsonify({"error": str(e)}), 500


def _fetch_workflow_data(owner, repo):
    """Fetch unfiltered workflow runs in parallel batches.

    Returns dict with keys: runs, workflows, all_time_total
    """
    max_runs = config.get("workflow_cache_max_runs", 1000)
    max_pages = max_runs // 100

    base_url = f"repos/{owner}/{repo}/actions/runs?per_page=100"
    jq_query = (
        "[.workflow_runs[] | {"
        "id, name, display_title, status, conclusion, "
        "created_at, updated_at, event, head_branch, "
        "run_attempt, run_number, html_url, "
        "actor_login: .actor.login, "
        "workflow_id: .workflow_id"
        "}]"
    )

    def fetch_page(page_num):
        """Fetch a single page of workflow runs."""
        try:
            output = run_gh_command(["api", f"{base_url}&page={page_num}", "--jq", jq_query])
            return parse_json_output(output) or []
        except RuntimeError:
            return []

    def fetch_workflows():
        """Fetch the workflows list."""
        try:
            wf_output = run_gh_command([
                "api", f"repos/{owner}/{repo}/actions/workflows",
                "--jq", "[.workflows[] | {id, name, state, path}]"
            ])
            return parse_json_output(wf_output) or []
        except RuntimeError:
            return []

    def fetch_total_count():
        """Fetch unfiltered all-time total count."""
        try:
            count_output = run_gh_command([
                "api", f"repos/{owner}/{repo}/actions/runs?per_page=1&page=1",
                "--jq", ".total_count"
            ])
            return int(count_output.strip()) if count_output.strip() else 0
        except (RuntimeError, ValueError):
            return 0

    runs = []
    workflows = []
    all_time_total = 0

    # Batch 1: workflows + total count + pages 1-3 in parallel
    batch1_pages = min(3, max_pages)
    with ThreadPoolExecutor(max_workers=5) as executor:
        wf_future = executor.submit(fetch_workflows)
        count_future = executor.submit(fetch_total_count)
        page_futures = {executor.submit(fetch_page, p): p for p in range(1, batch1_pages + 1)}

        workflows = wf_future.result()
        all_time_total = count_future.result()

        # Collect page results in order
        page_results = {}
        for future in page_futures:
            page_num = page_futures[future]
            page_results[page_num] = future.result()

    # Process batch 1 results in order, stop if a page returned < 100
    needs_more = True
    for p in range(1, batch1_pages + 1):
        page_runs = page_results.get(p, [])
        runs.extend(page_runs)
        if len(page_runs) < 100:
            needs_more = False
            break

    # Batch 2: pages 4-8 if all batch 1 pages returned 100
    if needs_more and max_pages > 3:
        batch2_end = min(8, max_pages)
        with ThreadPoolExecutor(max_workers=5) as executor:
            page_futures = {executor.submit(fetch_page, p): p for p in range(4, batch2_end + 1)}
            page_results = {}
            for future in page_futures:
                page_num = page_futures[future]
                page_results[page_num] = future.result()

        for p in range(4, batch2_end + 1):
            page_runs = page_results.get(p, [])
            runs.extend(page_runs)
            if len(page_runs) < 100:
                needs_more = False
                break

    # Batch 3: pages 9-10 if still needed
    if needs_more and max_pages > 8:
        batch3_end = min(10, max_pages)
        with ThreadPoolExecutor(max_workers=5) as executor:
            page_futures = {executor.submit(fetch_page, p): p for p in range(9, batch3_end + 1)}
            page_results = {}
            for future in page_futures:
                page_num = page_futures[future]
                page_results[page_num] = future.result()

        for p in range(9, batch3_end + 1):
            page_runs = page_results.get(p, [])
            runs.extend(page_runs)
            if len(page_runs) < 100:
                break

    # Pre-compute duration_seconds on each run before caching
    for run in runs:
        created = run.get("created_at")
        updated = run.get("updated_at")
        if created and updated:
            try:
                c = datetime.fromisoformat(created.replace("Z", "+00:00"))
                u = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                run["duration_seconds"] = max(int((u - c).total_seconds()), 0)
            except (ValueError, TypeError):
                run["duration_seconds"] = None
        else:
            run["duration_seconds"] = None

    return {"runs": runs, "workflows": workflows, "all_time_total": all_time_total}


def _filter_and_compute_stats(cached_data, filters):
    """Apply filters to cached workflow data and compute aggregate stats.

    Args:
        cached_data: dict with keys: runs, workflows, all_time_total
        filters: dict with optional keys: workflow_id, branch, event, conclusion, status
    Returns:
        dict with keys: runs, stats, workflows
    """
    runs = cached_data.get("runs", [])
    workflows = cached_data.get("workflows", [])
    all_time_total = cached_data.get("all_time_total", 0)

    # Apply Python-side filters
    filtered = runs
    wf_id = filters.get("workflow_id")
    if wf_id:
        try:
            wf_id_int = int(wf_id)
            filtered = [r for r in filtered if r.get("workflow_id") == wf_id_int]
        except (ValueError, TypeError):
            pass

    branch = filters.get("branch")
    if branch:
        filtered = [r for r in filtered if r.get("head_branch") == branch]

    event = filters.get("event")
    if event:
        filtered = [r for r in filtered if r.get("event") == event]

    conclusion = filters.get("conclusion")
    status_filter = filters.get("status")
    if conclusion:
        filtered = [r for r in filtered if r.get("conclusion") == conclusion]
    elif status_filter:
        # status can match either status or conclusion field
        filtered = [r for r in filtered
                    if r.get("status") == status_filter or r.get("conclusion") == status_filter]

    # Compute aggregate stats on filtered subset
    total_runs = len(filtered)
    success_count = 0
    failure_count = 0
    total_duration = 0
    duration_count = 0
    runs_by_workflow = {}

    for run in filtered:
        c = run.get("conclusion")
        if c == "success":
            success_count += 1
        elif c == "failure":
            failure_count += 1

        dur = run.get("duration_seconds")
        if dur is not None and c in ("success", "failure"):
            total_duration += dur
            duration_count += 1

        wf_name = run.get("name", "Unknown")
        if wf_name not in runs_by_workflow:
            runs_by_workflow[wf_name] = {"total": 0, "failures": 0}
        runs_by_workflow[wf_name]["total"] += 1
        if c == "failure":
            runs_by_workflow[wf_name]["failures"] += 1

    completed_runs = success_count + failure_count
    stats = {
        "total_runs": total_runs,
        "all_time_total": all_time_total,
        "pass_rate": round((success_count / completed_runs * 100), 1) if completed_runs > 0 else 0,
        "avg_duration": round(total_duration / duration_count) if duration_count > 0 else 0,
        "failure_count": failure_count,
        "success_count": success_count,
        "runs_by_workflow": runs_by_workflow
    }

    return {"runs": filtered, "stats": stats, "workflows": workflows}


def _background_refresh_workflows(owner, repo, repo_key):
    """Background task to refresh workflow cache for a repository."""
    try:
        logger.info(f"Background workflow refresh started for {repo_key}")
        data = _fetch_workflow_data(owner, repo)
        workflow_cache_db.save_cache(repo_key, data)
        logger.info(f"Background workflow refresh completed for {repo_key}: {len(data['runs'])} runs cached")
    except Exception as e:
        logger.error(f"Background workflow refresh failed for {repo_key}: {e}")
    finally:
        with _workflow_refresh_lock:
            _workflow_refresh_in_progress.discard(repo_key)


@app.route("/api/repos/<owner>/<repo>/workflow-runs")
def get_workflow_runs(owner, repo):
    """Get workflow runs with optional filters and aggregate stats.

    Uses SQLite cache with stale-while-revalidate pattern:
    - Cached + fresh: filter & return instantly
    - Cached + stale: return stale data, kick off background refresh
    - No cache: synchronous parallel fetch, save, filter & return
    """
    repo_key = f"{owner}/{repo}"
    ttl_minutes = config.get("workflow_cache_ttl_minutes", 60)
    force_refresh = request.args.get("refresh", "").lower() == "true"

    # Collect filter params
    filters = {
        "workflow_id": request.args.get("workflow_id"),
        "branch": request.args.get("branch"),
        "event": request.args.get("event"),
        "conclusion": request.args.get("conclusion"),
        "status": request.args.get("status"),
    }

    try:
        # Force refresh: synchronous fetch regardless of cache state
        if force_refresh:
            logger.info(f"Force refresh requested for {repo_key}")
            data = _fetch_workflow_data(owner, repo)
            workflow_cache_db.save_cache(repo_key, data)
            result = _filter_and_compute_stats(data, filters)
            return jsonify(result)

        cached = workflow_cache_db.get_cached(repo_key)
        is_stale = workflow_cache_db.is_stale(repo_key, ttl_minutes)

        if cached:
            # Stale: return immediately but trigger background refresh
            if is_stale:
                with _workflow_refresh_lock:
                    if repo_key not in _workflow_refresh_in_progress:
                        _workflow_refresh_in_progress.add(repo_key)
                        thread = threading.Thread(
                            target=_background_refresh_workflows,
                            args=(owner, repo, repo_key),
                            daemon=True
                        )
                        thread.start()

            result = _filter_and_compute_stats(cached["data"], filters)
            return jsonify(result)

        # No cache: synchronous fetch
        data = _fetch_workflow_data(owner, repo)
        workflow_cache_db.save_cache(repo_key, data)
        result = _filter_and_compute_stats(data, filters)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Failed to get workflow runs for {repo_key}: {e}")
        return jsonify({"error": str(e)}), 500


def _fetch_code_activity_data(owner, repo):
    """Fetch and process all 52 weeks of code activity data from GitHub stats APIs.

    Returns a dict with weekly_commits, code_changes, owner_commits, community_commits,
    or None if all data sources are empty.
    """
    # Fetch all 3 stats APIs in parallel
    with ThreadPoolExecutor(max_workers=3) as executor:
        freq_future = executor.submit(fetch_github_stats_api, owner, repo, "stats/code_frequency")
        commit_future = executor.submit(fetch_github_stats_api, owner, repo, "stats/commit_activity")
        participation_future = executor.submit(fetch_github_stats_api, owner, repo, "stats/participation")

        code_freq = freq_future.result()
        commit_activity = commit_future.result()
        participation = participation_future.result()

    # Process code_frequency: [timestamp, additions, deletions] — all weeks
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

    # Process commit_activity: {week, total, days[7]} — all weeks
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

    # Process participation: {all: [52 weeks], owner: [52 weeks]} — all weeks
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

    # Only return data if we got meaningful results
    if not weekly_commits and not code_changes and not owner_commits and not community_commits:
        return None

    return {
        "weekly_commits": weekly_commits,
        "code_changes": code_changes,
        "owner_commits": owner_commits,
        "community_commits": community_commits,
    }


def _background_refresh_code_activity(owner, repo, repo_key):
    """Background task to refresh code activity cache."""
    try:
        logger.info(f"Background code activity refresh started for {repo_key}")
        data = _fetch_code_activity_data(owner, repo)
        if data:
            code_activity_cache_db.save_cache(repo_key, data)
            logger.info(f"Background code activity refresh completed for {repo_key}")
    except Exception as e:
        logger.error(f"Background code activity refresh failed for {repo_key}: {e}")
    finally:
        with _activity_refresh_lock:
            _activity_refresh_in_progress.discard(repo_key)


def _compute_activity_summary(weekly_commits, code_changes, owner_commits, community_commits):
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


@app.route("/api/repos/<owner>/<repo>/code-activity")
def get_code_activity(owner, repo):
    """Get code activity stats (commit frequency, code changes, participation).

    Uses SQLite cache with 24-hour TTL and stale-while-revalidate.
    The full 52-week dataset is cached; the ?weeks param slices the cached data.
    """
    try:
        weeks = int(request.args.get("weeks", 52))
        weeks = min(max(weeks, 1), 52)
        repo_key = f"{owner}/{repo}"
        force_refresh = request.args.get("refresh", "").lower() == "true"

        if force_refresh:
            logger.info(f"Force refresh code activity for {repo_key}")
            data = _fetch_code_activity_data(owner, repo)
            if data:
                code_activity_cache_db.save_cache(repo_key, data)
            else:
                data = {"weekly_commits": [], "code_changes": [], "owner_commits": [], "community_commits": []}
            sliced = {
                "weekly_commits": data["weekly_commits"][-weeks:],
                "code_changes": data["code_changes"][-weeks:],
                "owner_commits": data["owner_commits"][-weeks:],
                "community_commits": data["community_commits"][-weeks:],
            }
            sliced["summary"] = _compute_activity_summary(
                sliced["weekly_commits"], sliced["code_changes"],
                sliced["owner_commits"], sliced["community_commits"]
            )
            return jsonify(sliced)

        cached = code_activity_cache_db.get_cached(repo_key)
        is_stale = code_activity_cache_db.is_stale(repo_key)

        if cached:
            if is_stale:
                with _activity_refresh_lock:
                    if repo_key not in _activity_refresh_in_progress:
                        _activity_refresh_in_progress.add(repo_key)
                        thread = threading.Thread(
                            target=_background_refresh_code_activity,
                            args=(owner, repo, repo_key),
                            daemon=True
                        )
                        thread.start()
            data = cached["data"]
            sliced = {
                "weekly_commits": data.get("weekly_commits", [])[-weeks:],
                "code_changes": data.get("code_changes", [])[-weeks:],
                "owner_commits": data.get("owner_commits", [])[-weeks:],
                "community_commits": data.get("community_commits", [])[-weeks:],
            }
            sliced["summary"] = _compute_activity_summary(
                sliced["weekly_commits"], sliced["code_changes"],
                sliced["owner_commits"], sliced["community_commits"]
            )
            return jsonify(sliced)

        # No cache: synchronous fetch
        data = _fetch_code_activity_data(owner, repo)
        if data:
            code_activity_cache_db.save_cache(repo_key, data)
        else:
            data = {"weekly_commits": [], "code_changes": [], "owner_commits": [], "community_commits": []}

        sliced = {
            "weekly_commits": data["weekly_commits"][-weeks:],
            "code_changes": data["code_changes"][-weeks:],
            "owner_commits": data["owner_commits"][-weeks:],
            "community_commits": data["community_commits"][-weeks:],
        }
        sliced["summary"] = _compute_activity_summary(
            sliced["weekly_commits"], sliced["code_changes"],
            sliced["owner_commits"], sliced["community_commits"]
        )
        return jsonify(sliced)

    except Exception as e:
        logger.error(f"Failed to fetch code activity: {e}")
        return jsonify({"error": str(e)}), 500


def _fetch_contributor_timeseries(owner, repo):
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


def _background_refresh_contributor_ts(owner, repo, repo_key):
    """Background task to refresh contributor time series cache."""
    try:
        logger.info(f"Background contributor TS refresh started for {repo_key}")
        data = _fetch_contributor_timeseries(owner, repo)
        if data:
            contributor_ts_cache_db.save_cache(repo_key, data)
            logger.info(f"Background contributor TS refresh completed for {repo_key}: {len(data)} contributors")
    except Exception as e:
        logger.error(f"Background contributor TS refresh failed for {repo_key}: {e}")
    finally:
        with _contributor_ts_refresh_lock:
            _contributor_ts_refresh_in_progress.discard(repo_key)


@app.route("/api/repos/<owner>/<repo>/contributor-timeseries")
def get_contributor_timeseries(owner, repo):
    """Get per-contributor weekly time series data (commits, additions, deletions).

    Uses SQLite cache with stale-while-revalidate (24-hour TTL).
    """
    repo_key = f"{owner}/{repo}"
    force_refresh = request.args.get("refresh", "").lower() == "true"

    try:
        if force_refresh:
            logger.info(f"Force refresh contributor TS for {repo_key}")
            data = _fetch_contributor_timeseries(owner, repo)
            if data:
                contributor_ts_cache_db.save_cache(repo_key, data)
            return jsonify({"contributors": data})

        cached = contributor_ts_cache_db.get_cached(repo_key)
        is_stale = contributor_ts_cache_db.is_stale(repo_key)

        if cached:
            if is_stale:
                with _contributor_ts_refresh_lock:
                    if repo_key not in _contributor_ts_refresh_in_progress:
                        _contributor_ts_refresh_in_progress.add(repo_key)
                        thread = threading.Thread(
                            target=_background_refresh_contributor_ts,
                            args=(owner, repo, repo_key),
                            daemon=True
                        )
                        thread.start()
            return jsonify({"contributors": cached["data"]})

        # No cache: synchronous fetch
        data = _fetch_contributor_timeseries(owner, repo)
        if data:
            contributor_ts_cache_db.save_cache(repo_key, data)
        return jsonify({"contributors": data})

    except Exception as e:
        logger.error(f"Failed to fetch contributor timeseries for {repo_key}: {e}")
        return jsonify({"error": str(e)}), 500


def fetch_pr_review_times(owner, repo, limit=50):
    """Fetch PRs with review timing data. Uses SQLite cache with 2-hour TTL."""
    cache_db = get_lifecycle_cache_db()
    repo_key = f"{owner}/{repo}"

    # Check cache first
    if not cache_db.is_stale(repo_key):
        cached = cache_db.get_cached(repo_key)
        if cached:
            return cached["data"]

    # Fetch PRs
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

    # Save to cache
    cache_db.save_cache(repo_key, enriched)
    return enriched


@app.route("/api/repos/<owner>/<repo>/lifecycle-metrics")
def get_lifecycle_metrics(owner, repo):
    """Get PR lifecycle metrics (time-to-merge, time-to-first-review, stale PRs)."""
    try:
        prs = fetch_pr_review_times(owner, repo)

        # Compute metrics
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

        # Compute medians/averages
        def median(lst):
            if not lst:
                return None
            s = sorted(lst)
            n = len(s)
            mid = n // 2
            return s[mid] if n % 2 else (s[mid-1] + s[mid]) / 2

        return jsonify({
            "median_time_to_merge": round(median(merge_times), 2) if merge_times else None,
            "avg_time_to_merge": round(sum(merge_times) / len(merge_times), 2) if merge_times else None,
            "median_time_to_first_review": round(median(review_times), 2) if review_times else None,
            "avg_time_to_first_review": round(sum(review_times) / len(review_times), 2) if review_times else None,
            "stale_prs": stale_prs,
            "stale_count": len(stale_prs),
            "distribution": distribution,
            "pr_table": pr_table
        })

    except Exception as e:
        logger.error(f"Failed to fetch lifecycle metrics: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/repos/<owner>/<repo>/review-responsiveness")
def get_review_responsiveness(owner, repo):
    """Get per-reviewer responsiveness metrics and bottleneck detection."""
    try:
        prs = fetch_pr_review_times(owner, repo)

        # Aggregate per-reviewer
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
        def safe_median(lst):
            if not lst:
                return None
            s = sorted(lst)
            n = len(s)
            mid = n // 2
            return s[mid] if n % 2 else (s[mid-1] + s[mid]) / 2

        leaderboard = []
        for reviewer, data in reviewer_data.items():
            times = data["response_times"]
            total = data["total_reviews"]
            approvals = data["approvals"]
            leaderboard.append({
                "reviewer": reviewer,
                "avg_response_time_hours": round(sum(times) / len(times), 2) if times else None,
                "median_response_time_hours": round(safe_median(times), 2) if times else None,
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

        return jsonify({
            "leaderboard": leaderboard,
            "bottlenecks": bottlenecks[:10],
            "avg_team_response_hours": avg_team_response,
            "fastest_reviewer": fastest,
            "prs_awaiting_review": len(bottlenecks)
        })

    except Exception as e:
        logger.error(f"Failed to fetch review responsiveness: {e}")
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
                "commits": stat.get("commits", 0),
                "avatar_url": stat.get("avatar_url"),
                "reviews_given": stat.get("reviews_given", 0),
                "approvals": stat.get("approvals", 0),
                "changes_requested": stat.get("changes_requested", 0),
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
                    "commits": stat.get("commits", 0),
                    "avatar_url": stat.get("avatar_url"),
                    "reviews_given": stat.get("reviews_given", 0),
                    "approvals": stat.get("approvals", 0),
                    "changes_requested": stat.get("changes_requested", 0),
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

            # Transform cached stats to match expected frontend format
            transformed_stats = []
            for stat in cached_stats:
                transformed_stats.append({
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

            stats_with_scores = _add_avg_pr_scores(transformed_stats, full_repo)
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
                "commits": stat.get("commits", 0),
                "avatar_url": stat.get("avatar_url"),
                "reviews_given": stat.get("reviews_given", 0),
                "approvals": stat.get("approvals", 0),
                "changes_requested": stat.get("changes_requested", 0),
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

    Uses fetch_github_stats_api helper which handles 202 retry logic.
    """
    return fetch_github_stats_api(
        owner, repo,
        "stats/contributors",
        jq_query="[.[] | select(.author) | {login: .author.login, avatar_url: .author.avatar_url, commits: .total, lines_added: ([.weeks[].a] | add), lines_deleted: ([.weeks[].d] | add)}]"
    )


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
    """Clear the in-memory cache and SQLite caches."""
    global cache
    cache = {}
    workflow_cache_db.clear()
    contributor_ts_cache_db.clear()
    code_activity_cache_db.clear()
    return jsonify({"message": "Cache cleared"})


@app.route("/api/merge-queue", methods=["GET"])
def get_merge_queue():
    """Get all items in the merge queue with fresh PR states and new commits info."""
    try:
        queue_items = queue_db.get_queue()
        if not queue_items:
            return jsonify({"queue": []})

        def enrich_queue_item(item):
            """Enrich a single queue item with GitHub data and review info."""
            notes_count = queue_db.get_notes_count(item["id"])
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
                # Single gh call for both state and SHA
                pr_state, current_sha = fetch_pr_state_and_sha(owner, repo, item["pr_number"])

                latest_review = reviews_db.get_latest_review_for_pr(item["repo"], item["pr_number"])
                if latest_review:
                    has_review = True
                    review_score = latest_review.get("score")
                    review_id = latest_review.get("id")
                    inline_comments_posted = latest_review.get("inline_comments_posted", False)
                    if latest_review.get("head_commit_sha"):
                        last_reviewed_sha = latest_review["head_commit_sha"]
                        if current_sha and last_reviewed_sha:
                            has_new_commits = current_sha != last_reviewed_sha
            else:
                pr_state = item.get("pr_state")

            return {
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
            }

        # Fetch GitHub data for all queue items in parallel
        with ThreadPoolExecutor(max_workers=5) as executor:
            queue = list(executor.map(enrich_queue_item, queue_items))

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

        # Fetch current PR state and SHA in one call
        repo_parts = pr_data["repo"].split("/")
        pr_state = None
        if len(repo_parts) == 2:
            pr_state, _ = fetch_pr_state_and_sha(repo_parts[0], repo_parts[1], pr_data["number"])

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
        review_body = {
            "commit_id": current_sha,
            "event": "COMMENT",
            "body": f"**Code Review Critical Issues** ({len(issues)} issue(s) flagged)",
            "comments": comments
        }

        try:
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
            logger.warning(f"Line-level comments failed, falling back to file-level: {e.stderr[:200]}")
            # Fallback: post as file-level comments (subject_type: file) when
            # line numbers are approximate and don't match the actual diff
            fallback_comments = []
            for issue in issues:
                fallback_comments.append({
                    "path": issue["path"],
                    "body": issue["body"] + f"\n\n*(Lines ~{issue['start_line']}-{issue['end_line']})*",
                    "subject_type": "file"
                })

            review_body_fallback = {
                "commit_id": current_sha,
                "event": "COMMENT",
                "body": f"**Code Review Critical Issues** ({len(issues)} issue(s) flagged)",
                "comments": fallback_comments
            }

            try:
                result = subprocess.run(
                    [
                        "gh", "api",
                        f"repos/{owner}/{repo_name}/pulls/{pr_number}/reviews",
                        "--method", "POST",
                        "--input", "-"
                    ],
                    input=json.dumps(review_body_fallback),
                    capture_output=True,
                    text=True,
                    check=True
                )
                logger.info(f"Posted file-level comments for review {review_id}: {result.stdout[:200]}")
            except subprocess.CalledProcessError as e2:
                logger.error(f"Failed to post inline comments (both attempts): {e2.stderr}")
                return jsonify({
                    "error": f"Failed to post comments to GitHub: {e2.stderr}",
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


def _startup_refresh_workflow_caches():
    """Background task: refresh any stale workflow caches on startup."""
    ttl_minutes = config.get("workflow_cache_ttl_minutes", 60)
    try:
        repos = workflow_cache_db.get_all_repos()
        for repo_key in repos:
            if workflow_cache_db.is_stale(repo_key, ttl_minutes):
                parts = repo_key.split("/", 1)
                if len(parts) == 2:
                    owner, repo = parts
                    with _workflow_refresh_lock:
                        if repo_key not in _workflow_refresh_in_progress:
                            _workflow_refresh_in_progress.add(repo_key)
                    try:
                        logger.info(f"Startup: refreshing stale workflow cache for {repo_key}")
                        data = _fetch_workflow_data(owner, repo)
                        workflow_cache_db.save_cache(repo_key, data)
                        logger.info(f"Startup: refreshed {repo_key} with {len(data['runs'])} runs")
                    except Exception as e:
                        logger.error(f"Startup: failed to refresh {repo_key}: {e}")
                    finally:
                        with _workflow_refresh_lock:
                            _workflow_refresh_in_progress.discard(repo_key)
    except Exception as e:
        logger.error(f"Startup workflow cache refresh failed: {e}")


if __name__ == "__main__":
    # Refresh stale workflow caches in background on startup
    threading.Thread(target=_startup_refresh_workflow_caches, daemon=True).start()

    app.run(
        host=config.get("host", "127.0.0.1"),
        port=config.get("port", 5050),
        debug=config.get("debug", False),
    )
