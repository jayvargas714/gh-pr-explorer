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
