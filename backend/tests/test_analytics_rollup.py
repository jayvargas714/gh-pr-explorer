"""Tests for the analytics daily rollup builder."""

from datetime import datetime

import pytest

import backend.database as database_pkg
from backend.database.base import Database
from backend.database.synced_prs import SyncedPRsDB
from backend.database.synced_commits import SyncedCommitsDB
from backend.database.analytics_daily import AnalyticsDailyDB
from backend.database.reviews import ReviewsDB
from backend.services.analytics_rollup import (
    ROLLUP_SCHEMA_VERSION, build_rows, needs_rebuild, rebuild_repo,
)


def _pr(number, author="alice", state="OPEN", created_at="2026-09-01T00:00:00Z",
        merged_at=None, closed_at=None, base_ref="main", additions=0, deletions=0,
        author_is_bot=False, reviews=None):
    return {
        "number": number, "state": state, "author": author, "author_is_bot": author_is_bot,
        "created_at": created_at, "merged_at": merged_at, "closed_at": closed_at,
        "base_ref": base_ref, "additions": additions, "deletions": deletions,
        "reviews": reviews or [],
    }


def _review(login, state, submitted_at):
    return {"login": login, "state": state, "submitted_at": submitted_at}


def _commit(branch="main", login="alice", committed_at="2026-09-01T00:00:00Z", parent_count=1):
    return {"branch": branch, "login": login, "committed_at": committed_at, "parent_count": parent_count}


def _find(rows, day, login, base_ref="main"):
    for r in rows:
        if (r["day"], r["login"], r["base_ref"]) == (day, login, base_ref):
            return r
    raise AssertionError(f"no row for {(day, login, base_ref)} in {rows}")


# -- day boundaries ------------------------------------------------------------

def test_utc_day_boundary_splits_prs():
    rows, _ = build_rows([
        _pr(1, created_at="2026-09-01T23:59:59Z"),
        _pr(2, created_at="2026-09-02T00:00:00Z"),
    ], [])
    days = {r["day"] for r in rows}
    assert days == {"2026-09-01", "2026-09-02"}


# -- MERGED ----------------------------------------------------------------

def test_merged_pr_increments_created_and_merged_days():
    rows, _ = build_rows([
        _pr(1, state="MERGED", created_at="2026-09-01T00:00:00Z",
            merged_at="2026-09-02T12:00:00Z", additions=10, deletions=4),
    ], [])
    created_row = _find(rows, "2026-09-01", "alice")
    merged_row = _find(rows, "2026-09-02", "alice")
    assert created_row["prs_created"] == 1
    assert created_row["prs_merged"] == 0
    assert merged_row["prs_merged"] == 1
    assert merged_row["additions"] == 10
    assert merged_row["deletions"] == 4
    assert merged_row["merge_hours_sum"] == 36.0
    assert merged_row["merge_hours_count"] == 1


def test_merged_pr_without_created_at_skips_hours():
    rows, _ = build_rows([
        _pr(1, state="MERGED", created_at=None, merged_at="2026-09-02T00:00:00Z"),
    ], [])
    merged_row = _find(rows, "2026-09-02", "alice")
    assert merged_row["prs_merged"] == 1
    assert merged_row["merge_hours_sum"] == 0
    assert merged_row["merge_hours_count"] == 0


def test_merged_pr_without_merged_at_only_counts_created():
    rows, _ = build_rows([
        _pr(1, state="MERGED", created_at="2026-09-01T00:00:00Z", merged_at=None),
    ], [])
    assert len(rows) == 1
    assert rows[0]["prs_created"] == 1
    assert rows[0]["prs_merged"] == 0


# -- CLOSED / OPEN ------------------------------------------------------------

def test_closed_not_merged_increments_prs_closed_only():
    rows, _ = build_rows([
        _pr(1, state="CLOSED", created_at="2026-09-01T00:00:00Z", closed_at="2026-09-03T00:00:00Z"),
    ], [])
    created_row = _find(rows, "2026-09-01", "alice")
    closed_row = _find(rows, "2026-09-03", "alice")
    assert created_row["prs_created"] == 1
    assert created_row["prs_closed"] == 0
    assert closed_row["prs_closed"] == 1
    assert closed_row["prs_merged"] == 0


def test_open_pr_increments_only_created():
    rows, _ = build_rows([_pr(1, state="OPEN", created_at="2026-09-01T00:00:00Z")], [])
    assert len(rows) == 1
    row = rows[0]
    assert row["prs_created"] == 1
    assert row["prs_merged"] == 0
    assert row["prs_closed"] == 0


# -- reviews -----------------------------------------------------------------

def test_reviews_per_state():
    rows, counters = build_rows([
        _pr(1, created_at="2026-09-01T00:00:00Z", base_ref="main", reviews=[
            _review("bob", "APPROVED", "2026-09-02T00:00:00Z"),
            _review("carol", "CHANGES_REQUESTED", "2026-09-02T00:00:00Z"),
            _review("dave", "COMMENTED", "2026-09-02T00:00:00Z"),
            _review("erin", "DISMISSED", "2026-09-02T00:00:00Z"),
            _review("frank", "PENDING", None),  # skipped: no submitted_at
        ]),
    ], [])
    bob = _find(rows, "2026-09-02", "bob")
    carol = _find(rows, "2026-09-02", "carol")
    dave = _find(rows, "2026-09-02", "dave")
    erin = _find(rows, "2026-09-02", "erin")
    assert bob["reviews"] == 1 and bob["approvals"] == 1
    assert carol["reviews"] == 1 and carol["changes_requested"] == 1
    assert dave["reviews"] == 1 and dave["comments"] == 1
    assert erin["reviews"] == 1 and erin["approvals"] == 0 and erin["changes_requested"] == 0 and erin["comments"] == 0
    assert not any(r["login"] == "frank" for r in rows)
    assert counters["review_count"] == 4  # PENDING with no submitted_at excluded


def test_review_row_uses_pr_base_ref():
    rows, _ = build_rows([
        _pr(1, base_ref="release", reviews=[_review("bob", "APPROVED", "2026-09-02T00:00:00Z")]),
    ], [])
    bob = _find(rows, "2026-09-02", "bob", base_ref="release")
    assert bob["approvals"] == 1


def test_self_review_counts():
    rows, _ = build_rows([
        _pr(1, author="alice", created_at="2026-09-01T00:00:00Z",
            reviews=[_review("alice", "APPROVED", "2026-09-01T00:00:00Z")]),
    ], [])
    row = _find(rows, "2026-09-01", "alice")
    assert row["prs_created"] == 1
    assert row["approvals"] == 1


def test_review_login_none_becomes_unknown():
    rows, _ = build_rows([
        _pr(1, reviews=[_review(None, "APPROVED", "2026-09-02T00:00:00Z")]),
    ], [])
    row = _find(rows, "2026-09-02", "unknown")
    assert row["approvals"] == 1


# -- commits -------------------------------------------------------------------

def test_commit_rows_use_login_and_branch():
    rows, counters = build_rows([], [_commit(branch="main", login="alice", committed_at="2026-09-01T00:00:00Z")])
    row = _find(rows, "2026-09-01", "alice", base_ref="main")
    assert row["commits"] == 1
    assert counters["commit_count"] == 1


def test_merge_commits_skipped():
    rows, counters = build_rows([], [_commit(parent_count=2)])
    assert rows == []
    assert counters["commit_count"] == 0


# -- is_bot propagation --------------------------------------------------------

def test_is_bot_propagates_to_all_rows_for_login_including_reviews():
    rows, _ = build_rows([
        _pr(1, author="bot-user", author_is_bot=True, created_at="2026-09-01T00:00:00Z"),
        _pr(2, author="bot-user", author_is_bot=False, created_at="2026-09-02T00:00:00Z",
            reviews=[_review("bot-user", "APPROVED", "2026-09-03T00:00:00Z")]),
    ], [])
    for r in rows:
        if r["login"] == "bot-user":
            assert r["is_bot"] == 1


def test_is_bot_zero_for_non_bot_login():
    rows, _ = build_rows([_pr(1, author="alice", author_is_bot=False, created_at="2026-09-01T00:00:00Z")], [])
    assert rows[0]["is_bot"] == 0


# -- defaults ------------------------------------------------------------------

def test_base_ref_none_becomes_unknown():
    rows, _ = build_rows([_pr(1, base_ref=None, created_at="2026-09-01T00:00:00Z")], [])
    assert rows[0]["base_ref"] == "unknown"


def test_author_none_becomes_unknown():
    rows, _ = build_rows([_pr(1, author=None, created_at="2026-09-01T00:00:00Z")], [])
    assert rows[0]["login"] == "unknown"


# -- counters --------------------------------------------------------------

def test_counters_earliest_days():
    _, counters = build_rows([
        _pr(1, created_at="2026-09-05T00:00:00Z"),
        _pr(2, created_at="2026-09-01T00:00:00Z"),
    ], [
        _commit(committed_at="2026-08-20T00:00:00Z"),
        _commit(committed_at="2026-08-25T00:00:00Z"),
    ])
    assert counters["earliest_pr_day"] == "2026-09-01"
    assert counters["earliest_commit_day"] == "2026-08-20"
    assert counters["pr_count"] == 2


def test_counters_no_data():
    rows, counters = build_rows([], [])
    assert rows == []
    assert counters == {
        "pr_count": 0, "review_count": 0, "commit_count": 0,
        "earliest_pr_day": None, "earliest_commit_day": None,
    }


# -- review rounds (avg review iterations before merge) ------------------------

def test_run_before_merge_counts():
    rows, _ = build_rows([
        _pr(1, state="MERGED", created_at="2026-09-01T00:00:00Z",
            merged_at="2026-09-02T12:00:00Z"),
    ], [], review_runs={1: ["2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z"]})
    row = _find(rows, "2026-09-02", "alice")
    assert row["review_rounds_sum"] == 2
    assert row["review_rounds_count"] == 1


def test_run_at_merged_at_exactly_counts():
    rows, _ = build_rows([
        _pr(1, state="MERGED", created_at="2026-09-01T00:00:00Z",
            merged_at="2026-09-02T12:00:00Z"),
    ], [], review_runs={1: ["2026-09-02T12:00:00Z"]})
    row = _find(rows, "2026-09-02", "alice")
    assert row["review_rounds_sum"] == 1
    assert row["review_rounds_count"] == 1


def test_run_after_merge_does_not_count():
    rows, _ = build_rows([
        _pr(1, state="MERGED", created_at="2026-09-01T00:00:00Z",
            merged_at="2026-09-02T12:00:00Z"),
    ], [], review_runs={1: ["2026-09-01T00:00:00Z", "2026-09-03T00:00:00Z"]})
    row = _find(rows, "2026-09-02", "alice")
    assert row["review_rounds_sum"] == 1
    assert row["review_rounds_count"] == 1


def test_merged_pr_with_zero_runs_contributes_nothing():
    rows, _ = build_rows([
        _pr(1, state="MERGED", created_at="2026-09-01T00:00:00Z",
            merged_at="2026-09-02T12:00:00Z"),
    ], [], review_runs={})
    row = _find(rows, "2026-09-02", "alice")
    assert row["review_rounds_sum"] == 0
    assert row["review_rounds_count"] == 0


def test_merged_pr_with_only_post_merge_runs_contributes_nothing():
    """All runs land after merged_at -- n == 0, so the count column stays 0
    too (not 1 with a 0 sum)."""
    rows, _ = build_rows([
        _pr(1, state="MERGED", created_at="2026-09-01T00:00:00Z",
            merged_at="2026-09-02T12:00:00Z"),
    ], [], review_runs={1: ["2026-09-03T00:00:00Z"]})
    row = _find(rows, "2026-09-02", "alice")
    assert row["review_rounds_sum"] == 0
    assert row["review_rounds_count"] == 0


def test_open_pr_never_contributes_review_rounds():
    rows, _ = build_rows([
        _pr(1, state="OPEN", created_at="2026-09-01T00:00:00Z"),
    ], [], review_runs={1: ["2026-09-01T00:00:00Z"]})
    row = _find(rows, "2026-09-01", "alice")
    assert row["review_rounds_sum"] == 0
    assert row["review_rounds_count"] == 0


def test_closed_pr_never_contributes_review_rounds():
    rows, _ = build_rows([
        _pr(1, state="CLOSED", created_at="2026-09-01T00:00:00Z", closed_at="2026-09-03T00:00:00Z"),
    ], [], review_runs={1: ["2026-09-01T00:00:00Z"]})
    row = _find(rows, "2026-09-03", "alice")
    assert row["review_rounds_sum"] == 0
    assert row["review_rounds_count"] == 0


def test_review_rounds_attributed_to_author_merge_day_base_ref():
    rows, _ = build_rows([
        _pr(1, author="bob", base_ref="release", state="MERGED", created_at="2026-09-01T00:00:00Z",
            merged_at="2026-09-05T00:00:00Z"),
    ], [], review_runs={1: ["2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z", "2026-09-03T00:00:00Z"]})
    row = _find(rows, "2026-09-05", "bob", base_ref="release")
    assert row["review_rounds_sum"] == 3
    assert row["review_rounds_count"] == 1


def test_review_rounds_fractional_second_timestamp_parses():
    """review_timestamp strings from SQLite can carry fractional seconds
    (e.g. datetime.now() with a non-zero microsecond); _parse_utc must
    still parse and compare them correctly."""
    rows, _ = build_rows([
        _pr(1, state="MERGED", created_at="2026-09-01T00:00:00Z",
            merged_at="2026-09-02T12:00:00Z"),
    ], [], review_runs={1: ["2026-09-02 11:59:59.123456", "2026-09-02 12:00:01.000000"]})
    row = _find(rows, "2026-09-02", "alice")
    assert row["review_rounds_sum"] == 1
    assert row["review_rounds_count"] == 1


def test_review_rounds_unknown_pr_number_ignored():
    """review_runs entries for a PR not in pr_rows are simply never looked up."""
    rows, _ = build_rows([
        _pr(1, state="MERGED", created_at="2026-09-01T00:00:00Z", merged_at="2026-09-02T00:00:00Z"),
    ], [], review_runs={999: ["2026-09-01T00:00:00Z"]})
    row = _find(rows, "2026-09-02", "alice")
    assert row["review_rounds_sum"] == 0
    assert row["review_rounds_count"] == 0


# -- output ordering -----------------------------------------------------------

def test_rows_sorted_by_day_login_base_ref():
    rows, _ = build_rows([
        _pr(1, author="bob", base_ref="dev", created_at="2026-09-01T00:00:00Z"),
        _pr(2, author="alice", base_ref="main", created_at="2026-09-01T00:00:00Z"),
        _pr(3, author="alice", base_ref="main", created_at="2026-08-30T00:00:00Z"),
    ], [])
    keys = [(r["day"], r["login"], r["base_ref"]) for r in rows]
    assert keys == sorted(keys)


# =========================== DB-backed: needs_rebuild / rebuild_repo ============

@pytest.fixture
def dbs(monkeypatch, tmp_path):
    db = Database(tmp_path / "test.db")
    prs_db = SyncedPRsDB(db)
    commits_db = SyncedCommitsDB(db)
    analytics_db = AnalyticsDailyDB(db)
    reviews_db = ReviewsDB(db)
    monkeypatch.setattr(database_pkg, "get_synced_prs_db", lambda: prs_db)
    monkeypatch.setattr(database_pkg, "get_synced_commits_db", lambda: commits_db)
    monkeypatch.setattr(database_pkg, "get_analytics_daily_db", lambda: analytics_db)
    monkeypatch.setattr(database_pkg, "get_reviews_db", lambda: reviews_db)
    return prs_db, commits_db, analytics_db, reviews_db


def _seed_pr(prs_db, repo, number=1, author="alice", state="MERGED",
             created="2026-09-01T00:00:00Z", merged="2026-09-02T00:00:00Z"):
    prs_db.register_repo(repo)
    prs_db.upsert_pr(repo, {
        "number": number, "state": state, "isDraft": False,
        "author": {"login": author, "is_bot": False},
        "createdAt": created, "updatedAt": merged or created,
        "closedAt": None, "mergedAt": merged,
        "baseRefName": "main", "additions": 5, "deletions": 1, "reviews": [],
    })


def test_rebuild_repo_writes_rows_and_meta(dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_pr(prs_db, "a/b")
    commits_db.upsert_commits("a/b", "main", [
        {"sha": "s1", "login": "alice", "committed_at": "2026-09-01T00:00:00Z", "parents": 1},
    ])

    meta = rebuild_repo("a/b")

    assert meta["schema_version"] == ROLLUP_SCHEMA_VERSION
    assert meta["pr_count"] == 1
    assert meta["commit_count"] == 1
    rows = analytics_db.query("a/b", "2000-01-01", "2100-01-01", base_ref="main")
    assert len(rows) > 0
    assert analytics_db.get_meta("a/b")["built_at"] == meta["built_at"]


def test_needs_rebuild_true_with_no_meta(dbs):
    assert needs_rebuild("a/b") is True


def test_needs_rebuild_false_right_after_rebuild(dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_pr(prs_db, "a/b")
    rebuild_repo("a/b")
    assert needs_rebuild("a/b") is False


def test_needs_rebuild_true_after_last_synced_bumped(dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_pr(prs_db, "a/b")
    rebuild_repo("a/b")
    assert needs_rebuild("a/b") is False

    # Push built_at into the past so the subsequent sync bump reads as newer.
    with analytics_db.db.connection() as conn:
        conn.execute(
            "UPDATE analytics_daily_meta SET built_at = ? WHERE repo = ?",
            ("2020-01-01T00:00:00Z", "a/b"),
        )
    prs_db.update_last_synced("a/b")
    assert needs_rebuild("a/b") is True


def test_needs_rebuild_true_on_schema_version_mismatch(dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_pr(prs_db, "a/b")
    rebuild_repo("a/b")
    with analytics_db.db.connection() as conn:
        conn.execute(
            "UPDATE analytics_daily_meta SET schema_version = ? WHERE repo = ?",
            (ROLLUP_SCHEMA_VERSION + 1, "a/b"),
        )
    assert needs_rebuild("a/b") is True


# -- rebuild_repo: review rounds sourced from ReviewsDB -------------------------

def test_rebuild_repo_counts_completed_review_rounds(dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_pr(prs_db, "a/b", number=1, author="alice",
             created="2026-09-01T00:00:00Z", merged="2026-09-02T00:00:00Z")
    reviews_db.save_review(pr_number=1, repo="a/b", status="completed", content_json="{}",
                            review_timestamp=datetime(2026, 9, 1, 6, 0, 0))
    reviews_db.save_review(pr_number=1, repo="a/b", status="completed", content_json="{}",
                            is_followup=True, review_timestamp=datetime(2026, 9, 1, 18, 0, 0))

    rebuild_repo("a/b")
    rows = analytics_db.query("a/b", "2000-01-01", "2100-01-01", base_ref="main")
    row = _find(rows, "2026-09-02", "alice")
    assert row["review_rounds_sum"] == 2
    assert row["review_rounds_count"] == 1


def test_rebuild_repo_excludes_failed_reviews(dbs):
    """A failed run is filtered out at the source (ReviewsDB.get_completed_run_times),
    so it never reaches the rollup as a review iteration."""
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_pr(prs_db, "a/b", number=1, author="alice",
             created="2026-09-01T00:00:00Z", merged="2026-09-02T00:00:00Z")
    reviews_db.save_review(pr_number=1, repo="a/b", status="completed", content_json="{}",
                            review_timestamp=datetime(2026, 9, 1, 6, 0, 0))
    reviews_db.save_review(pr_number=1, repo="a/b", status="failed", content_json="{}",
                            review_timestamp=datetime(2026, 9, 1, 18, 0, 0))

    rebuild_repo("a/b")
    rows = analytics_db.query("a/b", "2000-01-01", "2100-01-01", base_ref="main")
    row = _find(rows, "2026-09-02", "alice")
    assert row["review_rounds_sum"] == 1
    assert row["review_rounds_count"] == 1


def test_rebuild_repo_pr_never_reviewed_contributes_nothing(dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_pr(prs_db, "a/b", number=1, author="alice",
             created="2026-09-01T00:00:00Z", merged="2026-09-02T00:00:00Z")

    rebuild_repo("a/b")
    rows = analytics_db.query("a/b", "2000-01-01", "2100-01-01", base_ref="main")
    row = _find(rows, "2026-09-02", "alice")
    assert row["review_rounds_sum"] == 0
    assert row["review_rounds_count"] == 0
