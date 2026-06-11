"""Tests for queue enrichment rev-log builder."""

from backend.services.queue_enrichment import build_rev_log


def test_empty_when_no_runs():
    assert build_rev_log([], []) == []


def test_reviews_mapped_with_summary_fields():
    reviews = [{
        "id": 7, "review_timestamp": "2026-06-09 14:00:00", "status": "completed",
        "score": 8.0, "is_followup": 1,
    }]
    log = build_rev_log(reviews, [])
    assert log == [{
        "kind": "review", "id": 7, "timestamp": "2026-06-09 14:00:00",
        "status": "completed", "score": 8.0, "isFollowup": True,
    }]


def test_audits_mapped_with_summary_fields():
    audits = [{
        "id": 3, "audit_timestamp": "2026-06-09 13:00:00", "status": "completed",
        "finding_count": 5, "blocking_count": 2,
    }]
    log = build_rev_log([], audits)
    assert log == [{
        "kind": "audit", "id": 3, "timestamp": "2026-06-09 13:00:00",
        "status": "completed", "findingCount": 5, "blockingCount": 2,
        "reviewerAgent": "pb_ed",
    }]


def test_review_includes_reviewer_agent_when_present():
    reviews = [{
        "id": 8, "review_timestamp": "2026-06-09 14:00:00", "status": "completed",
        "score": 9.0, "is_followup": 0, "reviewer_agent": "ed",
    }]
    log = build_rev_log(reviews, [])
    assert log[0]["reviewerAgent"] == "ed"


def test_review_omits_reviewer_agent_when_absent():
    reviews = [{
        "id": 9, "review_timestamp": "2026-06-09 14:00:00", "status": "completed",
        "score": 9.0, "is_followup": 0,
    }]
    log = build_rev_log(reviews, [])
    assert "reviewerAgent" not in log[0]


def test_merged_sorted_newest_first():
    reviews = [{"id": 1, "review_timestamp": "2026-06-09 10:00:00", "status": "completed", "score": 7.0, "is_followup": 0}]
    audits = [{"id": 2, "audit_timestamp": "2026-06-09 12:00:00", "status": "completed", "finding_count": 1, "blocking_count": 0}]
    log = build_rev_log(reviews, audits)
    assert [e["kind"] for e in log] == ["audit", "review"]  # 12:00 audit before 10:00 review
