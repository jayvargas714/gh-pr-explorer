"""Background sync worker for the DB-backed PR list.

Keeps registered repos' PRs fresh using only small, 504-resistant queries:
numbers-only lists to find what changed, then one `gh pr view` per PR to
hydrate. Latency doesn't matter here — the UI serves from SQLite regardless.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from backend.config import get_pr_sync_config
from backend.services.github_service import fetch_full_pr, fetch_pr_numbers

logger = logging.getLogger(__name__)

HYDRATE_WORKERS = 4
# Re-fetch anything updated since last sync minus this slack, so clock skew
# between us and GitHub can't drop an update.
INCREMENTAL_SLACK = timedelta(minutes=10)


def _window_cutoff(history_days):
    return datetime.now(timezone.utc) - timedelta(days=history_days)


def _hydrate(store, repo_full, numbers):
    """Fetch each PR fully and upsert; one PR's failure never blocks the rest."""
    owner, name = repo_full.split("/", 1)

    def one(number):
        try:
            store.upsert_pr(repo_full, fetch_full_pr(owner, name, number))
            return True
        except RuntimeError as e:
            logger.warning(f"PR sync: hydration failed for {repo_full}#{number}: {e}")
            return False

    if not numbers:
        return 0
    with ThreadPoolExecutor(max_workers=HYDRATE_WORKERS) as executor:
        return sum(executor.map(one, numbers))


def backfill_repo(store, repo_full, history_days):
    """First full sync: open PRs first (UI fills fast), then recent closed/merged."""
    owner, name = repo_full.split("/", 1)
    cutoff = _window_cutoff(history_days).strftime("%Y-%m-%d")
    try:
        open_numbers = fetch_pr_numbers(owner, name, state="open")
        _hydrate(store, repo_full, open_numbers)
        closed_numbers = fetch_pr_numbers(
            owner, name, state="all", search=f"is:closed updated:>={cutoff}"
        )
        _hydrate(store, repo_full, [n for n in closed_numbers if n not in set(open_numbers)])
        store.mark_backfill_done(repo_full)
        store.update_last_synced(repo_full)
        logger.info(f"PR sync: backfill complete for {repo_full} ({store.count_prs(repo_full)} PRs)")
    except RuntimeError as e:
        logger.warning(f"PR sync: backfill failed for {repo_full}, will retry next cycle: {e}")
        store.set_backfill_error(repo_full, str(e))


def incremental_sync_repo(store, repo_full, history_days):
    """Re-hydrate PRs updated since the last sync; prune out-of-window rows."""
    owner, name = repo_full.split("/", 1)
    repo_row = store.get_repo(repo_full) or {}
    last = repo_row.get("last_synced_at")
    if last:
        # SQLite CURRENT_TIMESTAMP is UTC "YYYY-MM-DD HH:MM:SS"
        since_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) - INCREMENTAL_SLACK
    else:
        since_dt = _window_cutoff(history_days)
    since = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    numbers = fetch_pr_numbers(owner, name, state="all", search=f"updated:>={since}")
    known = store.get_prs_by_numbers(repo_full, numbers)
    new_numbers = [n for n in numbers if n not in known]
    _hydrate(store, repo_full, numbers)
    _record_automation_candidates(store, repo_full, new_numbers)
    store.prune_old(repo_full, _window_cutoff(history_days).strftime("%Y-%m-%dT%H:%M:%SZ"))
    store.update_last_synced(repo_full)


def _record_automation_candidates(store, repo_full, new_numbers):
    """Record newly-arrived PRs as automation dispatch candidates.

    Only called from incremental sync — backfill is structurally excluded, so
    enabling automation never sweeps a repo's existing PRs. Must never raise
    into the sync cycle.
    """
    if not new_numbers:
        return
    try:
        from backend.services.automation_config import get_config
        from backend.database import get_automation_dispatches_db

        config = get_config()
        if config["scope"] == "off" or repo_full not in config["repoAllowlist"]:
            return

        rows = store.get_prs_by_numbers(repo_full, new_numbers)
        dispatches = get_automation_dispatches_db()
        for number in new_numbers:
            pr = rows.get(number)
            if not pr:
                continue  # hydration failed for this PR; next cycle re-detects it
            # Drafts are recorded on purpose: the dispatch worker's readiness
            # gate holds them until they're marked ready (within the timeout).
            if (pr.get("state") or "").upper() != "OPEN":
                continue
            author = (pr.get("author") or {}).get("login")
            if config["scope"] == "authors" and author not in config["authors"]:
                continue
            if dispatches.record_candidate(repo_full, number):
                logger.info(f"Automation: recorded candidate {repo_full}#{number} (author={author})")
    except Exception:
        logger.exception(f"Automation candidate detection failed for {repo_full}")


def sync_cycle(store=None, cfg=None):
    """One pass over eligible repos. Each repo is isolated; one failure never
    blocks the others."""
    if store is None:
        from backend.database import get_synced_prs_db
        store = get_synced_prs_db()
    cfg = cfg or get_pr_sync_config()
    if not cfg["enabled"]:
        return

    excluded = set(cfg["exclude_repos"])
    repos = [r for r in store.list_repos() if r["repo"] not in excluded]
    repos = repos[: cfg["max_synced_repos"]]

    for repo_row in repos:
        repo_full = repo_row["repo"]
        try:
            if not repo_row["backfill_done"]:
                backfill_repo(store, repo_full, cfg["history_days"])
            else:
                incremental_sync_repo(store, repo_full, cfg["history_days"])
        except Exception:
            logger.exception(f"PR sync: cycle failed for {repo_full}")


def pr_sync_worker_loop():
    """Daemon loop; started from app.py."""
    logger.info("PR sync worker started")
    while True:
        try:
            sync_cycle()
        except Exception:
            logger.exception("PR sync: unexpected cycle error")
        time.sleep(get_pr_sync_config()["poll_interval_seconds"])
