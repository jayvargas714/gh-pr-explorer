"""Integration tests for the per-card auto-verdict routes via the Flask test client."""

import json
import tempfile
from pathlib import Path

import pytest

import backend.database as db_pkg
from backend.database.base import Database
from backend.database.merge_queue import MergeQueueDB
from backend import create_app

REPO = "owner/repo"
PR = 42


@pytest.fixture
def client(monkeypatch):
    tmp = Path(tempfile.mkdtemp()) / "queue_routes_test.db"
    queue_db = MergeQueueDB(Database(tmp))
    monkeypatch.setattr(db_pkg, "get_queue_db", lambda: queue_db)
    import backend.routes.queue_routes as qr
    monkeypatch.setattr(qr, "get_queue_db", lambda: queue_db)
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client(), queue_db


def _queued(queue_db):
    queue_db.add_to_queue(pr_number=PR, repo=REPO, pr_title="t", pr_author="a",
                          pr_url="u", additions=1, deletions=1)


def test_arming_with_comment_mode_persists(client):
    c, queue_db = client
    _queued(queue_db)

    resp = c.put(f"/api/merge-queue/{PR}/auto-verdict?repo={REPO}",
                 json={"enabled": True, "reviewerType": "default", "mode": "comment"})

    assert resp.status_code == 200
    assert resp.get_json()["autoVerdict"]["mode"] == "comment"
    assert queue_db.get_queue_item(PR, REPO)["auto_verdict_mode"] == "comment"


def test_arming_defaults_to_verdict_mode(client):
    c, queue_db = client
    _queued(queue_db)

    resp = c.put(f"/api/merge-queue/{PR}/auto-verdict?repo={REPO}",
                 json={"enabled": True, "reviewerType": "default"})

    assert resp.status_code == 200
    assert resp.get_json()["autoVerdict"]["mode"] == "verdict"


def test_invalid_mode_is_rejected(client):
    c, queue_db = client
    _queued(queue_db)

    resp = c.put(f"/api/merge-queue/{PR}/auto-verdict?repo={REPO}",
                 json={"enabled": True, "reviewerType": "default", "mode": "shout"})

    assert resp.status_code == 400


def test_criteria_override_is_set_and_returned(client):
    c, queue_db = client
    _queued(queue_db)

    resp = c.put(f"/api/merge-queue/{PR}/auto-verdict/criteria?repo={REPO}",
                 json={"criteria": {"maxCritical": 3, "maxMajor": 1, "maxMinor": 99,
                                    "allowAutoApprove": True, "autoFollowupReview": False}})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["criteriaOverride"]["maxCritical"] == 3
    assert "enabled" not in body["criteriaOverride"]
    stored = json.loads(queue_db.get_queue_item(PR, REPO)["auto_verdict_criteria"])
    assert stored["maxCritical"] == 3


def test_criteria_override_is_cleared_with_null(client):
    c, queue_db = client
    _queued(queue_db)
    queue_db.set_auto_verdict_criteria(PR, REPO, {"maxCritical": 3})

    resp = c.put(f"/api/merge-queue/{PR}/auto-verdict/criteria?repo={REPO}",
                 json={"criteria": None})

    assert resp.status_code == 200
    assert resp.get_json()["criteriaOverride"] is None
    assert queue_db.get_queue_item(PR, REPO)["auto_verdict_criteria"] is None


def test_negative_override_threshold_is_rejected(client):
    c, queue_db = client
    _queued(queue_db)

    resp = c.put(f"/api/merge-queue/{PR}/auto-verdict/criteria?repo={REPO}",
                 json={"criteria": {"maxCritical": -1}})

    assert resp.status_code == 400


def test_criteria_override_for_unqueued_pr_is_404(client):
    c, _ = client

    resp = c.put(f"/api/merge-queue/{PR}/auto-verdict/criteria?repo={REPO}",
                 json={"criteria": {"maxCritical": 1}})

    assert resp.status_code == 404
