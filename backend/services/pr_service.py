"""PR post-processing: review_status, ci_status computation."""

import logging

logger = logging.getLogger(__name__)


def get_review_status(review_decision, reviews=None):
    """Determine review status using full reviews history with reviewDecision fallback.

    GitHub's reviewDecision can be reset when a re-review is requested, even though
    the CHANGES_REQUESTED is still blocking. We compute the effective state from
    all reviews to catch this case.

    Priority:
    1. If any reviewer's most recent actionable review is CHANGES_REQUESTED → changes_requested
    2. If all actionable reviews are APPROVED → approved
    3. Fall back to reviewDecision field
    """
    # Compute effective state from full reviews history
    if reviews:
        has_changes_requested = False
        has_approved = False
        reviewer_state = {}  # login -> latest actionable state
        for review in reviews:
            author = review.get("author") or {}
            login = author.get("login")
            if not login:
                continue
            state = (review.get("state") or "").upper()
            if state in ("APPROVED", "CHANGES_REQUESTED"):
                reviewer_state[login] = state

        for state in reviewer_state.values():
            if state == "CHANGES_REQUESTED":
                has_changes_requested = True
            elif state == "APPROVED":
                has_approved = True

        if has_changes_requested:
            return "changes_requested"
        if has_approved:
            return "approved"

    # Fall back to reviewDecision
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


def get_current_reviewers(reviews):
    """Compute per-reviewer blocking state from ALL reviews.

    Uses the full reviews list (not latestReviews) to determine each reviewer's
    effective blocking state. This handles the case where a re-review is requested
    which resets latestReviews to PENDING, but the CHANGES_REQUESTED still blocks.

    For each reviewer, finds their most recent APPROVED or CHANGES_REQUESTED review.
    Only returns reviewers with an actionable state (not commenters or pending).

    Returns a list of dicts: [{login, avatarUrl, state}, ...]
    where state is APPROVED or CHANGES_REQUESTED.
    """
    if not reviews:
        return []

    actionable_states = {"APPROVED", "CHANGES_REQUESTED"}

    # Walk reviews in order (oldest first) to find each reviewer's latest actionable state
    reviewer_state = {}  # login -> {avatarUrl, state}
    for review in reviews:
        author = review.get("author") or {}
        login = author.get("login")
        if not login:
            continue
        state = (review.get("state") or "").upper()
        if state not in actionable_states:
            continue
        reviewer_state[login] = {
            "login": login,
            "avatarUrl": author.get("avatarUrl", ""),
            "state": state,
            "body": review.get("body", ""),
        }

    return list(reviewer_state.values())


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
