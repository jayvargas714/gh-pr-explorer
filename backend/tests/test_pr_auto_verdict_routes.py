"""Integration tests for the per-PR auto-verdict routes via the Flask test client."""

import json
import tempfile
from pathlib import Path

import pytest

import backend.database as db_pkg
from backend.database.base import Database
from backend.database.auto_verdict_arming import AutoVerdictArmingDB
from backend import create_app

REPO = "owner/repo"
PR = 42
URL = f"/api/prs/{REPO}/{PR}/auto-verdict"


@pytest.fixture
def client(monkeypatch):
    tmp = Path(tempfile.mkdtemp()) / "pr_auto_verdict_routes_test.db"
    arming_db = AutoVerdictArmingDB(Database(tmp))
    monkeypatch.setattr(db_pkg, "get_auto_verdict_arming_db", lambda: arming_db)
    import backend.routes.pr_routes as pr_routes
    monkeypatch.setattr(pr_routes, "get_auto_verdict_arming_db", lambda: arming_db)
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client(), arming_db


def test_arming_with_comment_mode_persists(client):
    c, arming_db = client

    resp = c.put(URL, json={"enabled": True, "reviewerType": "default", "mode": "comment"})

    assert resp.status_code == 200
    assert resp.get_json()["autoVerdict"] == {
        "enabled": True, "reviewerType": "default", "mode": "comment",
    }
    row = arming_db.get(REPO, PR)
    assert row["auto_verdict_enabled"] == 1
    assert row["auto_verdict_mode"] == "comment"


def test_arming_needs_no_queue_membership(client):
    """The whole point of the move: arming is per PR, not per queue card."""
    c, arming_db = client
    resp = c.put(URL, json={"enabled": True})
    assert resp.status_code == 200
    assert arming_db.get(REPO, PR)["auto_verdict_enabled"] == 1


def test_arming_defaults_to_verdict_mode(client):
    c, _ = client

    resp = c.put(URL, json={"enabled": True, "reviewerType": "default"})

    assert resp.status_code == 200
    assert resp.get_json()["autoVerdict"]["mode"] == "verdict"


def test_disarming_keeps_row(client):
    c, arming_db = client
    c.put(URL, json={"enabled": True})
    resp = c.put(URL, json={"enabled": False})
    assert resp.status_code == 200
    assert resp.get_json()["autoVerdict"]["enabled"] is False
    assert arming_db.get(REPO, PR)["auto_verdict_enabled"] == 0


def test_invalid_mode_is_rejected(client):
    c, _ = client
    resp = c.put(URL, json={"enabled": True, "reviewerType": "default", "mode": "shout"})
    assert resp.status_code == 400


def test_invalid_reviewer_type_is_rejected(client):
    c, _ = client
    resp = c.put(URL, json={"enabled": True, "reviewerType": "ghost"})
    assert resp.status_code == 400


def test_missing_enabled_is_rejected(client):
    c, _ = client
    assert c.put(URL, json={"mode": "verdict"}).status_code == 400


def test_criteria_override_is_set_and_returned(client):
    c, arming_db = client

    resp = c.put(f"{URL}/criteria",
                 json={"criteria": {"maxCritical": 3, "maxMajor": 1, "maxMinor": 99,
                                    "allowAutoApprove": True, "autoFollowupReview": False}})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["criteriaOverride"]["maxCritical"] == 3
    assert "enabled" not in body["criteriaOverride"]
    stored = json.loads(arming_db.get(REPO, PR)["auto_verdict_criteria"])
    assert stored["maxCritical"] == 3


def test_criteria_override_is_cleared_with_null(client):
    c, arming_db = client
    arming_db.set_criteria(REPO, PR, {"maxCritical": 3})

    resp = c.put(f"{URL}/criteria", json={"criteria": None})

    assert resp.status_code == 200
    assert resp.get_json()["criteriaOverride"] is None
    assert arming_db.get(REPO, PR)["auto_verdict_criteria"] is None


def test_negative_override_threshold_is_rejected(client):
    c, _ = client
    resp = c.put(f"{URL}/criteria", json={"criteria": {"maxCritical": -1}})
    assert resp.status_code == 400


def test_old_merge_queue_arming_routes_are_gone(client):
    c, _ = client
    assert c.put(f"/api/merge-queue/{PR}/auto-verdict?repo={REPO}",
                 json={"enabled": True}).status_code in (404, 405)
    assert c.put(f"/api/merge-queue/{PR}/auto-verdict/criteria?repo={REPO}",
                 json={"criteria": None}).status_code in (404, 405)
