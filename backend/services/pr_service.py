"""PR post-processing: review_status, ci_status computation."""

import logging

logger = logging.getLogger(__name__)


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

    if isinstance(status_check_rollup, list):
        contexts = status_check_rollup
    else:
        contexts = status_check_rollup.get("contexts", [])

    if not contexts:
        return None

    has_failure = False
    has_pending = False
    has_success = False

    for check in contexts:
        state = check.get("state", "").upper()
        conclusion = check.get("conclusion", "").upper() if check.get("conclusion") else None
        status = check.get("status", "").upper()

        if conclusion:
            if conclusion in ("FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED"):
                has_failure = True
            elif conclusion == "SUCCESS":
                has_success = True
            elif conclusion in ("NEUTRAL", "SKIPPED"):
                pass
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

    if has_failure:
        return "failure"
    if has_pending:
        return "pending"
    if has_success:
        return "success"
    return "neutral"
