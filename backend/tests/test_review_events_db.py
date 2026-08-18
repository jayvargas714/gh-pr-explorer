"""Tests for ReviewEventsDB."""

import tempfile
from pathlib import Path

import pytest

from backend.database.base import Database
from backend.database.review_events import ReviewEventsDB


@pytest.fixture
def events_db():
    p = Path(tempfile.mkdtemp()) / "events_test.db"
    return ReviewEventsDB(Database(p))


REPO = "owner/repo"


def test_log_event_returns_id_and_roundtrips(events_db):
    event_id = events_db.log_event(
        "started", REPO, 42, "run-1",
        reviewer_agent="default", attempt=1, max_attempts=3, pid=999,
    )
    assert isinstance(event_id, int)

    events, total = events_db.list_events(repo=REPO)
    assert total == 1
    assert events[0]["event"] == "started"
    assert events[0]["run_id"] == "run-1"
    assert events[0]["pr_number"] == 42
    assert events[0]["attempt"] == 1
    assert events[0]["pid"] == 999
    assert events[0]["created_at"]


def test_rejects_unknown_event(events_db):
    with pytest.raises(ValueError):
        events_db.log_event("exploded", REPO, 42, "run-1")


def test_rejects_unknown_reason(events_db):
    with pytest.raises(ValueError):
        events_db.log_event("failed", REPO, 42, "run-1", reason="vibes")


def test_rejects_unknown_column(events_db):
    with pytest.raises(ValueError):
        events_db.log_event("started", REPO, 42, "run-1", nonsense=1)


def test_events_ordered_newest_first(events_db):
    events_db.log_event("started", REPO, 42, "run-1", attempt=1)
    events_db.log_event("failed", REPO, 42, "run-1", attempt=1, reason="no_output")
    events_db.log_event("completed", REPO, 42, "run-1", attempt=2, score=8.0)

    events, total = events_db.list_events(repo=REPO)
    assert total == 3
    assert [e["event"] for e in events] == ["completed", "failed", "started"]


def test_filter_by_pr_number(events_db):
    events_db.log_event("started", REPO, 1, "run-1")
    events_db.log_event("started", REPO, 2, "run-2")

    events, total = events_db.list_events(repo=REPO, pr_number=2)
    assert total == 1
    assert events[0]["pr_number"] == 2


def test_filter_by_event_and_reason(events_db):
    events_db.log_event("started", REPO, 1, "run-1")
    events_db.log_event("failed", REPO, 1, "run-1", reason="no_output")
    events_db.log_event("failed", REPO, 2, "run-2", reason="nonzero_exit")

    events, total = events_db.list_events(repo=REPO, event="failed")
    assert total == 2

    events, total = events_db.list_events(repo=REPO, reason="no_output")
    assert total == 1
    assert events[0]["pr_number"] == 1


def test_filter_by_repo_isolates(events_db):
    events_db.log_event("started", "a/one", 1, "run-1")
    events_db.log_event("started", "b/two", 2, "run-2")

    events, total = events_db.list_events(repo="a/one")
    assert total == 1
    assert events[0]["repo"] == "a/one"

    _, total_all = events_db.list_events()
    assert total_all == 2


def test_pagination_reports_full_total(events_db):
    for i in range(5):
        events_db.log_event("started", REPO, i, "run-%d" % i)

    events, total = events_db.list_events(repo=REPO, limit=2, offset=0)
    assert total == 5
    assert len(events) == 2

    events, total = events_db.list_events(repo=REPO, limit=2, offset=4)
    assert total == 5
    assert len(events) == 1


def test_since_filter(events_db):
    events_db.log_event("started", REPO, 1, "run-1")
    _, total = events_db.list_events(repo=REPO, since="2999-01-01T00:00:00+00:00")
    assert total == 0
    _, total = events_db.list_events(repo=REPO, since="2000-01-01T00:00:00+00:00")
    assert total == 1


def test_stats_counts_runs_and_outcomes(events_db):
    # run-1: succeeded first try
    events_db.log_event("started", REPO, 1, "run-1", attempt=1)
    events_db.log_event("completed", REPO, 1, "run-1", attempt=1, score=8.0)
    # run-2: failed once, then succeeded -> rescued by retry
    events_db.log_event("started", REPO, 2, "run-2", attempt=1)
    events_db.log_event("failed", REPO, 2, "run-2", attempt=1, reason="no_output")
    events_db.log_event("started", REPO, 2, "run-2", attempt=2)
    events_db.log_event("completed", REPO, 2, "run-2", attempt=2, score=9.0)
    # run-3: gave up
    events_db.log_event("started", REPO, 3, "run-3", attempt=1)
    events_db.log_event("failed", REPO, 3, "run-3", attempt=1, reason="nonzero_exit")
    events_db.log_event("gave_up", REPO, 3, "run-3", attempt=1, reason="attempts_exhausted")

    stats = events_db.get_stats(repo=REPO)
    assert stats["runs"] == 3
    assert stats["completed"] == 2
    assert stats["failed"] == 1
    assert stats["rescued_by_retry"] == 1
    assert stats["by_reason"]["no_output"] == 1
    assert stats["by_reason"]["nonzero_exit"] == 1


def test_stats_without_repo_filter_spans_repos(events_db):
    events_db.log_event("started", "a/one", 1, "run-1", attempt=1)
    events_db.log_event("completed", "a/one", 1, "run-1", attempt=1)
    events_db.log_event("started", "b/two", 2, "run-2", attempt=1)
    events_db.log_event("completed", "b/two", 2, "run-2", attempt=1)

    stats = events_db.get_stats()
    assert stats["runs"] == 2
    assert stats["completed"] == 2


def test_stats_empty_db(events_db):
    stats = events_db.get_stats()
    assert stats == {"runs": 0, "completed": 0, "failed": 0, "rescued_by_retry": 0, "by_reason": {}}


def test_purge_older_than_removes_old_rows(events_db):
    with events_db.db.connection() as conn:
        conn.execute(
            "INSERT INTO review_events (created_at, run_id, event, repo, pr_number) "
            "VALUES ('2000-01-01T00:00:00+00:00', 'old', 'started', ?, 1)", (REPO,)
        )
    events_db.log_event("started", REPO, 2, "new")

    deleted = events_db.purge_older_than(30)
    assert deleted == 1
    _, total = events_db.list_events(repo=REPO)
    assert total == 1


def test_purge_zero_days_is_a_noop(events_db):
    events_db.log_event("started", REPO, 1, "run-1")
    assert events_db.purge_older_than(0) == 0
    _, total = events_db.list_events(repo=REPO)
    assert total == 1
