"""Tests for SyncedCommitsDB store."""
import pytest

from backend.database.base import Database
from backend.database.synced_commits import SyncedCommitsDB


@pytest.fixture
def store(tmp_path):
    return SyncedCommitsDB(Database(tmp_path / "test.db"))


def _commit(sha, login="alice", name=None, email=None, authored_at="2026-08-01T00:00:00Z",
            committed_at="2026-08-01T00:00:00Z", parents=1):
    return {
        "sha": sha, "login": login, "name": name, "email": email,
        "authored_at": authored_at, "committed_at": committed_at, "parents": parents,
    }


# -- branch state --------------------------------------------------------------

def test_get_branch_state_missing_returns_none(store):
    assert store.get_branch_state("a/b", "main") is None


def test_upsert_branch_state_partial_fields(store):
    store.upsert_branch_state("a/b", "main", backfill_until="2020-01-01")
    state = store.get_branch_state("a/b", "main")
    assert state["backfill_until"] == "2020-01-01"
    assert state["backfill_done"] is False
    assert state["last_committed_at"] is None
    assert state["error"] is None
    assert state["last_synced_at"] is not None  # touch=True by default

    store.upsert_branch_state("a/b", "main", backfill_done=True)
    state = store.get_branch_state("a/b", "main")
    assert state["backfill_done"] is True
    assert state["backfill_until"] == "2020-01-01"  # untouched field preserved


def test_upsert_branch_state_touch_false_leaves_last_synced_at(store):
    store.upsert_branch_state("a/b", "main", touch=False, error="boom")
    state = store.get_branch_state("a/b", "main")
    assert state["error"] == "boom"
    assert state["last_synced_at"] is None


def test_upsert_branch_state_repo_branch_segregation(store):
    store.upsert_branch_state("a/b", "main", backfill_until="X")
    store.upsert_branch_state("a/b", "dev", backfill_until="Y")
    store.upsert_branch_state("c/d", "main", backfill_until="Z")
    assert store.get_branch_state("a/b", "main")["backfill_until"] == "X"
    assert store.get_branch_state("a/b", "dev")["backfill_until"] == "Y"
    assert store.get_branch_state("c/d", "main")["backfill_until"] == "Z"


# -- upsert_commits --------------------------------------------------------------

def test_upsert_commits_idempotent_on_sha(store):
    n = store.upsert_commits("a/b", "main", [_commit("sha1"), _commit("sha2")])
    assert n == 2
    assert store.count("a/b") == 2

    n2 = store.upsert_commits("a/b", "main", [_commit("sha1", login="bob")])
    assert n2 == 1
    assert store.count("a/b") == 2  # still 2, sha1 updated not duplicated

    rows = store.get_rollup_rows("a/b")
    logins = {r["login"] for r in rows}
    assert "bob" in logins


def test_upsert_commits_empty(store):
    assert store.upsert_commits("a/b", "main", []) == 0


# -- count -------------------------------------------------------------------

def test_count_filters_by_branch(store):
    store.upsert_commits("a/b", "main", [_commit("sha1")])
    store.upsert_commits("a/b", "dev", [_commit("sha2"), _commit("sha3")])
    assert store.count("a/b") == 3
    assert store.count("a/b", branch="main") == 1
    assert store.count("a/b", branch="dev") == 2


# -- get_rollup_rows -----------------------------------------------------------

def test_get_rollup_rows_shape_and_login_fallback(store):
    store.upsert_commits("a/b", "main", [
        _commit("sha1", login="alice", name="Alice A"),
        _commit("sha2", login=None, name="Bob B"),
        _commit("sha3", login=None, name=None),
    ])
    rows = {r["login"]: r for r in store.get_rollup_rows("a/b")}
    assert rows["alice"]["branch"] == "main"
    assert rows["alice"]["committed_at"] == "2026-08-01T00:00:00Z"
    assert rows["alice"]["parent_count"] == 1
    assert "Bob B" in rows  # falls back to author_name when login is null
    assert "unknown" in rows  # falls back to 'unknown' when both are null


# -- earliest_committed_at ------------------------------------------------------

def test_earliest_committed_at(store):
    store.upsert_commits("a/b", "main", [
        _commit("sha1", committed_at="2026-03-01T00:00:00Z"),
        _commit("sha2", committed_at="2026-01-01T00:00:00Z"),
    ])
    assert store.earliest_committed_at("a/b") == "2026-01-01T00:00:00Z"


def test_earliest_committed_at_no_commits(store):
    assert store.earliest_committed_at("a/b") is None
