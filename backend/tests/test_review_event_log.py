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


def test_record_cancelled_with_stale_commits_reason_and_detail(events_db):
    rel.record_cancelled(RUN, REPO, PR, attempt=1,
                         reason=rel.REASON_STALE_COMMITS,
                         detail="new commits aaaa11111 -> bbbb22222")
    row = only_event(events_db)
    assert row["event"] == "cancelled"
    assert row["reason"] == "stale_commits"
    assert "bbbb22222" in row["detail"]


def test_every_reason_constant_is_in_the_db_vocabulary():
    from backend.database.review_events import VALID_REASONS
    for constant in (rel.REASON_NO_OUTPUT, rel.REASON_NONZERO_EXIT,
                     rel.REASON_SPAWN_FAILED, rel.REASON_ATTEMPTS_EXHAUSTED,
                     rel.REASON_CANCELLED, rel.REASON_STALE_COMMITS,
                     rel.REASON_ORPHANED):
        assert constant in VALID_REASONS


def test_get_orphaned_runs_finds_started_runs_without_terminal_events(events_db):
    # Run A: completed — not an orphan.
    events_db.log_event("started", REPO, 1, "run-a", attempt=1, pid=11,
                        reviewer_agent="default", is_followup=False, auto_started=True)
    events_db.log_event("completed", REPO, 1, "run-a", attempt=1, review_id=5)
    # Run B: in flight when the process died — orphan.
    events_db.log_event("started", REPO, 2, "run-b", attempt=1, pid=22,
                        reviewer_agent="pb", is_followup=True, auto_started=False)
    # Run C: lost during retry backoff (failed attempt, retry armed, no terminal) — orphan.
    events_db.log_event("started", REPO, 3, "run-c", attempt=1, pid=33,
                        reviewer_agent="default", is_followup=False, auto_started=True)
    events_db.log_event("failed", REPO, 3, "run-c", attempt=1, reason="nonzero_exit")
    events_db.log_event("retry_scheduled", REPO, 3, "run-c", attempt=1)
    # Run D: cancelled — not an orphan.
    events_db.log_event("started", REPO, 4, "run-d", attempt=1, pid=44)
    events_db.log_event("cancelled", REPO, 4, "run-d", attempt=1, reason="cancelled")

    orphans = events_db.get_orphaned_runs()

    by_run = {o["run_id"]: o for o in orphans}
    assert set(by_run) == {"run-b", "run-c"}
    b = by_run["run-b"]
    assert b["repo"] == REPO
    assert b["pr_number"] == 2
    assert b["pid"] == 22
    assert b["reviewer_agent"] == "pb"
    assert b["is_followup"] == 1
    assert b["auto_started"] == 0
    assert b["attempt"] == 1
    assert b["created_at"]


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


def test_get_run_id_for_review_finds_the_completing_run(events_db):
    events_db.log_event("started", REPO, PR, RUN, attempt=1)
    events_db.log_event("completed", REPO, PR, RUN, attempt=1, review_id=969)
    assert events_db.get_run_id_for_review(969) == RUN


def test_get_run_id_for_review_is_none_when_no_run_wrote_it(events_db):
    events_db.log_event("completed", REPO, PR, RUN, attempt=1, review_id=969)
    assert events_db.get_run_id_for_review(12345) is None


def test_record_verdict_posted_attaches_to_the_reviews_run(events_db):
    events_db.log_event("completed", REPO, PR, RUN, attempt=1, review_id=969)
    rel.record_verdict_posted(
        REPO, PR, review_id=969, event="APPROVE", auto_started=True,
        detail="0 critical, 1 major",
    )
    events, _ = events_db.list_events(repo=REPO, event="verdict_posted")
    assert len(events) == 1
    row = events[0]
    assert row["run_id"] == RUN
    assert row["review_id"] == 969
    assert row["auto_started"] == 1
    assert row["detail"] == "APPROVE — 0 critical, 1 major"
    assert row["reason"] is None


def test_record_verdict_posted_marks_manual_posts(events_db):
    events_db.log_event("completed", REPO, PR, RUN, attempt=1, review_id=969)
    rel.record_verdict_posted(REPO, PR, review_id=969, event="COMMENT", auto_started=False)
    row = events_db.list_events(repo=REPO, event="verdict_posted")[0][0]
    assert row["auto_started"] == 0
    assert row["detail"] == "COMMENT"


def test_record_verdict_not_posted_carries_reason_and_detail(events_db):
    events_db.log_event("completed", REPO, PR, RUN, attempt=1, review_id=969)
    rel.record_verdict_not_posted(
        REPO, PR, review_id=969, reason=rel.REASON_AUTO_SUPPRESSED,
        detail="auto-approve disabled",
    )
    row = events_db.list_events(repo=REPO, event="verdict_not_posted")[0][0]
    assert row["run_id"] == RUN
    assert row["reason"] == "auto_suppressed"
    assert row["detail"] == "auto-approve disabled"
    assert row["auto_started"] == 1


def test_verdict_recorders_skip_reviews_with_no_run(events_db):
    """A review that predates the log has no run to hang the verdict on."""
    rel.record_verdict_posted(REPO, PR, review_id=969, event="APPROVE", auto_started=True)
    rel.record_verdict_not_posted(
        REPO, PR, review_id=969, reason=rel.REASON_POST_FAILED, detail="boom",
    )
    assert events_db.list_events(repo=REPO)[1] == 0


def test_verdict_recorders_never_raise(monkeypatch):
    """A broken log must not take the verdict down with it."""
    class Exploding:
        def get_run_id_for_review(self, review_id):
            raise RuntimeError("db gone")

    monkeypatch.setattr(rel, "get_review_events_db", lambda: Exploding())
    rel.record_verdict_posted(REPO, PR, review_id=1, event="APPROVE", auto_started=True)
    rel.record_verdict_not_posted(REPO, PR, review_id=1, reason=rel.REASON_POST_FAILED)
