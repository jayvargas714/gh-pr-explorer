"""Tests that begin_review announces the review on the PR only when it starts.

start_review_process and the comment poster are both stubbed, so nothing here
spawns a Claude CLI process or touches GitHub.
"""

import pytest

from backend.extensions import active_reviews, reviews_lock
from backend.services import review_service

OWNER = "owner"
REPO = "repo"
PR = 42
KEY = f"{OWNER}/{REPO}/{PR}"
PR_URL = f"https://github.com/{OWNER}/{REPO}/pull/{PR}"


@pytest.fixture(autouse=True)
def clean_active_reviews():
    """Keep the process-wide active_reviews registry isolated per test."""
    with reviews_lock:
        active_reviews.clear()
    yield
    with reviews_lock:
        active_reviews.clear()


@pytest.fixture
def posted(monkeypatch):
    calls = []
    monkeypatch.setattr(
        review_service, "post_review_started_comment",
        lambda *args, **kwargs: calls.append({"args": args, "kwargs": kwargs}),
    )
    return calls


def stub_spawn(monkeypatch, process, result):
    monkeypatch.setattr(
        review_service, "start_review_process",
        lambda *args, **kwargs: (process, result, kwargs.get("is_followup", False)),
    )


def test_successful_start_announces_review(monkeypatch, posted):
    stub_spawn(monkeypatch, object(), "/tmp/review.md")

    payload, status = review_service.begin_review(
        OWNER, REPO, PR, PR_URL, reviews_db=None, reviewer_type="security"
    )

    assert status == 201
    assert len(posted) == 1
    assert posted[0]["args"] == (OWNER, REPO, PR)
    assert posted[0]["kwargs"]["reviewer_type"] == "security"
    assert posted[0]["kwargs"]["is_followup"] is False
    assert posted[0]["kwargs"]["auto_started"] is False


def test_auto_started_flag_is_passed_through(monkeypatch, posted):
    stub_spawn(monkeypatch, object(), "/tmp/review.md")

    review_service.begin_review(
        OWNER, REPO, PR, PR_URL, reviews_db=None, auto_started=True
    )

    assert posted[0]["kwargs"]["auto_started"] is True


def test_failed_spawn_announces_nothing(monkeypatch, posted):
    stub_spawn(monkeypatch, None, "claude CLI not found")

    payload, status = review_service.begin_review(
        OWNER, REPO, PR, PR_URL, reviews_db=None
    )

    assert status == 500
    assert posted == []


def test_duplicate_review_announces_nothing(monkeypatch, posted):
    stub_spawn(monkeypatch, object(), "/tmp/review.md")
    with reviews_lock:
        active_reviews[KEY] = {"status": "running"}

    payload, status = review_service.begin_review(
        OWNER, REPO, PR, PR_URL, reviews_db=None
    )

    assert status == 409
    assert posted == []
