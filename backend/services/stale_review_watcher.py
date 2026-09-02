"""Background watcher that stops and restarts reviews made stale by new commits.

A running review examines the PR as it stood when the review spawned. When new
commits land mid-run its findings describe code that no longer exists, so each
cycle compares every running review's baseline SHA (snapshotted by begin_review)
against the PR's live head. On a mismatch the review is cancelled (recorded with
reason "stale_commits") and a replacement review starts with the original spawn
parameters — its "review started" comment carries a note explaining the restart.
A standalone "review stopped" comment is posted only when the restart fails.

Complements auto_review_watcher, which handles the other half of the timeline:
new commits arriving *after* a review finished. That watcher skips running
reviews; this one only looks at them, so the two never race for the same PR.
Loop safety: _handled_shas ensures a head SHA that already triggered a
stop/restart is not acted on again if the restart failed; a successful restart
re-baselines the entry to the new SHA anyway.
"""

import logging
import time

logger = logging.getLogger(__name__)

WATCH_INTERVAL_SECONDS = 60

# key -> head SHA we last stopped/restarted for, so a failed restart is not
# retried every cycle. In-memory only; a restart may retry once, which is fine.
_handled_shas = {}


def scan_for_stale_reviews():
    """One pass over running reviews: stop and restart any with new commits."""
    from backend.database import get_reviews_db
    from backend.extensions import active_reviews, reviews_lock
    from backend.services.github_service import fetch_pr_state_and_sha
    from backend.services.review_event_log import REASON_STALE_COMMITS
    from backend.services.review_service import begin_review, cancel_active_review
    from backend.services.pr_status_comments import post_review_stopped_stale_comment

    # Snapshot under the lock; the gh calls below must not stall review polls.
    with reviews_lock:
        candidates = [
            (key, review["head_sha_at_start"], dict(review.get("spawn") or {}),
             review.get("pr_title"), review.get("pr_author"),
             review.get("auto_started", False))
            for key, review in active_reviews.items()
            if review.get("status") == "running" and review.get("head_sha_at_start")
        ]

    for key, started_sha, spawn, pr_title, pr_author, auto_started in candidates:
        parts = key.split("/")
        if len(parts) != 3 or not spawn.get("pr_url"):
            continue
        owner, repo, pr_number_str = parts
        try:
            pr_number = int(pr_number_str)
        except ValueError:
            continue

        pr_state, current_sha = fetch_pr_state_and_sha(owner, repo, pr_number)
        if not current_sha or current_sha == started_sha:
            continue
        if pr_state and pr_state != "OPEN":
            continue
        if _handled_shas.get(key) == current_sha:
            continue

        _handled_shas[key] = current_sha
        detail = f"new commits {started_sha[:8]} -> {current_sha[:8]}"
        logger.info(f"Stale review on {key}: {detail} — stopping and restarting")

        # require_running: if the review finished between the snapshot and now,
        # its result is legitimately saved — leave the follow-up decision to
        # auto_review_watcher rather than discard a completed review.
        result = cancel_active_review(
            key, reason=REASON_STALE_COMMITS, detail=detail, require_running=True,
        )
        if result != "cancelled":
            logger.info(f"Stale review on {key} not cancelled ({result}) — skipping restart")
            continue

        reviewer_type = spawn.get("reviewer_type", "default")

        # bypass_budget: this replaces the run cancelled just above, so it
        # never raises concurrency — gating it could turn a stop/restart into
        # a stop-only and silently drop the review. On success the replacement
        # review's started comment carries the restart story in its note; the
        # standalone "stopped" comment is reserved for a failed restart.
        payload, status = begin_review(
            owner, repo, pr_number, spawn["pr_url"], get_reviews_db(),
            is_followup=spawn.get("is_followup", False),
            pr_title=pr_title,
            pr_author=pr_author,
            reviewer_type=reviewer_type,
            auto_started=auto_started,
            bypass_budget=True,
            comment_note=(
                f"restarted after new commits (`{started_sha[:8]}` → "
                f"`{current_sha[:8]}`) made the running review stale"
            ),
        )
        if status != 201:
            logger.error(f"Stale-review restart failed to start for {key}: {payload.get('error')}")
            post_review_stopped_stale_comment(
                owner, repo, pr_number,
                old_sha=started_sha, new_sha=current_sha, reviewer_type=reviewer_type,
            )


def stale_review_watcher_loop(interval=WATCH_INTERVAL_SECONDS):
    """Poll running reviews for new commits until the process exits."""
    logger.info(f"Stale-review watcher started (interval={interval}s)")
    while True:
        try:
            scan_for_stale_reviews()
        except Exception as e:
            logger.error(f"Stale-review watcher iteration failed: {e}")
        time.sleep(interval)
