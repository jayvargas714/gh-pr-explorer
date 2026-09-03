"""Background worker that drains pending automation dispatches into reviews.

The sync worker only *detects* new PRs (cheap set difference) and records
pending rows in automation_dispatches; this worker does the heavy lifting per
row: fetch changed files -> classify against the routing rules -> start the
routed review -> arm per-PR auto-verdict per the rule. The worker never touches
the merge queue or swimlanes. Keeping dispatch out of the sync cycle
isolates gh latency/failures and gives natural retry + concurrency limiting.

Modeled on auto_review_watcher.py: deferred imports, per-item try/except, the
loop never raises.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _normalize_wait(text):
    """Wait reasons with only digit differences are the same state — a PR going
    from '12 commits behind base' to '13 commits behind base' must not repost."""
    return re.sub(r"\d+", "N", text or "")

WATCH_INTERVAL_SECONDS = 60
MAX_ATTEMPTS = 3
# Rows gate-evaluated per cycle. Larger than the concurrency budget so a PR
# stuck waiting on its conditions never starves ready PRs queued behind it.
EVAL_LIMIT = 20


def _dispatch_window_expired(row, config):
    """True when dispatchTimeoutHours is set and this row has waited past it.

    The clock is enrolled_at, not created_at: requeue (manual re-enroll,
    backfill revive, restart reconciliation) restarts it, so a row that
    expired once gets a full fresh window instead of re-expiring next cycle.
    """
    timeout_hours = config.get("dispatchTimeoutHours", 0)
    if not timeout_hours:
        return False
    enrolled = row.get("enrolled_at")
    if not enrolled:
        return False
    try:
        enrolled_dt = datetime.fromisoformat(str(enrolled))
    except ValueError:
        return False
    if enrolled_dt.tzinfo is None:
        enrolled_dt = enrolled_dt.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - enrolled_dt).total_seconds() / 3600
    return age_hours > timeout_hours


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

    Conditions: the PR targets the required base branch (when configured),
    CI completed and passing (when required; a PR with no checks at all
    passes), and the branch at most maxBehindBase commits behind its base
    head. State/draft gating happens earlier in _process_one.

    The base gate waits rather than skips: a stacked PR is typically retargeted
    to main once its parent merges, and the pending row picks it up then.
    """
    from backend.services.github_service import fetch_pr_behind_by
    from backend.services.pr_service import get_ci_status

    required_base = (config.get("requireBaseBranch") or "").strip()
    if required_base:
        pr_base = pr.get("baseRefName")
        if not pr_base:
            # Unknown base: don't dispatch blind against the requirement.
            return "base branch unknown"
        if pr_base != required_base:
            return f"base branch is {pr_base}, not {required_base}"

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
    from backend.database import (
        get_automation_dispatches_db, get_auto_verdict_arming_db, get_reviews_db,
    )
    from backend.services.automation_service import classify_files
    from backend.services.github_service import fetch_pr_files
    from backend.services.pr_status_comments import (
        post_automation_enrolled_comment,
        post_automation_failed_comment,
        post_automation_unidentified_comment,
        post_automation_waiting_comment,
        post_automation_window_expired_comment,
    )
    from backend.services.review_service import begin_review

    dispatches = get_automation_dispatches_db()
    repo_full = row["repo"]
    pr_number = row["pr_number"]

    # Config may have changed since detection.
    if repo_full not in config["repoAllowlist"]:
        dispatches.set_status(row["id"], "skipped", detail="repo no longer allowlisted")
        return False

    owner_repo = repo_full.split("/", 1)
    if len(owner_repo) != 2:
        dispatches.set_status(row["id"], "failed", detail=f"malformed repo: {repo_full}")
        return False
    owner, repo = owner_repo

    if _dispatch_window_expired(row, config):
        dispatches.set_status(
            row["id"], "skipped",
            detail=f"dispatch window expired ({config['dispatchTimeoutHours']}h)",
        )
        logger.info(f"Automation: {repo_full}#{pr_number} skipped — dispatch window expired")
        post_automation_window_expired_comment(
            owner, repo, pr_number, timeout_hours=config["dispatchTimeoutHours"])
        return False

    def _retry_or_fail(detail):
        attempts = dispatches.increment_attempts(row["id"])
        if attempts >= MAX_ATTEMPTS:
            dispatches.set_status(row["id"], "failed", detail=detail)
            logger.error(f"Automation: giving up on {repo_full}#{pr_number} after "
                         f"{attempts} attempts: {detail}")
            post_automation_failed_comment(
                owner, repo, pr_number, attempts=attempts, detail=detail)
        else:
            logger.warning(f"Automation: attempt {attempts} failed for "
                           f"{repo_full}#{pr_number}, will retry: {detail}")

    try:
        pr = _get_pr_metadata(repo_full, pr_number)
    except Exception as e:
        _retry_or_fail(f"metadata fetch failed: {e}")
        return False

    def _wait(reason):
        """Keep the row pending (rows wait as long as the PR stays open), and
        clear the attempt counter: a clean waiting evaluation proves the row is
        healthy, so transient errors over a long wait can't add up to failed.

        Announces the wait on the PR only when the blocking reason actually
        changed (digit-insensitively), so a PR parked on the same gate for
        hours is commented once, not every cycle."""
        if _normalize_wait(f"waiting: {reason}") != _normalize_wait(row.get("detail")):
            post_automation_waiting_comment(owner, repo, pr_number, reason=reason)
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

    # A row the worker has never touched (fresh from the sync worker or a
    # manual enroll — backfilled and requeued rows carry a detail) gets its
    # enrollment announced once the PR is confirmed open. Bulk backfills mark
    # their rows so a seeding run can't blast comments onto every open PR.
    if row.get("detail") is None and not row.get("attempts"):
        post_automation_enrolled_comment(owner, repo, pr_number)

    # Drafts stay pending (so the ready transition is caught) but are not
    # gated or routed until non-draft.
    if queue_data.get("isDraft"):
        _wait("PR is a draft")
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
        post_automation_unidentified_comment(
            owner, repo, pr_number,
            matched_rules=result["matched_rules"],
            unmatched_count=result["unmatched_count"])
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
        # PR with no review.
        if rule.get("autoVerdict"):
            get_auto_verdict_arming_db().set_arming(
                repo_full, pr_number, True, reviewer_key, mode=rule.get("autoVerdictMode"),
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
    elif status == 429:
        # begin_review's own budget gate refused (another path raced us past
        # the budget between our count and the spawn). Not a failure: the row
        # stays pending for the next cycle.
        _wait("concurrency budget full")
    else:
        _retry_or_fail(f"begin_review failed ({status}): {payload.get('error')}")
    return False


def process_pending_dispatches():
    """One pass over pending dispatch rows, within the concurrency budget."""
    from backend.database import get_automation_dispatches_db
    from backend.services.automation_config import get_config
    from backend.services.review_service import count_running_reviews

    config = get_config()
    if config["scope"] == "off":
        return

    # All running reviews count against the budget — manual ones included —
    # so total review concurrency stays bounded, not just the auto slice.
    budget = config["maxConcurrentAutoReviews"] - count_running_reviews()
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
    from backend.services.review_service import sweep_stale_workspaces

    logger.info(f"Automation dispatch worker started (interval={interval}s)")
    while True:
        try:
            # Piggybacked here (rather than a thread of its own) because this
            # loop runs unconditionally; the sweep itself never raises.
            sweep_stale_workspaces()
            process_pending_dispatches()
        except Exception as e:
            logger.error(f"Automation dispatch worker iteration failed: {e}")
        time.sleep(interval)
