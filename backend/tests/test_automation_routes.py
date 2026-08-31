"""Integration tests for the reviewer registry + automation config routes."""

import tempfile
from pathlib import Path

import pytest

import backend.database as db_pkg
from backend.database.base import Database
from backend.database.automation_dispatches import AutomationDispatchesDB
from backend.database.reviewers import ReviewersDB
from backend.database.settings import SettingsDB
from backend import create_app


@pytest.fixture
def client(monkeypatch):
    tmp = Path(tempfile.mkdtemp()) / "automation_routes_test.db"
    db = Database(tmp)
    reviewers_db = ReviewersDB(db)
    settings_db = SettingsDB(db)
    dispatches_db = AutomationDispatchesDB(db)
    monkeypatch.setattr(db_pkg, "get_reviewers_db", lambda: reviewers_db)
    monkeypatch.setattr(db_pkg, "get_settings_db", lambda: settings_db)
    monkeypatch.setattr(db_pkg, "get_automation_dispatches_db", lambda: dispatches_db)
    import backend.routes.automation_routes as ar
    monkeypatch.setattr(ar, "get_reviewers_db", lambda: reviewers_db)
    monkeypatch.setattr(ar, "get_automation_dispatches_db", lambda: dispatches_db)
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client(), reviewers_db, dispatches_db


def test_list_reviewers_includes_builtins(client):
    c, _, _ = client
    resp = c.get("/api/reviewers")
    assert resp.status_code == 200
    reviewers = resp.get_json()["reviewers"]
    keys = {r["key"] for r in reviewers}
    assert {"default", "pb", "ed"} <= keys
    default = next(r for r in reviewers if r["key"] == "default")
    assert default["agentName"] == "elite-code-reviewer"
    assert default["isBuiltin"] is True


def test_create_reviewer(client):
    c, reviewers_db, _ = client
    resp = c.post("/api/reviewers", json={
        "key": "rust", "label": "Rust", "agentName": "rust-engineer",
        "promptContext": "Focus on unsafe blocks.",
    })
    assert resp.status_code == 201
    assert resp.get_json()["reviewer"]["key"] == "rust"
    assert reviewers_db.get_by_key("rust")["agent_name"] == "rust-engineer"


def test_create_reviewer_validation_errors(client):
    c, _, _ = client
    assert c.post("/api/reviewers", json={"key": "Bad Key", "label": "x", "agentName": "y"}).status_code == 400
    assert c.post("/api/reviewers", json={"label": "x", "agentName": "y"}).status_code == 400
    assert c.post("/api/reviewers", json={"key": "default", "label": "x", "agentName": "y"}).status_code == 400


def test_patch_reviewer(client):
    c, reviewers_db, _ = client
    reviewers_db.create("rust", "Rust", "rust-engineer")
    resp = c.patch("/api/reviewers/rust", json={"label": "Rust Pro"})
    assert resp.status_code == 200
    assert reviewers_db.get_by_key("rust")["label"] == "Rust Pro"


def test_patch_builtin_agent_name_refused(client):
    c, _, _ = client
    resp = c.patch("/api/reviewers/pb", json={"agentName": "other"})
    assert resp.status_code == 400


def test_delete_reviewer(client):
    c, reviewers_db, _ = client
    reviewers_db.create("rust", "Rust", "rust-engineer")
    assert c.delete("/api/reviewers/rust").status_code == 200
    assert reviewers_db.get_by_key("rust") is None


def test_delete_builtin_refused(client):
    c, _, _ = client
    assert c.delete("/api/reviewers/default").status_code == 400


def test_get_automation_config_returns_defaults(client):
    c, _, _ = client
    resp = c.get("/api/automation/config")
    assert resp.status_code == 200
    config = resp.get_json()["config"]
    assert config["scope"] == "off"
    assert config["rules"] == []


def test_put_automation_config_roundtrip(client):
    c, _, _ = client
    payload = {
        "scope": "all",
        "authors": [],
        "repoAllowlist": ["owner/repo"],
        "maxConcurrentAutoReviews": 3,
        "ignorePatterns": ["*PB-000-index*"],
        "defaultRule": {"reviewerKey": "default", "autoVerdict": False, "autoVerdictMode": "verdict"},
        "rules": [{"name": "PB", "patterns": ["PB-[0-9]*"], "reviewerKey": "pb",
                   "autoVerdict": True, "autoVerdictMode": "comment"}],
    }
    resp = c.put("/api/automation/config", json={"config": payload})
    assert resp.status_code == 200
    assert resp.get_json()["config"]["scope"] == "all"
    assert c.get("/api/automation/config").get_json()["config"]["rules"][0]["name"] == "PB"


def test_put_automation_config_rejects_unknown_reviewer(client):
    c, _, _ = client
    payload = {
        "scope": "all",
        "defaultRule": {"reviewerKey": "default", "autoVerdict": False, "autoVerdictMode": "verdict"},
        "rules": [{"name": "X", "patterns": ["*"], "reviewerKey": "ghost",
                   "autoVerdict": False, "autoVerdictMode": "verdict"}],
    }
    assert c.put("/api/automation/config", json={"config": payload}).status_code == 400


def test_list_dispatches_returns_pipeline_rows(client):
    c, _, dispatches_db = client
    dispatches_db.record_candidate("owner/repo", 1)
    dispatches_db.record_candidate("owner/repo", 2)
    row = dispatches_db.get_by_pr("owner/repo", 2)
    dispatches_db.set_status(row["id"], "dispatched", reviewer_key="pb")

    resp = c.get("/api/automation/dispatches")
    assert resp.status_code == 200
    rows = resp.get_json()["dispatches"]
    assert len(rows) == 2
    newest = rows[0]
    assert newest["repo"] == "owner/repo"
    assert newest["prNumber"] == 2
    assert newest["status"] == "dispatched"
    assert newest["reviewerKey"] == "pb"
    assert "updatedAt" in newest and "createdAt" in newest


def test_list_dispatches_filters_by_status(client):
    c, _, dispatches_db = client
    dispatches_db.record_candidate("owner/repo", 1)
    dispatches_db.record_candidate("owner/repo", 2)
    row = dispatches_db.get_by_pr("owner/repo", 2)
    dispatches_db.set_status(row["id"], "dispatched")

    resp = c.get("/api/automation/dispatches?status=pending")
    rows = resp.get_json()["dispatches"]
    assert [r["prNumber"] for r in rows] == [1]


def test_list_dispatches_rejects_unknown_status(client):
    c, _, _ = client
    assert c.get("/api/automation/dispatches?status=exploded").status_code == 400


def test_enroll_adds_missing_pr_to_pipeline(client):
    c, _, dispatches_db = client
    resp = c.post("/api/automation/dispatches/owner/repo/5/enroll")
    assert resp.status_code == 201
    assert resp.get_json()["dispatch"]["status"] == "pending"
    assert dispatches_db.get_by_pr("owner/repo", 5)["status"] == "pending"


def test_enroll_revives_skipped_row(client):
    c, _, dispatches_db = client
    dispatches_db.record_candidate("owner/repo", 5)
    row = dispatches_db.get_by_pr("owner/repo", 5)
    dispatches_db.set_status(row["id"], "skipped", detail="manual opt-out")

    resp = c.post("/api/automation/dispatches/owner/repo/5/enroll")

    assert resp.status_code == 200
    updated = dispatches_db.get_by_pr("owner/repo", 5)
    assert updated["status"] == "pending"
    assert updated["detail"] == "manually re-enrolled"


def test_enroll_is_a_noop_for_active_rows(client):
    c, _, dispatches_db = client
    dispatches_db.record_candidate("owner/repo", 5)

    resp = c.post("/api/automation/dispatches/owner/repo/5/enroll")

    assert resp.status_code == 200
    assert resp.get_json()["dispatch"]["status"] == "pending"


def test_enroll_refuses_dispatched_rows(client):
    c, _, dispatches_db = client
    dispatches_db.record_candidate("owner/repo", 5)
    dispatches_db.set_status(dispatches_db.get_by_pr("owner/repo", 5)["id"], "dispatched")

    resp = c.post("/api/automation/dispatches/owner/repo/5/enroll")

    assert resp.status_code == 409
    assert dispatches_db.get_by_pr("owner/repo", 5)["status"] == "dispatched"


def test_enroll_respects_pipeline_cap(client, monkeypatch):
    c, _, dispatches_db = client
    from backend.services import automation_config
    stored = automation_config.get_config()
    stored["maxPipelineSize"] = 1
    monkeypatch.setattr(automation_config, "get_config", lambda: stored)
    dispatches_db.record_candidate("owner/repo", 1)

    resp = c.post("/api/automation/dispatches/owner/repo/5/enroll")

    assert resp.status_code == 409
    assert dispatches_db.get_by_pr("owner/repo", 5) is None


def test_optout_removes_pending_row_from_pipeline(client):
    c, _, dispatches_db = client
    dispatches_db.record_candidate("owner/repo", 5)

    resp = c.post("/api/automation/dispatches/owner/repo/5/optout")

    assert resp.status_code == 200
    row = dispatches_db.get_by_pr("owner/repo", 5)
    assert row["status"] == "skipped"
    assert row["detail"] == "manual opt-out"


def test_optout_requires_a_pending_row(client):
    c, _, dispatches_db = client
    assert c.post("/api/automation/dispatches/owner/repo/5/optout").status_code == 404

    dispatches_db.record_candidate("owner/repo", 5)
    dispatches_db.set_status(dispatches_db.get_by_pr("owner/repo", 5)["id"], "dispatched")
    assert c.post("/api/automation/dispatches/owner/repo/5/optout").status_code == 409


def test_put_automation_config_accepts_custom_reviewer_key(client):
    c, reviewers_db, _ = client
    reviewers_db.create("rust", "Rust", "rust-engineer")
    payload = {
        "scope": "authors", "authors": ["alice"], "repoAllowlist": ["o/r"],
        "defaultRule": {"reviewerKey": "rust", "autoVerdict": False, "autoVerdictMode": "verdict"},
        "rules": [],
    }
    assert c.put("/api/automation/config", json={"config": payload}).status_code == 200


def _review_state_fixtures(monkeypatch, tmp_path_name="review_state.db"):
    """Wire reviews + merge-queue DBs into the automation routes module."""
    import backend.routes.automation_routes as ar
    from backend.database.reviews import ReviewsDB
    from backend.database.merge_queue import MergeQueueDB
    tmp = Path(tempfile.mkdtemp()) / tmp_path_name
    db = Database(tmp)
    reviews_db = ReviewsDB(db)
    queue_db = MergeQueueDB(db)
    monkeypatch.setattr(ar, "get_reviews_db", lambda: reviews_db)
    monkeypatch.setattr(ar, "get_queue_db", lambda: queue_db)
    return reviews_db, queue_db


def test_list_dispatches_carries_review_state(client, monkeypatch):
    """Dispatched rows say whether a review ran, its verdict, and whether the
    card is armed — so the pipeline table explains why nothing is running."""
    c, _, dispatches_db = client
    reviews_db, queue_db = _review_state_fixtures(monkeypatch)

    dispatches_db.record_candidate("owner/repo", 5)
    row = dispatches_db.get_by_pr("owner/repo", 5)
    dispatches_db.set_status(row["id"], "dispatched", reviewer_key="default")
    rid = reviews_db.save_review(pr_number=5, repo="owner/repo", status="completed",
                                 score=8.0, is_followup=True)
    queue_db.add_to_queue(5, "owner/repo", "t", "a", "u", 1, 1)
    queue_db.set_auto_verdict(5, "owner/repo", True, "default", mode="verdict")

    resp = c.get("/api/automation/dispatches")
    assert resp.status_code == 200
    state = resp.get_json()["dispatches"][0]["reviewState"]
    assert state["running"] is False
    assert state["lastReviewId"] == rid
    assert state["lastReviewStatus"] == "completed"
    assert state["isFollowup"] is True
    assert state["score"] == 8.0
    assert state["armed"] is True
    assert state["autoVerdictMode"] == "verdict"


def test_list_dispatches_review_state_running(client, monkeypatch):
    c, _, dispatches_db = client
    _review_state_fixtures(monkeypatch, "review_state_running.db")
    from backend.extensions import active_reviews, reviews_lock

    dispatches_db.record_candidate("owner/repo", 7)
    row = dispatches_db.get_by_pr("owner/repo", 7)
    dispatches_db.set_status(row["id"], "dispatched")
    with reviews_lock:
        active_reviews["owner/repo/7"] = {"status": "running", "process": None}
    try:
        state = c.get("/api/automation/dispatches").get_json()["dispatches"][0]["reviewState"]
    finally:
        with reviews_lock:
            del active_reviews["owner/repo/7"]
    assert state["running"] is True


def test_list_dispatches_review_state_none_when_untouched(client, monkeypatch):
    """A never-reviewed, unarmed, not-running row carries reviewState: null."""
    c, _, dispatches_db = client
    _review_state_fixtures(monkeypatch, "review_state_none.db")
    dispatches_db.record_candidate("owner/repo", 9)
    resp = c.get("/api/automation/dispatches")
    assert resp.get_json()["dispatches"][0]["reviewState"] is None


def test_list_dispatches_hides_merged_and_closed_prs(client, monkeypatch):
    """The ledger keeps rows for merged/closed PRs (dispatch-at-most-once),
    but the pipeline view only shows PRs that still exist to act on."""
    import backend.routes.automation_routes as ar
    from backend.database.synced_prs import SyncedPRsDB
    c, _, dispatches_db = client
    _review_state_fixtures(monkeypatch, "closed_filter.db")
    store = SyncedPRsDB(Database(Path(tempfile.mkdtemp()) / "synced.db"))
    monkeypatch.setattr(ar, "get_synced_prs_db", lambda: store)

    def _pr(number, state):
        return {"number": number, "state": state, "isDraft": False,
                "author": {"login": "a"}, "updatedAt": "2026-08-01T00:00:00Z",
                "createdAt": "2026-08-01T00:00:00Z", "closedAt": None, "mergedAt": None}

    store.register_repo("owner/repo")
    store.upsert_pr("owner/repo", _pr(1, "OPEN"))
    store.upsert_pr("owner/repo", _pr(2, "MERGED"))
    store.upsert_pr("owner/repo", _pr(3, "CLOSED"))
    for n in (1, 2, 3, 4):  # 4 is unknown to the store: stays visible
        dispatches_db.record_candidate("owner/repo", n)

    resp = c.get("/api/automation/dispatches")
    numbers = sorted(r["prNumber"] for r in resp.get_json()["dispatches"])
    assert numbers == [1, 4]
