"""The one-shot `severity_two_tier_v1` data migration: legacy critical/major/minor
rows become blocking/non_blocking on the first init that runs the new code."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from backend.database.base import Database
from backend.database.severity_migration import MIGRATION_NAME, apply_severity_two_tier

REPO = "owner/repo"
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "migrate_severity_two_tier.py"

LEGACY_CRITERIA = {"enabled": True, "maxCritical": 0, "maxMajor": 1, "maxMinor": 99,
                   "allowAutoApprove": True, "autoFollowupReview": True}
UPGRADED_CRITERIA = {"enabled": True, "maxBlocking": 1, "maxNonBlocking": None,
                     "allowAutoApprove": True, "autoFollowupReview": True}


def _issue(title, **extra):
    base = {"title": title, "location": {"file": "a.rs", "start_line": 1, "end_line": 1}, "problem": "p"}
    base.update(extra)
    return base


def _legacy_content():
    return json.dumps({
        "schema_version": "1.0.0",
        "metadata": {"pr_number": 1, "repository": REPO},
        "summary": "s", "score": {"overall": 6},
        "sections": [
            {"type": "critical", "display_name": "Critical Issues", "issues": [_issue("C1")]},
            {"type": "major", "display_name": "Major Concerns", "issues": [_issue("M1"), _issue("M2")]},
            {"type": "minor", "display_name": "Minor Issues", "issues": [_issue("m1")]},
            {"type": "disputed", "display_name": "Disputed",
             "issues": [_issue("D1", severity="major", disposition="no")]},
            {"type": "deferred", "display_name": "Deferred",
             "issues": [_issue("F1", severity="minor", disposition="PR #9")]},
        ],
    })


STUB = json.dumps({"schema_version": "1.0.0", "error": True, "sections": [], "score": {"overall": 0}})
UNPARSEABLE = "not json{"

LEGACY_AV_COLUMNS = ("critical_count", "major_count", "minor_count")
LEGACY_REVIEW_COLUMNS = (
    "major_concerns_posted", "minor_issues_posted",
    "critical_posted_count", "critical_found_count", "major_posted_count", "major_found_count",
    "minor_posted_count", "minor_found_count",
)


def _build_legacy_db(path: Path) -> dict:
    """A DB as the old code left it: legacy columns populated, the migration
    not yet recorded. Returns the ids of the inserted rows."""
    db = Database(path)
    ids = {}
    with db.connection() as conn:
        for col in LEGACY_AV_COLUMNS:
            conn.execute(f"ALTER TABLE auto_verdicts ADD COLUMN {col} INTEGER")
        for col in LEGACY_REVIEW_COLUMNS:
            conn.execute(f"ALTER TABLE reviews ADD COLUMN {col} INTEGER")

        def review(content, **cols):
            keys = ", ".join(["pr_number", "repo", "content_json"] + list(cols))
            marks = ", ".join("?" * (3 + len(cols)))
            cur = conn.execute(f"INSERT INTO reviews ({keys}) VALUES ({marks})",
                               (1, REPO, content, *cols.values()))
            return cur.lastrowid

        ids["legacy"] = review(_legacy_content())
        ids["stub"] = review(STUB)
        ids["unparseable"] = review(UNPARSEABLE)
        ids["counters"] = review(
            _legacy_content(), inline_comments_posted=1, major_concerns_posted=0, minor_issues_posted=1,
            critical_posted_count=1, critical_found_count=2, major_posted_count=0, major_found_count=1,
            minor_posted_count=3, minor_found_count=3,
        )
        ids["counters_major_only"] = review(
            _legacy_content(), inline_comments_posted=0, major_concerns_posted=1,
            major_posted_count=2, major_found_count=2,
        )

        conn.execute(
            "INSERT INTO auto_verdicts (repo, pr_number, review_id, event, outcome, reason, "
            "critical_count, major_count, minor_count, criteria_json) "
            "VALUES (?, 1, ?, 'REQUEST_CHANGES', 'posted', '1 critical > 0 allowed', 1, 2, 3, ?)",
            (REPO, ids["legacy"], json.dumps(LEGACY_CRITERIA)))
        conn.execute(
            "INSERT INTO auto_verdicts (repo, pr_number, review_id, outcome, criteria_json) "
            "VALUES (?, 1, ?, 'skipped', ?)", (REPO, ids["stub"], json.dumps(LEGACY_CRITERIA)))
        conn.execute("INSERT INTO user_settings (key, value) VALUES ('auto_verdict_config', ?)",
                     (json.dumps(LEGACY_CRITERIA),))
        conn.execute(
            "INSERT INTO auto_verdict_arming (repo, pr_number, auto_verdict_enabled, auto_verdict_criteria) "
            "VALUES (?, 1, 1, ?)", (REPO, json.dumps({"maxCritical": 2, "maxMajor": 3, "maxMinor": 5})))
        conn.execute(
            "INSERT INTO auto_verdict_arming (repo, pr_number, auto_verdict_enabled) VALUES (?, 2, 1)", (REPO,))
        conn.execute("DELETE FROM migrations WHERE name = ?", (MIGRATION_NAME,))
    return ids


def _rows(path, sql, params=()):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _content_by_id(path):
    return {r["id"]: r["content_json"] for r in _rows(path, "SELECT id, content_json FROM reviews")}


@pytest.fixture
def legacy(tmp_path):
    path = tmp_path / "legacy.db"
    ids = _build_legacy_db(path)
    before = _content_by_id(path)
    return path, ids, before


# --- fresh databases -----------------------------------------------------------

def test_fresh_db_marks_the_migration_done(tmp_path):
    db = Database(tmp_path / "fresh.db")
    assert db.is_migration_done(MIGRATION_NAME)


def test_fresh_db_has_two_tier_columns_and_no_legacy_count_columns(tmp_path):
    db = Database(tmp_path / "fresh.db")
    with db.connection() as conn:
        av = {row[1] for row in conn.execute("PRAGMA table_info(auto_verdicts)")}
        rv = {row[1] for row in conn.execute("PRAGMA table_info(reviews)")}
    assert {"blocking_count", "non_blocking_count"} <= av
    assert not set(LEGACY_AV_COLUMNS) & av
    assert {"blocking_posted_count", "blocking_found_count", "non_blocking_posted_count",
            "non_blocking_found_count", "non_blocking_posted", "inline_comments_posted"} <= rv
    assert not set(LEGACY_REVIEW_COLUMNS) & rv


# --- the one-shot on an existing database -----------------------------------------

def test_reopening_a_legacy_db_rewrites_review_content(legacy):
    path, ids, _ = legacy
    Database(path)
    content = json.loads(_content_by_id(path)[ids["legacy"]])
    assert content["schema_version"] == "2.0.0"
    assert [s["type"] for s in content["sections"]] == ["blocking", "non_blocking", "disputed", "deferred"]
    assert [i["title"] for i in content["sections"][0]["issues"]] == ["C1", "M1", "M2"]
    assert content["sections"][0]["display_name"] == "Blocking Issues"
    assert [i["title"] for i in content["sections"][1]["issues"]] == ["m1"]
    assert content["sections"][2]["issues"][0]["severity"] == "blocking"
    assert content["sections"][3]["issues"][0]["severity"] == "non_blocking"
    assert content["sections"][3]["issues"][0]["disposition"] == "PR #9"


def test_error_stubs_get_only_the_version_bump_and_unparseable_rows_are_untouched(legacy):
    path, ids, before = legacy
    Database(path)
    after = _content_by_id(path)
    assert json.loads(after[ids["stub"]]) == {**json.loads(STUB), "schema_version": "2.0.0"}
    assert after[ids["unparseable"]] == before[ids["unparseable"]]


def test_auto_verdict_counts_are_backfilled_and_unknowns_stay_null(legacy):
    path, ids, _ = legacy
    Database(path)
    by_review = {r["review_id"]: r for r in _rows(path, "SELECT * FROM auto_verdicts")}
    posted = by_review[ids["legacy"]]
    assert (posted["blocking_count"], posted["non_blocking_count"]) == (3, 3)
    skipped = by_review[ids["stub"]]
    assert skipped["blocking_count"] is None and skipped["non_blocking_count"] is None
    for row in by_review.values():
        assert json.loads(row["criteria_json"]) == UPGRADED_CRITERIA


def test_review_posting_counters_are_summed_and_flags_combined(legacy):
    path, ids, _ = legacy
    Database(path)
    rows = {r["id"]: r for r in _rows(path, "SELECT * FROM reviews")}
    both = rows[ids["counters"]]
    assert (both["blocking_posted_count"], both["blocking_found_count"]) == (1, 3)
    assert (both["non_blocking_posted_count"], both["non_blocking_found_count"]) == (3, 3)
    assert both["inline_comments_posted"] == 1 and both["non_blocking_posted"] == 1
    major_only = rows[ids["counters_major_only"]]
    assert (major_only["blocking_posted_count"], major_only["blocking_found_count"]) == (2, 2)
    assert major_only["inline_comments_posted"] == 1  # OR of the two legacy flags
    assert major_only["non_blocking_posted_count"] is None
    untouched = rows[ids["legacy"]]
    assert untouched["blocking_found_count"] is None


def test_stored_criteria_are_upgraded(legacy):
    path, _, _ = legacy
    Database(path)
    (setting,) = _rows(path, "SELECT value FROM user_settings WHERE key = 'auto_verdict_config'")
    assert json.loads(setting["value"]) == UPGRADED_CRITERIA
    arming = {r["pr_number"]: r for r in _rows(path, "SELECT * FROM auto_verdict_arming")}
    assert json.loads(arming[1]["auto_verdict_criteria"]) == {"maxBlocking": 5, "maxNonBlocking": None}
    assert arming[2]["auto_verdict_criteria"] is None


def test_migration_is_recorded_and_a_second_init_changes_nothing(legacy):
    path, _, _ = legacy
    db = Database(path)
    assert db.is_migration_done(MIGRATION_NAME)
    after_first = _content_by_id(path)
    Database(path)
    assert _content_by_id(path) == after_first


def test_apply_reports_what_it_touched(legacy):
    path, _, _ = legacy
    conn = sqlite3.connect(path)
    try:
        report = apply_severity_two_tier(conn.cursor())
    finally:
        conn.rollback()
        conn.close()
    assert report["reviews_seen"] == 5
    assert report["reviews_rewritten"] == 4       # 3 legacy documents + the stub
    assert report["stubs_bumped"] == 1
    assert report["unparseable"] == 1
    assert report["sections_merged"] == 9         # 3 legacy sections x 3 documents
    assert report["disposition_severities_remapped"] == 6
    assert report["auto_verdict_counts_backfilled"] == 1
    assert report["review_counters_backfilled"] == 2
    assert report["criteria_snapshots_upgraded"] == 2
    assert report["settings_upgraded"] is True
    assert report["arming_overrides_upgraded"] == 1


# --- the rehearsal CLI -------------------------------------------------------------

def _run_cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_cli_dry_run_reports_without_changing_the_file(legacy):
    path, _, before = legacy
    result = _run_cli("--db", str(path), "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "reviews_rewritten" in result.stdout and "dry run" in result.stdout.lower()
    assert _content_by_id(path) == before
    assert not _rows(path, "SELECT 1 FROM migrations WHERE name = ?", (MIGRATION_NAME,))


def test_cli_applies_once_then_reports_already_applied(legacy):
    path, ids, _ = legacy
    result = _run_cli("--db", str(path))
    assert result.returncode == 0, result.stderr
    assert json.loads(_content_by_id(path)[ids["legacy"]])["schema_version"] == "2.0.0"
    assert _rows(path, "SELECT 1 FROM migrations WHERE name = ?", (MIGRATION_NAME,))
    again = _run_cli("--db", str(path))
    assert again.returncode == 0
    assert "already applied" in again.stdout.lower()


def test_cli_refuses_a_missing_database(tmp_path):
    result = _run_cli("--db", str(tmp_path / "nope.db"))
    assert result.returncode != 0
