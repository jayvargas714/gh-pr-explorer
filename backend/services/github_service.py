"""GitHub CLI wrapper: run_command, parse_json, fetch_stats_api (202-retry)."""

import json
import logging
import subprocess
import time

logger = logging.getLogger(__name__)


_TRANSIENT_ERRORS = (
    "stream error", "CANCEL", "received from peer", "connection reset",
    "502 Bad Gateway", "503 Service Unavailable", "504 Gateway Timeout",
    "HTTP 502", "HTTP 503", "HTTP 504",
)


# Full field set for PR list/view fetches. Single source of truth — the route,
# the filter builder, and the sync worker must all fetch identical shapes.
PR_LIST_JSON_FIELDS = (
    "number,title,author,state,isDraft,createdAt,updatedAt,closedAt,"
    "mergedAt,url,body,headRefName,headRefOid,baseRefName,labels,assignees,"
    "reviewRequests,reviewDecision,reviews,"
    "mergeable,additions,deletions,changedFiles,"
    "milestone,statusCheckRollup"
)


class TransientGitHubError(RuntimeError):
    """Raised when gh CLI fails with a transient upstream error after all retries."""
    pass


class RateLimitError(RuntimeError):
    """Raised when gh CLI fails because the GitHub API rate limit is exhausted.

    Subclasses RuntimeError so callers that catch RuntimeError keep working;
    callers that can defer-and-retry (the auto-verdict path) catch this first.
    """
    pass


def is_transient_gh_error(message):
    """True if the error string looks like a transient GitHub/HTTP error."""
    if not message:
        return False
    return any(err in message for err in _TRANSIENT_ERRORS)


def is_rate_limit_error(message):
    """True if the error string is a GitHub primary or secondary rate limit."""
    if not message:
        return False
    return "rate limit" in message.lower()


def run_gh_command(args, check=True, max_retries=3, retry_delay=1):
    """Run a gh CLI command and return the output.

    Retries automatically on transient HTTP/2 stream errors and 5xx responses
    with exponential backoff (retry_delay, 2x, 4x, ...). If all retries are
    exhausted on a transient error, raises TransientGitHubError so callers can
    distinguish upstream flakiness from genuine 4xx/auth errors.
    """
    for attempt in range(max_retries + 1):
        try:
            result = subprocess.run(
                ["gh"] + args,
                capture_output=True,
                text=True,
                check=check,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            stderr = e.stderr or ""
            if is_rate_limit_error(stderr):
                # No local backoff: the quota window is up to an hour, so
                # sleep-retrying here just blocks the calling thread. Callers
                # that can wait it out (auto verdicts) defer and retry later.
                raise RateLimitError(f"gh command failed: {stderr}")
            transient = is_transient_gh_error(stderr)
            if attempt < max_retries and transient:
                backoff = retry_delay * (2 ** attempt)
                logger.warning(f"Transient gh error (attempt {attempt + 1}/{max_retries + 1}), retrying in {backoff}s: {stderr.strip()}")
                time.sleep(backoff)
                continue
            if transient:
                raise TransientGitHubError(f"gh command failed: {stderr}")
            raise RuntimeError(f"gh command failed: {stderr}")
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


def fetch_full_pr(owner, repo, pr_number):
    """Fetch one PR with the full field set. Raises on failure (incl. transient)."""
    output = run_gh_command([
        "pr", "view", str(pr_number),
        "-R", f"{owner}/{repo}",
        "--json", PR_LIST_JSON_FIELDS,
    ])
    data = parse_json_output(output)
    if not isinstance(data, dict) or "number" not in data:
        raise RuntimeError(f"Unexpected gh pr view output for {owner}/{repo}#{pr_number}")
    return data


def fetch_pr_files(owner, repo, pr_number):
    """All changed file paths for a PR. Raises RuntimeError on failure.

    Uses the REST files endpoint with --paginate: `gh pr view --json files`
    truncates at 100 files, and huge PRs are exactly where a truncated list
    would mis-route the automation classifier.
    """
    output = run_gh_command([
        "api", f"repos/{owner}/{repo}/pulls/{pr_number}/files",
        "--paginate", "--jq", ".[].filename",
    ])
    return [line for line in output.splitlines() if line.strip()]


def fetch_pr_behind_by(owner, repo, base_ref, head_ref):
    """How many commits head_ref is behind base_ref. Raises RuntimeError on failure."""
    output = run_gh_command([
        "api", f"repos/{owner}/{repo}/compare/{base_ref}...{head_ref}",
        "--jq", ".behind_by",
    ])
    try:
        return int(output)
    except (TypeError, ValueError):
        raise RuntimeError(f"Unexpected compare output for {owner}/{repo} {base_ref}...{head_ref}: {output!r}")


def fetch_pr_numbers(owner, repo, state="open", search=None, limit=1000):
    """Fetch PR numbers only (tiny, 504-resistant query), in GitHub's order."""
    args = ["pr", "list", "-R", f"{owner}/{repo}", "--state", state,
            "--limit", str(limit), "--json", "number"]
    if search:
        args.extend(["--search", search])
    output = run_gh_command(args)
    rows = parse_json_output(output)
    return [row["number"] for row in rows if isinstance(row, dict) and "number" in row]


_authenticated_login = None


def get_authenticated_login():
    """Login of the gh-authenticated user, cached for the process lifetime.

    Used to detect self-authored PRs, which GitHub refuses to let you approve.
    """
    global _authenticated_login
    if _authenticated_login is None:
        try:
            output = run_gh_command(["api", "user", "--jq", ".login"])
            _authenticated_login = output.strip() or None
        except RuntimeError as e:
            logger.warning(f"Could not determine authenticated gh user: {e}")
            return None
    return _authenticated_login


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


def fetch_pr_head_sha(owner, repo, pr_number, raise_on_rate_limit=False):
    """Fetch the current head commit SHA of a PR from GitHub.

    With raise_on_rate_limit=True a drained API quota propagates as
    RateLimitError so the caller can defer instead of treating it like a
    permanent failure; every other error still returns None.
    """
    try:
        output = run_gh_command([
            "pr", "view", str(pr_number),
            "-R", f"{owner}/{repo}",
            "--json", "headRefOid",
            "--jq", ".headRefOid"
        ])
        return output.strip() if output else None
    except RateLimitError as e:
        if raise_on_rate_limit:
            raise
        logger.warning(f"Failed to fetch PR head SHA for {owner}/{repo}#{pr_number}: {e}")
        return None
    except RuntimeError as e:
        logger.warning(f"Failed to fetch PR head SHA for {owner}/{repo}#{pr_number}: {e}")
        return None


def fetch_pr_state_and_sha(owner, repo, pr_number):
    """Fetch PR state and head SHA in a single gh call.

    Returns:
        tuple: (state, head_sha) - either may be None on error.
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


def fetch_pr_queue_data(owner, repo, pr_number):
    """Fetch PR state, head SHA, review decision, CI status, and all reviews in a single gh call.

    Used by merge queue enrichment to avoid multiple API calls per item.
    Uses 'reviews' (full history) instead of 'latestReviews' so the caller
    can compute the effective blocking state even when a re-review is requested.

    Returns:
        dict with keys: state, headRefOid, reviewDecision, statusCheckRollup, reviews.
        All values may be None on error.
    """
    empty = {
        "state": None, "headRefOid": None, "reviewDecision": None,
        "statusCheckRollup": None, "isDraft": False, "reviews": None,
    }
    try:
        output = run_gh_command([
            "pr", "view", str(pr_number),
            "-R", f"{owner}/{repo}",
            "--json", "state,headRefOid,reviewDecision,statusCheckRollup,isDraft,reviews",
        ])
        data = parse_json_output(output)
        if isinstance(data, dict):
            return {
                "state": data.get("state", "").upper() or None,
                "headRefOid": data.get("headRefOid") or None,
                "reviewDecision": data.get("reviewDecision") or None,
                "statusCheckRollup": data.get("statusCheckRollup") or None,
                "isDraft": data.get("isDraft", False),
                "reviews": data.get("reviews") or None,
            }
        return empty
    except RuntimeError as e:
        logger.warning(f"Failed to fetch PR queue data for {owner}/{repo}#{pr_number}: {e}")
        return empty


def fetch_open_prs_queue_data(owner, repo, limit=1000):
    """Dispatch-gate data (state/draft/CI) for every open PR, in ONE gh call.

    The automation dispatch worker used to run fetch_pr_queue_data per pending
    row — at 20 rows per 30s cycle that alone burned ~half the shared GraphQL
    rate limit. One `gh pr list` covers the whole repo per cycle instead.

    Returns:
        dict mapping PR number -> {state, isDraft, statusCheckRollup}, or None
        when the fetch failed. Callers MUST treat None as "unknown", never as
        "no open PRs" — mistaking an outage for an empty repo would mass-skip
        the pipeline. A PR absent from a successful result is not open.
    """
    try:
        output = run_gh_command([
            "pr", "list", "-R", f"{owner}/{repo}",
            "--state", "open", "--limit", str(limit),
            "--json", "number,state,isDraft,statusCheckRollup",
        ])
        rows = parse_json_output(output)
    except RuntimeError as e:
        logger.warning(f"Failed to batch-fetch open PR queue data for {owner}/{repo}: {e}")
        return None
    if not isinstance(rows, list):
        return None
    return {
        row["number"]: {
            "state": (row.get("state") or "").upper() or "OPEN",
            "isDraft": bool(row.get("isDraft")),
            "statusCheckRollup": row.get("statusCheckRollup") or None,
        }
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("number"), int)
    }


def fetch_open_prs_head_shas(owner, repo, limit=1000):
    """Head SHA for every open PR, in ONE gh call.

    The auto follow-up watcher used to run fetch_pr_state_and_sha per armed
    PR every 60s — dozens of GraphQL calls per cycle against the shared rate
    limit. One lean `gh pr list` covers the whole repo per cycle instead.

    Returns:
        dict mapping PR number -> head SHA, or None when the fetch failed.
        Callers MUST treat None as "unknown", never as "no open PRs". A PR
        absent from a successful result is not open.
    """
    try:
        output = run_gh_command([
            "pr", "list", "-R", f"{owner}/{repo}",
            "--state", "open", "--limit", str(limit),
            "--json", "number,headRefOid",
        ])
        rows = parse_json_output(output)
    except RuntimeError as e:
        logger.warning(f"Failed to batch-fetch open PR head SHAs for {owner}/{repo}: {e}")
        return None
    if not isinstance(rows, list):
        return None
    return {
        row["number"]: row["headRefOid"]
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("number"), int) and row.get("headRefOid")
    }
