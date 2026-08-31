"""Tests for scan_for_stale_reviews — stop/comment/restart, with no GitHub calls.

Every gh-touching dependency is monkeypatched, so these tests assert on which
reviews *would* be cancelled and restarted, never on network or subprocess
behavior.
"""

import pytest

from backend.services import stale_review_watcher as watcher
from backend.services.review_event_log import REASON_STALE_COMMITS

OWNER = "owner"
REPO = "repo"
PR = 42
KEY = f"{OWNER}/{REPO}/{PR}"
PR_URL = f"https://github.com/{OWNER}/{REPO}/pull/{PR}"
OLD_SHA = "aaaa11112222"
NEW_SHA = "bbbb33334444"


class Harness:
    """Stubbed gh/cancel/comment/review-launch access plus a fake registry."""

    def __init__(self):
        self.active_reviews = {}
        self.cancelled = []
        self.commented = []
        self.started = []
        self.cancel_result = "cancelled"
        self.begin_result = ({"message": "Review started"}, 201)
        self.pr_state = "OPEN"
        self.current_sha = NEW_SHA
        self.sha_fetches = 0

    def fetch_pr_state_and_sha(self, owner, repo, pr_number):
        self.sha_fetches += 1
        return self.pr_state, self.current_sha

    def cancel_active_review(self, key, **kwargs):
        self.cancelled.append({"key": key, **kwargs})
        if self.cancel_result == "cancelled":
            self.active_reviews.pop(key, None)
        return self.cancel_result

    def post_review_stopped_stale_comment(self, owner, repo, pr_number, **kwargs):
        self.commented.append({"key": f"{owner}/{repo}/{pr_number}", **kwargs})
        return True

    def begin_review(self, owner, repo, pr_number, pr_url, reviews_db, **kwargs):
        self.started.append({"key": f"{owner}/{repo}/{pr_number}", "pr_url": pr_url, **kwargs})
        return self.begin_result


@pytest.fixture
def harness(monkeypatch):
    h = Harness()
    monkeypatch.setattr("backend.extensions.active_reviews", h.active_reviews)
    monkeypatch.setattr(
        "backend.services.github_service.fetch_pr_state_and_sha", h.fetch_pr_state_and_sha
    )
    monkeypatch.setattr(
        "backend.services.review_service.cancel_active_review", h.cancel_active_review
    )
    monkeypatch.setattr(
        "backend.services.review_service.begin_review", h.begin_review
    )
    monkeypatch.setattr(
        "backend.services.review_started_service.post_review_stopped_stale_comment",
        h.post_review_stopped_stale_comment,
    )
    monkeypatch.setattr("backend.database.get_reviews_db", lambda: "reviews-db")
    monkeypatch.setattr(watcher, "_handled_shas", {})
    return h


def running_review(head_sha_at_start=OLD_SHA, status="running", reviewer="default",
                   is_followup=False, auto_started=False):
    return {
        "status": status,
        "head_sha_at_start": head_sha_at_start,
        "pr_title": "title",
        "pr_author": "author",
        "auto_started": auto_started,
        "spawn": {
            "pr_url": PR_URL,
            "owner": OWNER,
            "repo": REPO,
            "pr_number": PR,
            "is_followup": is_followup,
            "previous_review_content": None,
            "reviewer_type": reviewer,
        },
    }


def test_new_commit_stops_comments_and_restarts(harness):
    harness.active_reviews[KEY] = running_review(reviewer="security", is_followup=True,
                                                 auto_started=True)

    watcher.scan_for_stale_reviews()

    assert len(harness.cancelled) == 1
    cancel = harness.cancelled[0]
    assert cancel["key"] == KEY
    assert cancel["reason"] == REASON_STALE_COMMITS
    assert OLD_SHA[:8] in cancel["detail"] and NEW_SHA[:8] in cancel["detail"]
    assert cancel["require_running"] is True

    assert len(harness.commented) == 1
    comment = harness.commented[0]
    assert comment["old_sha"] == OLD_SHA
    assert comment["new_sha"] == NEW_SHA
    assert comment["reviewer_type"] == "security"

    assert len(harness.started) == 1
    start = harness.started[0]
    assert start["key"] == KEY
    assert start["pr_url"] == PR_URL
    assert start["reviewer_type"] == "security"
    assert start["is_followup"] is True
    assert start["auto_started"] is True
    assert start["pr_title"] == "title"
    assert start["pr_author"] == "author"


def test_unchanged_sha_does_not_trigger(harness):
    harness.active_reviews[KEY] = running_review()
    harness.current_sha = OLD_SHA

    watcher.scan_for_stale_reviews()

    assert harness.cancelled == []
    assert harness.started == []


def test_review_without_baseline_is_skipped(harness):
    harness.active_reviews[KEY] = running_review(head_sha_at_start=None)

    watcher.scan_for_stale_reviews()

    assert harness.sha_fetches == 0
    assert harness.cancelled == []


def test_finished_entry_is_skipped(harness):
    harness.active_reviews[KEY] = running_review(status="completed")

    watcher.scan_for_stale_reviews()

    assert harness.sha_fetches == 0
    assert harness.cancelled == []


def test_non_open_pr_is_skipped(harness):
    harness.active_reviews[KEY] = running_review()
    harness.pr_state = "MERGED"

    watcher.scan_for_stale_reviews()

    assert harness.cancelled == []


def test_failed_sha_fetch_is_skipped(harness):
    harness.active_reviews[KEY] = running_review()
    harness.current_sha = None

    watcher.scan_for_stale_reviews()

    assert harness.cancelled == []


def test_review_that_finished_during_the_scan_is_not_restarted(harness):
    harness.active_reviews[KEY] = running_review()
    harness.cancel_result = "not_running"

    watcher.scan_for_stale_reviews()

    assert len(harness.cancelled) == 1
    assert harness.commented == []
    assert harness.started == []


def test_failed_restart_is_not_retried_for_the_same_sha(harness):
    harness.active_reviews[KEY] = running_review()
    harness.begin_result = ({"error": "spawn failed"}, 500)

    watcher.scan_for_stale_reviews()
    harness.active_reviews[KEY] = running_review()
    watcher.scan_for_stale_reviews()

    assert len(harness.started) == 1


def test_a_newer_sha_retries_after_a_failed_restart(harness):
    harness.active_reviews[KEY] = running_review()
    harness.begin_result = ({"error": "spawn failed"}, 500)

    watcher.scan_for_stale_reviews()
    harness.active_reviews[KEY] = running_review()
    harness.current_sha = "cccc55556666"
    watcher.scan_for_stale_reviews()

    assert len(harness.started) == 2
