"""Tests for AuditsDB."""

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from backend.database.base import Database
from backend.database.audits import AuditsDB


@pytest.fixture
def audits_db():
    p = Path(tempfile.mkdtemp()) / "audits_test.db"
    return AuditsDB(Database(p))


def _content(pr=1630):
    return json.dumps({
        "schema_version": "1.0.0", "format": "audit", "audit_type": "pb_ed",
        "metadata": {"pr_number": pr, "repository": "owner/repo"},
        "audits": [{"key": "A", "name": "Cross-ED consistency", "findings": []}],
    })


def test_add_and_get_audit(audits_db):
    audit_id = audits_db.add_audit(
        pr_number=1630, repo="owner/repo", pr_title="orch EDs MVP",
        pr_author="sxing", pr_url="https://github.com/owner/repo/pull/1630",
        head_ref="sxing/orch-eds-mvp", base_ref="main",
        content_json=_content(), finding_count=12, blocking_count=0,
    )
    assert isinstance(audit_id, int)
    got = audits_db.get_audit(audit_id)
    assert got["pr_number"] == 1630
    assert got["finding_count"] == 12
    assert got["blocking_count"] == 0
    assert got["audit_type"] == "pb_ed"


def test_get_latest_audit_for_pr(audits_db):
    first_id = audits_db.add_audit(
        pr_number=1630, repo="owner/repo", content_json=_content(),
        audit_timestamp=datetime(2025, 1, 1, 10, 0, 0),
    )
    second_id = audits_db.add_audit(
        pr_number=1630, repo="owner/repo", content_json=_content(),
        audit_timestamp=datetime(2025, 1, 2, 10, 0, 0),
    )
    latest = audits_db.get_latest_audit_for_pr("owner/repo", 1630)
    assert latest is not None
    assert latest["id"] == second_id
    all_for_pr = audits_db.get_audits_for_pr("owner/repo", 1630)
    assert len(all_for_pr) == 2


def test_check_pr_audited(audits_db):
    assert audits_db.check_pr_audited("owner/repo", 1630)["audited"] is False
    audits_db.add_audit(pr_number=1630, repo="owner/repo", content_json=_content())
    res = audits_db.check_pr_audited("owner/repo", 1630)
    assert res["audited"] is True
    assert res["audit_count"] == 1
    assert res["latest_audit"]["id"] is not None


def test_list_and_search(audits_db):
    audits_db.add_audit(pr_number=1630, repo="owner/repo", pr_title="orch EDs MVP",
                        content_json=_content(1630))
    audits_db.add_audit(pr_number=99, repo="other/repo", pr_title="something else",
                        content_json=_content(99))
    assert len(audits_db.list_audits(repo="owner/repo")) == 1
    assert len(audits_db.list_audits()) == 2
    assert len(audits_db.search_audits("orch")) == 1


def test_update_inline_comments_posted(audits_db):
    audit_id = audits_db.add_audit(pr_number=1630, repo="owner/repo", content_json=_content())
    audits_db.update_inline_comments_posted(audit_id, True)
    assert audits_db.get_audit(audit_id)["inline_comments_posted"] == 1


def test_singleton_factory(monkeypatch, tmp_path):
    import backend.database as db_pkg
    from backend.database.base import Database
    from backend.database import AuditsDB as ExportedAuditsDB
    monkeypatch.setattr(db_pkg, "_audits_db", None)
    monkeypatch.setattr(db_pkg, "get_database", lambda: Database(tmp_path / "singleton_test.db"))
    db = db_pkg.get_audits_db()
    assert isinstance(db, ExportedAuditsDB)
    monkeypatch.setattr(db_pkg, "_audits_db", None)
