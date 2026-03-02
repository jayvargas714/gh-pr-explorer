"""Post a formal PR review verdict (Approve, Request Changes, Comment) to GitHub."""

import json
import logging
import subprocess

from backend.services.github_service import fetch_pr_head_sha

logger = logging.getLogger(__name__)

VALID_EVENTS = {"APPROVE", "REQUEST_CHANGES", "COMMENT"}


def post_verdict(owner, repo, pr_number, event, body):
    """Post a PR review verdict via the GitHub API.

    Args:
        owner: Repository owner.
        repo: Repository name.
        pr_number: PR number.
        event: One of APPROVE, REQUEST_CHANGES, COMMENT.
        body: Review body text.

    Returns:
        tuple: (response_dict, status_code)
    """
    if event not in VALID_EVENTS:
        return {"error": f"Invalid event: {event}. Must be one of {sorted(VALID_EVENTS)}"}, 400

    if not body or not body.strip():
        return {"error": "Review body cannot be empty"}, 400

    current_sha = fetch_pr_head_sha(owner, repo, pr_number)
    if not current_sha:
        return {"error": "Could not fetch PR head commit SHA"}, 500

    review_body = {
        "commit_id": current_sha,
        "event": event,
        "body": body.strip()
    }

    try:
        result = subprocess.run(
            [
                "gh", "api",
                f"repos/{owner}/{repo}/pulls/{pr_number}/reviews",
                "--method", "POST",
                "--input", "-"
            ],
            input=json.dumps(review_body),
            capture_output=True,
            text=True,
            check=True
        )
        logger.info(f"Posted {event} verdict on {owner}/{repo}#{pr_number}")
        return {
            "message": f"Review verdict posted: {event}",
            "event": event,
            "pr_number": pr_number
        }, 200
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to post verdict on {owner}/{repo}#{pr_number}: {e.stderr[:300]}")
        return {"error": f"Failed to post review to GitHub: {e.stderr[:200]}"}, 500
