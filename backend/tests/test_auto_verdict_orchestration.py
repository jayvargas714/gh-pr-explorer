"""Tests for maybe_post_auto_verdict — the decision wiring, with no GitHub calls.

Every gh-touching dependency is monkeypatched, so these tests assert on which
verdict *would* be posted and what gets recorded, never on network behavior.
"""

import json
import tempfile
from pathlib import Path

import pytest

from backend.database.auto_verdicts import AutoVerdictsDB
from backend.database.base import Database
from backend.database.merge_queue import MergeQueueDB
from backend.database.reviews import ReviewsDB
from backend.services import auto_verdict_service as svc

REPO = "owner/repo"
PR = 42


def _content(critical=0, major=0, minor=0):
    def issues(n):
        return [
            {"title": f"Issue {i}", "location": {"file": "a.py", "start_line": 1, "end_line": 1},
             "problem": "p", "fix": "f"}
            for i in range(n)
        ]

    return json.dumps({
        "schema_version": "1.0.0",
        "metadata": {"pr_number": PR, "repository": REPO},
        "summary": "Summary text.",
        "sections": [
            {"type": "critical", "display_name": "Critical Issues", "issues": issues(critical)},
            {"type": "major", "display_name": "Major Concerns", "issues": issues(major)},
            {"type": "minor", "display_name": "Minor Issues", "issues": issues(minor)},
        ],
        "score": {"overall": 6},
    })


class Harness:
    """Wires temp DBs plus stubbed gh access into the service under test."""

    def __init__(self, db):
        self.db = db
        self.auto = AutoVerdictsDB(db)
        self.queue = MergeQueueDB(db)
        self.reviews = ReviewsDB(db)
        self.posted = []
        self.post_result = ({"message": "ok"}, 200)

    def post_verdict(self, owner, repo, pr_number, event, body, **kwargs):
        self.posted.append({"event": event, "body": body, "kwargs": kwargs})
        return self.post_result


@pytest.fixture
def harness(monkeypatch):
    db = Database(Path(tempfile.mkdtemp()) / "auto_verdict_orch.db")
    h = Harness(db)

    monkeypatch.setattr("backend.database.get_auto_verdicts_db", lambda: h.auto)
    monkeypatch.setattr("backend.database.get_queue_db", lambda: h.queue)
    monkeypatch.setattr("backend.database.get_reviews_db", lambda: h.reviews)
    monkeypatch.setattr(svc, "post_verdict", h.post_verdict)
    monkeypatch.setattr(svc, "fetch_pr_state_and_sha", lambda *a: ("OPEN", "sha123"))
    monkeypatch.setattr(svc, "get_authenticated_login", lambda: "me")
    return h


def _criteria(monkeypatch, **overrides):
    criteria = {"enabled": True, "maxCritical": 0, "maxMajor": 0,
                "maxMinor": 99, "allowAutoApprove": True}
    criteria.update(overrides)
    monkeypatch.setattr(svc, "get_criteria", lambda: criteria)
    return criteria


def _arm(h, enabled=True, author="someone-else"):
    h.queue.add_to_queue(pr_number=PR, repo=REPO, pr_title="t", pr_author=author,
                         pr_url="u", additions=1, deletions=1)
    h.queue.set_auto_verdict(PR, REPO, enabled, "default")


def _review(h, critical=0, major=0, minor=0, status="completed", author="someone-else"):
    return h.reviews.save_review(
        pr_number=PR, repo=REPO, pr_author=author, status=status,
        content_json=_content(critical, major, minor),
    )


def test_criticals_post_request_changes(harness, monkeypatch):
    _criteria(monkeypatch)
    _arm(harness)
    rid = _review(harness, critical=2)

    result = svc.maybe_post_auto_verdict(REPO, PR, rid)

    assert result["outcome"] == "posted"
    assert result["event"] == "REQUEST_CHANGES"
    assert harness.posted[0]["event"] == "REQUEST_CHANGES"
    assert "Summary text." in harness.posted[0]["body"]


def test_clean_review_posts_approve_when_allowed(harness, monkeypatch):
    _criteria(monkeypatch, allowAutoApprove=True)
    _arm(harness)
    rid = _review(harness)

    result = svc.maybe_post_auto_verdict(REPO, PR, rid)

    assert result["event"] == "APPROVE"
    assert harness.posted[0]["event"] == "APPROVE"


def test_clean_review_is_suppressed_when_auto_approve_is_off(harness, monkeypatch):
    _criteria(monkeypatch, allowAutoApprove=False)
    _arm(harness)
    rid = _review(harness)

    result = svc.maybe_post_auto_verdict(REPO, PR, rid)

    assert result["outcome"] == "suppressed"
    assert harness.posted == []          # nothing reaches GitHub
    assert "auto-approve disabled" in result["reason"]


def test_self_authored_pr_falls_back_to_comment(harness, monkeypatch):
    _criteria(monkeypatch, allowAutoApprove=True)
    _arm(harness, author="me")
    rid = _review(harness, author="me")

    result = svc.maybe_post_auto_verdict(REPO, PR, rid)

    assert result["event"] == "COMMENT"
    assert "self-authored" in result["reason"]


def test_disarmed_card_is_left_alone(harness, monkeypatch):
    _criteria(monkeypatch)
    _arm(harness, enabled=False)
    rid = _review(harness, critical=3)

    assert svc.maybe_post_auto_verdict(REPO, PR, rid) is None
    assert harness.posted == []
    assert harness.auto.get_latest_for_pr(REPO, PR) is None


def test_master_switch_off_is_left_alone(harness, monkeypatch):
    _criteria(monkeypatch, enabled=False)
    _arm(harness)
    rid = _review(harness, critical=3)

    assert svc.maybe_post_auto_verdict(REPO, PR, rid) is None
    assert harness.posted == []


def test_pr_not_in_queue_is_left_alone(harness, monkeypatch):
    _criteria(monkeypatch)
    rid = _review(harness, critical=3)

    assert svc.maybe_post_auto_verdict(REPO, PR, rid) is None
    assert harness.posted == []


def test_closed_pr_is_skipped(harness, monkeypatch):
    _criteria(monkeypatch)
    monkeypatch.setattr(svc, "fetch_pr_state_and_sha", lambda *a: ("MERGED", "sha123"))
    _arm(harness)
    rid = _review(harness, critical=3)

    result = svc.maybe_post_auto_verdict(REPO, PR, rid)

    assert result["outcome"] == "skipped"
    assert "MERGED" in result["reason"]
    assert harness.posted == []


def test_error_stub_review_is_skipped(harness, monkeypatch):
    _criteria(monkeypatch)
    _arm(harness)
    rid = harness.reviews.save_review(
        pr_number=PR, repo=REPO, status="completed",
        content_json=json.dumps({"error": True, "sections": [], "score": {"overall": 0}}),
    )

    result = svc.maybe_post_auto_verdict(REPO, PR, rid)

    assert result["outcome"] == "skipped"
    assert harness.posted == []


def test_a_second_evaluation_does_not_post_again(harness, monkeypatch):
    """The claim guard is what stops the watcher and the UI poll double-posting."""
    _criteria(monkeypatch)
    _arm(harness)
    rid = _review(harness, critical=1)

    svc.maybe_post_auto_verdict(REPO, PR, rid)
    assert svc.maybe_post_auto_verdict(REPO, PR, rid) is None
    assert len(harness.posted) == 1


def test_a_failed_post_is_recorded_as_error(harness, monkeypatch):
    _criteria(monkeypatch)
    _arm(harness)
    rid = _review(harness, critical=1)
    harness.post_result = ({"error": "GitHub said no"}, 500)

    result = svc.maybe_post_auto_verdict(REPO, PR, rid)

    assert result["outcome"] == "error"
    row = harness.auto.get_latest_for_pr(REPO, PR)
    assert "GitHub said no" in row["error_detail"]


def test_tallies_and_criteria_are_snapshotted_on_the_row(harness, monkeypatch):
    _criteria(monkeypatch, maxMinor=2)
    _arm(harness)
    rid = _review(harness, critical=1, major=2, minor=5)

    svc.maybe_post_auto_verdict(REPO, PR, rid)

    row = harness.auto.get_latest_for_pr(REPO, PR)
    assert (row["critical_count"], row["major_count"], row["minor_count"]) == (1, 2, 5)
    assert json.loads(row["criteria_json"])["maxMinor"] == 2
