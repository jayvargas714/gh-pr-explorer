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


# -- history state -----------------------------------------------------------

def test_history_state_defaults_for_unregistered_repo(store):
    state = store.get_history_state("nope/nope")
    assert state == {
        "repo_created_at": None, "history_cursor": None,
        "history_done": False, "history_error": None,
    }


def test_history_state_round_trip(store):
    store.register_repo("a/b")
    store.set_repo_created_at("a/b", "2020-01-01T00:00:00Z")
    store.set_history_cursor("a/b", "2020-06-01")
    state = store.get_history_state("a/b")
    assert state["repo_created_at"] == "2020-01-01T00:00:00Z"
    assert state["history_cursor"] == "2020-06-01"
    assert state["history_done"] is False
    assert state["history_error"] is None

    store.set_history_error("a/b", "boom")
    assert store.get_history_state("a/b")["history_error"] == "boom"

    # setting a new cursor clears the error
    store.set_history_cursor("a/b", "2020-07-01")
    state = store.get_history_state("a/b")
    assert state["history_cursor"] == "2020-07-01"
    assert state["history_error"] is None

    store.set_history_error("a/b", "boom again")
    store.mark_history_done("a/b")
    state = store.get_history_state("a/b")
    assert state["history_done"] is True
    assert state["history_error"] is None


def test_repo_row_bools_history_done(store):
    store.register_repo("a/b")
    store.mark_history_done("a/b")
    row = store.get_repo("a/b")
    assert row["history_done"] is True
    assert isinstance(row["history_done"], bool)


# -- get_states_by_numbers ----------------------------------------------------

def test_get_states_by_numbers(store):
    store.upsert_pr("a/b", _pr(1, state="OPEN"))
    store.upsert_pr("a/b", _pr(2, state="MERGED"))
    result = store.get_states_by_numbers("a/b", [1, 2, 99])
    assert result == {1: "OPEN", 2: "MERGED"}


def test_get_states_by_numbers_chunks_over_500(store):
    store.upsert_pr("a/b", _pr(1, state="OPEN"))
    store.upsert_pr("a/b", _pr(600, state="MERGED"))
    numbers = list(range(1, 601))  # 600 numbers, forces >1 chunk at 500
    result = store.get_states_by_numbers("a/b", numbers)
    assert result == {1: "OPEN", 600: "MERGED"}


def test_get_states_by_numbers_empty(store):
    assert store.get_states_by_numbers("a/b", []) == {}


# -- get_pr_rollup_rows --------------------------------------------------------

def _pr_with_reviews(number, base_ref="main", additions=None, deletions=None,
                      is_bot=False, reviews=None, **extra):
    pr = _pr(number, **extra)
    pr["baseRefName"] = base_ref
    if additions is not None:
        pr["additions"] = additions
    if deletions is not None:
        pr["deletions"] = deletions
    pr["author"] = {"login": pr["author"]["login"], "is_bot": is_bot}
    if reviews is not None:
        pr["reviews"] = reviews
    return pr


def test_get_pr_rollup_rows_shape(store):
    store.upsert_pr("a/b", _pr_with_reviews(
        1, base_ref="main", additions=10, deletions=3, is_bot=False,
        reviews=[
            {"author": {"login": "bob"}, "state": "APPROVED", "submittedAt": "2026-08-01T00:00:00Z"},
            {"author": None, "state": "COMMENTED", "submittedAt": "2026-08-02T00:00:00Z"},
        ],
    ))
    rows = store.get_pr_rollup_rows("a/b")
    assert len(rows) == 1
    row = rows[0]
    assert row["number"] == 1
    assert row["state"] == "OPEN"
    assert row["author"] == "alice"
    assert row["author_is_bot"] is False
    assert row["created_at"] == "2026-07-01T00:00:00Z"
    assert row["base_ref"] == "main"
    assert row["additions"] == 10
    assert row["deletions"] == 3
    assert row["reviews"] == [
        {"login": "bob", "state": "APPROVED", "submitted_at": "2026-08-01T00:00:00Z"},
        {"login": None, "state": "COMMENTED", "submitted_at": "2026-08-02T00:00:00Z"},
    ]


def test_get_pr_rollup_rows_bot_author(store):
    store.upsert_pr("a/b", _pr_with_reviews(1, is_bot=True))
    rows = store.get_pr_rollup_rows("a/b")
    assert rows[0]["author_is_bot"] is True


def test_get_pr_rollup_rows_defaults_missing_fields(store):
    pr = _pr(1)
    pr["author"] = {"login": "alice"}  # no is_bot, no baseRefName/additions/deletions/reviews
    store.upsert_pr("a/b", pr)
    rows = store.get_pr_rollup_rows("a/b")
    row = rows[0]
    assert row["additions"] == 0
    assert row["deletions"] == 0
    assert row["reviews"] == []
    assert row["author_is_bot"] is False
    assert row["base_ref"] is None


# -- earliest_created_at -------------------------------------------------------

def test_earliest_created_at(store):
    store.upsert_pr("a/b", _pr(1, **{"createdAt": "2026-03-01T00:00:00Z"}))
    store.upsert_pr("a/b", _pr(2, **{"createdAt": "2026-01-01T00:00:00Z"}))
    store.upsert_pr("a/b", _pr(3, **{"createdAt": "2026-05-01T00:00:00Z"}))
    assert store.earliest_created_at("a/b") == "2026-01-01T00:00:00Z"


def test_earliest_created_at_no_prs(store):
    assert store.earliest_created_at("a/b") is None


# -- commits-behind cache + write-through setters --------------------------

def test_behind_columns_survive_upsert(store):
    store.upsert_pr("acme/widgets", _pr(1))
    store.set_behind("acme/widgets", 1, 4, "base1", "head1")
    store.upsert_pr("acme/widgets", _pr(1, title="renamed"))
    assert store.get_behind_by("acme/widgets", 1) == 4
    assert store.get_behind_state("acme/widgets")[1] == {
        "behind_by": 4, "behind_base_sha": "base1", "behind_head_sha": "head1",
    }


def test_pr_rows_expose_behind_by(store):
    store.upsert_pr("acme/widgets", _pr(1))
    store.upsert_pr("acme/widgets", _pr(2))
    store.set_behind("acme/widgets", 1, 0, "b", "h")
    rows = {p["number"]: p for p in store.get_prs("acme/widgets")}
    assert rows[1]["behindBy"] == 0
    assert rows[2]["behindBy"] is None
    by_number = store.get_prs_by_numbers("acme/widgets", [1, 2])
    assert by_number[1]["behindBy"] == 0
    assert by_number[2]["behindBy"] is None


def test_get_behind_by_unknown_pr_is_none(store):
    assert store.get_behind_by("acme/widgets", 99) is None


def test_get_behind_state_open_only(store):
    store.upsert_pr("acme/widgets", _pr(1))
    store.upsert_pr("acme/widgets", _pr(2, state="MERGED"))
    assert set(store.get_behind_state("acme/widgets")) == {1}
    assert store.get_behind_state("acme/widgets")[1]["behind_by"] is None


def test_set_draft_updates_column_and_json(store):
    store.upsert_pr("acme/widgets", _pr(1))
    store.set_draft("acme/widgets", 1, True)
    assert store.get_prs_by_numbers("acme/widgets", [1])[1]["isDraft"] is True
    with store.db.connection() as conn:
        assert conn.execute("SELECT is_draft FROM synced_prs").fetchone()[0] == 1
    store.set_draft("acme/widgets", 1, False)
    assert store.get_prs_by_numbers("acme/widgets", [1])[1]["isDraft"] is False


def test_set_state_updates_column_and_json(store):
    store.upsert_pr("acme/widgets", _pr(1))
    store.set_state("acme/widgets", 1, "MERGED")
    assert store.get_prs_by_numbers("acme/widgets", [1])[1]["state"] == "MERGED"
    assert store.get_prs("acme/widgets", {"MERGED"})[0]["number"] == 1
