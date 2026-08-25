"""Integration tests for the review log routes via the Flask test client."""

import tempfile
from pathlib import Path

import pytest

from backend.database.base import Database
from backend.database.review_events import ReviewEventsDB
from backend.database.reviews import ReviewsDB
from backend import create_app

REPO = "owner/repo"


@pytest.fixture
def client(monkeypatch):
    tmp = Path(tempfile.mkdtemp()) / "review_log_routes.db"
    db = Database(tmp)
    events_db = ReviewEventsDB(db)
    # The list route also tallies issue counts out of `reviews`; without this the
    # tests would read the developer's live application database.
    reviews_db = ReviewsDB(db)
    import backend.routes.review_log_routes as rlr
    monkeypatch.setattr(rlr, "get_review_events_db", lambda: events_db)
    monkeypatch.setattr(rlr, "get_reviews_db", lambda: reviews_db)
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client(), events_db


def test_empty_log_returns_empty_list(client):
    c, _ = client
    resp = c.get("/api/review-logs")
    assert resp.status_code == 200
    assert resp.get_json() == {"events": [], "total": 0}


def test_lists_events_newest_first(client):
    c, db = client
    db.log_event("started", REPO, 42, "run-1", attempt=1)
    db.log_event("completed", REPO, 42, "run-1", attempt=1, score=8.0)

    resp = c.get("/api/review-logs")
    body = resp.get_json()
    assert body["total"] == 2
    assert body["events"][0]["event"] == "completed"
    assert body["events"][0]["run_id"] == "run-1"
    assert body["events"][0]["score"] == 8.0


def test_filters_by_repo_and_pr(client):
    c, db = client
    db.log_event("started", REPO, 1, "run-1")
    db.log_event("started", REPO, 2, "run-2")
    db.log_event("started", "other/repo", 3, "run-3")

    assert c.get("/api/review-logs?repo=owner/repo").get_json()["total"] == 2
    assert c.get("/api/review-logs?repo=owner/repo&pr_number=2").get_json()["total"] == 1


def test_filters_by_event_and_reason(client):
    c, db = client
    db.log_event("started", REPO, 1, "run-1")
    db.log_event("failed", REPO, 1, "run-1", reason="no_output")

    assert c.get("/api/review-logs?event=failed").get_json()["total"] == 1
    assert c.get("/api/review-logs?reason=no_output").get_json()["total"] == 1
    assert c.get("/api/review-logs?reason=nonzero_exit").get_json()["total"] == 0


def test_rejects_unknown_event_filter(client):
    c, _ = client
    resp = c.get("/api/review-logs?event=exploded")
    assert resp.status_code == 400


def test_rejects_unknown_reason_filter(client):
    c, _ = client
    resp = c.get("/api/review-logs?reason=vibes")
    assert resp.status_code == 400


def test_limit_is_capped(client):
    c, db = client
    for i in range(5):
        db.log_event("started", REPO, i, f"run-{i}")

    resp = c.get("/api/review-logs?limit=99999")
    assert resp.status_code == 200
    assert len(resp.get_json()["events"]) == 5


def test_negative_offset_is_clamped(client):
    c, db = client
    db.log_event("started", REPO, 1, "run-1")

    resp = c.get("/api/review-logs?offset=-5")
    assert resp.status_code == 200
    assert resp.get_json()["total"] == 1


def test_pagination(client):
    c, db = client
    for i in range(5):
        db.log_event("started", REPO, i, f"run-{i}")

    body = c.get("/api/review-logs?limit=2&offset=0").get_json()
    assert body["total"] == 5
    assert len(body["events"]) == 2

    body = c.get("/api/review-logs?limit=2&offset=4").get_json()
    assert body["total"] == 5
    assert len(body["events"]) == 1


def test_stats_endpoint(client):
    c, db = client
    db.log_event("started", REPO, 1, "run-1", attempt=1)
    db.log_event("failed", REPO, 1, "run-1", attempt=1, reason="no_output")
    db.log_event("started", REPO, 1, "run-1", attempt=2)
    db.log_event("completed", REPO, 1, "run-1", attempt=2, score=9.0)

    stats = c.get("/api/review-logs/stats?repo=owner/repo").get_json()["stats"]
    assert stats["runs"] == 1
    assert stats["completed"] == 1
    assert stats["rescued_by_retry"] == 1
    assert stats["by_reason"]["no_output"] == 1


def test_stats_endpoint_on_empty_log(client):
    c, _ = client
    stats = c.get("/api/review-logs/stats").get_json()["stats"]
    assert stats == {
        "runs": 0, "completed": 0, "failed": 0,
        "rescued_by_retry": 0, "by_reason": {},
    }


def _review_with(reviews_db, *, critical=0, major=0, minor=0):
    import json
    issues = lambda n: [{"title": f"i{i}"} for i in range(n)]
    return reviews_db.save_review(
        pr_number=1, repo=REPO,
        content_json=json.dumps({"sections": [
            {"type": "critical", "issues": issues(critical)},
            {"type": "major", "issues": issues(major)},
            {"type": "minor", "issues": issues(minor)},
        ]}),
    )


def test_completed_events_carry_issue_counts(client):
    c, events_db = client
    reviews_db = ReviewsDB(events_db.db)
    rid = _review_with(reviews_db, critical=1, major=2, minor=3)
    events_db.log_event("completed", REPO, 1, "run-1", attempt=1, review_id=rid)

    events = c.get("/api/review-logs").get_json()["events"]
    assert events[0]["issue_counts"] == {"critical": 1, "major": 2, "minor": 3}


def test_events_without_a_review_have_null_counts(client):
    c, events_db = client
    reviews_db = ReviewsDB(events_db.db)
    _review_with(reviews_db)
    events_db.log_event("started", REPO, 1, "run-1", attempt=1)

    events = c.get("/api/review-logs").get_json()["events"]
    assert events[0]["issue_counts"] is None


def test_counts_are_null_when_the_review_is_gone(client):
    """A dangling review_id must read as unknown, never as a clean review."""
    c, events_db = client
    events_db.log_event("completed", REPO, 1, "run-1", attempt=1, review_id=424242)

    events = c.get("/api/review-logs").get_json()["events"]
    assert events[0]["issue_counts"] is None
