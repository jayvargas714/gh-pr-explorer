"""save_review_to_db folds legacy (critical/major/minor) agent output into the
two-tier schema before validation and storage — the compatibility window that
lets the reviewer agents keep emitting the old vocabulary until they are updated."""

import json
import tempfile
from pathlib import Path

import pytest

from backend.database.base import Database
from backend.database.reviews import ReviewsDB
from backend.services import review_service

OWNER, REPO, PR = "owner", "repo", 42
KEY = f"{OWNER}/{REPO}/{PR}"


def _issue(title):
    return {"title": title, "location": {"file": "a.py", "start_line": 1, "end_line": 2},
            "problem": "p", "fix": "f"}


LEGACY_JSON = {
    "schema_version": "1.0.0",
    "metadata": {"pr_number": PR, "repository": f"{OWNER}/{REPO}"},
    "summary": "Legacy summary.", "score": {"overall": 6}, "highlights": [],
    "sections": [
        {"type": "critical", "display_name": "Critical Issues", "issues": [_issue("C1")]},
        {"type": "major", "display_name": "Major Concerns", "issues": [_issue("M1")]},
        {"type": "minor", "display_name": "Minor Issues", "issues": [_issue("m1")]},
        {"type": "disputed", "display_name": "Disputed",
         "issues": [dict(_issue("D1"), severity="major", disposition="no")]},
    ],
}

TWO_TIER_JSON = {
    "schema_version": "2.0.0",
    "metadata": {"pr_number": PR, "repository": f"{OWNER}/{REPO}"},
    "summary": "Two-tier summary.", "score": {"overall": 8}, "highlights": [],
    "sections": [
        {"type": "blocking", "display_name": "Blocking Issues", "issues": [_issue("B1")]},
        {"type": "non_blocking", "display_name": "Non-Blocking Issues", "issues": []},
    ],
}

LEGACY_MD = (
    "# Code Review: PR #42\n\n**Repository**: owner/repo\n\n---\n\n**Summary**\n\nMarkdown summary.\n\n"
    "---\n\n**Critical Issues**\n\n**1. C1**\n- Location: `a.py:1-2`\n- Problem: p\n- Fix: f\n\n"
    "---\n\n**Major Concerns**\n\n**1. M1**\n- Location: `a.py:3`\n- Problem: p\n\n"
    "---\n\n**Minor Issues**\n\nNone\n\n---\n\n**Score: 6/10**\n"
)


@pytest.fixture
def env(monkeypatch, tmp_path):
    reviews_db = ReviewsDB(Database(Path(tempfile.mkdtemp(dir=tmp_path)) / "save.db"))
    monkeypatch.setattr(review_service, "fetch_pr_head_sha", lambda *a, **kw: "abc123")
    monkeypatch.setattr(review_service, "fetch_pr_state", lambda *a, **kw: "OPEN")
    return reviews_db, tmp_path


def _save(reviews_db, review_file):
    review = {"review_file": str(review_file), "pr_url": "u", "pr_title": "t", "pr_author": "a",
              "is_followup": False, "reviewer_type": "default"}
    rid = review_service.save_review_to_db(KEY, review, "completed", reviews_db)
    assert rid is not None
    return json.loads(reviews_db.get_review(rid)["content_json"])


def test_legacy_json_from_the_agent_is_stored_as_two_tier(env):
    reviews_db, tmp_path = env
    md = tmp_path / "review.md"
    md.write_text(LEGACY_MD)
    md.with_suffix(".json").write_text(json.dumps(LEGACY_JSON))

    stored = _save(reviews_db, md)

    assert stored["schema_version"] == "2.0.0"
    assert [s["type"] for s in stored["sections"]] == ["blocking", "non_blocking", "disputed"]
    assert [i["title"] for i in stored["sections"][0]["issues"]] == ["C1", "M1"]
    assert stored["sections"][2]["issues"][0]["severity"] == "blocking"
    assert "error" not in stored


def test_legacy_markdown_fallback_is_stored_as_two_tier(env):
    reviews_db, tmp_path = env
    md = tmp_path / "review.md"
    md.write_text(LEGACY_MD)

    stored = _save(reviews_db, md)

    assert stored["schema_version"] == "2.0.0"
    by_type = {s["type"]: s for s in stored["sections"]}
    assert set(by_type) == {"blocking", "non_blocking"}
    assert [i["title"] for i in by_type["blocking"]["issues"]] == ["C1", "M1"]
    assert stored["summary"] == "Markdown summary."


def test_two_tier_json_is_stored_as_is(env):
    reviews_db, tmp_path = env
    md = tmp_path / "review.md"
    md.write_text("# Code Review: PR #42\n\n---\n\n**Summary**\n\nTwo-tier summary.\n")
    md.with_suffix(".json").write_text(json.dumps(TWO_TIER_JSON))

    stored = _save(reviews_db, md)

    expected = json.loads(json.dumps(TWO_TIER_JSON["sections"]))
    for section in expected:
        for issue in section["issues"]:
            issue.pop("fix", None)
    assert stored["sections"] == expected
    assert stored["schema_version"] == "2.0.0"


# --- reviewers report problems, never solutions ---------------------------------

def _no_fix_anywhere(content):
    return all("fix" not in issue for section in content["sections"] for issue in section["issues"])


def test_fix_emitted_in_json_is_stripped_on_save(env):
    reviews_db, tmp_path = env
    md = tmp_path / "review.md"
    md.write_text("# Code Review: PR #42\n\n---\n\n**Summary**\n\nTwo-tier summary.\n")
    md.with_suffix(".json").write_text(json.dumps(TWO_TIER_JSON))

    stored = _save(reviews_db, md)

    assert stored["sections"][0]["issues"][0]["problem"] == "p"
    assert _no_fix_anywhere(stored)


def test_fix_lines_in_legacy_markdown_are_stripped_on_save(env):
    reviews_db, tmp_path = env
    md = tmp_path / "review.md"
    md.write_text(LEGACY_MD)

    stored = _save(reviews_db, md)

    assert stored["sections"][0]["issues"][0]["problem"] == "p"
    assert _no_fix_anywhere(stored)
