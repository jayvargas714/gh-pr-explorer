"""Background worker that drains pending automation dispatches into reviews.

The sync worker only *detects* new PRs (cheap set difference) and records
pending rows in automation_dispatches; this worker does the heavy lifting per
row: fetch changed files -> classify against the routing rules -> add the PR
to the merge queue and the protected Auto lane -> start the routed review ->
arm per-PR auto-verdict per the rule. Keeping dispatch out of the sync cycle
isolates gh latency/failures and gives natural retry + concurrency limiting.

Modeled on auto_review_watcher.py: deferred imports, per-item try/except, the
loop never raises.
"""

import json
import logging
import time

logger = logging.getLogger(__name__)

WATCH_INTERVAL_SECONDS = 30
MAX_ATTEMPTS = 3


def _count_running_auto_reviews():
    from backend.extensions import active_reviews, reviews_lock

    with reviews_lock:
        return sum(
            1 for entry in active_reviews.values()
            if entry.get("status") == "running" and entry.get("auto_started")
        )


def _ensure_queued_in_auto_lane(pr, repo_full, pr_number):
    """Add the PR to the merge queue (if absent) and place it in the Auto lane.

    Returns the queue item row.
    """
    from backend.database import get_queue_db, get_swimlanes_db

    queue_db = get_queue_db()
    item = queue_db.get_queue_item(pr_number, repo_full)
    if item is None:
        item = queue_db.add_to_queue(
            pr_number=pr_number,
            repo=repo_full,
            pr_title=pr.get("title"),
            pr_author=(pr.get("author") or {}).get("login"),
            pr_url=pr.get("url"),
            additions=pr.get("additions", 0),
            deletions=pr.get("deletions", 0),
            pr_state=pr.get("state"),
        )
    swimlanes_db = get_swimlanes_db()
    auto_lane = swimlanes_db.ensure_auto_lane()
    swimlanes_db.assign_card_to_lane(item["id"], auto_lane["id"])
    return item


def _get_pr_metadata(repo_full, pr_number):
    """PR metadata from the synced store, falling back to a live fetch."""
    from backend.database import get_synced_prs_db
    from backend.services.github_service import fetch_full_pr

    pr = get_synced_prs_db().get_prs_by_numbers(repo_full, [pr_number]).get(pr_number)
    if pr is None:
        owner, repo = repo_full.split("/", 1)
        pr = fetch_full_pr(owner, repo, pr_number)
    if not pr.get("url"):
        pr = dict(pr)
        pr["url"] = f"https://github.com/{repo_full}/pull/{pr_number}"
    return pr


def _process_one(row, config):
    from backend.database import get_automation_dispatches_db, get_queue_db, get_reviews_db
    from backend.services.automation_service import classify_files
    from backend.services.github_service import fetch_pr_files
    from backend.services.review_service import begin_review

    dispatches = get_automation_dispatches_db()
    repo_full = row["repo"]
    pr_number = row["pr_number"]

    # Config may have changed since detection.
    if repo_full not in config["repoAllowlist"]:
        dispatches.set_status(row["id"], "skipped", detail="repo no longer allowlisted")
        return

    def _retry_or_fail(detail):
        attempts = dispatches.increment_attempts(row["id"])
        if attempts >= MAX_ATTEMPTS:
            dispatches.set_status(row["id"], "failed", detail=detail)
            logger.error(f"Automation: giving up on {repo_full}#{pr_number} after "
                         f"{attempts} attempts: {detail}")
        else:
            logger.warning(f"Automation: attempt {attempts} failed for "
                           f"{repo_full}#{pr_number}, will retry: {detail}")

    owner_repo = repo_full.split("/", 1)
    if len(owner_repo) != 2:
        dispatches.set_status(row["id"], "failed", detail=f"malformed repo: {repo_full}")
        return
    owner, repo = owner_repo

    try:
        files = fetch_pr_files(owner, repo, pr_number)
    except Exception as e:
        _retry_or_fail(f"file fetch failed: {e}")
        return

    result = classify_files(files, config)
    outcome_json = json.dumps({
        "outcome": result["outcome"],
        "rule": (result["rule"] or {}).get("name") if result["outcome"] == "matched" else None,
        "matched_rules": result["matched_rules"],
        "unmatched_count": result["unmatched_count"],
        "ignored_count": result["ignored_count"],
    })

    try:
        pr = _get_pr_metadata(repo_full, pr_number)
        item = _ensure_queued_in_auto_lane(pr, repo_full, pr_number)
    except Exception as e:
        _retry_or_fail(f"queue/lane placement failed: {e}")
        return

    if result["outcome"] == "unidentified":
        dispatches.set_status(row["id"], "unidentified", outcome_json=outcome_json,
                              detail="files span multiple rules or mix rule and unmatched files")
        logger.info(f"Automation: {repo_full}#{pr_number} unidentified "
                    f"(rules={result['matched_rules']}, unmatched={result['unmatched_count']})")
        return

    rule = result["rule"]
    reviewer_key = rule["reviewerKey"]
    payload, status = begin_review(
        owner, repo, pr_number, pr.get("url"), get_reviews_db(),
        pr_title=pr.get("title"),
        pr_author=(pr.get("author") or {}).get("login"),
        reviewer_type=reviewer_key,
        auto_started=True,
    )
    if status == 201:
        # Arm only after a successful spawn so a failure never leaves an armed
        # card with no review.
        if rule.get("autoVerdict"):
            get_queue_db().set_auto_verdict(
                pr_number, repo_full, True, reviewer_key, mode=rule.get("autoVerdictMode"),
            )
        dispatches.set_status(row["id"], "dispatched", outcome_json=outcome_json,
                              reviewer_key=reviewer_key)
        logger.info(f"Automation: dispatched {reviewer_key} review for {repo_full}#{pr_number}")
    elif status == 409:
        # A review is already running (e.g. operator started one manually).
        dispatches.set_status(row["id"], "skipped", outcome_json=outcome_json,
                              reviewer_key=reviewer_key,
                              detail="review already in progress")
    else:
        _retry_or_fail(f"begin_review failed ({status}): {payload.get('error')}")


def process_pending_dispatches():
    """One pass over pending dispatch rows, within the concurrency budget."""
    from backend.database import get_automation_dispatches_db
    from backend.services.automation_config import get_config

    config = get_config()
    if config["scope"] == "off":
        return

    budget = config["maxConcurrentAutoReviews"] - _count_running_auto_reviews()
    if budget <= 0:
        return

    for row in get_automation_dispatches_db().get_pending(budget):
        try:
            _process_one(row, config)
        except Exception:
            logger.exception(f"Automation dispatch failed for {row['repo']}#{row['pr_number']}")


def automation_dispatch_worker_loop(interval=WATCH_INTERVAL_SECONDS):
    """Poll pending dispatches until the process exits."""
    logger.info(f"Automation dispatch worker started (interval={interval}s)")
    while True:
        try:
            process_pending_dispatches()
        except Exception as e:
            logger.error(f"Automation dispatch worker iteration failed: {e}")
        time.sleep(interval)
