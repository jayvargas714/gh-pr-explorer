"""Sync worker tests with gh fully mocked."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from backend.database.base import Database
from backend.database.synced_commits import SyncedCommitsDB
from backend.database.synced_prs import SyncedPRsDB
from backend.services.pr_sync_worker import (
    backfill_repo, incremental_sync_repo, sync_cycle,
)


@pytest.fixture
def store(tmp_path):
    return SyncedPRsDB(Database(tmp_path / "test.db"))


@pytest.fixture
def commits_db(tmp_path):
    return SyncedCommitsDB(Database(tmp_path / "commits.db"))


def _pr(number, state="OPEN", updated="2026-08-20T00:00:00Z"):
    return {
        "number": number, "title": f"PR {number}", "state": state,
        "isDraft": False, "author": {"login": "alice"},
        "createdAt": "2026-08-01T00:00:00Z", "updatedAt": updated,
        "closedAt": None, "mergedAt": None,
    }


WORKER = "backend.services.pr_sync_worker"


def test_backfill_hydrates_open_first_then_recent_closed(store):
    store.register_repo("acme/widgets")
    calls = []

    def fake_numbers(owner, repo, state="open", search=None, limit=1000):
        calls.append((state, search))
        return [1, 2] if state == "open" else [3]

    def fake_full(owner, repo, number):
        return _pr(number, state="OPEN" if number in (1, 2) else "MERGED")

    with patch(f"{WORKER}.fetch_pr_numbers", side_effect=fake_numbers), \
         patch(f"{WORKER}.fetch_full_pr", side_effect=fake_full):
        backfill_repo(store, "acme/widgets", history_days=180)

    assert store.count_prs("acme/widgets") == 3
    assert store.get_repo("acme/widgets")["backfill_done"] is True
    assert calls[0][0] == "open"                # open numbers first
    assert "is:closed" in calls[1][1]           # then recent closed/merged
    assert "updated:>=" in calls[1][1]


def test_backfill_failure_records_error_not_done(store):
    store.register_repo("acme/widgets")
    with patch(f"{WORKER}.fetch_pr_numbers", side_effect=RuntimeError("boom")):
        backfill_repo(store, "acme/widgets", history_days=180)
    row = store.get_repo("acme/widgets")
    assert row["backfill_done"] is False
    assert "boom" in row["backfill_error"]


def test_backfill_survives_single_pr_hydration_failure(store):
    store.register_repo("acme/widgets")

    def fake_full(owner, repo, number):
        if number == 2:
            raise RuntimeError("flaky")
        return _pr(number)

    with patch(f"{WORKER}.fetch_pr_numbers", side_effect=[[1, 2, 3], []]), \
         patch(f"{WORKER}.fetch_full_pr", side_effect=fake_full):
        backfill_repo(store, "acme/widgets", history_days=180)

    assert store.count_prs("acme/widgets") == 2
    assert store.get_repo("acme/widgets")["backfill_done"] is True


def test_incremental_hydrates_updated_and_does_not_prune_by_default(store):
    """retain_days=0 (the default) means keep forever."""
    store.register_repo("acme/widgets")
    store.mark_backfill_done("acme/widgets")
    store.update_last_synced("acme/widgets")
    store.upsert_pr("acme/widgets", _pr(9, state="MERGED", updated="2020-01-01T00:00:00Z"))

    with patch(f"{WORKER}.fetch_pr_numbers", return_value=[4]) as mock_numbers, \
         patch(f"{WORKER}.fetch_full_pr", return_value=_pr(4, state="CLOSED")):
        n = incremental_sync_repo(store, "acme/widgets", history_days=180)

    assert n == 1
    search = mock_numbers.call_args.kwargs.get("search") or mock_numbers.call_args[0][3]
    assert "updated:>=" in search
    rows = {r["number"]: r for r in store.get_prs("acme/widgets")}
    assert 4 in rows and rows[4]["state"] == "CLOSED"
    assert 9 in rows  # retain_days=0: never pruned


def test_incremental_prunes_when_retain_days_set(store):
    store.register_repo("acme/widgets")
    store.mark_backfill_done("acme/widgets")
    store.update_last_synced("acme/widgets")
    store.upsert_pr("acme/widgets", _pr(9, state="MERGED", updated="2020-01-01T00:00:00Z"))

    with patch(f"{WORKER}.fetch_pr_numbers", return_value=[4]), \
         patch(f"{WORKER}.fetch_full_pr", return_value=_pr(4, state="CLOSED")):
        incremental_sync_repo(store, "acme/widgets", history_days=180, retain_days=30)

    rows = {r["number"]: r for r in store.get_prs("acme/widgets")}
    assert 4 in rows and rows[4]["state"] == "CLOSED"
    assert 9 not in rows  # pruned: merged, older than the retention window


def test_sync_cycle_respects_cap_exclusions_and_isolation(store, commits_db):
    for name in ("a/one", "a/two", "a/skip"):
        store.register_repo(name)
    cfg = {
        "enabled": True, "poll_interval_seconds": 120, "history_days": 180,
        "max_synced_repos": 2, "exclude_repos": ["a/skip"],
    }
    synced = []

    def fake_backfill(s, repo, history_days):
        if repo == "a/two":
            raise RuntimeError("kaboom")   # must not break the loop
        synced.append(repo)

    with patch(f"{WORKER}.backfill_repo", side_effect=fake_backfill), \
         patch(f"{WORKER}.fetch_commits_page", return_value=[]), \
         patch(f"{WORKER}.analytics_rollup.needs_rebuild", return_value=False), \
         patch(f"{WORKER}.analytics_rollup.rebuild_repo"):
        sync_cycle(store=store, cfg=cfg, commits_db=commits_db)

    assert "a/skip" not in synced
    assert len(synced) >= 1  # a/one synced despite a/two failing


def test_backfill_stamps_history_cursor_at_tomorrow(store):
    store.register_repo("acme/widgets")
    with patch(f"{WORKER}.fetch_pr_numbers", side_effect=[[1], []]), \
         patch(f"{WORKER}.fetch_full_pr", side_effect=lambda o, r, n: _pr(n)):
        backfill_repo(store, "acme/widgets", history_days=180)

    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    state = store.get_history_state("acme/widgets")
    assert state["history_cursor"] == tomorrow
    assert state["history_done"] is False


def test_sync_cycle_orders_stages_and_rebuilds_once_when_changed(store, commits_db):
    """incremental -> history slice -> commits, then a single rebuild_repo call
    when anything changed."""
    store.register_repo("acme/widgets")
    store.mark_backfill_done("acme/widgets")
    store.update_last_synced("acme/widgets")
    store.set_history_cursor("acme/widgets", "2025-01-01")
    store.mark_history_done("acme/widgets")  # history slice is a no-op this cycle

    cfg = {
        "enabled": True, "poll_interval_seconds": 120, "history_days": 180,
        "max_synced_repos": 10, "exclude_repos": [], "retain_days": 0,
        "history_backfill_budget": 60, "history_chunk_days": 30,
        "min_graphql_remaining": 1500, "commit_branches": [],
        "commit_pages_per_cycle": 40,
    }
    order = []

    def fake_incremental(s, repo, history_days, retain_days=0):
        order.append("incremental")
        return 1  # something changed

    def fake_rebuild(repo):
        order.append("rebuild")

    with patch(f"{WORKER}.incremental_sync_repo", side_effect=fake_incremental), \
         patch(f"{WORKER}.history_backfill_slice", side_effect=lambda s, r, c: order.append("history") or 0), \
         patch(f"{WORKER}.sync_commits", side_effect=lambda s, cdb, r, c: order.append("commits") or 0), \
         patch(f"{WORKER}.analytics_rollup.needs_rebuild", return_value=False), \
         patch(f"{WORKER}.analytics_rollup.rebuild_repo", side_effect=fake_rebuild):
        sync_cycle(store=store, cfg=cfg, commits_db=commits_db)

    assert order == ["incremental", "history", "commits", "rebuild"]


def test_sync_cycle_skips_rebuild_when_nothing_changed_and_not_needed(store, commits_db):
    store.register_repo("acme/widgets")
    store.mark_backfill_done("acme/widgets")
    store.update_last_synced("acme/widgets")
    store.mark_history_done("acme/widgets")
    cfg = {
        "enabled": True, "poll_interval_seconds": 120, "history_days": 180,
        "max_synced_repos": 10, "exclude_repos": [], "retain_days": 0,
        "commit_branches": [],
    }

    with patch(f"{WORKER}.incremental_sync_repo", return_value=0), \
         patch(f"{WORKER}.history_backfill_slice", return_value=0), \
         patch(f"{WORKER}.analytics_rollup.needs_rebuild", return_value=False), \
         patch(f"{WORKER}.analytics_rollup.rebuild_repo") as mock_rebuild:
        sync_cycle(store=store, cfg=cfg, commits_db=commits_db)

    mock_rebuild.assert_not_called()


def test_sync_cycle_rebuilds_when_needs_rebuild_true_even_if_unchanged(store, commits_db):
    store.register_repo("acme/widgets")
    store.mark_backfill_done("acme/widgets")
    store.update_last_synced("acme/widgets")
    store.mark_history_done("acme/widgets")
    cfg = {
        "enabled": True, "poll_interval_seconds": 120, "history_days": 180,
        "max_synced_repos": 10, "exclude_repos": [], "retain_days": 0,
        "commit_branches": [],
    }

    with patch(f"{WORKER}.incremental_sync_repo", return_value=0), \
         patch(f"{WORKER}.history_backfill_slice", return_value=0), \
         patch(f"{WORKER}.analytics_rollup.needs_rebuild", return_value=True), \
         patch(f"{WORKER}.analytics_rollup.rebuild_repo") as mock_rebuild:
        sync_cycle(store=store, cfg=cfg, commits_db=commits_db)

    mock_rebuild.assert_called_once_with("acme/widgets")


# ----- Automation candidate detection -----


def _automation_cfg(**overrides):
    cfg = {
        "scope": "all", "authors": [], "repoAllowlist": ["acme/widgets"],
        "maxConcurrentAutoReviews": 2, "ignorePatterns": [],
        "defaultRule": {"reviewerKey": "default", "autoVerdict": False, "autoVerdictMode": "verdict"},
        "rules": [],
    }
    cfg.update(overrides)
    return cfg


@pytest.fixture
def dispatches(tmp_path, monkeypatch):
    from backend.database.automation_dispatches import AutomationDispatchesDB
    ddb = AutomationDispatchesDB(Database(tmp_path / "dispatch.db"))
    import backend.database as db_pkg
    monkeypatch.setattr(db_pkg, "get_automation_dispatches_db", lambda: ddb)
    return ddb


def _synced_repo(store):
    store.register_repo("acme/widgets")
    store.mark_backfill_done("acme/widgets")
    store.update_last_synced("acme/widgets")


def _run_incremental(store, numbers, prs_by_number):
    with patch(f"{WORKER}.fetch_pr_numbers", return_value=numbers), \
         patch(f"{WORKER}.fetch_full_pr", side_effect=lambda o, r, n: prs_by_number[n]):
        incremental_sync_repo(store, "acme/widgets", history_days=180)


def test_incremental_records_candidates_only_for_unseen_prs(store, dispatches, monkeypatch):
    from backend.services import automation_config
    monkeypatch.setattr(automation_config, "get_config", lambda: _automation_cfg())
    _synced_repo(store)
    store.upsert_pr("acme/widgets", _pr(1))  # already known

    _run_incremental(store, [1, 2], {1: _pr(1), 2: _pr(2)})

    assert dispatches.get_by_pr("acme/widgets", 2) is not None
    assert dispatches.get_by_pr("acme/widgets", 1) is None


def test_incremental_records_nothing_when_scope_off(store, dispatches, monkeypatch):
    from backend.services import automation_config
    monkeypatch.setattr(automation_config, "get_config", lambda: _automation_cfg(scope="off"))
    _synced_repo(store)
    _run_incremental(store, [2], {2: _pr(2)})
    assert dispatches.get_pending(10) == []


def test_incremental_records_nothing_for_non_allowlisted_repo(store, dispatches, monkeypatch):
    from backend.services import automation_config
    monkeypatch.setattr(automation_config, "get_config",
                        lambda: _automation_cfg(repoAllowlist=["other/repo"]))
    _synced_repo(store)
    _run_incremental(store, [2], {2: _pr(2)})
    assert dispatches.get_pending(10) == []


def test_incremental_author_scope_filters_authors(store, dispatches, monkeypatch):
    from backend.services import automation_config
    monkeypatch.setattr(automation_config, "get_config",
                        lambda: _automation_cfg(scope="authors", authors=["alice"]))
    _synced_repo(store)
    bob_pr = _pr(3)
    bob_pr["author"] = {"login": "bob"}
    _run_incremental(store, [2, 3], {2: _pr(2), 3: bob_pr})
    assert dispatches.get_by_pr("acme/widgets", 2) is not None
    assert dispatches.get_by_pr("acme/widgets", 3) is None


def test_incremental_skips_closed_but_records_draft_prs(store, dispatches, monkeypatch):
    """Drafts are recorded — the dispatch worker's readiness gate holds them
    until they're marked ready (so ready-later drafts still get auto-reviewed)."""
    from backend.services import automation_config
    monkeypatch.setattr(automation_config, "get_config", lambda: _automation_cfg())
    _synced_repo(store)
    draft = _pr(4)
    draft["isDraft"] = True
    _run_incremental(store, [4, 5], {4: draft, 5: _pr(5, state="MERGED")})
    assert dispatches.get_by_pr("acme/widgets", 4) is not None
    assert dispatches.get_by_pr("acme/widgets", 5) is None


def test_incremental_respects_pipeline_cap(store, dispatches, monkeypatch):
    """At maxPipelineSize pending rows, new candidates are refused (protection
    over completeness — the backfill script can enroll stragglers later)."""
    from backend.services import automation_config
    monkeypatch.setattr(automation_config, "get_config",
                        lambda: _automation_cfg(maxPipelineSize=2))
    _synced_repo(store)
    dispatches.record_candidate("acme/widgets", 90)
    dispatches.record_candidate("acme/widgets", 91)

    _run_incremental(store, [2], {2: _pr(2)})

    assert dispatches.get_by_pr("acme/widgets", 2) is None


def test_candidate_hook_failure_does_not_break_sync(store, monkeypatch):
    from backend.services import automation_config
    def boom():
        raise RuntimeError("config unreadable")
    monkeypatch.setattr(automation_config, "get_config", boom)
    _synced_repo(store)
    _run_incremental(store, [2], {2: _pr(2)})   # must not raise
    assert store.count_prs("acme/widgets") == 1


def test_backfill_records_no_candidates(store, dispatches, monkeypatch):
    from backend.services import automation_config
    monkeypatch.setattr(automation_config, "get_config", lambda: _automation_cfg())
    store.register_repo("acme/widgets")
    with patch(f"{WORKER}.fetch_pr_numbers", side_effect=[[1], []]), \
         patch(f"{WORKER}.fetch_full_pr", side_effect=lambda o, r, n: _pr(n)):
        backfill_repo(store, "acme/widgets", history_days=180)
    assert dispatches.get_pending(10) == []


# ----- review-request detection hook -----

ME = "jayvargas714"


def _pr_with_requests(number, *logins, updated="2026-08-20T00:00:00Z"):
    pr = _pr(number, updated=updated)
    pr["reviewRequests"] = [{"__typename": "User", "login": l} for l in logins]
    return pr


@pytest.fixture
def review_request_hook(monkeypatch):
    calls = []
    monkeypatch.setattr(f"{WORKER}.get_authenticated_login", lambda: ME)
    monkeypatch.setattr(
        "backend.services.review_request_service.handle_review_request",
        lambda repo, number, pr_row: calls.append((repo, number)),
    )
    # The sweep needs the dispatch/request stores; the diff tests isolate it.
    monkeypatch.setattr(
        "backend.services.review_request_service.untracked_review_requests",
        lambda repo, rows, login: [],
    )
    return calls


@pytest.fixture
def untracked_sweep(monkeypatch):
    """Record what the sweep is asked to inspect; report every requested PR as untracked."""
    seen = {}

    def _sweep(repo, rows, login):
        seen[repo] = sorted(rows)
        return sorted(n for n, r in rows.items()
                      if any(x.get("login") == login for x in r.get("reviewRequests") or []))
    monkeypatch.setattr("backend.services.review_request_service.untracked_review_requests", _sweep)
    return seen


def test_incremental_detects_new_review_request_for_me(store, review_request_hook):
    _synced_repo(store)
    store.upsert_pr("acme/widgets", _pr_with_requests(1))
    store.upsert_pr("acme/widgets", _pr_with_requests(2, ME))  # already requested

    _run_incremental(store, [1, 2, 3], {
        1: _pr_with_requests(1, ME, updated="2026-08-21T00:00:00Z"),   # newly requested
        2: _pr_with_requests(2, ME, updated="2026-08-21T00:00:00Z"),   # unchanged
        3: _pr_with_requests(3, ME),                                    # first seen, requested
    })

    assert sorted(review_request_hook) == [("acme/widgets", 1), ("acme/widgets", 3)]


def test_incremental_detects_nothing_without_login(store, review_request_hook, monkeypatch):
    monkeypatch.setattr(f"{WORKER}.get_authenticated_login", lambda: None)
    _synced_repo(store)
    _run_incremental(store, [1], {1: _pr_with_requests(1, ME)})
    assert review_request_hook == []


def test_backfill_detects_no_review_requests(store, review_request_hook):
    store.register_repo("acme/widgets")
    with patch(f"{WORKER}.fetch_pr_numbers", side_effect=[[1], []]), \
         patch(f"{WORKER}.fetch_full_pr", side_effect=lambda o, r, n: _pr_with_requests(n, ME)):
        backfill_repo(store, "acme/widgets", history_days=180)
    assert review_request_hook == []


def test_review_request_hook_failure_does_not_break_sync(store, monkeypatch):
    _synced_repo(store)
    monkeypatch.setattr(f"{WORKER}.get_authenticated_login", lambda: ME)

    def boom(*args, **kwargs):
        raise RuntimeError("router exploded")
    monkeypatch.setattr("backend.services.review_request_service.handle_review_request", boom)
    monkeypatch.setattr("backend.services.review_request_service.untracked_review_requests", boom)

    _run_incremental(store, [1], {1: _pr_with_requests(1, ME)})
    assert 1 in store.get_prs_by_numbers("acme/widgets", [1])
    assert store.get_repo("acme/widgets")["last_synced_at"] is not None


def test_incremental_sweeps_every_open_pr_for_untracked_requests(store, review_request_hook,
                                                                 untracked_sweep):
    """A standing request on a PR outside this cycle's batch is still routed,
    and one the diff already handled is not routed twice."""
    _synced_repo(store)
    store.upsert_pr("acme/widgets", _pr_with_requests(2, ME))                  # quiet, standing request
    store.upsert_pr("acme/widgets", _pr_with_requests(4))                      # quiet, no request
    store.upsert_pr("acme/widgets", _pr_with_requests(5, ME))
    store.upsert_pr("acme/widgets", {**_pr_with_requests(5, ME), "state": "MERGED"})  # closed

    _run_incremental(store, [1], {1: _pr_with_requests(1, ME)})  # diff detects 1

    assert untracked_sweep == {"acme/widgets": [1, 2, 4]}
    assert review_request_hook == [("acme/widgets", 1), ("acme/widgets", 2)]


def test_incremental_sweeps_even_when_nothing_changed(store, review_request_hook, untracked_sweep):
    _synced_repo(store)
    store.upsert_pr("acme/widgets", _pr_with_requests(2, ME))

    _run_incremental(store, [], {})

    assert untracked_sweep == {"acme/widgets": [2]}
    assert review_request_hook == [("acme/widgets", 2)]
