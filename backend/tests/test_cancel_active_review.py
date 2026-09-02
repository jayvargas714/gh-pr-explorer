"""Tests for cancel_active_review — the shared terminate-and-remove path.

Used by the DELETE route (user cancel) and the stale-review watcher (automatic
cancel on new commits). Processes are fakes; nothing here spawns anything.
"""

import subprocess

import pytest

from backend.extensions import active_reviews, reviews_lock
from backend.services import review_service
from backend.services.review_event_log import REASON_CANCELLED, REASON_STALE_COMMITS

KEY = "owner/repo/42"


class FakeProcess:
    def __init__(self, hangs=False):
        self.hangs = hangs
        self.pid = 4242
        self.terminated = False
        self.killed = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout):
        if self.hangs and not self.killed:
            raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout)

    def kill(self):
        self.killed = True


@pytest.fixture(autouse=True)
def clean_active_reviews():
    with reviews_lock:
        active_reviews.clear()
    yield
    with reviews_lock:
        active_reviews.clear()


@pytest.fixture
def cancelled_events(monkeypatch):
    calls = []
    monkeypatch.setattr(
        review_service, "record_cancelled",
        lambda *args, **kwargs: calls.append({"args": args, "kwargs": kwargs}),
    )
    return calls


def put_review(status="running", process=None, run_id="run-1"):
    with reviews_lock:
        active_reviews[KEY] = {
            "status": status,
            "process": process,
            "run_id": run_id,
            "attempt": 1,
        }


def test_cancels_running_review_and_records_reason(cancelled_events):
    process = FakeProcess()
    put_review(process=process)

    result = review_service.cancel_active_review(
        KEY, reason=REASON_STALE_COMMITS, detail="new commits aaaa1111 -> bbbb2222",
    )

    assert result == "cancelled"
    assert process.terminated is True
    with reviews_lock:
        assert KEY not in active_reviews
    assert len(cancelled_events) == 1
    assert cancelled_events[0]["args"] == ("run-1", "owner/repo", 42)
    assert cancelled_events[0]["kwargs"]["reason"] == REASON_STALE_COMMITS
    assert "bbbb2222" in cancelled_events[0]["kwargs"]["detail"]


def test_default_reason_is_user_cancelled(cancelled_events):
    put_review(process=FakeProcess())

    review_service.cancel_active_review(KEY)

    assert cancelled_events[0]["kwargs"]["reason"] == REASON_CANCELLED


def test_unknown_key_is_not_found(cancelled_events):
    assert review_service.cancel_active_review(KEY) == "not_found"
    assert cancelled_events == []


def test_finished_entry_is_skipped_when_running_required(cancelled_events):
    put_review(status="completed")

    result = review_service.cancel_active_review(KEY, require_running=True)

    assert result == "not_running"
    with reviews_lock:
        assert KEY in active_reviews
    assert cancelled_events == []


def test_finished_entry_is_still_removed_by_default(cancelled_events):
    put_review(status="completed")

    result = review_service.cancel_active_review(KEY)

    assert result == "cancelled"
    with reviews_lock:
        assert KEY not in active_reviews
    assert len(cancelled_events) == 1


def test_hung_process_is_killed(cancelled_events):
    process = FakeProcess(hangs=True)
    put_review(process=process)

    result = review_service.cancel_active_review(KEY)

    assert result == "cancelled"
    assert process.killed is True
    with reviews_lock:
        assert KEY not in active_reviews


def test_terminate_failure_keeps_the_entry(cancelled_events):
    class ExplodingProcess(FakeProcess):
        def terminate(self):
            raise OSError("no such process table")

    put_review(process=ExplodingProcess())

    result = review_service.cancel_active_review(KEY)

    assert result == "error"
    with reviews_lock:
        assert KEY in active_reviews
    assert cancelled_events == []


def test_user_cancel_cleans_up_status_comments(monkeypatch, cancelled_events):
    deleted = []
    monkeypatch.setattr(
        review_service, "delete_status_comments",
        lambda owner, repo, pr_number: deleted.append((owner, repo, pr_number)),
    )
    put_review(process=FakeProcess())

    assert review_service.cancel_active_review(KEY) == "cancelled"
    assert deleted == [("owner", "repo", 42)]


def test_stale_cancel_leaves_status_comments_alone(monkeypatch, cancelled_events):
    """The stale watcher's restart posts its own started comment, which
    supersedes the old one — deleting here would race that flow."""
    deleted = []
    monkeypatch.setattr(
        review_service, "delete_status_comments",
        lambda owner, repo, pr_number: deleted.append((owner, repo, pr_number)),
    )
    put_review(process=FakeProcess())

    review_service.cancel_active_review(KEY, reason=REASON_STALE_COMMITS)
    assert deleted == []
