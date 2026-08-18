"""Tests for the review event recorders.

Recorders must write the right row AND must never raise — a logging failure
cannot be allowed to break the review it is observing.
"""

import tempfile
from pathlib import Path

import pytest

from backend.database.base import Database
from backend.database.review_events import ReviewEventsDB
from backend.services import review_event_log as rel

REPO = "owner/repo"
PR = 42
RUN = "run-abc"


@pytest.fixture
def events_db(monkeypatch):
    p = Path(tempfile.mkdtemp()) / "recorders_test.db"
    db = ReviewEventsDB(Database(p))
    monkeypatch.setattr(rel, "get_review_events_db", lambda: db)
    return db


def only_event(events_db):
    events, total = events_db.list_events(repo=REPO)
    assert total == 1
    return events[0]


def test_new_run_id_is_unique():
    assert rel.new_run_id() != rel.new_run_id()


def test_record_started(events_db):
    rel.record_started(
        RUN, REPO, PR, attempt=1, max_attempts=3, reviewer_agent="pb",
        is_followup=True, auto_started=True, review_file="/tmp/r.md", pid=123,
    )
    row = only_event(events_db)
    assert row["event"] == "started"
    assert row["run_id"] == RUN
    assert row["attempt"] == 1
    assert row["max_attempts"] == 3
    assert row["reviewer_agent"] == "pb"
    assert row["is_followup"] == 1
    assert row["auto_started"] == 1
    assert row["review_file"] == "/tmp/r.md"
    assert row["pid"] == 123
    assert row["reason"] is None


def test_record_completed(events_db):
    rel.record_completed(RUN, REPO, PR, attempt=2, review_id=969, score=8.0,
                         review_file="/tmp/r.md")
    row = only_event(events_db)
    assert row["event"] == "completed"
    assert row["attempt"] == 2
    assert row["review_id"] == 969
    assert row["score"] == 8.0
    assert row["reason"] is None


def test_record_failed_carries_reason_and_detail(events_db):
    rel.record_failed(RUN, REPO, PR, attempt=1, max_attempts=3,
                      reason=rel.REASON_NO_OUTPUT, exit_code=0,
                      detail="exited 0 without writing /tmp/r.md")
    row = only_event(events_db)
    assert row["event"] == "failed"
    assert row["reason"] == "no_output"
    assert row["exit_code"] == 0
    assert "without writing" in row["detail"]


def test_record_retry_scheduled_describes_the_delay(events_db):
    rel.record_retry_scheduled(RUN, REPO, PR, attempt=1, max_attempts=3, delay_seconds=30)
    row = only_event(events_db)
    assert row["event"] == "retry_scheduled"
    assert "30" in row["detail"]


def test_record_gave_up_sets_attempts_exhausted(events_db):
    rel.record_gave_up(RUN, REPO, PR, attempt=3, max_attempts=3)
    row = only_event(events_db)
    assert row["event"] == "gave_up"
    assert row["reason"] == "attempts_exhausted"
    assert row["attempt"] == 3


def test_record_cancelled(events_db):
    rel.record_cancelled(RUN, REPO, PR, attempt=1)
    row = only_event(events_db)
    assert row["event"] == "cancelled"
    assert row["reason"] == "cancelled"


def test_every_reason_constant_is_in_the_db_vocabulary():
    from backend.database.review_events import VALID_REASONS
    for constant in (rel.REASON_NO_OUTPUT, rel.REASON_NONZERO_EXIT,
                     rel.REASON_SPAWN_FAILED, rel.REASON_ATTEMPTS_EXHAUSTED,
                     rel.REASON_CANCELLED):
        assert constant in VALID_REASONS


@pytest.mark.parametrize("recorder,kwargs", [
    ("record_started", dict(attempt=1, max_attempts=3, reviewer_agent="default",
                            is_followup=False, auto_started=False,
                            review_file="/tmp/r.md", pid=1)),
    ("record_completed", dict(attempt=1, review_id=1, score=1.0, review_file="/tmp/r.md")),
    ("record_failed", dict(attempt=1, max_attempts=3, reason="no_output")),
    ("record_retry_scheduled", dict(attempt=1, max_attempts=3, delay_seconds=30)),
    ("record_gave_up", dict(attempt=3, max_attempts=3)),
    ("record_cancelled", dict(attempt=1)),
])
def test_recorders_never_raise_when_the_db_is_broken(monkeypatch, recorder, kwargs):
    """A dead database must not take a review down with it."""
    def boom():
        raise RuntimeError("database is on fire")

    monkeypatch.setattr(rel, "get_review_events_db", boom)
    getattr(rel, recorder)(RUN, REPO, PR, **kwargs)  # must not raise


def test_recorders_never_raise_on_bad_vocabulary(monkeypatch, events_db):
    """Even a programming error in a call site must not break the review."""
    rel._record("failed", RUN, REPO, PR, reason="not-a-real-reason")  # must not raise
    _, total = events_db.list_events(repo=REPO)
    assert total == 0


def test_recorders_do_not_touch_the_application_database():
    """The autouse conftest guard must redirect recorder writes away from the app DB.

    Regression guard: driving a review lifecycle in a test used to write fake
    events into the real pr_explorer.db, polluting the Review Logs tab.
    """
    from backend.config import DB_PATH
    from backend.database import get_review_events_db as real_getter

    assert rel.get_review_events_db is not real_getter, \
        "conftest must patch the recorders' DB getter"
    assert str(rel.get_review_events_db().db.db_path) != str(DB_PATH), \
        "recorders must not resolve the application database during tests"
