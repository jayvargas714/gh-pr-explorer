"""Background watcher that auto-starts follow-up reviews when armed PRs get new commits.

Completes the armed-card loop: review -> auto verdict -> author pushes fixes ->
follow-up review -> auto verdict. Each cycle compares every armed PR's live head
SHA against the latest review's recorded SHA (the same signal that drives the
"new commits" badge) and starts a follow-up review with the card's armed
reviewer agent when they differ.

Only PRs that already have a review qualify, so an auto-started review is always
a follow-up. Loop safety: a finished review (completed or failed) records the
then-current head SHA, which clears the trigger, and _attempted_shas guards
against spawn-retry loops within a process lifetime.
"""

import logging
import time

logger = logging.getLogger(__name__)

WATCH_INTERVAL_SECONDS = 60

# key -> head SHA we last tried to auto-review, so a failed spawn is not
# retried every cycle. In-memory only; a restart may retry once, which is fine.
_attempted_shas = {}


def scan_and_start_followups():
    """One pass over the armed queue: start follow-up reviews for new commits."""
    from backend.database import get_queue_db, get_reviews_db
    from backend.extensions import active_reviews, reviews_lock
    from backend.services.auto_verdict_config import get_criteria
    from backend.services.github_service import fetch_pr_state_and_sha
    from backend.services.review_service import begin_review

    if not get_criteria().get("autoFollowupReview"):
        return

    armed = [item for item in get_queue_db().get_queue() if item.get("auto_verdict_enabled")]
    if not armed:
        return

    reviews_db = get_reviews_db()
    for item in armed:
        repo_full = item["repo"]
        pr_number = item["pr_number"]
        parts = repo_full.split("/")
        if len(parts) != 2:
            continue
        owner, repo = parts
        key = f"{owner}/{repo}/{pr_number}"

        with reviews_lock:
            running = key in active_reviews and active_reviews[key]["status"] == "running"
        if running:
            continue

        latest_review = reviews_db.get_latest_review_for_pr(repo_full, pr_number)
        if not latest_review:
            continue  # never reviewed — auto reviews are follow-ups only
        last_reviewed_sha = latest_review.get("head_commit_sha")
        if not last_reviewed_sha:
            # Unknown baseline (SHA capture failed at save time). Triggering here
            # could re-review without any new commits, so leave it to the human.
            continue

        pr_state, current_sha = fetch_pr_state_and_sha(owner, repo, pr_number)
        if not current_sha or current_sha == last_reviewed_sha:
            continue
        if pr_state and pr_state != "OPEN":
            continue
        if _attempted_shas.get(key) == current_sha:
            continue

        _attempted_shas[key] = current_sha
        reviewer_type = item.get("auto_verdict_reviewer") or "default"
        logger.info(
            f"Auto follow-up review: new commits on {key} "
            f"({last_reviewed_sha[:9]} -> {current_sha[:9]}), starting {reviewer_type} review"
        )
        payload, status = begin_review(
            owner, repo, pr_number, item["pr_url"], reviews_db,
            is_followup=True,
            pr_title=item.get("pr_title"),
            pr_author=item.get("pr_author"),
            reviewer_type=reviewer_type,
        )
        if status != 201:
            logger.error(f"Auto follow-up review failed to start for {key}: {payload.get('error')}")


def auto_review_watcher_loop(interval=WATCH_INTERVAL_SECONDS):
    """Poll armed PRs for new commits until the process exits."""
    logger.info(f"Auto follow-up review watcher started (interval={interval}s)")
    while True:
        try:
            scan_and_start_followups()
        except Exception as e:
            logger.error(f"Auto-review watcher iteration failed: {e}")
        time.sleep(interval)
