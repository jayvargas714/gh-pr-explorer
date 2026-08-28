"""Tests for SyncedPRsDB store."""
import pytest

from backend.database.base import Database
from backend.database.synced_prs import SyncedPRsDB


@pytest.fixture
def store(tmp_path):
    return SyncedPRsDB(Database(tmp_path / "test.db"))


def _pr(number, state="OPEN", author="alice", updated="2026-08-01T00:00:00Z", **extra):
    pr = {
        "number": number, "title": f"PR {number}", "state": state,
        "isDraft": False, "author": {"login": author},
        "createdAt": "2026-07-01T00:00:00Z", "updatedAt": updated,
        "closedAt": None, "mergedAt": None, "labels": [], "assignees": [],
    }
    pr.update(extra)
    return pr


def test_register_repo_idempotent_and_touch(store):
    store.register_repo("acme/widgets")
    first = store.get_repo("acme/widgets")
    store.register_repo("acme/widgets")
    again = store.get_repo("acme/widgets")
    assert again["backfill_done"] is False
    assert again["last_visited_at"] is not None
    assert store.count_prs("acme/widgets") == 0
    assert first["repo"] == "acme/widgets"


def test_upsert_and_get_prs_injects_fetched_at(store):
    store.upsert_pr("acme/widgets", _pr(1))
    rows = store.get_prs("acme/widgets")
    assert len(rows) == 1
    assert rows[0]["number"] == 1
    assert rows[0]["fetchedAt"]  # stamped


def test_upsert_is_idempotent_and_updates(store):
    store.upsert_pr("acme/widgets", _pr(1, state="OPEN"))
    store.upsert_pr("acme/widgets", _pr(1, state="MERGED"))
    rows = store.get_prs("acme/widgets")
    assert len(rows) == 1
    assert rows[0]["state"] == "MERGED"


def test_repo_segregation(store):
    store.upsert_pr("acme/widgets", _pr(1))
    store.upsert_pr("acme/gadgets", _pr(1))
    store.upsert_pr("evil/widgets", _pr(2))
    assert {r["number"] for r in store.get_prs("acme/widgets")} == {1}
    assert store.count_prs("acme/gadgets") == 1
    assert store.count_prs("evil/widgets") == 1


def test_get_prs_state_filter(store):
    store.upsert_pr("a/b", _pr(1, state="OPEN"))
    store.upsert_pr("a/b", _pr(2, state="MERGED"))
    store.upsert_pr("a/b", _pr(3, state="CLOSED"))
    assert {r["number"] for r in store.get_prs("a/b", states={"OPEN"})} == {1}
    assert {r["number"] for r in store.get_prs("a/b", states={"MERGED", "CLOSED"})} == {2, 3}


def test_get_prs_by_numbers_preserves_lookup(store):
    store.upsert_pr("a/b", _pr(1))
    store.upsert_pr("a/b", _pr(2))
    found = store.get_prs_by_numbers("a/b", [2, 99])
    assert set(found.keys()) == {2}


def test_prune_old_only_closed_merged(store):
    store.upsert_pr("a/b", _pr(1, state="OPEN", updated="2020-01-01T00:00:00Z"))
    store.upsert_pr("a/b", _pr(2, state="MERGED", updated="2020-01-01T00:00:00Z"))
    store.upsert_pr("a/b", _pr(3, state="CLOSED", updated="2026-08-01T00:00:00Z"))
    deleted = store.prune_old("a/b", "2026-01-01T00:00:00Z")
    assert deleted == 1
    assert {r["number"] for r in store.get_prs("a/b")} == {1, 3}


def test_backfill_flags_and_sync_stamp(store):
    store.register_repo("a/b")
    store.set_backfill_error("a/b", "boom")
    assert store.get_repo("a/b")["backfill_error"] == "boom"
    store.mark_backfill_done("a/b")
    row = store.get_repo("a/b")
    assert row["backfill_done"] is True
    assert row["backfill_error"] is None
    store.update_last_synced("a/b")
    assert store.get_repo("a/b")["last_synced_at"] is not None


def test_list_repos_ordered_by_visit(store):
    store.register_repo("a/old")
    import time; time.sleep(1.1)  # CURRENT_TIMESTAMP has 1s resolution
    store.register_repo("a/new")
    repos = [r["repo"] for r in store.list_repos()]
    assert repos[0] == "a/new"


def test_delete_pr(store):
    store.upsert_pr("a/b", _pr(1))
    store.delete_pr("a/b", 1)
    assert store.count_prs("a/b") == 0
