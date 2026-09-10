"""Tests for the inception-walk history backfill slice (`history_backfill_slice`)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from backend.database.base import Database
from backend.database.synced_prs import SyncedPRsDB
from backend.services.pr_sync_worker import history_backfill_slice

WORKER = "backend.services.pr_sync_worker"


@pytest.fixture
def store(tmp_path):
    return SyncedPRsDB(Database(tmp_path / "test.db"))


def _pr(number, state="MERGED"):
    return {
        "number": number, "title": f"PR {number}", "state": state,
        "isDraft": False, "author": {"login": "alice"},
        "createdAt": "2024-01-01T00:00:00Z", "updatedAt": "2024-01-01T00:00:00Z",
        "closedAt": "2024-01-01T00:00:00Z", "mergedAt": None,
    }


def _cfg(**overrides):
    cfg = {
        "history_backfill_budget": 100,
        "history_chunk_days": 30,
        "min_graphql_remaining": 1500,
    }
    cfg.update(overrides)
    return cfg


def _prep(store, repo="acme/widgets", cursor="2025-03-01", created_at="2025-01-01T00:00:00Z"):
    store.register_repo(repo)
    store.mark_backfill_done(repo)
    store.set_repo_created_at(repo, created_at)
    store.set_history_cursor(repo, cursor)


def test_history_done_makes_no_gh_calls(store):
    _prep(store)
    store.mark_history_done("acme/widgets")
    with patch(f"{WORKER}.fetch_pr_numbers") as numbers, \
         patch(f"{WORKER}.fetch_repo_created_at") as created, \
         patch(f"{WORKER}.fetch_graphql_remaining") as remaining:
        result = history_backfill_slice(store, "acme/widgets", _cfg())
    assert result == 0
    numbers.assert_not_called()
    created.assert_not_called()
    remaining.assert_not_called()


def test_missing_cursor_initializes_to_tomorrow_and_continues_the_walk(store):
    """Every repo that finished the fast backfill before cursor-stamping
    existed (i.e. every pre-deploy repo) has backfill_done=1 and no cursor.
    It must still start the inception walk on its first slice, not be stuck
    at `cursor is None` forever."""
    store.register_repo("acme/widgets")
    store.mark_backfill_done("acme/widgets")
    now = datetime.now(timezone.utc)
    floor_date = (now - timedelta(days=3)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")
    store.set_repo_created_at("acme/widgets", f"{floor_date}T00:00:00Z")
    calls = []

    def fake_numbers(owner, repo, state="all", search=None):
        calls.append(search)
        return []

    with patch(f"{WORKER}.fetch_pr_numbers", side_effect=fake_numbers), \
         patch(f"{WORKER}.fetch_graphql_remaining", return_value=5000):
        result = history_backfill_slice(store, "acme/widgets", _cfg(history_chunk_days=30))

    assert result == 0
    # Cursor was initialized to tomorrow, so the first (and only, since the
    # floor is only 3 days back) window's end is today.
    assert calls == [f"is:closed created:{floor_date}..{today}"]
    state = store.get_history_state("acme/widgets")
    assert state["history_cursor"] == floor_date
    assert state["history_done"] is True


def test_backfill_done_repo_without_cursor_is_walked_on_first_slice(store):
    """Same scenario as above, but proves real hydration happens (not just
    that a search is issued) -- the case observed live: backfill_done=1,
    history_cursor NULL, no created: searches ever issued."""
    store.register_repo("acme/widgets")
    store.mark_backfill_done("acme/widgets")
    floor_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    store.set_repo_created_at("acme/widgets", f"{floor_date}T00:00:00Z")

    with patch(f"{WORKER}.fetch_pr_numbers", return_value=[42]), \
         patch(f"{WORKER}.fetch_graphql_remaining", return_value=5000), \
         patch(f"{WORKER}.fetch_full_pr", side_effect=lambda o, r, n: _pr(n)):
        total = history_backfill_slice(store, "acme/widgets", _cfg())

    assert total == 1
    assert store.count_prs("acme/widgets") == 1
    state = store.get_history_state("acme/widgets")
    assert state["history_cursor"] is not None


def test_quota_guard_skips_below_minimum(store):
    _prep(store)
    with patch(f"{WORKER}.fetch_graphql_remaining", return_value=100), \
         patch(f"{WORKER}.fetch_pr_numbers") as numbers:
        result = history_backfill_slice(store, "acme/widgets", _cfg(min_graphql_remaining=1500))
    assert result == 0
    numbers.assert_not_called()


def test_walks_newest_first_in_chunk_steps_and_marks_done_at_floor(store):
    _prep(store, cursor="2025-03-01", created_at="2025-01-01T00:00:00Z")
    calls = []

    def fake_numbers(owner, repo, state="all", search=None):
        calls.append(search)
        return []

    with patch(f"{WORKER}.fetch_pr_numbers", side_effect=fake_numbers), \
         patch(f"{WORKER}.fetch_graphql_remaining", return_value=5000):
        total = history_backfill_slice(store, "acme/widgets", _cfg(history_chunk_days=30))

    assert total == 0
    assert calls == [
        "is:closed created:2025-01-30..2025-02-28",
        "is:closed created:2025-01-01..2025-01-29",
    ]
    state = store.get_history_state("acme/widgets")
    assert state["history_done"] is True
    assert state["history_cursor"] == "2025-01-01"


def test_windows_per_cycle_is_capped_and_resumes(store):
    """Many empty windows must not turn into an unbounded number of searches
    in one cycle: the walk stops after MAX_HISTORY_WINDOWS_PER_CYCLE windows
    even though budget remains, and resumes from where it left off next call."""
    _prep(store, cursor="2025-03-01", created_at="2000-01-01T00:00:00Z")
    calls = []

    def fake_numbers(owner, repo, state="all", search=None):
        calls.append(search)
        return []

    with patch(f"{WORKER}.fetch_pr_numbers", side_effect=fake_numbers), \
         patch(f"{WORKER}.fetch_graphql_remaining", return_value=5000):
        total = history_backfill_slice(store, "acme/widgets", _cfg(history_chunk_days=30))

    assert total == 0
    assert len(calls) == 12  # MAX_HISTORY_WINDOWS_PER_CYCLE, not the ~300+ windows to floor
    state = store.get_history_state("acme/widgets")
    assert state["history_done"] is False
    cursor_after_first_slice = state["history_cursor"]
    assert cursor_after_first_slice != "2025-03-01"  # cursor still advanced for covered windows

    calls.clear()
    with patch(f"{WORKER}.fetch_pr_numbers", side_effect=fake_numbers), \
         patch(f"{WORKER}.fetch_graphql_remaining", return_value=5000):
        history_backfill_slice(store, "acme/widgets", _cfg(history_chunk_days=30))

    assert len(calls) == 12  # resumes and walks another 12 windows next call
    state2 = store.get_history_state("acme/widgets")
    assert state2["history_cursor"] != cursor_after_first_slice


def test_adaptive_split_when_window_caps_at_1000(store):
    _prep(store, cursor="2025-02-01", created_at="2000-01-01T00:00:00Z")
    calls = []

    def fake_numbers(owner, repo, state="all", search=None):
        calls.append(search)
        if search == "is:closed created:2025-01-02..2025-01-31":
            return list(range(1000))
        if search == "is:closed created:2025-01-17..2025-01-31":
            return list(range(10))
        raise AssertionError(f"unexpected search {search}")

    with patch(f"{WORKER}.fetch_pr_numbers", side_effect=fake_numbers), \
         patch(f"{WORKER}.fetch_graphql_remaining", return_value=5000), \
         patch(f"{WORKER}.fetch_full_pr", side_effect=lambda o, r, n: _pr(n)):
        total = history_backfill_slice(
            store, "acme/widgets", _cfg(history_chunk_days=30, history_backfill_budget=5),
        )

    assert calls == [
        "is:closed created:2025-01-02..2025-01-31",
        "is:closed created:2025-01-17..2025-01-31",
    ]
    assert total == 5  # budget-capped hydration of the narrowed (10-PR) window
    # Window not fully covered (10 todo > 5 hydrated this cycle) -> cursor unmoved.
    state = store.get_history_state("acme/widgets")
    assert state["history_cursor"] == "2025-02-01"
    assert state["history_done"] is False


def test_budget_stops_mid_window_without_moving_cursor_then_resumes(store):
    _prep(store, cursor="2025-02-01", created_at="2000-01-01T00:00:00Z")

    def fake_numbers(owner, repo, state="all", search=None):
        return [1, 2, 3, 4]

    with patch(f"{WORKER}.fetch_pr_numbers", side_effect=fake_numbers), \
         patch(f"{WORKER}.fetch_graphql_remaining", return_value=5000), \
         patch(f"{WORKER}.fetch_full_pr", side_effect=lambda o, r, n: _pr(n)):
        total1 = history_backfill_slice(store, "acme/widgets", _cfg(history_backfill_budget=2))

    assert total1 == 2
    state = store.get_history_state("acme/widgets")
    assert state["history_cursor"] == "2025-02-01"  # unmoved: 4 todo > 2 hydrated
    assert store.count_prs("acme/widgets") == 2

    # Second cycle: same window resurfaces the same 4 numbers, but 1 and 2 are
    # already MERGED so they're skipped -- only 3 and 4 remain, budget covers
    # them, and the window is now fully covered so the cursor advances.
    with patch(f"{WORKER}.fetch_pr_numbers", side_effect=fake_numbers), \
         patch(f"{WORKER}.fetch_graphql_remaining", return_value=5000), \
         patch(f"{WORKER}.fetch_full_pr", side_effect=lambda o, r, n: _pr(n)):
        total2 = history_backfill_slice(store, "acme/widgets", _cfg(history_backfill_budget=2))

    assert total2 == 2
    state = store.get_history_state("acme/widgets")
    assert state["history_cursor"] == "2025-01-02"
    assert store.count_prs("acme/widgets") == 4


def test_runtime_error_records_history_error(store):
    _prep(store)
    with patch(f"{WORKER}.fetch_pr_numbers", side_effect=RuntimeError("boom")), \
         patch(f"{WORKER}.fetch_graphql_remaining", return_value=5000):
        total = history_backfill_slice(store, "acme/widgets", _cfg())
    assert total == 0
    state = store.get_history_state("acme/widgets")
    assert "boom" in state["history_error"]


def test_never_records_review_requests_or_automation_candidates(store):
    _prep(store)
    with patch(f"{WORKER}.fetch_pr_numbers", return_value=[1]), \
         patch(f"{WORKER}.fetch_graphql_remaining", return_value=5000), \
         patch(f"{WORKER}.fetch_full_pr", side_effect=lambda o, r, n: _pr(n)), \
         patch(f"{WORKER}._record_review_requests") as rr_spy, \
         patch(f"{WORKER}._record_automation_candidates") as ac_spy:
        history_backfill_slice(store, "acme/widgets", _cfg())
    rr_spy.assert_not_called()
    ac_spy.assert_not_called()


def test_missing_repo_created_at_is_fetched_and_stored(store):
    store.register_repo("acme/widgets")
    store.mark_backfill_done("acme/widgets")
    store.set_history_cursor("acme/widgets", "2025-02-01")
    with patch(f"{WORKER}.fetch_pr_numbers", return_value=[]), \
         patch(f"{WORKER}.fetch_graphql_remaining", return_value=5000), \
         patch(f"{WORKER}.fetch_repo_created_at", return_value="2025-01-15T00:00:00Z"):
        history_backfill_slice(store, "acme/widgets", _cfg())
    state = store.get_history_state("acme/widgets")
    assert state["repo_created_at"] == "2025-01-15T00:00:00Z"


def test_missing_repo_created_at_falls_back_to_genesis_on_fetch_failure(store):
    store.register_repo("acme/widgets")
    store.mark_backfill_done("acme/widgets")
    store.set_history_cursor("acme/widgets", "2025-02-01")
    with patch(f"{WORKER}.fetch_pr_numbers", return_value=[]), \
         patch(f"{WORKER}.fetch_graphql_remaining", return_value=5000), \
         patch(f"{WORKER}.fetch_repo_created_at", return_value=None):
        history_backfill_slice(store, "acme/widgets", _cfg())
    state = store.get_history_state("acme/widgets")
    assert state["repo_created_at"] == "2008-01-01T00:00:00Z"
