"""Tests for GET /api/reviews — the live registry behind the Running Reviews view."""

import pytest

from backend import create_app
from backend.extensions import active_reviews, reviews_lock


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with reviews_lock:
        active_reviews.clear()
    yield app.test_client()
    with reviews_lock:
        active_reviews.clear()


def test_active_reviews_carry_reviewer_and_attempt_budget(client):
    with reviews_lock:
        active_reviews["owner/repo/42"] = {
            "process": None,  # no live process: status checks leave the entry alone
            "status": "running",
            "started_at": "2026-08-31T21:00:00+00:00",
            "pr_url": "https://github.com/owner/repo/pull/42",
            "review_file": "/tmp/r.md",
            "is_followup": True,
            "auto_started": True,
            "reviewer_type": "pb",
            "attempt": 2,
            "max_attempts": 3,
        }

    resp = client.get("/api/reviews")

    assert resp.status_code == 200
    rows = resp.get_json()["reviews"]
    assert len(rows) == 1
    row = rows[0]
    assert row["key"] == "owner/repo/42"
    assert row["status"] == "running"
    assert row["reviewer_type"] == "pb"
    assert row["attempt"] == 2
    assert row["max_attempts"] == 3
    assert row["is_followup"] is True
    assert row["auto_started"] is True
