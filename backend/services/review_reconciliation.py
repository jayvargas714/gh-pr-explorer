"""Startup reconciliation of orphaned review runs.

A service restart wipes the in-memory active_reviews registry and kills the
Claude CLI subprocesses it was tracking, so any review in flight (or waiting
out a retry backoff) is silently lost: its run has a `started` event but no
terminal event, no review row, and nothing left to retry it. Because the
automation ledger already says `dispatched`, the pipeline would never touch
the PR again either.

reconcile_orphaned_reviews() runs once at startup, before the watcher threads:
each orphaned run is closed with a `cancelled` event (reason "orphaned") so
the Review Logs tab tells the truth, any leftover subprocess is terminated,
and the review is restarted — auto-dispatched PRs by requeueing their dispatch
row (the worker re-dispatches with routing, arming, and the concurrency
budget), manual runs directly via begin_review with the recorded spawn facts.
Runs whose PR already has a newer completed review (e.g. the follow-up watcher
recovered it) or whose PR is no longer open are closed without a restart.
"""

import logging
import os
import signal
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _kill_if_alive(pid):
    """Best-effort SIGTERM for a leftover CLI process from the previous run."""
    if not pid:
        return
    try:
        os.kill(int(pid), signal.SIGTERM)
        logger.info(f"Terminated leftover review process (PID {pid})")
    except (ProcessLookupError, PermissionError, ValueError, OSError):
        pass


def _parse_ts(value):
    """Parse either timestamp format in play (ISO with tz, or naive UTC)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _has_newer_completed_review(reviews_db, repo_full, pr_number, orphan_started_at):
    latest = reviews_db.get_latest_review_for_pr(repo_full, pr_number)
    if not latest or latest.get("status") != "completed":
        return False
    review_ts = _parse_ts(latest.get("review_timestamp"))
    orphan_ts = _parse_ts(orphan_started_at)
    if review_ts is None or orphan_ts is None:
        return False
    return review_ts >= orphan_ts


def reconcile_orphaned_reviews():
    """Close and restart review runs lost to a restart. Never raises.

    Returns:
        dict: counts — orphans found, requeued (auto), restarted (manual),
        already_recovered, pr_closed, errors.
    """
    from backend.database import (
        get_automation_dispatches_db,
        get_review_events_db,
        get_reviews_db,
    )
    from backend.services.review_event_log import REASON_ORPHANED, record_cancelled

    summary = {"orphans": 0, "requeued": 0, "restarted": 0,
               "already_recovered": 0, "pr_closed": 0, "errors": 0}
    try:
        orphans = get_review_events_db().get_orphaned_runs()
    except Exception:
        logger.exception("Startup reconciliation could not scan for orphaned runs")
        return summary

    summary["orphans"] = len(orphans)
    if not orphans:
        return summary

    logger.warning(f"Startup reconciliation: {len(orphans)} orphaned review run(s) found")
    reviews_db = get_reviews_db()
    dispatches = get_automation_dispatches_db()

    for run in orphans:
        repo_full = run["repo"]
        pr_number = run["pr_number"]
        key = f"{repo_full}#{pr_number}"
        try:
            _kill_if_alive(run.get("pid"))
            record_cancelled(
                run["run_id"], repo_full, pr_number,
                attempt=run.get("attempt"),
                reason=REASON_ORPHANED,
                detail="review lost in a service restart",
            )

            if _has_newer_completed_review(reviews_db, repo_full, pr_number,
                                           run.get("created_at")):
                summary["already_recovered"] += 1
                logger.info(f"Orphaned run on {key}: newer completed review exists — closed only")
                continue

            parts = repo_full.split("/")
            if len(parts) != 2:
                summary["errors"] += 1
                continue
            owner, repo = parts

            from backend.services.github_service import fetch_pr_state
            pr_state = fetch_pr_state(owner, repo, pr_number)
            if pr_state and pr_state != "OPEN":
                summary["pr_closed"] += 1
                logger.info(f"Orphaned run on {key}: PR is {pr_state} — closed only")
                continue

            dispatch_row = dispatches.get_by_pr(repo_full, pr_number)
            if dispatch_row and dispatch_row["status"] == "dispatched":
                # The pipeline owns this PR: requeue so the worker re-dispatches
                # with routing, verdict arming, and the concurrency budget.
                dispatches.requeue(dispatch_row["id"],
                                   detail="requeued after restart (orphaned review)")
                summary["requeued"] += 1
                logger.info(f"Orphaned run on {key}: dispatch row requeued")
                continue

            from backend.services.review_service import begin_review
            payload, status = begin_review(
                owner, repo, pr_number,
                f"https://github.com/{repo_full}/pull/{pr_number}",
                reviews_db,
                is_followup=bool(run.get("is_followup")),
                reviewer_type=run.get("reviewer_agent") or "default",
                auto_started=bool(run.get("auto_started")),
            )
            if status == 201:
                summary["restarted"] += 1
                logger.info(f"Orphaned run on {key}: review restarted")
            else:
                summary["errors"] += 1
                logger.error(f"Orphaned run on {key}: restart failed ({status}): "
                             f"{payload.get('error')}")
        except Exception:
            summary["errors"] += 1
            logger.exception(f"Startup reconciliation failed for {key}")

    logger.info(
        f"Startup reconciliation done: {summary['requeued']} requeued, "
        f"{summary['restarted']} restarted, {summary['already_recovered']} already recovered, "
        f"{summary['pr_closed']} closed PRs, {summary['errors']} errors"
    )
    return summary
