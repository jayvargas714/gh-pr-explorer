"""Integration tests for audit routes via the Flask test client."""

import json
import tempfile
from pathlib import Path

import pytest

import backend.database as db_pkg
from backend.database.base import Database
from backend.database.audits import AuditsDB
from backend import create_app


@pytest.fixture
def client(monkeypatch):
    # Point the audits singleton at a temp DB
    tmp = Path(tempfile.mkdtemp()) / "routes_test.db"
    audits_db = AuditsDB(Database(tmp))
    monkeypatch.setattr(db_pkg, "get_audits_db", lambda: audits_db)
    import backend.routes.audit_routes as ar
    monkeypatch.setattr(ar, "get_audits_db", lambda: audits_db)
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client(), audits_db


def _content(pr=1630):
    return json.dumps({
        "schema_version": "1.0.0", "format": "audit", "audit_type": "pb_ed",
        "metadata": {"pr_number": pr, "repository": "owner/repo", "pr_title": "orch EDs MVP"},
        "executive_summary": "Strong set.",
        "audits": [{"key": "A", "name": "Cross-ED consistency", "findings": [
            {"id": "CE-1", "severity": "INCONSISTENCY", "summary": "x"}]}],
    })


def test_start_audit_requires_fields(client):
    c, _ = client
    resp = c.post("/api/audits", json={"number": 1})
    assert resp.status_code == 400


def test_audit_history_list_and_detail(client):
    c, audits_db = client
    audit_id = audits_db.add_audit(pr_number=1630, repo="owner/repo",
                                   pr_title="orch EDs MVP", content_json=_content(),
                                   finding_count=1, blocking_count=0)
    resp = c.get("/api/audit-history")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total"] == 1
    assert body["audits"][0]["pr_number"] == 1630

    resp = c.get(f"/api/audit-history/{audit_id}")
    assert resp.status_code == 200
    detail = resp.get_json()["audit"]
    assert detail["content_json"]["metadata"]["pr_number"] == 1630
    assert "Cross-ED consistency" in detail["content"]


def test_check_audit(client):
    c, audits_db = client
    resp = c.get("/api/audit-history/check/owner/repo/1630")
    assert resp.get_json()["audited"] is False
    audits_db.add_audit(pr_number=1630, repo="owner/repo", content_json=_content())
    resp = c.get("/api/audit-history/check/owner/repo/1630")
    assert resp.get_json()["audited"] is True


def test_findings_to_inline_comments_mapping():
    from backend.routes.audit_routes import _findings_to_inline_comments
    cj = {"audits": [{"key": "A", "name": "x", "findings": [
        {"id": "CE-1", "severity": "INCONSISTENCY", "summary": "s1",
         "detail": "d", "recommendation": "r",
         "locations": [{"file": "docs/ED-010.md", "line": 5}, {"file": "docs/ED-010.md", "line": 9}]},
        {"id": "CE-2", "severity": "INFO", "summary": "s2",
         "locations": [{"file": "docs/ED-010.md", "line": 0}]},   # line<1 -> skipped
        {"id": "CE-3", "severity": "INFO", "summary": "s3", "locations": None},  # None -> skipped, no crash
        {"id": "CE-4", "severity": "INFO", "summary": "s4"},        # no locations -> skipped
    ]}]}
    comments = _findings_to_inline_comments(cj)
    assert len(comments) == 1                      # only CE-1 maps (first location)
    c = comments[0]
    assert c["path"] == "docs/ED-010.md"
    assert c["start_line"] == 5 and c["end_line"] == 5
    assert c["title"] == "CE-1"
    assert "CE-1" in c["body"] and "s1" in c["body"]


def test_findings_to_inline_comments_handles_null_findings():
    from backend.routes.audit_routes import _findings_to_inline_comments
    cj = {"audits": [{"key": "A", "name": "x", "findings": None}, "not-a-dict"]}
    assert _findings_to_inline_comments(cj) == []
