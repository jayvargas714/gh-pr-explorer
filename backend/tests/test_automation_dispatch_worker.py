"""Tests for the automation dispatch worker (detection rows -> reviews)."""

import json
from unittest.mock import patch

import pytest

import backend.database as db_pkg
from backend.database.base import Database
from backend.database.automation_dispatches import AutomationDispatchesDB
from backend.database.merge_queue import MergeQueueDB
from backend.database.swimlanes import SwimlanesDB
from backend.database.synced_prs import SyncedPRsDB
from backend.services.automation_dispatch_worker import process_pending_dispatches

REPO = "acme/widgets"
WORKER = "backend.services.automation_dispatch_worker"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Shared temp DB with all stores wired through the singleton getters."""
    db = Database(tmp_path / "dispatch_worker_test.db")
    stores = {
        "dispatches": AutomationDispatchesDB(db),
        "queue": MergeQueueDB(db),
        "swimlanes": SwimlanesDB(db),
        "synced": SyncedPRsDB(db),
    }
    stores["swimlanes"].ensure_default_lane()
    monkeypatch.setattr(db_pkg, "get_automation_dispatches_db", lambda: stores["dispatches"])
    monkeypatch.setattr(db_pkg, "get_queue_db", lambda: stores["queue"])
    monkeypatch.setattr(db_pkg, "get_swimlanes_db", lambda: stores["swimlanes"])
    monkeypatch.setattr(db_pkg, "get_synced_prs_db", lambda: stores["synced"])
    monkeypatch.setattr(db_pkg, "get_reviews_db", lambda: None)  # begin_review is mocked

    from backend.extensions import active_reviews
    active_reviews.clear()

    stores["synced"].register_repo(REPO)
    stores["synced"].upsert_pr(REPO, {
        "number": 7, "title": "Add chart shell", "state": "OPEN", "isDraft": False,
        "author": {"login": "alice"}, "url": f"https://github.com/{REPO}/pull/7",
        "additions": 10, "deletions": 2,
        "createdAt": "2026-08-29T00:00:00Z", "updatedAt": "2026-08-29T01:00:00Z",
        "closedAt": None, "mergedAt": None,
    })
    return stores


def _cfg(**overrides):
    cfg = {
        "scope": "all", "authors": [], "repoAllowlist": [REPO],
        "maxConcurrentAutoReviews": 2,
        "ignorePatterns": ["*PB-000-index*", "*ED-000-index*"],
        "defaultRule": {"reviewerKey": "default", "autoVerdict": False, "autoVerdictMode": "verdict"},
        "rules": [
            {"name": "PB", "patterns": ["PB-[0-9]*"], "reviewerKey": "pb",
             "autoVerdict": True, "autoVerdictMode": "comment"},
            {"name": "ED", "patterns": ["ED-[0-9]*"], "reviewerKey": "ed",
             "autoVerdict": True, "autoVerdictMode": "verdict"},
        ],
    }
    cfg.update(overrides)
    return cfg


def _patch_config(monkeypatch, **overrides):
    from backend.services import automation_config
    monkeypatch.setattr(automation_config, "get_config", lambda: _cfg(**overrides))


def _auto_lane_ids(stores):
    lane = stores["swimlanes"].ensure_auto_lane()
    return [a["queue_item_id"] for a in stores["swimlanes"].get_assignments()
            if a["swimlane_id"] == lane["id"]]


def test_matched_rule_dispatches_routed_review_and_arms_verdict(env, monkeypatch):
    _patch_config(monkeypatch)
    env["dispatches"].record_candidate(REPO, 7)

    with patch("backend.services.github_service.fetch_pr_files",
               return_value=["briefs/PB-008-a.md", "briefs/PB-000-index.md"]), \
         patch("backend.services.review_service.begin_review",
               return_value=({"message": "started"}, 201)) as mock_begin:
        process_pending_dispatches()

    assert mock_begin.call_count == 1
    kwargs = mock_begin.call_args.kwargs
    assert kwargs["reviewer_type"] == "pb"
    assert kwargs["auto_started"] is True

    item = env["queue"].get_queue_item(7, REPO)
    assert item is not None
    assert item["auto_verdict_enabled"] == 1
    assert item["auto_verdict_reviewer"] == "pb"
    assert item["auto_verdict_mode"] == "comment"
    assert item["id"] in _auto_lane_ids(env)

    row = env["dispatches"].get_by_pr(REPO, 7)
    assert row["status"] == "dispatched"
    assert row["reviewer_key"] == "pb"


def test_default_fallthrough_does_not_arm_when_rule_says_off(env, monkeypatch):
    _patch_config(monkeypatch)
    env["dispatches"].record_candidate(REPO, 7)

    with patch("backend.services.github_service.fetch_pr_files",
               return_value=["src/app.py"]), \
         patch("backend.services.review_service.begin_review",
               return_value=({"message": "started"}, 201)) as mock_begin:
        process_pending_dispatches()

    assert mock_begin.call_args.kwargs["reviewer_type"] == "default"
    item = env["queue"].get_queue_item(7, REPO)
    assert item["auto_verdict_enabled"] == 0
    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "dispatched"


def test_unidentified_pr_is_queued_and_flagged_but_not_reviewed(env, monkeypatch):
    _patch_config(monkeypatch)
    env["dispatches"].record_candidate(REPO, 7)

    with patch("backend.services.github_service.fetch_pr_files",
               return_value=["briefs/PB-008-a.md", "docs/designs/ED-052-b.md"]), \
         patch("backend.services.review_service.begin_review") as mock_begin:
        process_pending_dispatches()

    assert mock_begin.call_count == 0
    item = env["queue"].get_queue_item(7, REPO)
    assert item is not None
    assert item["id"] in _auto_lane_ids(env)
    row = env["dispatches"].get_by_pr(REPO, 7)
    assert row["status"] == "unidentified"
    assert set(json.loads(row["outcome_json"])["matched_rules"]) == {"PB", "ED"}


def test_scope_off_is_a_kill_switch(env, monkeypatch):
    _patch_config(monkeypatch, scope="off")
    env["dispatches"].record_candidate(REPO, 7)

    with patch("backend.services.github_service.fetch_pr_files") as mock_files:
        process_pending_dispatches()

    assert mock_files.call_count == 0
    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "pending"


def test_repo_no_longer_allowlisted_is_skipped(env, monkeypatch):
    _patch_config(monkeypatch, repoAllowlist=["other/repo"])
    env["dispatches"].record_candidate(REPO, 7)

    with patch("backend.services.github_service.fetch_pr_files") as mock_files:
        process_pending_dispatches()

    assert mock_files.call_count == 0
    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "skipped"


def test_concurrency_budget_defers_pending_rows(env, monkeypatch):
    _patch_config(monkeypatch, maxConcurrentAutoReviews=1)
    env["dispatches"].record_candidate(REPO, 7)

    from backend.extensions import active_reviews
    active_reviews["x/y/1"] = {"status": "running", "auto_started": True}

    with patch("backend.services.github_service.fetch_pr_files") as mock_files:
        process_pending_dispatches()
    active_reviews.clear()

    assert mock_files.call_count == 0
    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "pending"


def test_file_fetch_failure_retries_then_fails(env, monkeypatch):
    _patch_config(monkeypatch)
    env["dispatches"].record_candidate(REPO, 7)

    with patch("backend.services.github_service.fetch_pr_files",
               side_effect=RuntimeError("boom")):
        process_pending_dispatches()
        assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "pending"
        assert env["dispatches"].get_by_pr(REPO, 7)["attempts"] == 1
        process_pending_dispatches()
        process_pending_dispatches()

    row = env["dispatches"].get_by_pr(REPO, 7)
    assert row["status"] == "failed"
    assert row["attempts"] == 3


def test_begin_review_conflict_marks_skipped_without_arming(env, monkeypatch):
    _patch_config(monkeypatch)
    env["dispatches"].record_candidate(REPO, 7)

    with patch("backend.services.github_service.fetch_pr_files",
               return_value=["briefs/PB-008-a.md"]), \
         patch("backend.services.review_service.begin_review",
               return_value=({"error": "Review already in progress for this PR"}, 409)):
        process_pending_dispatches()

    item = env["queue"].get_queue_item(7, REPO)
    assert item["auto_verdict_enabled"] == 0
    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "skipped"


def test_begin_review_failure_retries(env, monkeypatch):
    _patch_config(monkeypatch)
    env["dispatches"].record_candidate(REPO, 7)

    with patch("backend.services.github_service.fetch_pr_files",
               return_value=["briefs/PB-008-a.md"]), \
         patch("backend.services.review_service.begin_review",
               return_value=({"error": "spawn failed"}, 500)):
        process_pending_dispatches()

    row = env["dispatches"].get_by_pr(REPO, 7)
    assert row["status"] == "pending"
    assert row["attempts"] == 1


def test_pr_already_in_queue_is_reused(env, monkeypatch):
    _patch_config(monkeypatch)
    env["queue"].add_to_queue(pr_number=7, repo=REPO, pr_title="t", pr_author="alice",
                              pr_url="u", additions=1, deletions=1)
    env["dispatches"].record_candidate(REPO, 7)

    with patch("backend.services.github_service.fetch_pr_files",
               return_value=["briefs/PB-008-a.md"]), \
         patch("backend.services.review_service.begin_review",
               return_value=({"message": "started"}, 201)):
        process_pending_dispatches()

    item = env["queue"].get_queue_item(7, REPO)
    assert item["id"] in _auto_lane_ids(env)
    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "dispatched"
