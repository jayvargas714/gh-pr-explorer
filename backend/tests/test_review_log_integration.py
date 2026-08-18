"""End-to-end test of the review event log.

Drives a real review lifecycle (a failed attempt, a retry, a success) through the
real recorders into a real database, then reads it back through the HTTP API. The
unit tests cover each layer; this one proves they are actually wired together.

No Claude CLI process is spawned: start_review_process is stubbed and the process
objects are fakes with scripted exit codes.
"""

import tempfile
from pathlib import Path

import pytest

from backend import create_app
from backend.database.base import Database
from backend.database.review_events import ReviewEventsDB
from backend.extensions import active_reviews, reviews_lock
from backend.services import review_event_log as rel
from backend.services import review_service

OWNER = "owner"
REPO = "repo"
PR = 4242
KEY = f"{OWNER}/{REPO}/{PR}"
FULL_REPO = f"{OWNER}/{REPO}"
PR_URL = f"https://github.com/{OWNER}/{REPO}/pull/{PR}"


class FakeProcess:
    def __init__(self, exit_code=0, pid=1234):
        self._exit_code = exit_code
        self.pid = pid

    def poll(self):
        return self._exit_code

    def communicate(self, timeout=None):
        return ("", "")


@pytest.fixture
def stack(monkeypatch, tmp_path):
    """Real events DB shared by the recorders and the HTTP layer."""
    db_path = Path(tempfile.mkdtemp()) / "integration.db"
    events_db = ReviewEventsDB(Database(db_path))

    monkeypatch.setattr(rel, "get_review_events_db", lambda: events_db)
    import backend.routes.review_log_routes as rlr
    monkeypatch.setattr(rlr, "get_review_events_db", lambda: events_db)

    # Keep the review lifecycle off GitHub and off the reviews table.
    monkeypatch.setattr(review_service, "save_review_to_db",
                        lambda key, review, status, reviews_db: 501)
    monkeypatch.setattr(review_service, "_spawn_auto_verdict", lambda key, review_id: None)
    monkeypatch.setattr(review_service, "post_review_started_comment",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(review_service, "get_review_retry_settings", lambda: (3, 0))

    with reviews_lock:
        active_reviews.clear()

    app = create_app()
    app.config["TESTING"] = True
    yield app.test_client(), tmp_path

    with reviews_lock:
        active_reviews.clear()


def test_failed_then_retried_review_reads_back_as_one_run(stack):
    client, tmp_path = stack

    # Attempt 1 writes nothing; the retry writes its review file.
    first_file = tmp_path / "review.md"
    retry_file = tmp_path / "retry.md"
    spawns = []

    def fake_spawn(*args, **kwargs):
        spawns.append(kwargs)
        followup = kwargs.get("is_followup", False)
        if len(spawns) == 1:
            return FakeProcess(exit_code=0, pid=1001), str(first_file), followup
        retry_file.write_text("# Review\n\n**Score: 8/10**")
        return FakeProcess(exit_code=0, pid=1002), str(retry_file), followup

    import backend.services.review_service as rs
    original_spawn = rs.start_review_process
    rs.start_review_process = fake_spawn
    try:
        payload, status = review_service.begin_review(
            OWNER, REPO, PR, PR_URL, reviews_db=None, reviewer_type="default",
        )
        assert status == 201

        # Attempt 1 exits 0 with no file -> failed attempt, retry armed.
        review = review_service.check_review_status(KEY, active_reviews, reviews_lock, None)
        assert review["status"] == "running"

        # Backoff is 0, so the next poll starts attempt 2.
        review = review_service.check_review_status(KEY, active_reviews, reviews_lock, None)
        assert review["attempt"] == 2

        # Attempt 2 exits 0 with a file on disk -> completed.
        review = review_service.check_review_status(KEY, active_reviews, reviews_lock, None)
        assert review["status"] == "completed"
    finally:
        rs.start_review_process = original_spawn

    # --- read the whole story back through the API -------------------------
    body = client.get(f"/api/review-logs?repo={FULL_REPO}").get_json()
    events = body["events"]

    # started(1) -> failed(1) -> retry_scheduled -> started(2) -> completed(2)
    assert body["total"] == 5
    # Newest first.
    assert [e["event"] for e in events] == [
        "completed", "started", "retry_scheduled", "failed", "started",
    ]

    # One run ties them together.
    assert len({e["run_id"] for e in events}) == 1

    failed = next(e for e in events if e["event"] == "failed")
    assert failed["reason"] == "no_output"
    assert failed["exit_code"] == 0
    assert failed["attempt"] == 1
    assert str(first_file) in failed["detail"]

    started_attempts = sorted(e["attempt"] for e in events if e["event"] == "started")
    assert started_attempts == [1, 2]

    completed = next(e for e in events if e["event"] == "completed")
    assert completed["attempt"] == 2
    assert completed["review_id"] == 501

    # --- and the stats strip reflects the rescue ---------------------------
    stats = client.get(f"/api/review-logs/stats?repo={FULL_REPO}").get_json()["stats"]
    assert stats["runs"] == 1
    assert stats["completed"] == 1
    assert stats["failed"] == 0, "a run rescued by a retry is not a failed run"
    assert stats["rescued_by_retry"] == 1
    assert stats["by_reason"] == {"no_output": 1}


def test_exhausted_review_reads_back_as_gave_up(stack):
    client, tmp_path = stack

    import backend.services.review_service as rs
    original_spawn = rs.start_review_process
    rs.start_review_process = lambda *args, **kwargs: (
        FakeProcess(exit_code=1, pid=2001), str(tmp_path / "never.md"), False,
    )
    try:
        review_service.begin_review(OWNER, REPO, PR, PR_URL, reviews_db=None)
        for _ in range(8):
            review = review_service.check_review_status(KEY, active_reviews, reviews_lock, None)
            if review["status"] != "running":
                break
        assert review["status"] == "failed"
    finally:
        rs.start_review_process = original_spawn

    body = client.get(f"/api/review-logs?repo={FULL_REPO}").get_json()
    kinds = [e["event"] for e in body["events"]]

    assert kinds.count("started") == 3, "initial attempt plus two retries"
    assert kinds.count("failed") == 3
    assert kinds.count("gave_up") == 1

    gave_up = next(e for e in body["events"] if e["event"] == "gave_up")
    assert gave_up["reason"] == "attempts_exhausted"
    assert gave_up["attempt"] == 3
    assert gave_up["max_attempts"] == 3

    stats = client.get(f"/api/review-logs/stats?repo={FULL_REPO}").get_json()["stats"]
    assert stats["runs"] == 1
    assert stats["completed"] == 0
    assert stats["failed"] == 1
    assert stats["by_reason"]["nonzero_exit"] == 3
