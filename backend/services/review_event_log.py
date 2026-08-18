"""Recorders for the review event log.

One named function per lifecycle event, so call sites pass domain values rather
than building dicts, and the event/reason vocabularies stay enforced in one place.

Every recorder swallows its own exceptions. This mirrors
post_review_started_comment(): observing a review must never be able to break the
review it observes.
"""

import logging
import uuid

from backend.database import get_review_events_db

logger = logging.getLogger(__name__)

REASON_NO_OUTPUT = "no_output"
REASON_NONZERO_EXIT = "nonzero_exit"
REASON_SPAWN_FAILED = "spawn_failed"
REASON_ATTEMPTS_EXHAUSTED = "attempts_exhausted"
REASON_CANCELLED = "cancelled"


def new_run_id() -> str:
    """Mint the id that ties every attempt of one review together."""
    return uuid.uuid4().hex


def _record(event, run_id, repo, pr_number, **fields):
    """Append one event, absorbing any failure."""
    try:
        get_review_events_db().log_event(event, repo, pr_number, run_id, **fields)
    except Exception as e:
        logger.warning(
            f"Could not record '{event}' review event for {repo}#{pr_number}: {e}"
        )


def record_started(run_id, repo, pr_number, *, attempt, max_attempts,
                   reviewer_agent, is_followup, auto_started, review_file, pid):
    """An attempt's subprocess spawned."""
    _record(
        "started", run_id, repo, pr_number,
        attempt=attempt,
        max_attempts=max_attempts,
        reviewer_agent=reviewer_agent,
        is_followup=bool(is_followup),
        auto_started=bool(auto_started),
        review_file=review_file,
        pid=pid,
    )


def record_completed(run_id, repo, pr_number, *, attempt, review_id, score, review_file):
    """An attempt produced output and the review was persisted."""
    _record(
        "completed", run_id, repo, pr_number,
        attempt=attempt,
        review_id=review_id,
        score=score,
        review_file=review_file,
    )


def record_failed(run_id, repo, pr_number, *, attempt, max_attempts, reason,
                  exit_code=None, detail=None, review_file=None):
    """An attempt failed. ``reason`` must be one of the REASON_* constants."""
    _record(
        "failed", run_id, repo, pr_number,
        attempt=attempt,
        max_attempts=max_attempts,
        reason=reason,
        exit_code=exit_code,
        detail=detail,
        review_file=review_file,
    )


def record_retry_scheduled(run_id, repo, pr_number, *, attempt, max_attempts, delay_seconds):
    """A retry was armed after a failed attempt."""
    _record(
        "retry_scheduled", run_id, repo, pr_number,
        attempt=attempt,
        max_attempts=max_attempts,
        detail=f"retrying in {delay_seconds:g}s",
    )


def record_gave_up(run_id, repo, pr_number, *, attempt, max_attempts):
    """The attempt limit was reached and the review was recorded as failed."""
    _record(
        "gave_up", run_id, repo, pr_number,
        attempt=attempt,
        max_attempts=max_attempts,
        reason=REASON_ATTEMPTS_EXHAUSTED,
    )


def record_cancelled(run_id, repo, pr_number, *, attempt=None):
    """The user cancelled the review."""
    _record(
        "cancelled", run_id, repo, pr_number,
        attempt=attempt,
        reason=REASON_CANCELLED,
    )
