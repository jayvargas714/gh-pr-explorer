"""Tests for scan_and_start_followups — trigger conditions, with no GitHub calls.

Every gh-touching dependency is monkeypatched, so these tests assert on which
follow-up reviews *would* start, never on network or subprocess behavior.
"""

import tempfile
from pathlib import Path

import pytest

from backend.database.base import Database
from backend.database.merge_queue import MergeQueueDB
from backend.database.reviews import ReviewsDB
from backend.services import auto_review_watcher as watcher

REPO = "owner/repo"
PR = 42
OLD_SHA = "aaaa11111"
NEW_SHA = "bbbb22222"


class Harness:
    """Wires temp DBs plus stubbed gh/review-launch access into the scan."""

    def __init__(self, db):
        self.db = db
        self.queue = MergeQueueDB(db)
        self.reviews = ReviewsDB(db)
        self.started = []
        self.begin_result = ({"message": "Review started"}, 201)
        self.pr_state = "OPEN"
        self.current_sha = NEW_SHA
        self.sha_fetches = 0

    def fetch_pr_state_and_sha(self, owner, repo, pr_number):
        self.sha_fetches += 1
        return self.pr_state, self.current_sha

    def begin_review(self, owner, repo, pr_number, pr_url, reviews_db, **kwargs):
        self.started.append({"key": f"{owner}/{repo}/{pr_number}", **kwargs})
        return self.begin_result


@pytest.fixture
def harness(monkeypatch):
    db = Database(Path(tempfile.mkdtemp()) / "auto_review_watcher.db")
    h = Harness(db)

    monkeypatch.setattr("backend.database.get_queue_db", lambda: h.queue)
    monkeypatch.setattr("backend.database.get_reviews_db", lambda: h.reviews)
    monkeypatch.setattr(
        "backend.services.github_service.fetch_pr_state_and_sha", h.fetch_pr_state_and_sha
    )
    monkeypatch.setattr("backend.services.review_service.begin_review", h.begin_review)
    monkeypatch.setattr(
        "backend.services.auto_verdict_config.get_criteria",
        lambda: {"autoFollowupReview": True},
    )
    monkeypatch.setattr(watcher, "_attempted_shas", {})
    monkeypatch.setattr("backend.extensions.active_reviews", {})
    return h


def _arm(h, enabled=True, reviewer="default"):
    h.queue.add_to_queue(pr_number=PR, repo=REPO, pr_title="t", pr_author="a",
                         pr_url="u", additions=1, deletions=1)
    h.queue.set_auto_verdict(PR, REPO, enabled, reviewer)


def _review(h, head_commit_sha=OLD_SHA, status="completed"):
    return h.reviews.save_review(
        pr_number=PR, repo=REPO, status=status,
        content_json="{}", head_commit_sha=head_commit_sha,
    )


def test_new_commits_start_a_followup_with_the_armed_reviewer(harness):
    _arm(harness, reviewer="ed")
    _review(harness)

    watcher.scan_and_start_followups()

    assert len(harness.started) == 1
    start = harness.started[0]
    assert start["key"] == f"{REPO}/{PR}"
    assert start["is_followup"] is True
    assert start["reviewer_type"] == "ed"


def test_disabled_setting_scans_nothing(harness, monkeypatch):
    monkeypatch.setattr(
        "backend.services.auto_verdict_config.get_criteria",
        lambda: {"autoFollowupReview": False},
    )
    _arm(harness)
    _review(harness)

    watcher.scan_and_start_followups()

    assert harness.started == []
    assert harness.sha_fetches == 0


def test_unarmed_card_is_ignored(harness):
    _arm(harness, enabled=False)
    _review(harness)

    watcher.scan_and_start_followups()

    assert harness.started == []


def test_unchanged_sha_does_not_trigger(harness):
    _arm(harness)
    _review(harness, head_commit_sha=NEW_SHA)

    watcher.scan_and_start_followups()

    assert harness.started == []


def test_never_reviewed_pr_is_skipped(harness):
    _arm(harness)

    watcher.scan_and_start_followups()

    assert harness.started == []


def test_review_without_recorded_sha_is_skipped(harness):
    _arm(harness)
    _review(harness, head_commit_sha=None)

    watcher.scan_and_start_followups()

    assert harness.started == []
    assert harness.sha_fetches == 0


def test_non_open_pr_is_skipped(harness):
    _arm(harness)
    _review(harness)
    harness.pr_state = "MERGED"

    watcher.scan_and_start_followups()

    assert harness.started == []


def test_running_review_is_not_doubled(harness, monkeypatch):
    _arm(harness)
    _review(harness)
    monkeypatch.setattr(
        "backend.extensions.active_reviews",
        {f"{REPO}/{PR}": {"status": "running"}},
    )

    watcher.scan_and_start_followups()

    assert harness.started == []
    assert harness.sha_fetches == 0


def test_failed_start_is_not_retried_for_the_same_sha(harness):
    _arm(harness)
    _review(harness)
    harness.begin_result = ({"error": "spawn failed"}, 500)

    watcher.scan_and_start_followups()
    watcher.scan_and_start_followups()

    assert len(harness.started) == 1


def test_a_newer_sha_retries_after_a_failed_attempt(harness):
    _arm(harness)
    _review(harness)
    harness.begin_result = ({"error": "spawn failed"}, 500)

    watcher.scan_and_start_followups()
    harness.current_sha = "cccc33333"
    watcher.scan_and_start_followups()

    assert len(harness.started) == 2
