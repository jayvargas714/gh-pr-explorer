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


def _issues(n):
    return [{"title": f"i{i}"} for i in range(n)]


def _content(blocking=0, non_blocking=0):
    import json
    return json.dumps({
        "schema_version": "2.0.0",
        "sections": [
            {"type": "blocking", "issues": _issues(blocking)},
            {"type": "non_blocking", "issues": _issues(non_blocking)},
        ]
    })


def _legacy_content(critical=0, major=0, minor=0):
    import json
    return json.dumps({
        "schema_version": "1.0.0",
        "sections": [
            {"type": "critical", "issues": _issues(critical)},
            {"type": "major", "issues": _issues(major)},
            {"type": "minor", "issues": _issues(minor)},
        ]
    })


def test_get_issue_counts_tallies_each_tier(reviews_db):
    rid = reviews_db.save_review(pr_number=1, repo="owner/repo",
                                 content_json=_content(blocking=2, non_blocking=4))
    counts = reviews_db.get_issue_counts([rid])
    assert counts[rid] == {"blocking": 2, "non_blocking": 4}


def test_get_issue_counts_folds_legacy_content(reviews_db):
    rid = reviews_db.save_review(pr_number=1, repo="owner/repo",
                                 content_json=_legacy_content(critical=2, major=3, minor=4))
    assert reviews_db.get_issue_counts([rid]) == {rid: {"blocking": 5, "non_blocking": 4}}


def test_get_issue_counts_handles_many_reviews_at_once(reviews_db):
    ids = [
        reviews_db.save_review(pr_number=n, repo="owner/repo", content_json=_content(blocking=n))
        for n in range(1, 6)
    ]
    counts = reviews_db.get_issue_counts(ids)
    assert len(counts) == 5
    assert [counts[i]["blocking"] for i in ids] == [1, 2, 3, 4, 5]


def test_get_issue_counts_dedupes_and_ignores_none(reviews_db):
    rid = reviews_db.save_review(pr_number=1, repo="owner/repo", content_json=_content(non_blocking=1))
    assert reviews_db.get_issue_counts([rid, rid, None]) == {rid: {"blocking": 0, "non_blocking": 1}}


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
    assert reviews_db.get_issue_counts([rid]) == {rid: {"blocking": 0, "non_blocking": 0}}


def test_get_issue_counts_empty_input(reviews_db):
    assert reviews_db.get_issue_counts([]) == {}


# -- update_section_posted ------------------------------------------------------

def test_update_section_posted_writes_the_blocking_columns(reviews_db):
    rid = reviews_db.save_review(pr_number=1, repo="owner/repo", content_json=_content(blocking=2))
    reviews_db.update_section_posted(rid, "blocking", True, posted_count=1, found_count=2)
    row = reviews_db.get_review(rid)
    assert row["inline_comments_posted"] == 1
    assert (row["blocking_posted_count"], row["blocking_found_count"]) == (1, 2)


def test_update_section_posted_writes_the_non_blocking_columns(reviews_db):
    rid = reviews_db.save_review(pr_number=1, repo="owner/repo", content_json=_content(non_blocking=3))
    reviews_db.update_section_posted(rid, "non_blocking", True, posted_count=3, found_count=3)
    row = reviews_db.get_review(rid)
    assert row["non_blocking_posted"] == 1
    assert (row["non_blocking_posted_count"], row["non_blocking_found_count"]) == (3, 3)
    assert not row["inline_comments_posted"]


@pytest.mark.parametrize("section", ["critical", "major", "minor", "disputed"])
def test_update_section_posted_rejects_non_tier_sections(reviews_db, section):
    rid = reviews_db.save_review(pr_number=1, repo="owner/repo", content_json=_content())
    with pytest.raises(ValueError):
        reviews_db.update_section_posted(rid, section, True)


def test_get_latest_for_prs_returns_newest_per_pr(reviews_db):
    from datetime import datetime
    reviews_db.save_review(pr_number=1, repo="owner/repo", status="completed",
                           review_timestamp=datetime(2026, 8, 1, 10, 0))
    newest = reviews_db.save_review(pr_number=1, repo="owner/repo", status="failed",
                                    review_timestamp=datetime(2026, 8, 2, 10, 0))
    other = reviews_db.save_review(pr_number=2, repo="owner/repo", status="completed",
                                   review_timestamp=datetime(2026, 8, 1, 12, 0))

    latest = reviews_db.get_latest_for_prs([("owner/repo", 1), ("owner/repo", 2),
                                            ("owner/repo", 3)])
    assert latest[("owner/repo", 1)]["id"] == newest
    assert latest[("owner/repo", 1)]["status"] == "failed"
    assert latest[("owner/repo", 2)]["id"] == other
    assert ("owner/repo", 3) not in latest


def test_get_latest_for_prs_empty_input(reviews_db):
    assert reviews_db.get_latest_for_prs([]) == {}


# -- get_completed_run_times --------------------------------------------------

def test_get_completed_run_times_completed_only(reviews_db):
    from datetime import datetime
    reviews_db.save_review(pr_number=1, repo="owner/repo", status="completed",
                            review_timestamp=datetime(2026, 8, 1, 10, 0))
    reviews_db.save_review(pr_number=1, repo="owner/repo", status="failed",
                            review_timestamp=datetime(2026, 8, 2, 10, 0))
    reviews_db.save_review(pr_number=1, repo="owner/repo", status="running",
                            review_timestamp=datetime(2026, 8, 3, 10, 0))

    result = reviews_db.get_completed_run_times("owner/repo")
    assert result == {1: ["2026-08-01 10:00:00"]}


def test_get_completed_run_times_grouped_by_pr_number(reviews_db):
    from datetime import datetime
    reviews_db.save_review(pr_number=1, repo="owner/repo", status="completed",
                            review_timestamp=datetime(2026, 8, 1, 10, 0))
    reviews_db.save_review(pr_number=1, repo="owner/repo", status="completed",
                            review_timestamp=datetime(2026, 8, 5, 10, 0), is_followup=True)
    reviews_db.save_review(pr_number=2, repo="owner/repo", status="completed",
                            review_timestamp=datetime(2026, 8, 1, 10, 0))

    result = reviews_db.get_completed_run_times("owner/repo")
    assert result[1] == ["2026-08-01 10:00:00", "2026-08-05 10:00:00"]
    assert result[2] == ["2026-08-01 10:00:00"]


def test_get_completed_run_times_repo_scoped(reviews_db):
    from datetime import datetime
    reviews_db.save_review(pr_number=1, repo="owner/repo", status="completed",
                            review_timestamp=datetime(2026, 8, 1, 10, 0))
    reviews_db.save_review(pr_number=1, repo="other/repo", status="completed",
                            review_timestamp=datetime(2026, 8, 1, 10, 0))

    result = reviews_db.get_completed_run_times("owner/repo")
    assert list(result.keys()) == [1]


def test_get_completed_run_times_no_reviews(reviews_db):
    assert reviews_db.get_completed_run_times("owner/repo") == {}
