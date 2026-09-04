"""Tests for which review a follow-up uses as its parent.

A review whose attempts were all exhausted is stored with an {"error": true}
content stub carrying no findings. Handing that to a follow-up asks the reviewer
to track resolution against an empty issue list, so the parent lookup must skip
stubs and walk back to the last review that actually produced findings.

start_review_process is stubbed, so nothing here spawns a Claude CLI process.
"""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backend.database.base import Database
from backend.database.reviews import ReviewsDB
from backend.extensions import active_reviews, reviews_lock
from backend.services import review_service

OWNER = "owner"
REPO = "repo"
PR = 42
KEY = f"{OWNER}/{REPO}/{PR}"
FULL_REPO = f"{OWNER}/{REPO}"
PR_URL = f"https://github.com/{OWNER}/{REPO}/pull/{PR}"

BASE_TIME = datetime(2026, 8, 18, 12, 0, 0)


@pytest.fixture(autouse=True)
def clean_active_reviews():
    with reviews_lock:
        active_reviews.clear()
    yield
    with reviews_lock:
        active_reviews.clear()


@pytest.fixture
def reviews_db():
    p = Path(tempfile.mkdtemp()) / "followup_parent.db"
    return ReviewsDB(Database(p))


@pytest.fixture
def spawned(monkeypatch):
    """Capture what start_review_process was asked to run."""
    calls = []

    def fake_spawn(pr_url, owner, repo, pr_number, is_followup=False,
                   previous_review_content=None, reviewer_type="default",
                   head_sha=None, **kwargs):
        calls.append({
            "is_followup": is_followup,
            "previous_review_content": previous_review_content,
        })
        return object(), "/tmp/review.md", is_followup

    monkeypatch.setattr(review_service, "start_review_process", fake_spawn)
    monkeypatch.setattr(review_service, "post_review_started_comment",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(review_service, "record_started", lambda *args, **kwargs: None)
    return calls


def findings_content(summary):
    return json.dumps({
        "schema_version": "1.0.0",
        "metadata": {"pr_number": PR, "repository": FULL_REPO},
        "summary": summary,
        "sections": [{"type": "major", "display_name": "Major Concerns", "issues": [
            {"title": "Something real", "location": {"file": "a.go", "start_line": 1,
                                                     "end_line": 2}, "problem": "x"}]}],
        "highlights": [],
        "score": {"overall": 8.0},
    })


STUB_CONTENT = json.dumps({
    "schema_version": "1.0.0",
    "error": True,
    "metadata": {"pr_number": PR, "repository": FULL_REPO},
    "summary": "",
    "sections": [],
    "highlights": [],
    "score": {"overall": 0},
})


def add_review(reviews_db, content, minutes, status="completed", score=8.0):
    """Insert a review at a controlled timestamp so ordering is deterministic."""
    return reviews_db.save_review(
        pr_number=PR, repo=FULL_REPO, pr_title="A PR", pr_author="dev",
        pr_url=PR_URL, status=status, content_json=content, score=score,
        review_timestamp=BASE_TIME + timedelta(minutes=minutes),
    )


def start_followup(reviews_db, previous_review_id=None):
    return review_service.begin_review(
        OWNER, REPO, PR, PR_URL, reviews_db,
        is_followup=True, previous_review_id=previous_review_id,
    )


# --- the carry-over bug ------------------------------------------------------

def test_stub_latest_review_is_skipped_for_the_last_real_one(reviews_db, spawned):
    """The regression: a failure stub must not become a follow-up's parent."""
    real_id = add_review(reviews_db, findings_content("real findings"), minutes=0)
    add_review(reviews_db, STUB_CONTENT, minutes=10, status="failed", score=0.0)

    payload, status = start_followup(reviews_db)

    assert status == 201
    assert payload["is_followup"] is True
    assert len(spawned) == 1
    assert spawned[0]["is_followup"] is True
    assert "real findings" in spawned[0]["previous_review_content"]
    assert '"error": true' not in spawned[0]["previous_review_content"]

    with reviews_lock:
        assert active_reviews[KEY]["parent_review_id"] == real_id


def test_walks_back_past_several_stubs(reviews_db, spawned):
    real_id = add_review(reviews_db, findings_content("oldest real"), minutes=0)
    for i in range(1, 4):
        add_review(reviews_db, STUB_CONTENT, minutes=i * 10, status="failed", score=0.0)

    start_followup(reviews_db)

    assert "oldest real" in spawned[0]["previous_review_content"]
    with reviews_lock:
        assert active_reviews[KEY]["parent_review_id"] == real_id


def test_all_stubs_falls_back_to_a_normal_review(reviews_db, spawned):
    add_review(reviews_db, STUB_CONTENT, minutes=0, status="failed", score=0.0)
    add_review(reviews_db, STUB_CONTENT, minutes=10, status="failed", score=0.0)

    payload, status = start_followup(reviews_db)

    assert status == 201
    assert payload["is_followup"] is False
    assert spawned[0]["is_followup"] is False
    assert spawned[0]["previous_review_content"] is None
    with reviews_lock:
        assert active_reviews[KEY]["parent_review_id"] is None


def test_explicit_stub_parent_walks_back(reviews_db, spawned):
    """Naming a stub explicitly must not force it to be used."""
    real_id = add_review(reviews_db, findings_content("real findings"), minutes=0)
    stub_id = add_review(reviews_db, STUB_CONTENT, minutes=10, status="failed", score=0.0)

    start_followup(reviews_db, previous_review_id=stub_id)

    assert "real findings" in spawned[0]["previous_review_content"]
    with reviews_lock:
        assert active_reviews[KEY]["parent_review_id"] == real_id


def test_explicit_stub_parent_with_no_alternative_falls_back(reviews_db, spawned):
    stub_id = add_review(reviews_db, STUB_CONTENT, minutes=0, status="failed", score=0.0)

    payload, _ = start_followup(reviews_db, previous_review_id=stub_id)

    assert payload["is_followup"] is False
    assert spawned[0]["previous_review_content"] is None


# --- unchanged behaviour ----------------------------------------------------

def test_real_latest_review_is_used(reviews_db, spawned):
    real_id = add_review(reviews_db, findings_content("newest real"), minutes=10)
    add_review(reviews_db, findings_content("older real"), minutes=0)

    start_followup(reviews_db)

    assert "newest real" in spawned[0]["previous_review_content"]
    with reviews_lock:
        assert active_reviews[KEY]["parent_review_id"] == real_id


def test_explicit_real_parent_is_honoured(reviews_db, spawned):
    older_id = add_review(reviews_db, findings_content("older real"), minutes=0)
    add_review(reviews_db, findings_content("newest real"), minutes=10)

    start_followup(reviews_db, previous_review_id=older_id)

    assert "older real" in spawned[0]["previous_review_content"]
    with reviews_lock:
        assert active_reviews[KEY]["parent_review_id"] == older_id


def test_no_reviews_at_all_falls_back_to_a_normal_review(reviews_db, spawned):
    payload, status = start_followup(reviews_db)

    assert status == 201
    assert payload["is_followup"] is False
    assert spawned[0]["previous_review_content"] is None


def test_other_prs_reviews_are_not_borrowed(reviews_db, spawned):
    reviews_db.save_review(
        pr_number=99, repo=FULL_REPO, pr_title="Other PR", pr_author="dev",
        pr_url=PR_URL, status="completed", content_json=findings_content("other PR"),
        score=8.0, review_timestamp=BASE_TIME,
    )

    payload, _ = start_followup(reviews_db)

    assert payload["is_followup"] is False
    assert spawned[0]["previous_review_content"] is None


# --- stub detection edge cases ----------------------------------------------

def test_empty_content_counts_as_unusable(reviews_db, spawned):
    real_id = add_review(reviews_db, findings_content("real findings"), minutes=0)
    add_review(reviews_db, "", minutes=10)

    start_followup(reviews_db)

    with reviews_lock:
        assert active_reviews[KEY]["parent_review_id"] == real_id


def test_unparseable_content_is_still_offered(reviews_db, spawned):
    """Not an error stub — start_review_process passes odd content through as-is."""
    odd_id = add_review(reviews_db, "not json at all", minutes=10)
    add_review(reviews_db, findings_content("real findings"), minutes=0)

    start_followup(reviews_db)

    assert spawned[0]["previous_review_content"] == "not json at all"
    with reviews_lock:
        assert active_reviews[KEY]["parent_review_id"] == odd_id


def test_error_false_is_not_a_stub(reviews_db, spawned):
    content = json.dumps({"schema_version": "1.0.0", "error": False,
                          "summary": "explicitly fine", "sections": [],
                          "score": {"overall": 7.0}})
    fine_id = add_review(reviews_db, content, minutes=10)

    start_followup(reviews_db)

    assert "explicitly fine" in spawned[0]["previous_review_content"]
    with reviews_lock:
        assert active_reviews[KEY]["parent_review_id"] == fine_id
