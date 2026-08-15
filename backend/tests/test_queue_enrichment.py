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
        "autoStarted": False,
    }]


def test_review_marks_auto_started():
    reviews = [{
        "id": 12, "review_timestamp": "2026-06-09 14:00:00", "status": "completed",
        "score": 8.0, "is_followup": 1, "auto_started": 1,
    }]
    log = build_rev_log(reviews, [])
    assert log[0]["autoStarted"] is True


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


def test_auto_verdict_folded_into_its_review():
    reviews = [{"id": 5, "review_timestamp": "2026-06-09 10:00:00", "status": "completed", "score": 9.0, "is_followup": 0}]
    verdicts = [{"id": 1, "review_id": 5, "created_at": "2026-06-09 10:05:00",
                 "outcome": "posted", "event": "APPROVE", "reason": "0 critical"}]
    log = build_rev_log(reviews, [], verdicts)
    assert len(log) == 1
    assert log[0]["kind"] == "review"
    assert log[0]["verdictOutcome"] == "posted"
    assert log[0]["verdictEvent"] == "APPROVE"
    assert log[0]["verdictReason"] == "0 critical"


def test_auto_verdict_without_matching_review_stays_standalone():
    verdicts = [{"id": 1, "review_id": 99, "created_at": "2026-06-09 10:05:00",
                 "outcome": "posted", "event": "REQUEST_CHANGES", "reason": "2 critical"}]
    log = build_rev_log([], [], verdicts)
    assert len(log) == 1
    assert log[0]["kind"] == "auto_verdict"
    assert log[0]["event"] == "REQUEST_CHANGES"


def test_only_newest_verdict_folds_older_stays_standalone():
    reviews = [{"id": 5, "review_timestamp": "2026-06-09 10:00:00", "status": "completed", "score": 9.0, "is_followup": 0}]
    verdicts = [
        {"id": 2, "review_id": 5, "created_at": "2026-06-09 11:00:00",
         "outcome": "posted", "event": "APPROVE", "reason": "clean"},
        {"id": 1, "review_id": 5, "created_at": "2026-06-09 10:05:00",
         "outcome": "error", "event": None, "reason": "gh failed"},
    ]
    log = build_rev_log(reviews, [], verdicts)
    assert [e["kind"] for e in log] == ["auto_verdict", "review"]
    assert log[1]["verdictEvent"] == "APPROVE"
    assert log[0]["id"] == 1


def test_merged_sorted_newest_first():
    reviews = [{"id": 1, "review_timestamp": "2026-06-09 10:00:00", "status": "completed", "score": 7.0, "is_followup": 0}]
    audits = [{"id": 2, "audit_timestamp": "2026-06-09 12:00:00", "status": "completed", "finding_count": 1, "blocking_count": 0}]
    log = build_rev_log(reviews, audits)
    assert [e["kind"] for e in log] == ["audit", "review"]  # 12:00 audit before 10:00 review
