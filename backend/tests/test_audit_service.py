"""Tests for audit_service.save_audit_to_db (parse → validate → tally → persist)."""

import json
import tempfile
from pathlib import Path

import pytest

from backend.database.base import Database
from backend.database.audits import AuditsDB
from backend.services.audit_service import save_audit_to_db


@pytest.fixture
def audits_db():
    p = Path(tempfile.mkdtemp()) / "svc_test.db"
    return AuditsDB(Database(p))


def _write_audit_json(tmpdir, pr=1630, blocking=False):
    data = {
        "schema_version": "1.0.0", "format": "audit", "audit_type": "pb_ed",
        "metadata": {"pr_number": pr, "repository": "owner/repo"},
        "audits": [
            {"key": "A", "name": "Cross-ED consistency", "findings": [
                {"id": "CE-1", "severity": "INCONSISTENCY", "summary": "x"},
            ]},
            {"key": "B", "name": "PB↔ED parity", "findings": [
                {"id": "PE-1",
                 "severity": "SCOPE-VIOLATION" if blocking else "UN-ANCHORED",
                 "summary": "y"},
            ]},
        ],
    }
    md = Path(tmpdir) / "owner-repo-pr-1630-audit.md"
    js = Path(tmpdir) / "owner-repo-pr-1630-audit.json"
    md.write_text("# audit", encoding="utf-8")
    js.write_text(json.dumps(data), encoding="utf-8")
    return str(md)


def test_save_completed_audit_persists_tallies(audits_db, monkeypatch):
    # Avoid network in fetch_pr_head_sha / fetch_pr_state
    monkeypatch.setattr("backend.services.audit_service.fetch_pr_head_sha", lambda *a, **k: "abc")
    monkeypatch.setattr("backend.services.audit_service.fetch_pr_state", lambda *a, **k: "OPEN")
    tmp = tempfile.mkdtemp()
    audit_file = _write_audit_json(tmp, blocking=True)
    audit = {"audit_file": audit_file, "pr_url": "https://github.com/owner/repo/pull/1630",
             "pr_title": "orch EDs MVP", "pr_author": "sxing",
             "head_ref": "sxing/orch-eds-mvp", "base_ref": "main"}
    save_audit_to_db("owner/repo/1630", audit, "completed", audits_db)

    latest = audits_db.get_latest_audit_for_pr("owner/repo", 1630)
    assert latest is not None
    assert latest["finding_count"] == 2
    assert latest["blocking_count"] == 1   # SCOPE-VIOLATION
    assert latest["status"] == "completed"


def test_failed_audit_persists_stub(audits_db, monkeypatch):
    monkeypatch.setattr("backend.services.audit_service.fetch_pr_head_sha", lambda *a, **k: "abc")
    monkeypatch.setattr("backend.services.audit_service.fetch_pr_state", lambda *a, **k: "OPEN")
    audit = {"audit_file": None, "pr_url": "", "pr_title": None, "pr_author": None}
    save_audit_to_db("owner/repo/1630", audit, "failed", audits_db)
    latest = audits_db.get_latest_audit_for_pr("owner/repo", 1630)
    assert latest["status"] == "failed"
    assert latest["finding_count"] == 0
