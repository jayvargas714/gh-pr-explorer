"""Tests for the automation dispatch worker (detection rows -> reviews)."""

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest

import backend.database as db_pkg
from backend.database.base import Database
from backend.database.auto_verdict_arming import AutoVerdictArmingDB
from backend.database.automation_dispatches import AutomationDispatchesDB
from backend.database.merge_queue import MergeQueueDB
from backend.database.review_requests import ReviewRequestsDB
from backend.database.reviews import ReviewsDB
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
        "arming": AutoVerdictArmingDB(db),
        # Present only so tests can assert the worker never writes to them.
        "queue": MergeQueueDB(db),
        "swimlanes": SwimlanesDB(db),
        "synced": SyncedPRsDB(db),
        "requests": ReviewRequestsDB(db),
        "reviews": ReviewsDB(db),
    }
    stores["swimlanes"].ensure_default_lane()
    monkeypatch.setattr(db_pkg, "get_automation_dispatches_db", lambda: stores["dispatches"])
    monkeypatch.setattr(db_pkg, "get_auto_verdict_arming_db", lambda: stores["arming"])
    monkeypatch.setattr(db_pkg, "get_queue_db", lambda: stores["queue"])
    monkeypatch.setattr(db_pkg, "get_swimlanes_db", lambda: stores["swimlanes"])
    monkeypatch.setattr(db_pkg, "get_synced_prs_db", lambda: stores["synced"])
    monkeypatch.setattr(db_pkg, "get_review_requests_db", lambda: stores["requests"])
    monkeypatch.setattr(db_pkg, "get_reviews_db", lambda: stores["reviews"])  # begin_review is mocked

    from backend.extensions import active_reviews
    active_reviews.clear()

    stores["synced"].register_repo(REPO)
    stores["synced"].upsert_pr(REPO, _synced_pr(7))
    return stores


def _cfg(**overrides):
    cfg = {
        "scope": "all", "authors": [], "repoAllowlist": [REPO],
        "maxConcurrentAutoReviews": 2,
        "requireCiPass": True, "maxBehindBase": 10, "maxPipelineSize": 1000,
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
def _gates(state="OPEN", is_draft=False, rollup=CI_SUCCESS, behind=0, batch=..., head_sha="newsha"):
    """Patch the live PR condition sources (batched state/draft/CI + divergence).

    The worker gates from one fetch_open_prs_queue_data call per repo: a PR
    absent from the map is not open, and a None map means the fetch failed.
    """
    if batch is ...:
        if state == "OPEN":
            batch = {7: {"state": "OPEN", "isDraft": is_draft, "statusCheckRollup": rollup,
                         "headRefOid": head_sha}}
        else:
            batch = {}  # non-open PRs don't appear in an open-PR listing
    behind_side = behind if not isinstance(behind, Exception) else None
    with patch("backend.services.github_service.fetch_open_prs_queue_data",
               return_value=batch) as mock_batch, \
         patch("backend.services.github_service.fetch_pr_behind_by",
               side_effect=(behind if isinstance(behind, Exception) else None),
               return_value=behind_side) as mock_behind:
        mock_behind.batch_mock = mock_batch
        yield mock_behind


def _age_row(stores, pr_number, hours):
    with stores["db"].connection() as conn:
        conn.execute(
            "UPDATE automation_dispatches SET created_at = datetime('now', ?), "
            "enrolled_at = datetime('now', ?) WHERE repo = ? AND pr_number = ?",
            (f"-{hours} hours", f"-{hours} hours", REPO, pr_number),
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

    arming = env["arming"].get(REPO, 7)
    assert arming is not None
    assert arming["auto_verdict_enabled"] == 1
    assert arming["auto_verdict_reviewer"] == "pb"
    assert arming["auto_verdict_mode"] == "comment"

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
    assert env["arming"].get(REPO, 7) is None
    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "dispatched"


def test_unidentified_pr_is_flagged_but_not_reviewed(env, monkeypatch):
    _patch_config(monkeypatch)
    env["dispatches"].record_candidate(REPO, 7)

    with _gates(), \
         patch("backend.services.github_service.fetch_pr_files",
               return_value=["briefs/PB-008-a.md", "docs/designs/ED-052-b.md"]), \
         patch("backend.services.review_service.begin_review") as mock_begin:
        process_pending_dispatches()

    assert mock_begin.call_count == 0
    row = env["dispatches"].get_by_pr(REPO, 7)
    assert row["status"] == "unidentified"
    assert set(json.loads(row["outcome_json"])["matched_rules"]) == {"PB", "ED"}


def test_scope_off_is_a_kill_switch(env, monkeypatch):
    _patch_config(monkeypatch, scope="off")
    env["dispatches"].record_candidate(REPO, 7)

    with patch("backend.services.github_service.fetch_open_prs_queue_data") as mock_data:
        process_pending_dispatches()

    assert mock_data.call_count == 0
    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "pending"


def test_repo_no_longer_allowlisted_is_skipped(env, monkeypatch):
    _patch_config(monkeypatch, repoAllowlist=["other/repo"])
    env["dispatches"].record_candidate(REPO, 7)

    with patch("backend.services.github_service.fetch_open_prs_queue_data") as mock_data:
        process_pending_dispatches()

    assert mock_data.call_count == 0
    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "skipped"


def test_concurrency_budget_defers_pending_rows(env, monkeypatch):
    _patch_config(monkeypatch, maxConcurrentAutoReviews=1)
    env["dispatches"].record_candidate(REPO, 7)

    from backend.extensions import active_reviews
    active_reviews["x/y/1"] = {"status": "running", "auto_started": True}

    with patch("backend.services.github_service.fetch_open_prs_queue_data") as mock_data:
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

    assert env["arming"].get(REPO, 7) is None
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


def test_worker_never_touches_merge_queue_or_swimlanes(env, monkeypatch):
    """Dispatch writes arming + the ledger only: the operator's watch list and
    board are never modified by automation."""
    _patch_config(monkeypatch)
    env["dispatches"].record_candidate(REPO, 7)

    with _gates(), \
         patch("backend.services.github_service.fetch_pr_files",
               return_value=["briefs/PB-008-a.md"]), \
         patch("backend.services.review_service.begin_review",
               return_value=({"message": "started"}, 201)):
        process_pending_dispatches()

    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "dispatched"
    assert env["queue"].get_queue() == []
    assert [lane["name"] for lane in env["swimlanes"].list_lanes()] == ["Unassigned"]


# ----- Dispatch conditions (CI / behind-base / draft) -----


def _run_gated(env, monkeypatch, gate_kwargs, cfg_overrides=None):
    _patch_config(monkeypatch, **(cfg_overrides or {}))
    if env["dispatches"].get_by_pr(REPO, 7) is None:
        env["dispatches"].record_candidate(REPO, 7)
    with _gates(**gate_kwargs), \
         patch("backend.services.github_service.fetch_pr_files") as mock_files, \
         patch("backend.services.review_service.begin_review") as mock_begin:
        process_pending_dispatches()
    return mock_files, mock_begin


def test_draft_pr_waits(env, monkeypatch):
    """Drafts stay pending (not routed) until they leave draft."""
    mock_files, mock_begin = _run_gated(env, monkeypatch, {"is_draft": True})

    assert mock_begin.call_count == 0
    assert mock_files.call_count == 0
    row = env["dispatches"].get_by_pr(REPO, 7)
    assert row["status"] == "pending"
    assert "draft" in row["detail"]


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


def test_wrong_base_branch_waits(env, monkeypatch):
    """A stacked PR (base != main) waits; retargeting to main later unblocks it."""
    pr = _synced_pr(7)
    pr["baseRefName"] = "feature-parent"
    env["synced"].upsert_pr(REPO, pr)
    _, mock_begin = _run_gated(env, monkeypatch, {},
                               cfg_overrides={"requireBaseBranch": "main"})
    assert mock_begin.call_count == 0
    row = env["dispatches"].get_by_pr(REPO, 7)
    assert row["status"] == "pending"
    assert "base branch is feature-parent" in row["detail"]


def test_unknown_base_branch_waits(env, monkeypatch):
    pr = _synced_pr(7)
    pr["baseRefName"] = None
    env["synced"].upsert_pr(REPO, pr)
    _, mock_begin = _run_gated(env, monkeypatch, {},
                               cfg_overrides={"requireBaseBranch": "main"})
    assert mock_begin.call_count == 0
    row = env["dispatches"].get_by_pr(REPO, 7)
    assert "base branch unknown" in row["detail"]


def test_matching_base_branch_proceeds(env, monkeypatch):
    _patch_config(monkeypatch, requireBaseBranch="main")
    env["dispatches"].record_candidate(REPO, 7)
    with _gates(), \
         patch("backend.services.github_service.fetch_pr_files",
               return_value=["briefs/PB-008-a.md"]), \
         patch("backend.services.review_service.begin_review",
               return_value=({"message": "started"}, 201)) as mock_begin:
        process_pending_dispatches()
    assert mock_begin.call_count == 1


def test_empty_require_base_branch_disables_the_gate(env, monkeypatch):
    pr = _synced_pr(7)
    pr["baseRefName"] = "feature-parent"
    env["synced"].upsert_pr(REPO, pr)
    _patch_config(monkeypatch, requireBaseBranch="")
    env["dispatches"].record_candidate(REPO, 7)
    with _gates(), \
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
    """A PR absent from the open-PR listing is closed or merged — skip it."""
    _, mock_begin = _run_gated(env, monkeypatch, {"state": "MERGED"})
    assert mock_begin.call_count == 0
    row = env["dispatches"].get_by_pr(REPO, 7)
    assert row["status"] == "skipped"
    assert "not open" in row["detail"]


def test_batch_fetch_failure_keeps_rows_waiting(env, monkeypatch):
    """A failed batch fetch means UNKNOWN, never 'no open PRs' — rows must
    wait, not be mass-skipped."""
    _, mock_begin = _run_gated(env, monkeypatch, {"batch": None})
    assert mock_begin.call_count == 0
    row = env["dispatches"].get_by_pr(REPO, 7)
    assert row["status"] == "pending"
    assert "status check failed" in row["detail"]


def test_one_batch_fetch_per_repo_per_cycle(env, monkeypatch):
    """Both same-repo rows must gate from a single gh call."""
    _patch_config(monkeypatch)
    env["synced"].upsert_pr(REPO, _synced_pr(8))
    env["dispatches"].record_candidate(REPO, 7)
    env["dispatches"].record_candidate(REPO, 8)

    batch = {
        7: {"state": "OPEN", "isDraft": True, "statusCheckRollup": None},
        8: {"state": "OPEN", "isDraft": True, "statusCheckRollup": None},
    }
    with _gates(batch=batch) as gates, \
         patch("backend.services.github_service.fetch_pr_files"), \
         patch("backend.services.review_service.begin_review"):
        process_pending_dispatches()

    assert gates.batch_mock.call_count == 1
    for n in (7, 8):
        assert "draft" in env["dispatches"].get_by_pr(REPO, n)["detail"]


def test_blocked_row_waits_indefinitely(env, monkeypatch):
    """No dispatch timeout: an open PR stays in the pipeline no matter how
    long its conditions take to come good."""
    env["dispatches"].record_candidate(REPO, 7)
    _age_row(env, 7, hours=24 * 45)

    _run_gated(env, monkeypatch, {"rollup": CI_PENDING})

    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "pending"


def test_waiting_evaluation_resets_attempts(env, monkeypatch):
    """Transient errors spread over a long wait must not add up to a permanent
    failure: a clean waiting evaluation clears the attempt counter."""
    env["dispatches"].record_candidate(REPO, 7)
    row = env["dispatches"].get_by_pr(REPO, 7)
    env["dispatches"].increment_attempts(row["id"])
    env["dispatches"].increment_attempts(row["id"])

    _run_gated(env, monkeypatch, {"rollup": CI_PENDING})

    row = env["dispatches"].get_by_pr(REPO, 7)
    assert row["status"] == "pending"
    assert row["attempts"] == 0


def test_waiting_row_does_not_starve_ready_row(env, monkeypatch):
    """Row 7 blocked on CI must not stop the later, ready row 8 from dispatching."""
    _patch_config(monkeypatch, maxConcurrentAutoReviews=1)
    env["synced"].upsert_pr(REPO, _synced_pr(8))
    env["dispatches"].record_candidate(REPO, 7)
    env["dispatches"].record_candidate(REPO, 8)

    batch = {
        7: {"state": "OPEN", "isDraft": False, "statusCheckRollup": CI_PENDING},
        8: {"state": "OPEN", "isDraft": False, "statusCheckRollup": CI_SUCCESS},
    }
    with _gates(batch=batch), \
         patch("backend.services.github_service.fetch_pr_files",
               return_value=["briefs/PB-008-a.md"]), \
         patch("backend.services.review_service.begin_review",
               return_value=({"message": "started"}, 201)) as mock_begin:
        process_pending_dispatches()

    assert mock_begin.call_count == 1
    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "pending"
    assert env["dispatches"].get_by_pr(REPO, 8)["status"] == "dispatched"


# ----- PR status comments -----


@pytest.fixture
def comments(monkeypatch):
    """Record every automation status comment the worker would post."""
    calls = []

    def _recorder(kind):
        def _post(owner, repo, pr_number, **kwargs):
            calls.append({"kind": kind, "pr": pr_number, **kwargs})
            return True
        return _post

    for kind in ("enrolled", "waiting", "window_expired", "failed", "unidentified"):
        monkeypatch.setattr(
            f"backend.services.pr_status_comments.post_automation_{kind}_comment",
            _recorder(kind),
        )
    return calls


def _kinds(calls):
    return [c["kind"] for c in calls]


def test_fresh_enrollment_is_announced_once(env, monkeypatch, comments):
    _run_gated(env, monkeypatch, {"is_draft": True})

    assert _kinds(comments) == ["enrolled", "waiting"]
    assert comments[1]["reason"] == "PR is a draft"

    # Second cycle: same wait state — nothing new is announced.
    comments.clear()
    _run_gated(env, monkeypatch, {"is_draft": True})
    assert comments == []


def test_marked_rows_do_not_reannounce_enrollment(env, monkeypatch, comments):
    """Backfilled/requeued rows carry a detail and must enroll silently."""
    env["dispatches"].record_candidate(REPO, 7)
    row = env["dispatches"].get_by_pr(REPO, 7)
    env["dispatches"].requeue(row["id"], detail="enrolled by backfill")

    _run_gated(env, monkeypatch, {"is_draft": True})

    assert "enrolled" not in _kinds(comments)


def test_wait_reason_change_reposts(env, monkeypatch, comments):
    _run_gated(env, monkeypatch, {"is_draft": True})
    comments.clear()

    _run_gated(env, monkeypatch, {"rollup": CI_PENDING})

    assert _kinds(comments) == ["waiting"]
    assert comments[0]["reason"] == "CI pending"


def test_digit_only_wait_change_does_not_repost(env, monkeypatch, comments):
    _run_gated(env, monkeypatch, {"behind": 12})
    assert [c["reason"] for c in comments if c["kind"] == "waiting"] == [
        "12 commits behind base (max 10)"
    ]
    comments.clear()

    _run_gated(env, monkeypatch, {"behind": 13})

    assert comments == []


def test_window_expiry_is_announced(env, monkeypatch, comments):
    env["dispatches"].record_candidate(REPO, 7)
    _age_row(env, 7, hours=100)

    _run_gated(env, monkeypatch, {}, cfg_overrides={"dispatchTimeoutHours": 48})

    assert _kinds(comments) == ["window_expired"]
    assert comments[0]["timeout_hours"] == 48


def test_dispatch_give_up_is_announced(env, monkeypatch, comments):
    _patch_config(monkeypatch)
    env["dispatches"].record_candidate(REPO, 7)

    with _gates(), \
         patch("backend.services.github_service.fetch_pr_files",
               side_effect=RuntimeError("boom")):
        for _ in range(3):
            process_pending_dispatches()

    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "failed"
    assert _kinds(comments) == ["enrolled", "failed"]
    assert comments[1]["attempts"] == 3
    assert "boom" in comments[1]["detail"]


def test_unidentified_routing_is_announced(env, monkeypatch, comments):
    _patch_config(monkeypatch)
    env["dispatches"].record_candidate(REPO, 7)

    with _gates(), \
         patch("backend.services.github_service.fetch_pr_files",
               return_value=["briefs/PB-008-a.md", "src/main.rs"]):
        process_pending_dispatches()

    assert _kinds(comments) == ["enrolled", "unidentified"]
    assert comments[1]["matched_rules"] == ["PB"]
    assert comments[1]["unmatched_count"] == 1


def test_closed_pr_skip_is_silent(env, monkeypatch, comments):
    _run_gated(env, monkeypatch, {"state": "MERGED"})

    assert comments == []


def test_reenrolled_row_gets_a_fresh_dispatch_window(env, monkeypatch):
    """Requeue restarts the dispatch-window timer: a row that expired once and
    was re-enrolled must wait the full window again, not re-expire next cycle."""
    env["dispatches"].record_candidate(REPO, 7)
    _age_row(env, 7, hours=100)
    row = env["dispatches"].get_by_pr(REPO, 7)
    env["dispatches"].requeue(row["id"], detail="manually re-enrolled")

    _run_gated(env, monkeypatch, {"rollup": CI_PENDING}, cfg_overrides={"dispatchTimeoutHours": 48})

    fresh = env["dispatches"].get_by_pr(REPO, 7)
    assert fresh["status"] == "pending"
    assert fresh["detail"].startswith("waiting:")


# ----- review-request follow-ups -----

OLD_SHA = "oldsha"


def _dispatched(env, reviewer_key="pb"):
    env["dispatches"].record_candidate(REPO, 7)
    row = env["dispatches"].get_by_pr(REPO, 7)
    env["dispatches"].set_status(row["id"], "dispatched", reviewer_key=reviewer_key)
    return row


def _saved_review(env, head_commit_sha=OLD_SHA):
    return env["reviews"].save_review(
        pr_number=7, repo=REPO, status="completed", pr_url="https://github.com/owner/repo/pull/7",
        pr_title="t", pr_author="a", content_json="{}", head_commit_sha=head_commit_sha,
    )


def _age_request(env, hours):
    with env["db"].connection() as conn:
        conn.execute(
            "UPDATE review_requests SET requested_at = datetime('now', ?) WHERE repo = ? AND pr_number = ?",
            (f"-{hours} hours", REPO, 7),
        )


def _run_request(env, monkeypatch, gate_kwargs=None, cfg_overrides=None, begin=({"message": "started"}, 201)):
    _patch_config(monkeypatch, **(cfg_overrides or {}))
    with _gates(**(gate_kwargs or {})) as mock_behind, \
         patch("backend.services.github_service.fetch_pr_files") as mock_files, \
         patch("backend.services.review_service.begin_review", return_value=begin) as mock_begin:
        process_pending_dispatches()
    mock_begin.batch_mock = mock_behind.batch_mock
    mock_begin.files_mock = mock_files
    return mock_begin


def test_review_request_starts_followup_with_armed_reviewer(env, monkeypatch):
    _dispatched(env, reviewer_key="pb")
    env["arming"].set_arming(REPO, 7, True, "ed", mode="verdict")
    _saved_review(env)
    env["requests"].record(REPO, 7)

    mock_begin = _run_request(env, monkeypatch)

    assert mock_begin.call_count == 1
    kwargs = mock_begin.call_args.kwargs
    assert kwargs["is_followup"] is True
    assert kwargs["auto_started"] is True
    assert kwargs["reviewer_type"] == "ed"
    assert kwargs["head_unchanged"] is False
    assert "new commits" in kwargs["comment_note"]
    assert mock_begin.files_mock.call_count == 0  # no routing for follow-ups
    req = env["requests"].get_by_pr(REPO, 7)
    assert req["status"] == "fulfilled"
    assert "ed" in req["detail"]


def test_review_request_uses_routed_reviewer_when_unarmed(env, monkeypatch):
    _dispatched(env, reviewer_key="pb")
    _saved_review(env)
    env["requests"].record(REPO, 7)
    mock_begin = _run_request(env, monkeypatch)
    assert mock_begin.call_args.kwargs["reviewer_type"] == "pb"


def test_review_request_falls_back_to_default_reviewer(env, monkeypatch):
    _dispatched(env, reviewer_key=None)
    env["requests"].record(REPO, 7)  # no saved review either
    mock_begin = _run_request(env, monkeypatch)
    assert mock_begin.call_args.kwargs["reviewer_type"] == "default"
    assert mock_begin.call_args.kwargs["head_unchanged"] is False


def test_review_request_with_unchanged_head_says_so(env, monkeypatch):
    _dispatched(env)
    _saved_review(env, head_commit_sha="samesha")
    env["requests"].record(REPO, 7)
    mock_begin = _run_request(env, monkeypatch, {"head_sha": "samesha"})
    kwargs = mock_begin.call_args.kwargs
    assert kwargs["head_unchanged"] is True
    assert "no new commits" in kwargs["comment_note"]


def test_review_request_waits_on_ci_with_followup_comment(env, monkeypatch, comments):
    _dispatched(env)
    env["requests"].record(REPO, 7)
    mock_begin = _run_request(env, monkeypatch, {"rollup": CI_PENDING})
    assert mock_begin.call_count == 0
    req = env["requests"].get_by_pr(REPO, 7)
    assert req["status"] == "pending"
    assert req["detail"] == "waiting: CI pending"
    assert comments == [{"kind": "waiting", "pr": 7, "reason": "CI pending", "is_followup": True}]


def test_review_request_waiting_reason_is_not_reposted(env, monkeypatch, comments):
    _dispatched(env)
    env["requests"].record(REPO, 7)
    _run_request(env, monkeypatch, {"rollup": CI_PENDING})
    _run_request(env, monkeypatch, {"rollup": CI_PENDING})
    assert len(comments) == 1


def test_review_request_draft_waits(env, monkeypatch):
    _dispatched(env)
    env["requests"].record(REPO, 7)
    mock_begin = _run_request(env, monkeypatch, {"is_draft": True})
    assert mock_begin.call_count == 0
    assert env["requests"].get_by_pr(REPO, 7)["detail"] == "waiting: PR is a draft"


def test_review_request_closed_pr_is_skipped(env, monkeypatch, comments):
    _dispatched(env)
    env["requests"].record(REPO, 7)
    _run_request(env, monkeypatch, {"state": "CLOSED"})
    assert env["requests"].get_by_pr(REPO, 7)["status"] == "skipped"
    assert comments == []


def test_review_request_409_is_fulfilled_by_running_review(env, monkeypatch):
    _dispatched(env)
    env["requests"].record(REPO, 7)
    _run_request(env, monkeypatch, begin=({"error": "running"}, 409))
    req = env["requests"].get_by_pr(REPO, 7)
    assert req["status"] == "fulfilled"
    assert "already in progress" in req["detail"]


def test_review_request_429_stays_pending_without_attempts(env, monkeypatch):
    _dispatched(env)
    env["requests"].record(REPO, 7)
    _run_request(env, monkeypatch, begin=({"error": "budget", "over_budget": True}, 429))
    req = env["requests"].get_by_pr(REPO, 7)
    assert req["status"] == "pending"
    assert req["attempts"] == 0


def test_review_request_failure_retries_then_fails(env, monkeypatch, comments):
    _dispatched(env)
    env["requests"].record(REPO, 7)
    for _ in range(2):
        _run_request(env, monkeypatch, begin=({"error": "boom"}, 500))
        assert env["requests"].get_by_pr(REPO, 7)["status"] == "pending"
    _run_request(env, monkeypatch, begin=({"error": "boom"}, 500))
    req = env["requests"].get_by_pr(REPO, 7)
    assert req["status"] == "failed"
    assert req["attempts"] == 3
    assert _kinds(comments) == ["failed"]


def test_review_request_window_expires_from_requested_at(env, monkeypatch, comments):
    _dispatched(env)
    env["requests"].record(REPO, 7)
    _age_request(env, hours=100)
    mock_begin = _run_request(env, monkeypatch, {"rollup": CI_PENDING},
                              cfg_overrides={"dispatchTimeoutHours": 48})
    assert mock_begin.call_count == 0
    assert env["requests"].get_by_pr(REPO, 7)["status"] == "skipped"
    assert _kinds(comments) == ["window_expired"]


def test_review_request_without_timeout_waits_indefinitely(env, monkeypatch):
    _dispatched(env)
    env["requests"].record(REPO, 7)
    _age_request(env, hours=24 * 45)
    _run_request(env, monkeypatch, {"rollup": CI_PENDING})
    assert env["requests"].get_by_pr(REPO, 7)["status"] == "pending"


def test_review_requests_share_the_concurrency_budget(env, monkeypatch):
    """Budget 1, a ready first review and a ready follow-up: only one starts."""
    env["dispatches"].record_candidate(REPO, 8)
    env["synced"].upsert_pr(REPO, _synced_pr(8))
    _dispatched(env)
    env["requests"].record(REPO, 7)
    _patch_config(monkeypatch, maxConcurrentAutoReviews=1)
    batch = {n: {"state": "OPEN", "isDraft": False, "statusCheckRollup": CI_SUCCESS,
                 "headRefOid": "x"} for n in (7, 8)}
    with _gates(batch=batch), \
         patch("backend.services.github_service.fetch_pr_files", return_value=["briefs/PB-1.md"]), \
         patch("backend.services.review_service.begin_review",
               return_value=({"message": "started"}, 201)) as mock_begin:
        process_pending_dispatches()
    assert mock_begin.call_count == 1
    assert env["dispatches"].get_by_pr(REPO, 8)["status"] == "dispatched"
    assert env["requests"].get_by_pr(REPO, 7)["status"] == "pending"


def test_review_request_shares_the_per_repo_batch_fetch(env, monkeypatch):
    env["dispatches"].record_candidate(REPO, 8)
    env["synced"].upsert_pr(REPO, _synced_pr(8))
    _dispatched(env)
    env["requests"].record(REPO, 7)
    _patch_config(monkeypatch)
    batch = {n: {"state": "OPEN", "isDraft": False, "statusCheckRollup": CI_PENDING,
                 "headRefOid": "x"} for n in (7, 8)}
    with _gates(batch=batch) as mock_behind, \
         patch("backend.services.github_service.fetch_pr_files"), \
         patch("backend.services.review_service.begin_review"):
        process_pending_dispatches()
    assert mock_behind.batch_mock.call_count == 1


def test_scope_off_ignores_review_requests(env, monkeypatch):
    _dispatched(env)
    env["requests"].record(REPO, 7)
    mock_begin = _run_request(env, monkeypatch, cfg_overrides={"scope": "off"})
    assert mock_begin.call_count == 0
    assert env["requests"].get_by_pr(REPO, 7)["status"] == "pending"


def test_review_request_never_touches_merge_queue_or_swimlanes(env, monkeypatch):
    _dispatched(env)
    env["requests"].record(REPO, 7)
    _run_request(env, monkeypatch)
    assert env["queue"].get_queue() == []
    with env["db"].connection() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM swimlane_assignments").fetchone()["n"] == 0
