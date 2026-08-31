"""Tests for the automation dispatch worker (detection rows -> reviews)."""

import json
from contextlib import contextmanager
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

CI_SUCCESS = [{"name": "ci", "conclusion": "SUCCESS"}]
CI_PENDING = [{"name": "ci", "status": "IN_PROGRESS"}]
CI_FAILURE = [{"name": "ci", "conclusion": "FAILURE"}]


def _synced_pr(number, title="Add chart shell"):
    return {
        "number": number, "title": title, "state": "OPEN", "isDraft": False,
        "author": {"login": "alice"}, "url": f"https://github.com/{REPO}/pull/{number}",
        "additions": 10, "deletions": 2,
        "baseRefName": "main", "headRefName": f"feature-{number}",
        "createdAt": "2026-08-29T00:00:00Z", "updatedAt": "2026-08-29T01:00:00Z",
        "closedAt": None, "mergedAt": None,
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Shared temp DB with all stores wired through the singleton getters."""
    db = Database(tmp_path / "dispatch_worker_test.db")
    stores = {
        "db": db,
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
    stores["synced"].upsert_pr(REPO, _synced_pr(7))
    return stores


def _cfg(**overrides):
    cfg = {
        "scope": "all", "authors": [], "repoAllowlist": [REPO],
        "maxConcurrentAutoReviews": 2,
        "requireCiPass": True, "maxBehindBase": 10, "dispatchTimeoutHours": 24,
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


@contextmanager
def _gates(state="OPEN", is_draft=False, rollup=CI_SUCCESS, behind=0):
    """Patch the live PR condition sources (state/draft/CI + divergence)."""
    queue_data = {"state": state, "isDraft": is_draft, "statusCheckRollup": rollup,
                  "headRefOid": "abc", "reviewDecision": None, "reviews": None}
    behind_side = behind if not isinstance(behind, Exception) else None
    with patch("backend.services.github_service.fetch_pr_queue_data",
               return_value=queue_data), \
         patch("backend.services.github_service.fetch_pr_behind_by",
               side_effect=(behind if isinstance(behind, Exception) else None),
               return_value=behind_side) as mock_behind:
        yield mock_behind


def _auto_lane_ids(stores):
    lane = stores["swimlanes"].ensure_auto_lane()
    return [a["queue_item_id"] for a in stores["swimlanes"].get_assignments()
            if a["swimlane_id"] == lane["id"]]


def _age_row(stores, pr_number, hours):
    with stores["db"].connection() as conn:
        conn.execute(
            "UPDATE automation_dispatches SET created_at = datetime('now', ?) "
            "WHERE repo = ? AND pr_number = ?",
            (f"-{hours} hours", REPO, pr_number),
        )


# ----- Routing / dispatch (conditions all green) -----


def test_matched_rule_dispatches_routed_review_and_arms_verdict(env, monkeypatch):
    _patch_config(monkeypatch)
    env["dispatches"].record_candidate(REPO, 7)

    with _gates(), \
         patch("backend.services.github_service.fetch_pr_files",
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

    with _gates(), \
         patch("backend.services.github_service.fetch_pr_files",
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

    with _gates(), \
         patch("backend.services.github_service.fetch_pr_files",
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

    with patch("backend.services.github_service.fetch_pr_queue_data") as mock_data:
        process_pending_dispatches()

    assert mock_data.call_count == 0
    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "pending"


def test_repo_no_longer_allowlisted_is_skipped(env, monkeypatch):
    _patch_config(monkeypatch, repoAllowlist=["other/repo"])
    env["dispatches"].record_candidate(REPO, 7)

    with patch("backend.services.github_service.fetch_pr_queue_data") as mock_data:
        process_pending_dispatches()

    assert mock_data.call_count == 0
    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "skipped"


def test_concurrency_budget_defers_pending_rows(env, monkeypatch):
    _patch_config(monkeypatch, maxConcurrentAutoReviews=1)
    env["dispatches"].record_candidate(REPO, 7)

    from backend.extensions import active_reviews
    active_reviews["x/y/1"] = {"status": "running", "auto_started": True}

    with patch("backend.services.github_service.fetch_pr_queue_data") as mock_data:
        process_pending_dispatches()
    active_reviews.clear()

    assert mock_data.call_count == 0
    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "pending"


def test_file_fetch_failure_retries_then_fails(env, monkeypatch):
    _patch_config(monkeypatch)
    env["dispatches"].record_candidate(REPO, 7)

    with _gates(), \
         patch("backend.services.github_service.fetch_pr_files",
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

    with _gates(), \
         patch("backend.services.github_service.fetch_pr_files",
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

    with _gates(), \
         patch("backend.services.github_service.fetch_pr_files",
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

    with _gates(), \
         patch("backend.services.github_service.fetch_pr_files",
               return_value=["briefs/PB-008-a.md"]), \
         patch("backend.services.review_service.begin_review",
               return_value=({"message": "started"}, 201)):
        process_pending_dispatches()

    item = env["queue"].get_queue_item(7, REPO)
    assert item["id"] in _auto_lane_ids(env)
    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "dispatched"


# ----- Dispatch conditions (CI / behind-base / draft / timeout) -----


def _run_gated(env, monkeypatch, gate_kwargs, cfg_overrides=None):
    _patch_config(monkeypatch, **(cfg_overrides or {}))
    if env["dispatches"].get_by_pr(REPO, 7) is None:
        env["dispatches"].record_candidate(REPO, 7)
    with _gates(**gate_kwargs), \
         patch("backend.services.github_service.fetch_pr_files") as mock_files, \
         patch("backend.services.review_service.begin_review") as mock_begin:
        process_pending_dispatches()
    return mock_files, mock_begin


def test_draft_pr_waits_in_auto_lane(env, monkeypatch):
    mock_files, mock_begin = _run_gated(env, monkeypatch, {"is_draft": True})

    assert mock_begin.call_count == 0
    assert mock_files.call_count == 0
    row = env["dispatches"].get_by_pr(REPO, 7)
    assert row["status"] == "pending"
    assert "draft" in row["detail"]
    # Waiting PRs are visible: queued and placed in the Auto lane.
    item = env["queue"].get_queue_item(7, REPO)
    assert item["id"] in _auto_lane_ids(env)


def test_ci_pending_and_failure_wait(env, monkeypatch):
    for rollup, expected in ((CI_PENDING, "CI pending"), (CI_FAILURE, "CI failure")):
        _, mock_begin = _run_gated(env, monkeypatch, {"rollup": rollup})
        assert mock_begin.call_count == 0
        row = env["dispatches"].get_by_pr(REPO, 7)
        assert row["status"] == "pending"
        assert expected in row["detail"]


def test_no_ci_checks_counts_as_satisfied(env, monkeypatch):
    _patch_config(monkeypatch)
    env["dispatches"].record_candidate(REPO, 7)
    with _gates(rollup=None), \
         patch("backend.services.github_service.fetch_pr_files",
               return_value=["briefs/PB-008-a.md"]), \
         patch("backend.services.review_service.begin_review",
               return_value=({"message": "started"}, 201)) as mock_begin:
        process_pending_dispatches()
    assert mock_begin.call_count == 1


def test_require_ci_pass_off_ignores_ci(env, monkeypatch):
    _patch_config(monkeypatch, requireCiPass=False)
    env["dispatches"].record_candidate(REPO, 7)
    with _gates(rollup=CI_PENDING), \
         patch("backend.services.github_service.fetch_pr_files",
               return_value=["briefs/PB-008-a.md"]), \
         patch("backend.services.review_service.begin_review",
               return_value=({"message": "started"}, 201)) as mock_begin:
        process_pending_dispatches()
    assert mock_begin.call_count == 1


def test_too_far_behind_base_waits(env, monkeypatch):
    _, mock_begin = _run_gated(env, monkeypatch, {"behind": 11})
    assert mock_begin.call_count == 0
    row = env["dispatches"].get_by_pr(REPO, 7)
    assert row["status"] == "pending"
    assert "behind" in row["detail"]


def test_behind_at_limit_proceeds(env, monkeypatch):
    _patch_config(monkeypatch)
    env["dispatches"].record_candidate(REPO, 7)
    with _gates(behind=10), \
         patch("backend.services.github_service.fetch_pr_files",
               return_value=["briefs/PB-008-a.md"]), \
         patch("backend.services.review_service.begin_review",
               return_value=({"message": "started"}, 201)) as mock_begin:
        process_pending_dispatches()
    assert mock_begin.call_count == 1


def test_divergence_check_failure_waits_without_burning_attempts(env, monkeypatch):
    _, mock_begin = _run_gated(env, monkeypatch, {"behind": RuntimeError("compare boom")})
    assert mock_begin.call_count == 0
    row = env["dispatches"].get_by_pr(REPO, 7)
    assert row["status"] == "pending"
    assert row["attempts"] == 0


def test_closed_pr_is_skipped(env, monkeypatch):
    _, mock_begin = _run_gated(env, monkeypatch, {"state": "MERGED"})
    assert mock_begin.call_count == 0
    row = env["dispatches"].get_by_pr(REPO, 7)
    assert row["status"] == "skipped"
    assert "MERGED" in row["detail"]


def test_blocked_row_times_out_to_skipped(env, monkeypatch):
    _patch_config(monkeypatch, dispatchTimeoutHours=24)
    env["dispatches"].record_candidate(REPO, 7)
    _age_row(env, 7, hours=30)

    _, mock_begin = _run_gated(env, monkeypatch, {"rollup": CI_PENDING})

    assert mock_begin.call_count == 0
    row = env["dispatches"].get_by_pr(REPO, 7)
    assert row["status"] == "skipped"
    assert "24h" in row["detail"]
    assert "CI pending" in row["detail"]


def test_blocked_row_within_window_keeps_waiting(env, monkeypatch):
    _patch_config(monkeypatch, dispatchTimeoutHours=24)
    env["dispatches"].record_candidate(REPO, 7)
    _age_row(env, 7, hours=10)

    _run_gated(env, monkeypatch, {"rollup": CI_PENDING})

    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "pending"


def test_waiting_row_does_not_starve_ready_row(env, monkeypatch):
    """Row 7 blocked on CI must not stop the later, ready row 8 from dispatching."""
    _patch_config(monkeypatch, maxConcurrentAutoReviews=1)
    env["synced"].upsert_pr(REPO, _synced_pr(8))
    env["dispatches"].record_candidate(REPO, 7)
    env["dispatches"].record_candidate(REPO, 8)

    def queue_data_for(owner, repo, number):
        rollup = CI_PENDING if number == 7 else CI_SUCCESS
        return {"state": "OPEN", "isDraft": False, "statusCheckRollup": rollup,
                "headRefOid": "abc", "reviewDecision": None, "reviews": None}

    with patch("backend.services.github_service.fetch_pr_queue_data",
               side_effect=queue_data_for), \
         patch("backend.services.github_service.fetch_pr_behind_by", return_value=0), \
         patch("backend.services.github_service.fetch_pr_files",
               return_value=["briefs/PB-008-a.md"]), \
         patch("backend.services.review_service.begin_review",
               return_value=({"message": "started"}, 201)) as mock_begin:
        process_pending_dispatches()

    assert mock_begin.call_count == 1
    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "pending"
    assert env["dispatches"].get_by_pr(REPO, 8)["status"] == "dispatched"
