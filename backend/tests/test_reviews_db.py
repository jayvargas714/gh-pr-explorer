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


def _content(critical=0, major=0, minor=0):
    import json
    issues = lambda n: [{"title": f"i{i}"} for i in range(n)]
    return json.dumps({
        "sections": [
            {"type": "critical", "issues": issues(critical)},
            {"type": "major", "issues": issues(major)},
            {"type": "minor", "issues": issues(minor)},
        ]
    })


def test_get_issue_counts_tallies_each_severity(reviews_db):
    rid = reviews_db.save_review(pr_number=1, repo="owner/repo",
                                 content_json=_content(critical=2, major=3, minor=4))
    counts = reviews_db.get_issue_counts([rid])
    assert counts[rid] == {"critical": 2, "major": 3, "minor": 4}


def test_get_issue_counts_handles_many_reviews_at_once(reviews_db):
    ids = [
        reviews_db.save_review(pr_number=n, repo="owner/repo",
                               content_json=_content(critical=n, major=0, minor=0))
        for n in range(1, 6)
    ]
    counts = reviews_db.get_issue_counts(ids)
    assert len(counts) == 5
    assert [counts[i]["critical"] for i in ids] == [1, 2, 3, 4, 5]


def test_get_issue_counts_dedupes_and_ignores_none(reviews_db):
    rid = reviews_db.save_review(pr_number=1, repo="owner/repo", content_json=_content(minor=1))
    assert reviews_db.get_issue_counts([rid, rid, None]) == {rid: {"critical": 0, "major": 0, "minor": 1}}


def test_get_issue_counts_omits_unknown_ids(reviews_db):
    """A missing entry means 'unknown', which the UI must not read as zero."""
    assert reviews_db.get_issue_counts([999999]) == {}


def test_get_issue_counts_omits_unparseable_content(reviews_db):
    rid = reviews_db.save_review(pr_number=1, repo="owner/repo", content_json="not json{")
    assert reviews_db.get_issue_counts([rid]) == {}


def test_get_issue_counts_omits_non_object_content(reviews_db):
    rid = reviews_db.save_review(pr_number=1, repo="owner/repo", content_json='["a list"]')
    assert reviews_db.get_issue_counts([rid]) == {}


def test_get_issue_counts_tallies_zero_for_a_clean_review(reviews_db):
    """A review with sections but no issues is a real zero, not unknown."""
    rid = reviews_db.save_review(pr_number=1, repo="owner/repo", content_json=_content())
    assert reviews_db.get_issue_counts([rid]) == {rid: {"critical": 0, "major": 0, "minor": 0}}


def test_get_issue_counts_empty_input(reviews_db):
    assert reviews_db.get_issue_counts([]) == {}
