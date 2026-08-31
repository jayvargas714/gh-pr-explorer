"""Post review lifecycle comments to a PR.

Plain PR conversation comments (the issues comments API), distinct from the
formal review verdict posted by verdict_service once the review has produced
findings: a "review underway" comment when a review starts, and a "review
stopped" comment when a running review is cancelled because new commits made
it stale. They exist so anyone watching the PR knows what the reviewer is
doing before any results land.
"""

import logging
from datetime import datetime, timezone

from backend.config import get_config
from backend.services.github_service import run_gh_command

logger = logging.getLogger(__name__)


def _build_body(is_followup, reviewer_type, auto_started):
    """Build the comment markdown, wording the lead line for the review kind."""
    if auto_started:
        lead = "A follow-up review has been started automatically for this PR by GitHub PR Explorer."
    elif is_followup:
        lead = "A follow-up review has been started for this PR by GitHub PR Explorer."
    else:
        lead = "A review has been started for this PR by GitHub PR Explorer."

    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        "🤖 **Code review in progress**\n\n"
        f"{lead}\n\n"
        f"- Reviewer: `{reviewer_type}`\n"
        f"- Started: {started}\n"
    )


def _post_comment(owner, repo, pr_number, body, kind):
    """POST one issue comment, absorbing any failure.

    Controlled by config.json's "post_review_started_comment" (default true).
    Never raises: a failed comment must not fail the review it announces.

    Returns:
        bool: True if a comment was posted, False if disabled or the post failed.
    """
    if not get_config().get("post_review_started_comment", True):
        return False

    try:
        run_gh_command(
            [
                "api",
                f"repos/{owner}/{repo}/issues/{pr_number}/comments",
                "--method", "POST",
                "--field", f"body={body}",
            ],
            max_retries=1,
        )
    except Exception as e:
        logger.warning(f"Could not post {kind} comment on {owner}/{repo}#{pr_number}: {e}")
        return False

    logger.info(f"Posted {kind} comment on {owner}/{repo}#{pr_number}")
    return True


def post_review_started_comment(owner, repo, pr_number, is_followup=False,
                                reviewer_type="default", auto_started=False):
    """Comment on a PR that a review is underway."""
    body = _build_body(is_followup, reviewer_type, auto_started)
    return _post_comment(owner, repo, pr_number, body, "review-started")


def post_review_stopped_stale_comment(owner, repo, pr_number, *, old_sha, new_sha,
                                      reviewer_type="default"):
    """Comment on a PR that its running review was stopped because it went stale.

    Posted just before the replacement review starts, so the follow-on
    "review started" comment explains the restart half of the story.
    """
    stopped = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = (
        "🤖 **Code review stopped — new commits**\n\n"
        "The review running on this PR was stopped by GitHub PR Explorer because "
        "new commits were pushed while it was underway, making its findings stale "
        f"(`{old_sha[:8]}` → `{new_sha[:8]}`). "
        "A new review covering the latest commits is being started.\n\n"
        f"- Reviewer: `{reviewer_type}`\n"
        f"- Stopped: {stopped}\n"
    )
    return _post_comment(owner, repo, pr_number, body, "review-stopped")
