"""Post a "review underway" comment to a PR when a code review starts.

This is a plain PR conversation comment (the issues comments API), distinct
from the formal review verdict posted by verdict_service once the review has
produced findings. It exists so anyone watching the PR knows a review is
running before any results land.
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


def post_review_started_comment(owner, repo, pr_number, is_followup=False,
                                reviewer_type="default", auto_started=False):
    """Comment on a PR that a review is underway.

    Controlled by config.json's "post_review_started_comment" (default true).
    Never raises: a failed comment must not fail the review it announces.

    Returns:
        bool: True if a comment was posted, False if disabled or the post failed.
    """
    if not get_config().get("post_review_started_comment", True):
        return False

    body = _build_body(is_followup, reviewer_type, auto_started)
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
        logger.warning(f"Could not post review-started comment on {owner}/{repo}#{pr_number}: {e}")
        return False

    logger.info(f"Posted review-started comment on {owner}/{repo}#{pr_number}")
    return True
