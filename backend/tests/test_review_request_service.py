"""Tests for review_request_service — detecting review requests addressed to the
authenticated user and routing them into the pipeline."""

from unittest.mock import patch

import pytest

import backend.database as db_pkg
from backend.database.base import Database
from backend.database.automation_dispatches import AutomationDispatchesDB
from backend.database.review_requests import ReviewRequestsDB
from backend.services.review_request_service import (
    detect_new_review_requests, handle_review_request, review_requested_from,
)

REPO = "acme/widgets"
ME = "jayvargas714"
SVC = "backend.services.review_request_service"


def _row(*requested, number=7):
    # Shape of SyncedPRsDB rows: the gh pr view blob itself.
    return {"number": number, "state": "OPEN",
            "reviewRequests": [
                {"__typename": "User", "login": r} if not r.startswith("team:")
                else {"__typename": "Team", "name": r[5:], "slug": r[5:]}
                for r in requested]}


# ----- detection (pure) -----

def test_detects_absent_to_present():
    assert detect_new_review_requests({7: _row()}, {7: _row(ME)}, ME) == [7]


def test_ignores_already_present():
    assert detect_new_review_requests({7: _row(ME)}, {7: _row(ME)}, ME) == []


def test_ignores_removal():
    assert detect_new_review_requests({7: _row(ME)}, {7: _row()}, ME) == []


def test_ignores_other_users_and_teams():
    old = {7: _row()}
    new = {7: _row("someone-else", "team:platform")}
    assert detect_new_review_requests(old, new, ME) == []


def test_first_seen_pr_with_request_counts():
    assert detect_new_review_requests({}, {7: _row(ME)}, ME) == [7]


def test_no_login_detects_nothing():
    assert detect_new_review_requests({7: _row()}, {7: _row(ME)}, None) == []


def test_missing_review_requests_key_is_tolerated():
    old = {7: {"number": 7}}
    new = {7: {"number": 7, "reviewRequests": None}}
    assert detect_new_review_requests(old, new, ME) == []


def test_returns_sorted_numbers():
    old = {}
    new = {9: _row(ME, number=9), 3: _row(ME, number=3)}
    assert detect_new_review_requests(old, new, ME) == [3, 9]


# ----- routing -----

@pytest.fixture
def env(tmp_path, monkeypatch):
    db = Database(tmp_path / "rr_service.db")
    stores = {
        "dispatches": AutomationDispatchesDB(db),
        "requests": ReviewRequestsDB(db),
    }
    monkeypatch.setattr(db_pkg, "get_automation_dispatches_db", lambda: stores["dispatches"])
    monkeypatch.setattr(db_pkg, "get_review_requests_db", lambda: stores["requests"])
    return stores


def _cfg(**overrides):
    cfg = {"scope": "authors", "authors": ["someone-else"], "repoAllowlist": [REPO],
           "maxPipelineSize": 1000}
    cfg.update(overrides)
    return cfg


@pytest.fixture
def comments(monkeypatch):
    calls = []

    def _rec(kind):
        def _post(owner, repo, pr_number, **kwargs):
            calls.append({"kind": kind, "pr": pr_number, **kwargs})
            return True
        return _post

    for kind in ("enrolled", "followup_queued", "unidentified"):
        monkeypatch.setattr(
            f"backend.services.pr_status_comments.post_review_requested_{kind}_comment",
            _rec(kind))
    return calls


def _handle(monkeypatch, pr_row=None, **cfg):
    from backend.services import automation_config
    monkeypatch.setattr(automation_config, "get_config", lambda: _cfg(**cfg))
    handle_review_request(REPO, 7, pr_row or _row(ME))


def test_unenrolled_pr_is_enrolled_with_request_detail(env, monkeypatch, comments):
    _handle(monkeypatch)
    row = env["dispatches"].get_by_pr(REPO, 7)
    assert row["status"] == "pending"
    assert row["detail"] == "review requested"
    assert comments == [{"kind": "enrolled", "pr": 7, "reenrolled": False}]
    assert env["requests"].get_by_pr(REPO, 7) is None


def test_author_scope_is_ignored_for_explicit_requests(env, monkeypatch, comments):
    """scope=authors with an author outside the list still enrolls: a human asked."""
    _handle(monkeypatch, scope="authors", authors=["nobody"])
    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "pending"


def test_scope_off_does_nothing(env, monkeypatch, comments):
    _handle(monkeypatch, scope="off")
    assert env["dispatches"].get_by_pr(REPO, 7) is None
    assert comments == []


def test_non_allowlisted_repo_does_nothing(env, monkeypatch, comments):
    _handle(monkeypatch, repoAllowlist=["other/repo"])
    assert env["dispatches"].get_by_pr(REPO, 7) is None
    assert comments == []


def test_pipeline_cap_refuses_enrollment(env, monkeypatch, comments):
    env["dispatches"].record_candidate(REPO, 1)
    _handle(monkeypatch, maxPipelineSize=1)
    assert env["dispatches"].get_by_pr(REPO, 7) is None
    assert comments == []


def test_pending_row_is_left_alone(env, monkeypatch, comments):
    env["dispatches"].record_candidate(REPO, 7)
    row = env["dispatches"].get_by_pr(REPO, 7)
    env["dispatches"].set_status(row["id"], "pending", detail="waiting: CI pending")
    _handle(monkeypatch)
    assert env["dispatches"].get_by_pr(REPO, 7)["detail"] == "waiting: CI pending"
    assert comments == []


@pytest.mark.parametrize("status,detail", [
    ("skipped", "dispatch window expired (72h)"),
    ("skipped", "manual opt-out"),
    ("failed", "begin_review failed (500)"),
])
def test_terminal_rows_are_requeued(env, monkeypatch, comments, status, detail):
    env["dispatches"].record_candidate(REPO, 7)
    row = env["dispatches"].get_by_pr(REPO, 7)
    env["dispatches"].set_status(row["id"], status, detail=detail)
    env["dispatches"].increment_attempts(row["id"])

    _handle(monkeypatch)

    fresh = env["dispatches"].get_by_pr(REPO, 7)
    assert fresh["status"] == "pending"
    assert fresh["attempts"] == 0
    assert fresh["detail"] == "review requested"
    assert comments == [{"kind": "enrolled", "pr": 7, "reenrolled": True}]


def test_unidentified_row_only_comments(env, monkeypatch, comments):
    env["dispatches"].record_candidate(REPO, 7)
    row = env["dispatches"].get_by_pr(REPO, 7)
    env["dispatches"].set_status(row["id"], "unidentified", detail="files span rules")
    _handle(monkeypatch)
    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "unidentified"
    assert env["requests"].get_by_pr(REPO, 7) is None
    assert [c["kind"] for c in comments] == ["unidentified"]


def test_dispatched_row_queues_followup_request(env, monkeypatch, comments):
    env["dispatches"].record_candidate(REPO, 7)
    row = env["dispatches"].get_by_pr(REPO, 7)
    env["dispatches"].set_status(row["id"], "dispatched", reviewer_key="ed")

    _handle(monkeypatch)

    req = env["requests"].get_by_pr(REPO, 7)
    assert req["status"] == "pending"
    assert env["dispatches"].get_by_pr(REPO, 7)["status"] == "dispatched"
    assert [c["kind"] for c in comments] == ["followup_queued"]


def test_repeat_request_while_pending_is_silent(env, monkeypatch, comments):
    env["dispatches"].record_candidate(REPO, 7)
    row = env["dispatches"].get_by_pr(REPO, 7)
    env["dispatches"].set_status(row["id"], "dispatched")
    _handle(monkeypatch)
    _handle(monkeypatch)
    assert env["requests"].count_pending() == 1
    assert [c["kind"] for c in comments] == ["followup_queued"]


def test_handle_never_raises(env, monkeypatch, comments):
    from backend.services import automation_config
    def boom():
        raise RuntimeError("config exploded")
    monkeypatch.setattr(automation_config, "get_config", boom)
    handle_review_request(REPO, 7, _row(ME))  # must not raise
    assert comments == []


# ----- badge helper (pure) -----

def test_review_requested_from_reads_current_requests():
    assert review_requested_from(_row(ME), ME) is True
    assert review_requested_from(_row("someone-else"), ME) is False
    assert review_requested_from(_row("team:platform"), ME) is False
    assert review_requested_from({}, ME) is False
    assert review_requested_from(_row(ME), None) is False
