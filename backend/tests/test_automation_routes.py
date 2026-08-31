"""Integration tests for the reviewer registry + automation config routes."""

import tempfile
from pathlib import Path

import pytest

import backend.database as db_pkg
from backend.database.base import Database
from backend.database.reviewers import ReviewersDB
from backend.database.settings import SettingsDB
from backend import create_app


@pytest.fixture
def client(monkeypatch):
    tmp = Path(tempfile.mkdtemp()) / "automation_routes_test.db"
    db = Database(tmp)
    reviewers_db = ReviewersDB(db)
    settings_db = SettingsDB(db)
    monkeypatch.setattr(db_pkg, "get_reviewers_db", lambda: reviewers_db)
    monkeypatch.setattr(db_pkg, "get_settings_db", lambda: settings_db)
    import backend.routes.automation_routes as ar
    monkeypatch.setattr(ar, "get_reviewers_db", lambda: reviewers_db)
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client(), reviewers_db


def test_list_reviewers_includes_builtins(client):
    c, _ = client
    resp = c.get("/api/reviewers")
    assert resp.status_code == 200
    reviewers = resp.get_json()["reviewers"]
    keys = {r["key"] for r in reviewers}
    assert {"default", "pb", "ed"} <= keys
    default = next(r for r in reviewers if r["key"] == "default")
    assert default["agentName"] == "elite-code-reviewer"
    assert default["isBuiltin"] is True


def test_create_reviewer(client):
    c, reviewers_db = client
    resp = c.post("/api/reviewers", json={
        "key": "rust", "label": "Rust", "agentName": "rust-engineer",
        "promptContext": "Focus on unsafe blocks.",
    })
    assert resp.status_code == 201
    assert resp.get_json()["reviewer"]["key"] == "rust"
    assert reviewers_db.get_by_key("rust")["agent_name"] == "rust-engineer"


def test_create_reviewer_validation_errors(client):
    c, _ = client
    assert c.post("/api/reviewers", json={"key": "Bad Key", "label": "x", "agentName": "y"}).status_code == 400
    assert c.post("/api/reviewers", json={"label": "x", "agentName": "y"}).status_code == 400
    assert c.post("/api/reviewers", json={"key": "default", "label": "x", "agentName": "y"}).status_code == 400


def test_patch_reviewer(client):
    c, reviewers_db = client
    reviewers_db.create("rust", "Rust", "rust-engineer")
    resp = c.patch("/api/reviewers/rust", json={"label": "Rust Pro"})
    assert resp.status_code == 200
    assert reviewers_db.get_by_key("rust")["label"] == "Rust Pro"


def test_patch_builtin_agent_name_refused(client):
    c, _ = client
    resp = c.patch("/api/reviewers/pb", json={"agentName": "other"})
    assert resp.status_code == 400


def test_delete_reviewer(client):
    c, reviewers_db = client
    reviewers_db.create("rust", "Rust", "rust-engineer")
    assert c.delete("/api/reviewers/rust").status_code == 200
    assert reviewers_db.get_by_key("rust") is None


def test_delete_builtin_refused(client):
    c, _ = client
    assert c.delete("/api/reviewers/default").status_code == 400


def test_get_automation_config_returns_defaults(client):
    c, _ = client
    resp = c.get("/api/automation/config")
    assert resp.status_code == 200
    config = resp.get_json()["config"]
    assert config["scope"] == "off"
    assert config["rules"] == []


def test_put_automation_config_roundtrip(client):
    c, _ = client
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
    c, _ = client
    payload = {
        "scope": "all",
        "defaultRule": {"reviewerKey": "default", "autoVerdict": False, "autoVerdictMode": "verdict"},
        "rules": [{"name": "X", "patterns": ["*"], "reviewerKey": "ghost",
                   "autoVerdict": False, "autoVerdictMode": "verdict"}],
    }
    assert c.put("/api/automation/config", json={"config": payload}).status_code == 400


def test_put_automation_config_accepts_custom_reviewer_key(client):
    c, reviewers_db = client
    reviewers_db.create("rust", "Rust", "rust-engineer")
    payload = {
        "scope": "authors", "authors": ["alice"], "repoAllowlist": ["o/r"],
        "defaultRule": {"reviewerKey": "rust", "autoVerdict": False, "autoVerdictMode": "verdict"},
        "rules": [],
    }
    assert c.put("/api/automation/config", json={"config": payload}).status_code == 200
