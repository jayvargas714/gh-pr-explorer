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


def _dedupe_checks(contexts):
    """Keep only the most recent run per check name.

    GitHub's statusCheckRollup includes all historical runs (e.g. a cancelled
    run followed by a successful re-run). We only care about the latest result
    for each unique check name. Uses completedAt/startedAt timestamps to pick
    the most recent; falls back to last-in-list order.
    """
    latest_by_name = {}
    for check in contexts:
        name = check.get("name") or check.get("context") or ""
        if not name:
            # No name to dedupe by — always include
            name = f"__unnamed_{id(check)}"

        existing = latest_by_name.get(name)
        if existing is None:
            latest_by_name[name] = check
        else:
            # Compare timestamps: prefer completedAt, fall back to startedAt
            new_time = check.get("completedAt") or check.get("startedAt") or ""
            old_time = existing.get("completedAt") or existing.get("startedAt") or ""
            if new_time >= old_time:
                latest_by_name[name] = check

    return list(latest_by_name.values())


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

    # Deduplicate: only evaluate the latest run per check name
    contexts = _dedupe_checks(contexts)

    has_failure = False
    has_pending = False
    has_success = False

    for check in contexts:
        state = check.get("state", "").upper()
        conclusion = check.get("conclusion", "").upper() if check.get("conclusion") else None
        status = check.get("status", "").upper()

        if conclusion:
            if conclusion in ("FAILURE", "TIMED_OUT", "ACTION_REQUIRED"):
                has_failure = True
            elif conclusion in ("SUCCESS", "CANCELLED", "SKIPPED", "NEUTRAL"):
                # CANCELLED/SKIPPED are not failures — they indicate a
                # superseded or intentionally skipped run
                if conclusion == "SUCCESS":
                    has_success = True
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
