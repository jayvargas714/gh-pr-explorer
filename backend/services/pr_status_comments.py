"""Per-event PR status comments.

Plain PR conversation comments (the issues comments API), distinct from the
formal review verdict posted by verdict_service: one named function per
pipeline event (same convention as review_event_log), so anyone watching the
PR can follow what the pipeline is doing — reviews starting, retrying, giving
up, verdicts deferred by rate limits, automation gates blocking, and so on.

Every status comment carries an invisible STATUS_MARKER, and posting a new one
deletes the previous marker-bearing comments, so at most one bot status comment
stands on a PR at any time (verdict reviews are PR reviews, not issue comments,
and can never be touched by the deletion path). The list-then-post-then-delete
order means there is never a window with zero status comments and the new
comment can never delete itself.

All posting is gated by config.json's "post_review_started_comment" flag (the
name is historical — it now gates every status comment) and NEVER raises: a
failed comment must not fail the pipeline step it announces.
"""

import logging
import threading
from datetime import datetime, timezone

from backend.config import get_config
from backend.services.github_service import RateLimitError, run_gh_command

logger = logging.getLogger(__name__)

STATUS_MARKER = "<!-- gh-pr-explorer:status -->"

# Serializes list/post/delete sequences across the app's watcher threads so
# two concurrent events cannot interleave their supersede flows.
_comment_lock = threading.Lock()

_MAX_DETAIL_CHARS = 300


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _trunc(text):
    text = str(text)
    return text if len(text) <= _MAX_DETAIL_CHARS else text[:_MAX_DETAIL_CHARS] + "…"


def _failure_line(reason, detail):
    return f"{reason} — {_trunc(detail)}" if detail else str(reason)


def _tallies_line(tallies):
    tallies = tallies or {}
    return (
        f"{tallies.get('critical', 0)} critical, "
        f"{tallies.get('major', 0)} major, "
        f"{tallies.get('minor', 0)} minor"
    )


def _list_status_comment_ids(owner, repo, pr_number):
    """Ids of existing marker-bearing status comments, oldest first."""
    output = run_gh_command(
        [
            "api",
            f"repos/{owner}/{repo}/issues/{pr_number}/comments",
            "--paginate",
            "--jq", f'.[] | select(.body | contains("{STATUS_MARKER}")) | .id',
        ],
        max_retries=1,
    )
    ids = []
    for line in (output or "").splitlines():
        line = line.strip()
        if line.isdigit():
            ids.append(int(line))
    return ids


def _delete_comment_ids(owner, repo, comment_ids):
    """DELETE each id, absorbing individual failures (e.g. manual deletions)."""
    for comment_id in comment_ids:
        try:
            run_gh_command(
                [
                    "api",
                    f"repos/{owner}/{repo}/issues/comments/{comment_id}",
                    "--method", "DELETE",
                ],
                max_retries=1,
            )
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning(f"Could not delete status comment {comment_id} on {owner}/{repo}: {e}")


def _post_status_comment(owner, repo, pr_number, body, kind):
    """Post one status comment, superseding any previous ones.

    Never raises. Returns True if the comment was posted, False if disabled
    or the post failed.
    """
    if not get_config().get("post_review_started_comment", True):
        return False

    with _comment_lock:
        try:
            try:
                old_ids = _list_status_comment_ids(owner, repo, pr_number)
            except RateLimitError:
                raise
            except Exception as e:
                # Post anyway: a stale leftover beats total silence.
                logger.warning(f"Could not list status comments on {owner}/{repo}#{pr_number}: {e}")
                old_ids = []

            run_gh_command(
                [
                    "api",
                    f"repos/{owner}/{repo}/issues/{pr_number}/comments",
                    "--method", "POST",
                    "--field", f"body={body}\n{STATUS_MARKER}",
                ],
                max_retries=1,
            )
            _delete_comment_ids(owner, repo, old_ids)
        except RateLimitError:
            logger.info(f"Skipped {kind} comment on {owner}/{repo}#{pr_number}: GitHub rate limit exhausted")
            return False
        except Exception as e:
            logger.warning(f"Could not post {kind} comment on {owner}/{repo}#{pr_number}: {e}")
            return False

    logger.info(f"Posted {kind} comment on {owner}/{repo}#{pr_number}")
    return True


def delete_status_comments(owner, repo, pr_number):
    """Remove all status comments without posting a replacement.

    Used when the status story ends with something better than a status
    comment (a posted verdict review) or with silence (a user cancel).
    Never raises. Returns True if the cleanup ran, False if disabled or failed.
    """
    if not get_config().get("post_review_started_comment", True):
        return False

    with _comment_lock:
        try:
            _delete_comment_ids(owner, repo, _list_status_comment_ids(owner, repo, pr_number))
        except RateLimitError:
            logger.info(f"Skipped status comment cleanup on {owner}/{repo}#{pr_number}: GitHub rate limit exhausted")
            return False
        except Exception as e:
            logger.warning(f"Could not clean up status comments on {owner}/{repo}#{pr_number}: {e}")
            return False
    return True


# --- review lifecycle ---------------------------------------------------------

def post_review_started_comment(owner, repo, pr_number, is_followup=False,
                                reviewer_type="default", auto_started=False,
                                attempt=1, max_attempts=None, head_sha=None,
                                note=None):
    """Comment on a PR that a review (or a retry attempt) is underway."""
    if attempt > 1:
        lead = (
            f"Attempt {attempt} of {max_attempts} has been started automatically "
            "after a failed attempt."
        )
    elif auto_started:
        lead = "A follow-up review has been started automatically for this PR by GitHub PR Explorer."
    elif is_followup:
        lead = "A follow-up review has been started for this PR by GitHub PR Explorer."
    else:
        lead = "A review has been started for this PR by GitHub PR Explorer."

    lines = [f"- Reviewer: `{reviewer_type}`"]
    if max_attempts:
        lines.append(f"- Attempt: {attempt} of {max_attempts}")
    if head_sha:
        lines.append(f"- Commit: `{head_sha[:8]}`")
    lines.append(f"- Started: {_now()}")
    if note:
        lines.append(f"- Note: {note}")

    body = "🤖 **Code review in progress**\n\n" + lead + "\n\n" + "\n".join(lines) + "\n"
    return _post_status_comment(owner, repo, pr_number, body, "review-started")


def post_review_retry_scheduled_comment(owner, repo, pr_number, *, reviewer_type,
                                        attempt, max_attempts, delay_seconds,
                                        reason, detail=None):
    """Comment that an attempt failed and a retry is scheduled."""
    body = (
        "🤖 **Code review attempt failed — retry scheduled**\n\n"
        f"Attempt {attempt} of {max_attempts} of this PR's review failed. "
        "A retry will start automatically — no action is needed.\n\n"
        f"- Reviewer: `{reviewer_type}`\n"
        f"- Failure: {_failure_line(reason, detail)}\n"
        f"- Next attempt: in ~{delay_seconds:g}s\n"
        f"- Failed: {_now()}\n"
    )
    return _post_status_comment(owner, repo, pr_number, body, "review-retry")


def post_review_gave_up_comment(owner, repo, pr_number, *, reviewer_type,
                                attempt, max_attempts, reason, detail=None,
                                spawn_failed=False):
    """Comment that the review failed for good — no further automatic retries."""
    if spawn_failed:
        lead = (
            f"Attempt {attempt}'s retry could not be started, so the review "
            "has been recorded as failed."
        )
    else:
        lead = (
            f"All {max_attempts} review attempts for this PR failed. "
            "No further automatic retries will run."
        )
    body = (
        "🤖 **Code review failed — giving up**\n\n"
        f"{lead}\n\n"
        f"- Reviewer: `{reviewer_type}`\n"
        f"- Last failure: {_failure_line(reason, detail)}\n"
        f"- Failed: {_now()}\n\n"
        "**Next step:** start a new review manually from GitHub PR Explorer, "
        "or push new commits to trigger a fresh automatic review.\n"
    )
    return _post_status_comment(owner, repo, pr_number, body, "review-gave-up")


def post_review_stopped_stale_comment(owner, repo, pr_number, *, old_sha, new_sha,
                                      reviewer_type="default"):
    """Comment that a stale review was stopped and its automatic restart failed.

    The success path says nothing here — the replacement review's started
    comment carries the restart story in its note line instead.
    """
    body = (
        "🤖 **Code review stopped — new commits**\n\n"
        "The review running on this PR was stopped by GitHub PR Explorer because "
        "new commits were pushed while it was underway, making its findings stale "
        f"(`{old_sha[:8]}` → `{new_sha[:8]}`).\n\n"
        f"- Reviewer: `{reviewer_type}`\n"
        f"- Stopped: {_now()}\n\n"
        "**Next step:** the automatic restart failed — start a new review "
        "manually from GitHub PR Explorer.\n"
    )
    return _post_status_comment(owner, repo, pr_number, body, "review-stopped")


def post_review_orphaned_requeued_comment(owner, repo, pr_number):
    """Comment that a restart interrupted the review and it was requeued."""
    body = (
        "🤖 **Code review interrupted — requeued**\n\n"
        "The review running on this PR was interrupted by a GitHub PR Explorer "
        "restart. It has been requeued and will be re-dispatched automatically "
        "— no action is needed.\n\n"
        f"- Requeued: {_now()}\n"
    )
    return _post_status_comment(owner, repo, pr_number, body, "review-requeued")


# --- verdict outcomes -----------------------------------------------------------

def post_verdict_suppressed_comment(owner, repo, pr_number, *, tallies, reason):
    """Comment that the review passed but auto-approve is off."""
    body = (
        "🤖 **Review complete — approval needs manual action**\n\n"
        "The automatic review finished within the configured thresholds, but "
        "auto-approve is disabled, so no verdict was posted.\n\n"
        f"- Findings: {_tallies_line(tallies)}\n"
        f"- Result: {reason}\n"
        f"- Completed: {_now()}\n\n"
        "**Next step:** review the findings in GitHub PR Explorer and post the "
        "verdict manually.\n"
    )
    return _post_status_comment(owner, repo, pr_number, body, "verdict-suppressed")


def post_verdict_deferred_comment(owner, repo, pr_number, *, event, tallies):
    """Comment that the verdict is decided but deferred by a GitHub rate limit.

    This comment shares the drained quota and will often fail to post; that is
    absorbed silently, and a later outcome (posted/error) re-tells the story.
    """
    body = (
        "🤖 **Review complete — verdict delayed by GitHub rate limit**\n\n"
        f"The review finished and its verdict ({event}) is ready, but GitHub's "
        "API rate limit is exhausted. The verdict will be posted automatically "
        "once the quota resets (retried with backoff for up to 24h) — no action "
        "is needed yet.\n\n"
        f"- Findings: {_tallies_line(tallies)}\n"
        f"- Pending verdict: {event}\n"
        f"- Deferred: {_now()}\n"
    )
    return _post_status_comment(owner, repo, pr_number, body, "verdict-deferred")


def post_verdict_error_comment(owner, repo, pr_number, *, event, tallies, error_detail):
    """Comment that posting the verdict failed for good."""
    body = (
        "🤖 **Review verdict could not be posted**\n\n"
        f"The automatic review finished, but posting its verdict ({event}) to "
        "GitHub failed.\n\n"
        f"- Findings: {_tallies_line(tallies)}\n"
        f"- Error: {_trunc(error_detail)}\n"
        f"- Failed: {_now()}\n\n"
        "**Next step:** post the verdict manually from GitHub PR Explorer, or "
        "re-run the review.\n"
    )
    return _post_status_comment(owner, repo, pr_number, body, "verdict-error")


def post_verdict_skipped_comment(owner, repo, pr_number, *, reason):
    """Comment that the review completed but no verdict was posted."""
    body = (
        "🤖 **Automatic verdict skipped**\n\n"
        f"The automatic review completed, but no verdict was posted: {reason}.\n\n"
        "**Next step:** check the review in GitHub PR Explorer and post a "
        "verdict manually if one is needed.\n"
    )
    return _post_status_comment(owner, repo, pr_number, body, "verdict-skipped")


# --- automation pipeline ----------------------------------------------------------

def post_automation_enrolled_comment(owner, repo, pr_number):
    """Comment that the PR entered the automatic review pipeline."""
    body = (
        "🤖 **PR enrolled for automated review**\n\n"
        "GitHub PR Explorer has queued this PR for automatic code review. The "
        "review starts once all gates pass (not a draft, CI green, branch close "
        "enough to base, review slot free).\n\n"
        f"- Enrolled: {_now()}\n"
    )
    return _post_status_comment(owner, repo, pr_number, body, "automation-enrolled")


def post_automation_waiting_comment(owner, repo, pr_number, *, reason):
    """Comment that the queued review is blocked on a dispatch gate."""
    body = (
        "🤖 **Automated review waiting**\n\n"
        "This PR's automatic review is queued but waiting on a gate:\n\n"
        f"- Waiting on: {reason}\n"
        f"- Since: {_now()}\n\n"
        "The pipeline re-checks about once a minute and starts the review "
        "automatically when the gate clears.\n"
    )
    return _post_status_comment(owner, repo, pr_number, body, "automation-waiting")


def post_automation_window_expired_comment(owner, repo, pr_number, *, timeout_hours):
    """Comment that the PR waited too long on gates and left the pipeline."""
    body = (
        "🤖 **Automated review window expired**\n\n"
        f"This PR waited more than {timeout_hours}h for its gates to clear and "
        "has been removed from the automatic review pipeline.\n\n"
        "**Next step:** start a review manually from GitHub PR Explorer once "
        "the PR is ready.\n"
    )
    return _post_status_comment(owner, repo, pr_number, body, "automation-expired")


def post_automation_failed_comment(owner, repo, pr_number, *, attempts, detail):
    """Comment that the pipeline gave up dispatching a review."""
    body = (
        "🤖 **Automated review dispatch failed**\n\n"
        "The automation pipeline could not start a review for this PR after "
        f"{attempts} attempts.\n\n"
        f"- Last error: {_trunc(detail)}\n"
        f"- Failed: {_now()}\n\n"
        "**Next step:** start a review manually from GitHub PR Explorer.\n"
    )
    return _post_status_comment(owner, repo, pr_number, body, "automation-failed")


def post_automation_unidentified_comment(owner, repo, pr_number, *, matched_rules,
                                         unmatched_count):
    """Comment that routing could not pick a reviewer for the PR."""
    body = (
        "🤖 **Automated review needs manual routing**\n\n"
        "This PR's changed files span multiple routing rules or mix matched and "
        "unmatched files, so no reviewer agent could be chosen automatically.\n\n"
        f"- Matched rules: {', '.join(matched_rules) if matched_rules else 'none'}\n"
        f"- Unmatched files: {unmatched_count}\n\n"
        "**Next step:** start a review manually from GitHub PR Explorer with "
        "the right reviewer.\n"
    )
    return _post_status_comment(owner, repo, pr_number, body, "automation-unidentified")
