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

WATCH_INTERVAL_SECONDS = 60
MAX_ATTEMPTS = 3
# Rows gate-evaluated per cycle. Larger than the concurrency budget so a PR
# stuck waiting on its conditions never starves ready PRs queued behind it.
EVAL_LIMIT = 20


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


def _dispatch_blocker(config, queue_data, pr, owner, repo, pr_number):
    """The reason this PR cannot be reviewed yet, or None when all conditions hold.

    Conditions: CI completed and passing (when required; a PR with no checks at
    all passes) and the branch at most maxBehindBase commits behind its base
    head. State/draft gating happens earlier in _process_one, before the PR is
    placed on the board.
    """
    from backend.services.github_service import fetch_pr_behind_by
    from backend.services.pr_service import get_ci_status

    if config.get("requireCiPass", True):
        ci = get_ci_status(queue_data.get("statusCheckRollup"))
        if ci in ("pending", "failure"):
            return f"CI {ci}"
    base_ref, head_ref = pr.get("baseRefName"), pr.get("headRefName")
    if base_ref and head_ref:
        try:
            behind = fetch_pr_behind_by(owner, repo, base_ref, head_ref)
        except Exception as e:
            logger.warning(f"Automation: divergence check failed for {owner}/{repo}#{pr_number}: {e}")
            return "divergence check failed"
        max_behind = config.get("maxBehindBase", 10)
        if behind > max_behind:
            return f"{behind} commits behind base (max {max_behind})"
    return None


def _repo_open_prs(cache, repo_full):
    """Per-cycle cache of one batched open-PR fetch per repo.

    The gate data for every pending row in a repo comes from a single
    `gh pr list` call — per-row `gh pr view` polling burned ~half the shared
    GraphQL rate limit on its own. None means the fetch failed (unknown, not
    "no open PRs").
    """
    if repo_full not in cache:
        from backend.services.github_service import fetch_open_prs_queue_data
        owner, repo = repo_full.split("/", 1)
        cache[repo_full] = fetch_open_prs_queue_data(owner, repo)
    return cache[repo_full]


def _process_one(row, config, batch_cache):
    """Handle one pending dispatch row. Returns True when a review was started."""
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
        return False

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
        return False
    owner, repo = owner_repo

    try:
        pr = _get_pr_metadata(repo_full, pr_number)
    except Exception as e:
        _retry_or_fail(f"metadata fetch failed: {e}")
        return False

    def _wait(reason):
        """Keep the row pending (rows wait as long as the PR stays open), and
        clear the attempt counter: a clean waiting evaluation proves the row is
        healthy, so transient errors over a long wait can't add up to failed."""
        dispatches.set_status(row["id"], "pending", detail=f"waiting: {reason}")
        if row.get("attempts"):
            dispatches.reset_attempts(row["id"])

    open_prs = _repo_open_prs(batch_cache, repo_full)
    if open_prs is None:
        # Batch fetch failed; don't let a transient failure look like
        # "no draft flag, no CI" and dispatch blind — or worse, like an empty
        # repo and mass-skip the pipeline.
        _wait("PR status check failed")
        return False
    queue_data = open_prs.get(pr_number)
    if queue_data is None:
        # Absent from a successful open-PR listing: closed or merged.
        dispatches.set_status(row["id"], "skipped", detail="PR is not open (closed or merged)")
        return False

    # Drafts wait off the board: they stay pending (so the ready transition is
    # caught) but are not queued or placed in the Auto lane until non-draft.
    if queue_data.get("isDraft"):
        _wait("PR is a draft")
        return False

    # Queue + lane placement happens before the remaining gates so a non-draft
    # waiting PR is visible on the board (Auto lane, ⏳ badge) while its
    # conditions settle.
    try:
        item = _ensure_queued_in_auto_lane(pr, repo_full, pr_number)
    except Exception as e:
        _retry_or_fail(f"queue/lane placement failed: {e}")
        return False

    blocker = _dispatch_blocker(config, queue_data, pr, owner, repo, pr_number)
    if blocker:
        _wait(blocker)
        return False

    try:
        files = fetch_pr_files(owner, repo, pr_number)
    except Exception as e:
        _retry_or_fail(f"file fetch failed: {e}")
        return False

    result = classify_files(files, config)
    outcome_json = json.dumps({
        "outcome": result["outcome"],
        "rule": (result["rule"] or {}).get("name") if result["outcome"] == "matched" else None,
        "matched_rules": result["matched_rules"],
        "unmatched_count": result["unmatched_count"],
        "ignored_count": result["ignored_count"],
    })

    if result["outcome"] == "unidentified":
        dispatches.set_status(row["id"], "unidentified", outcome_json=outcome_json,
                              detail="files span multiple rules or mix rule and unmatched files")
        logger.info(f"Automation: {repo_full}#{pr_number} unidentified "
                    f"(rules={result['matched_rules']}, unmatched={result['unmatched_count']})")
        return False

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
        return True
    elif status == 409:
        # A review is already running (e.g. operator started one manually).
        dispatches.set_status(row["id"], "skipped", outcome_json=outcome_json,
                              reviewer_key=reviewer_key,
                              detail="review already in progress")
    else:
        _retry_or_fail(f"begin_review failed ({status}): {payload.get('error')}")
    return False


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

    # Evaluate more rows than the budget: waiting rows return without starting
    # a review, so a ready row behind them still dispatches this cycle.
    # batch_cache scopes the one-fetch-per-repo gate data to this cycle.
    started = 0
    batch_cache = {}
    for row in get_automation_dispatches_db().get_pending(max(budget, EVAL_LIMIT)):
        if started >= budget:
            break
        try:
            if _process_one(row, config, batch_cache):
                started += 1
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
