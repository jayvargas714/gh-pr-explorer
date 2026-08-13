"""Tests for AutoVerdictsDB — chiefly the claim() double-post guard."""

import tempfile
from pathlib import Path

import pytest

from backend.database.auto_verdicts import AutoVerdictsDB
from backend.database.base import Database
from backend.database.reviews import ReviewsDB


@pytest.fixture
def db():
    p = Path(tempfile.mkdtemp()) / "auto_verdicts_test.db"
    return Database(p)


@pytest.fixture
def auto_db(db):
    return AutoVerdictsDB(db)


@pytest.fixture
def review_ids(db):
    """Two real review rows — auto_verdicts.review_id is a foreign key."""
    reviews_db = ReviewsDB(db)
    return [
        reviews_db.save_review(
            pr_number=42, repo="owner/repo", content_json='{"score": {"overall": 7}}'
        )
        for _ in range(2)
    ]


def test_claim_succeeds_once_per_review(auto_db, review_ids):
    """The second claim must lose, so a verdict can never post twice."""
    rid = review_ids[0]
    assert auto_db.claim("owner/repo", 42, review_id=rid, head_commit_sha="abc") is True
    assert auto_db.claim("owner/repo", 42, review_id=rid, head_commit_sha="abc") is False


def test_distinct_reviews_can_each_be_claimed(auto_db, review_ids):
    assert auto_db.claim("owner/repo", 42, review_id=review_ids[0]) is True
    assert auto_db.claim("owner/repo", 42, review_id=review_ids[1]) is True
    assert len(auto_db.get_for_pr("owner/repo", 42)) == 2


def test_claim_fails_for_a_review_that_does_not_exist(auto_db):
    """A foreign-key violation must not be reported as a successful claim."""
    assert auto_db.claim("owner/repo", 42, review_id=99999) is False
    assert auto_db.get_latest_for_pr("owner/repo", 42) is None


def test_claim_creates_a_pending_row(auto_db, review_ids):
    auto_db.claim("owner/repo", 42, review_id=review_ids[0], head_commit_sha="deadbeef")
    row = auto_db.get_latest_for_pr("owner/repo", 42)
    assert row["outcome"] == "pending"
    assert row["event"] is None
    assert row["head_commit_sha"] == "deadbeef"


def test_finalize_records_the_decision(auto_db, review_ids):
    rid = review_ids[0]
    auto_db.claim("owner/repo", 42, review_id=rid)
    auto_db.finalize(
        rid, "posted", event="REQUEST_CHANGES", reason="2 critical > 0 allowed",
        tallies={"critical": 2, "major": 0, "minor": 3},
        criteria={"maxCritical": 0, "maxMajor": 0, "maxMinor": 99},
    )
    row = auto_db.get_latest_for_pr("owner/repo", 42)
    assert row["outcome"] == "posted"
    assert row["event"] == "REQUEST_CHANGES"
    assert row["critical_count"] == 2
    assert row["minor_count"] == 3
    assert "maxMinor" in row["criteria_json"]


def test_finalize_rejects_an_unknown_outcome(auto_db, review_ids):
    auto_db.claim("owner/repo", 42, review_id=review_ids[0])
    with pytest.raises(ValueError):
        auto_db.finalize(review_ids[0], "definitely-not-an-outcome")


def test_get_latest_returns_none_when_no_verdicts(auto_db):
    assert auto_db.get_latest_for_pr("owner/repo", 999) is None
