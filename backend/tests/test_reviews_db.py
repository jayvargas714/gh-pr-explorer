"""Tests for ReviewsDB."""

import tempfile
from pathlib import Path

import pytest

from backend.database.base import Database
from backend.database.reviews import ReviewsDB


@pytest.fixture
def reviews_db():
    p = Path(tempfile.mkdtemp()) / "reviews_test.db"
    return ReviewsDB(Database(p))


def test_reviews_table_has_reviewer_agent_column(reviews_db):
    with reviews_db.db.connection() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(reviews)")}
    assert "reviewer_agent" in cols


def test_save_review_persists_reviewer_agent(reviews_db):
    rid = reviews_db.save_review(
        pr_number=42, repo="owner/repo", content_json='{"score": {"overall": 8}}',
        reviewer_agent="ed",
    )
    got = reviews_db.get_review(rid)
    assert got["reviewer_agent"] == "ed"


def test_save_review_reviewer_agent_defaults_null(reviews_db):
    rid = reviews_db.save_review(
        pr_number=43, repo="owner/repo", content_json='{"score": {"overall": 5}}',
    )
    got = reviews_db.get_review(rid)
    assert got["reviewer_agent"] is None
