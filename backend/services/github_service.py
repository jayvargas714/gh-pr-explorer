"""GitHub CLI wrapper: run_command, parse_json, fetch_stats_api (202-retry)."""

import json
import logging
import subprocess
import time

logger = logging.getLogger(__name__)


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
    """Fetch the current head commit SHA of a PR from GitHub."""
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
