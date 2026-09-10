"""Background sync worker for the DB-backed PR list.

Keeps registered repos' PRs fresh using only small, 504-resistant queries:
numbers-only lists to find what changed, then one `gh pr view` per PR to
hydrate. Latency doesn't matter here — the UI serves from SQLite regardless.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from backend.config import DEFAULT_PR_SYNC, get_pr_sync_config
from backend.services import analytics_rollup
from backend.services.github_service import (
    fetch_commits_page, fetch_full_pr, fetch_graphql_remaining, fetch_pr_numbers,
    fetch_repo_created_at, get_authenticated_login,
)

logger = logging.getLogger(__name__)

HYDRATE_WORKERS = 4
# Hard cap on the number of history windows walked per history_backfill_slice
# call, independent of the hydration budget: a long run of empty windows
# (nothing to hydrate) would otherwise let the walk issue an unbounded
# number of searches in a single sync cycle.
MAX_HISTORY_WINDOWS_PER_CYCLE = 12
# Re-fetch anything updated since last sync minus this slack, so clock skew
# between us and GitHub can't drop an update.
INCREMENTAL_SLACK = timedelta(minutes=10)
# Used when a repo's creation date can't be fetched, so the inception walk
# still has a floor to walk down to (GitHub's own founding year).
GENESIS_FALLBACK = "2008-01-01T00:00:00Z"


def _window_cutoff(history_days):
    return datetime.now(timezone.utc) - timedelta(days=history_days)


def _tomorrow_utc_date_str():
    """Tomorrow's UTC date (YYYY-MM-DD), used as the inception-walk cursor's
    starting point so the first window ends today."""
    return (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")


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
        # Stamp the history-walk cursor at tomorrow (UTC) so the inception
        # walk's first window ends today; history_done stays separate from
        # backfill_done, which only gates the PR-list DB path.
        store.set_history_cursor(repo_full, _tomorrow_utc_date_str())
        store.update_last_synced(repo_full)
        logger.info(f"PR sync: backfill complete for {repo_full} ({store.count_prs(repo_full)} PRs)")
    except RuntimeError as e:
        logger.warning(f"PR sync: backfill failed for {repo_full}, will retry next cycle: {e}")
        store.set_backfill_error(repo_full, str(e))


def incremental_sync_repo(store, repo_full, history_days, retain_days=0):
    """Re-hydrate PRs updated since the last sync; prune out-of-window rows
    only when retain_days > 0 (0 means keep forever)."""
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
    _record_review_requests(store, repo_full, numbers, known)
    if retain_days > 0:
        store.prune_old(repo_full, _window_cutoff(retain_days).strftime("%Y-%m-%dT%H:%M:%SZ"))
    store.update_last_synced(repo_full)
    return len(numbers)


def history_backfill_slice(store, repo_full, cfg):
    """Walk one paced slice of the inception history backward from the
    history cursor, hydrating closed/merged PRs the fast backfill skipped.

    Never touches review-request detection or automation candidates: these
    rows are old, so neither hook applies (same exclusion as backfill_repo).
    """
    state = store.get_history_state(repo_full)
    if state["history_done"]:
        return 0
    cursor = state["history_cursor"]
    if cursor is None:
        # Repos that finished the fast backfill before this cursor stamping
        # existed (every pre-deploy repo) would otherwise never start the
        # inception walk. sync_cycle only reaches this function once
        # backfill_done is already true, so it's safe to initialize here and
        # continue the walk in this same call.
        cursor = _tomorrow_utc_date_str()
        store.set_history_cursor(repo_full, cursor)

    owner, name = repo_full.split("/", 1)

    repo_created_at = state["repo_created_at"]
    if not repo_created_at:
        repo_created_at = fetch_repo_created_at(owner, name) or GENESIS_FALLBACK
        store.set_repo_created_at(repo_full, repo_created_at)

    min_remaining = cfg.get("min_graphql_remaining", DEFAULT_PR_SYNC["min_graphql_remaining"])
    remaining = fetch_graphql_remaining()
    if remaining is not None and remaining < min_remaining:
        logger.info(f"PR sync: history backfill for {repo_full} skipped, "
                    f"GraphQL quota low ({remaining} < {min_remaining})")
        return 0

    floor_date = datetime.strptime(repo_created_at[:10], "%Y-%m-%d").date()
    cursor_date = datetime.strptime(cursor, "%Y-%m-%d").date()
    budget = cfg.get("history_backfill_budget", DEFAULT_PR_SYNC["history_backfill_budget"])
    chunk_days = max(1, cfg.get("history_chunk_days", DEFAULT_PR_SYNC["history_chunk_days"]))
    total = 0
    windows_walked = 0

    try:
        while budget > 0 and cursor_date > floor_date and windows_walked < MAX_HISTORY_WINDOWS_PER_CYCLE:
            windows_walked += 1
            end = cursor_date - timedelta(days=1)
            start = max(cursor_date - timedelta(days=chunk_days), floor_date)

            while True:
                search = f"is:closed created:{start.isoformat()}..{end.isoformat()}"
                numbers = fetch_pr_numbers(owner, name, state="all", search=search)
                span_days = (end - start).days
                if len(numbers) >= 1000 and span_days > 0:
                    half = span_days // 2 + span_days % 2
                    start = start + timedelta(days=half)
                    continue
                if len(numbers) >= 1000:
                    logger.warning(f"PR sync: history window {repo_full} {search} "
                                    f"still capped at 1000 results; continuing anyway")
                break

            known = store.get_states_by_numbers(repo_full, numbers)
            todo = [n for n in numbers if known.get(n) not in ("CLOSED", "MERGED")]
            hydrate_now = todo[:budget]
            done = _hydrate(store, repo_full, hydrate_now)
            budget -= len(hydrate_now)
            total += done

            if len(todo) > len(hydrate_now):
                break  # window not fully covered; re-run it next cycle

            store.set_history_cursor(repo_full, start.isoformat())
            cursor_date = start

        if cursor_date <= floor_date:
            store.mark_history_done(repo_full)
            logger.info(f"PR sync: history backfill complete for {repo_full}")
    except RuntimeError as e:
        store.set_history_error(repo_full, str(e))
        logger.warning(f"PR sync: history backfill slice failed for {repo_full}: {e}")

    return total


def _record_review_requests(store, repo_full, numbers, old_rows):
    """Route GitHub review requests addressed to the authenticated user.

    Two feeds, both free of gh calls: diffing the pre-hydration rows against the
    fresh ones catches a request the moment it appears; sweeping every open row
    for a standing request the pipeline is not tracking catches the ones the
    diff cannot see (requests predating the detector, or re-requests GitHub
    records as remove+add between two syncs). Only called from incremental sync
    — never from backfill. Must never raise into the sync cycle.
    """
    try:
        from backend.services.review_request_service import (
            detect_new_review_requests, handle_review_request, untracked_review_requests,
        )

        login = get_authenticated_login()
        if not login:
            return
        new_rows = store.get_prs_by_numbers(repo_full, numbers)
        handled = set()
        for number in detect_new_review_requests(old_rows, new_rows, login):
            logger.info(f"Review request for {login} detected on {repo_full}#{number}")
            handle_review_request(repo_full, number, new_rows[number])
            handled.add(number)

        open_rows = {pr["number"]: pr for pr in store.get_prs(repo_full, {"OPEN"})}
        for number in untracked_review_requests(repo_full, open_rows, login):
            if number in handled:
                continue
            logger.info(f"Standing review request for {login} on {repo_full}#{number} "
                        f"is not tracked by the pipeline; routing it")
            handle_review_request(repo_full, number, open_rows[number])
    except Exception:
        logger.exception(f"Review request detection failed for {repo_full}")


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

        # Pipeline cap: at maxPipelineSize pending rows, refuse new candidates
        # rather than grow without bound. Protection over completeness — a PR
        # refused here is not retroactively enrolled when space frees up, but
        # the backfill script can enroll stragglers on demand.
        cap = config.get("maxPipelineSize", 1000)
        headroom = cap - dispatches.count_pending()
        for number in new_numbers:
            if headroom <= 0:
                logger.warning(
                    f"Automation: pipeline at maxPipelineSize ({cap}); "
                    f"not enrolling {repo_full}#{number}"
                )
                continue
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
                headroom -= 1
                logger.info(f"Automation: recorded candidate {repo_full}#{number} (author={author})")
    except Exception:
        logger.exception(f"Automation candidate detection failed for {repo_full}")


def _commit_backfill_branch(commits_db, repo_full, owner, name, branch, bs, pages_cap):
    """Page backward through a branch's commit history via REST.

    Once established, `until` anchors the whole page walk (paging is
    relative to it) so a push landing mid-walk can't shift later pages and
    silently drop commits; only the checkpoint written for the *next* cycle
    moves. On the very first cycle there is no anchor yet, so page 1 runs
    with until=None to observe the branch's true HEAD. Its max is then fixed
    as this cycle's anchor for every remaining page AND written immediately
    as the last_committed_at high-water mark -- before any further page is
    fetched, so a later page's failure can't leave last_committed_at NULL.
    """
    until = bs.get("backfill_until")
    existing_last = bs.get("last_committed_at")
    first_cycle = existing_last is None
    page_anchor = until
    total = 0
    cycle_max = None

    for page in range(1, pages_cap + 1):
        rows = fetch_commits_page(owner, name, branch, page, until=page_anchor)
        if rows:
            commits_db.upsert_commits(repo_full, branch, rows)
            total += len(rows)
            committed_ats = [r["committed_at"] for r in rows]
            min_committed = min(committed_ats)
            max_committed = max(committed_ats)
            cycle_max = max_committed if cycle_max is None else max(cycle_max, max_committed)

        if not rows or len(rows) < 100:
            last_committed_at = cycle_max
            if existing_last and (last_committed_at is None or existing_last > last_committed_at):
                last_committed_at = existing_last
            commits_db.upsert_branch_state(
                repo_full, branch, backfill_done=1, backfill_until=None,
                last_committed_at=last_committed_at, error=None,
            )
            return total

        if page == 1 and first_cycle:
            page_anchor = max_committed
            existing_last = max_committed
            commits_db.upsert_branch_state(
                repo_full, branch, last_committed_at=max_committed, error=None,
            )

        commits_db.upsert_branch_state(repo_full, branch, backfill_until=min_committed, error=None)

    return total


def _commit_incremental_branch(commits_db, repo_full, owner, name, branch, bs, pages_cap):
    """Re-fetch commits since the last high-water mark (minus clock slack).

    A backlog bigger than pages_cap*100 commits exits the loop by exhausting
    the per-cycle page budget rather than hitting a short page; last_committed_at
    still advances to what was seen (single since-based walk, per design), but
    a WARNING is logged so the gap is observable rather than silent.
    """
    last_committed_at = bs.get("last_committed_at")
    since = None
    if last_committed_at:
        since_dt = datetime.strptime(last_committed_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc) - INCREMENTAL_SLACK
        since = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    total = 0
    max_seen = last_committed_at
    hit_cap = True
    for page in range(1, pages_cap + 1):
        rows = fetch_commits_page(owner, name, branch, page, since=since)
        if rows:
            commits_db.upsert_commits(repo_full, branch, rows)
            total += len(rows)
            page_max = max(r["committed_at"] for r in rows)
            if max_seen is None or page_max > max_seen:
                max_seen = page_max
        if not rows or len(rows) < 100:
            hit_cap = False
            break

    if hit_cap:
        logger.warning(
            f"PR sync: incremental commit sync for {repo_full}@{branch} hit the "
            f"{pages_cap}-page cycle cap without a short page; the backlog exceeds "
            f"{pages_cap * 100} commits and some updates may lag until it drains"
        )

    commits_db.upsert_branch_state(repo_full, branch, last_committed_at=max_seen, error=None)
    return total


def sync_commits(store, commits_db, repo_full, cfg):
    """Sync commits on each configured branch via REST. Returns rows upserted.

    Each branch is isolated: one branch's failure never blocks the others.
    """
    owner, name = repo_full.split("/", 1)
    branches = cfg.get("commit_branches", DEFAULT_PR_SYNC["commit_branches"])
    pages_cap = cfg.get("commit_pages_per_cycle", DEFAULT_PR_SYNC["commit_pages_per_cycle"])
    total = 0
    for branch in branches:
        try:
            bs = commits_db.get_branch_state(repo_full, branch) or {}
            if not bs.get("backfill_done"):
                total += _commit_backfill_branch(commits_db, repo_full, owner, name, branch, bs, pages_cap)
            else:
                total += _commit_incremental_branch(commits_db, repo_full, owner, name, branch, bs, pages_cap)
        except RuntimeError as e:
            commits_db.upsert_branch_state(repo_full, branch, error=str(e))
            logger.warning(f"PR sync: commit sync failed for {repo_full}@{branch}: {e}")
    return total


def sync_cycle(store=None, cfg=None, commits_db=None):
    """One pass over eligible repos. Each repo is isolated, and within a repo
    each stage (PR sync, history slice, commit sync, rollup) is isolated too,
    so one failing stage never blocks the next."""
    if store is None:
        from backend.database import get_synced_prs_db
        store = get_synced_prs_db()
    if commits_db is None:
        from backend.database import get_synced_commits_db
        commits_db = get_synced_commits_db()
    cfg = cfg or get_pr_sync_config()
    if not cfg["enabled"]:
        return

    excluded = set(cfg["exclude_repos"])
    repos = [r for r in store.list_repos() if r["repo"] not in excluded]
    repos = repos[: cfg["max_synced_repos"]]

    for repo_row in repos:
        repo_full = repo_row["repo"]
        changed = 0

        if not repo_row["backfill_done"]:
            try:
                backfill_repo(store, repo_full, cfg["history_days"])
                changed = 1
            except Exception:
                logger.exception(f"PR sync: backfill failed for {repo_full}")
        else:
            try:
                changed += incremental_sync_repo(
                    store, repo_full, cfg["history_days"],
                    cfg.get("retain_days", DEFAULT_PR_SYNC["retain_days"]),
                )
            except Exception:
                logger.exception(f"PR sync: incremental sync failed for {repo_full}")
            try:
                changed += history_backfill_slice(store, repo_full, cfg)
            except Exception:
                logger.exception(f"PR sync: history backfill slice failed for {repo_full}")

        try:
            changed += sync_commits(store, commits_db, repo_full, cfg)
        except Exception:
            logger.exception(f"PR sync: commit sync failed for {repo_full}")

        try:
            if changed or analytics_rollup.needs_rebuild(repo_full):
                analytics_rollup.rebuild_repo(repo_full)
        except Exception:
            logger.exception(f"PR sync: rollup rebuild failed for {repo_full}")


def pr_sync_worker_loop():
    """Daemon loop; started from app.py."""
    logger.info("PR sync worker started")
    while True:
        try:
            sync_cycle()
        except Exception:
            logger.exception("PR sync: unexpected cycle error")
        time.sleep(get_pr_sync_config()["poll_interval_seconds"])
