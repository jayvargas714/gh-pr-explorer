"""Review-request trigger: turn "X requested a review from <me>" into pipeline work.

Detection is a pure diff of the synced PR blobs (see pr_sync_worker); routing
sends the request through the automation pipeline so every auto review — first
or follow-up — obeys the same dispatch gates:

    dispatch row      action
    ----------------  -----------------------------------------------------------
    none              enroll (pending, detail "review requested")
    pending           nothing — already waiting on gates
    skipped/failed    requeue (overrides manual opt-out; a request is newer intent)
    unidentified      comment only — routing stays a human decision
    dispatched        queue a follow-up in review_requests; the dispatch worker
                      fulfils it regardless of arming

Author scope is deliberately ignored (a human asked explicitly); the scope kill
switch and the repo allowlist still apply.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

REQUEST_DETAIL = "review requested"


def _requested_logins(pr_row: Optional[Dict[str, Any]]) -> set:
    requests = (pr_row or {}).get("reviewRequests") or []
    return {
        r.get("login") for r in requests
        if isinstance(r, dict) and r.get("__typename", "User") == "User" and r.get("login")
    }


def review_requested_from(pr_row: Optional[Dict[str, Any]], login: Optional[str]) -> bool:
    """True when `login` is currently a requested reviewer on the PR blob
    (gh pr view / pr list `reviewRequests`). Badge helper; no gh calls."""
    return bool(login) and login in _requested_logins(pr_row)


def detect_new_review_requests(old_rows: Dict[int, Dict[str, Any]],
                               new_rows: Dict[int, Dict[str, Any]],
                               login: Optional[str]) -> List[int]:
    """PR numbers where `login` appears in reviewRequests now but not before.

    Rows are SyncedPRsDB rows (the gh pr view blob). A PR absent from old_rows
    counts as "not requested before", so a first-seen PR with a pending request
    is detected too.
    """
    if not login:
        return []
    hits = []
    for number, new_row in new_rows.items():
        if login in _requested_logins(new_row) and login not in _requested_logins(old_rows.get(number)):
            hits.append(number)
    return sorted(hits)


def handle_review_request(repo_full: str, pr_number: int, pr_row: Dict[str, Any]) -> None:
    """Route one detected review request into the pipeline. Never raises."""
    try:
        _handle(repo_full, pr_number)
    except Exception:
        logger.exception(f"Review request handling failed for {repo_full}#{pr_number}")


def _handle(repo_full: str, pr_number: int) -> None:
    from backend.database import get_automation_dispatches_db, get_review_requests_db
    from backend.services import pr_status_comments
    from backend.services.automation_config import get_config

    config = get_config()
    if config["scope"] == "off" or repo_full not in config["repoAllowlist"]:
        logger.info(f"Review request on {repo_full}#{pr_number} ignored: automation off "
                    f"or repo not allowlisted")
        return

    owner, repo = repo_full.split("/", 1)
    dispatches = get_automation_dispatches_db()
    row = dispatches.get_by_pr(repo_full, pr_number)

    if row is None:
        cap = config.get("maxPipelineSize", 1000)
        if dispatches.count_pending() >= cap:
            logger.warning(f"Review request on {repo_full}#{pr_number} not enrolled: "
                           f"pipeline at maxPipelineSize ({cap})")
            return
        dispatches.record_candidate(repo_full, pr_number)
        fresh = dispatches.get_by_pr(repo_full, pr_number)
        # A detail suppresses the worker's generic enrolled comment; ours is posted here.
        dispatches.set_status(fresh["id"], "pending", detail=REQUEST_DETAIL)
        logger.info(f"Review request enrolled {repo_full}#{pr_number} in the pipeline")
        pr_status_comments.post_review_requested_enrolled_comment(
            owner, repo, pr_number, reenrolled=False)
        return

    status = row["status"]
    if status == "pending":
        return
    if status in ("skipped", "failed"):
        dispatches.requeue(row["id"], detail=REQUEST_DETAIL)
        logger.info(f"Review request re-enrolled {repo_full}#{pr_number} (was {status})")
        pr_status_comments.post_review_requested_enrolled_comment(
            owner, repo, pr_number, reenrolled=True)
        return
    if status == "unidentified":
        pr_status_comments.post_review_requested_unidentified_comment(owner, repo, pr_number)
        return
    # dispatched: a follow-up is wanted; the dispatch worker fulfils it under the gates.
    if get_review_requests_db().record(repo_full, pr_number):
        logger.info(f"Review request queued a follow-up for {repo_full}#{pr_number}")
        pr_status_comments.post_review_requested_followup_queued_comment(owner, repo, pr_number)
