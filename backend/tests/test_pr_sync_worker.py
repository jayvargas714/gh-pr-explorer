"""Sync worker tests with gh fully mocked."""
from unittest.mock import patch

import pytest

from backend.database.base import Database
from backend.database.synced_prs import SyncedPRsDB
from backend.services.pr_sync_worker import (
    backfill_repo, incremental_sync_repo, sync_cycle,
)


@pytest.fixture
def store(tmp_path):
    return SyncedPRsDB(Database(tmp_path / "test.db"))


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


def test_incremental_hydrates_updated_and_prunes(store):
    store.register_repo("acme/widgets")
    store.mark_backfill_done("acme/widgets")
    store.update_last_synced("acme/widgets")
    store.upsert_pr("acme/widgets", _pr(9, state="MERGED", updated="2020-01-01T00:00:00Z"))

    with patch(f"{WORKER}.fetch_pr_numbers", return_value=[4]) as mock_numbers, \
         patch(f"{WORKER}.fetch_full_pr", return_value=_pr(4, state="CLOSED")):
        incremental_sync_repo(store, "acme/widgets", history_days=180)

    search = mock_numbers.call_args.kwargs.get("search") or mock_numbers.call_args[0][3]
    assert "updated:>=" in search
    rows = {r["number"]: r for r in store.get_prs("acme/widgets")}
    assert 4 in rows and rows[4]["state"] == "CLOSED"
    assert 9 not in rows  # pruned: merged, older than window


def test_sync_cycle_respects_cap_exclusions_and_isolation(store):
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

    with patch(f"{WORKER}.backfill_repo", side_effect=fake_backfill):
        sync_cycle(store=store, cfg=cfg)

    assert "a/skip" not in synced
    assert len(synced) >= 1  # a/one synced despite a/two failing


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
    return calls


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

    _run_incremental(store, [1], {1: _pr_with_requests(1, ME)})
    assert 1 in store.get_prs_by_numbers("acme/widgets", [1])
    assert store.get_repo("acme/widgets")["last_synced_at"] is not None
