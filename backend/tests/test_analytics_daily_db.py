"""Tests for AnalyticsDailyDB store."""
import pytest

from backend.database.base import Database
from backend.database.analytics_daily import AnalyticsDailyDB


@pytest.fixture
def store(tmp_path):
    return AnalyticsDailyDB(Database(tmp_path / "test.db"))


def _row(day, login, base_ref="main", is_bot=0, prs_created=0, prs_merged=0, prs_closed=0,
         reviews=0, approvals=0, changes_requested=0, comments=0, additions=0, deletions=0,
         commits=0, merge_hours_sum=0.0, merge_hours_count=0,
         review_rounds_sum=0, review_rounds_count=0):
    return {
        "day": day, "login": login, "base_ref": base_ref, "is_bot": is_bot,
        "prs_created": prs_created, "prs_merged": prs_merged, "prs_closed": prs_closed,
        "reviews": reviews, "approvals": approvals, "changes_requested": changes_requested,
        "comments": comments, "additions": additions, "deletions": deletions,
        "commits": commits, "merge_hours_sum": merge_hours_sum, "merge_hours_count": merge_hours_count,
        "review_rounds_sum": review_rounds_sum, "review_rounds_count": review_rounds_count,
    }


def _meta(**overrides):
    meta = {
        "built_at": "2026-09-01T00:00:00Z", "schema_version": 1,
        "pr_count": 10, "review_count": 5, "commit_count": 20,
        "earliest_pr_day": "2026-01-01", "earliest_commit_day": "2026-01-01",
    }
    meta.update(overrides)
    return meta


# -- replace_repo --------------------------------------------------------------

def test_replace_repo_replaces_not_appends(store):
    store.replace_repo("a/b", [_row("2026-01-01", "alice", prs_created=1)], _meta())
    store.replace_repo("a/b", [_row("2026-01-02", "bob", prs_created=2)], _meta(pr_count=1))

    rows = store.query("a/b", "2000-01-01", "2100-01-01", base_ref="main")
    assert len(rows) == 1
    assert rows[0]["day"] == "2026-01-02"
    assert rows[0]["login"] == "bob"


def test_replace_repo_segregates_by_repo(store):
    store.replace_repo("a/b", [_row("2026-01-01", "alice")], _meta())
    store.replace_repo("c/d", [_row("2026-01-01", "carol")], _meta())
    rows_ab = store.query("a/b", "2000-01-01", "2100-01-01", base_ref="main")
    rows_cd = store.query("c/d", "2000-01-01", "2100-01-01", base_ref="main")
    assert {r["login"] for r in rows_ab} == {"alice"}
    assert {r["login"] for r in rows_cd} == {"carol"}


def test_replace_repo_empty_rows(store):
    store.replace_repo("a/b", [_row("2026-01-01", "alice")], _meta())
    store.replace_repo("a/b", [], _meta(pr_count=0))
    assert store.query("a/b", "2000-01-01", "2100-01-01", base_ref="main") == []
    assert store.get_meta("a/b")["pr_count"] == 0


# -- get_meta --------------------------------------------------------------

def test_get_meta_missing_returns_none(store):
    assert store.get_meta("a/b") is None


def test_get_meta_round_trip(store):
    store.replace_repo("a/b", [], _meta(built_at="2026-09-05T00:00:00Z", schema_version=2))
    meta = store.get_meta("a/b")
    assert meta["built_at"] == "2026-09-05T00:00:00Z"
    assert meta["schema_version"] == 2
    assert meta["pr_count"] == 10
    assert meta["earliest_pr_day"] == "2026-01-01"


# -- query -----------------------------------------------------------------

def test_query_filtered_by_base_ref_returns_raw_rows(store):
    store.replace_repo("a/b", [
        _row("2026-01-01", "alice", base_ref="main", prs_created=1),
        _row("2026-01-01", "alice", base_ref="dev", prs_created=5),
    ], _meta())
    rows = store.query("a/b", "2026-01-01", "2026-01-01", base_ref="main")
    assert len(rows) == 1
    assert rows[0]["base_ref"] == "main"
    assert rows[0]["prs_created"] == 1


def test_query_without_base_ref_groups_and_sums(store):
    store.replace_repo("a/b", [
        _row("2026-01-01", "alice", base_ref="main", is_bot=0, prs_created=1, additions=10),
        _row("2026-01-01", "alice", base_ref="dev", is_bot=0, prs_created=2, additions=20),
        _row("2026-01-01", "bob", base_ref="main", is_bot=1, prs_created=3, additions=30),
    ], _meta())
    rows = store.query("a/b", "2026-01-01", "2026-01-01")
    by_login = {r["login"]: r for r in rows}
    assert by_login["alice"]["prs_created"] == 3     # summed across base refs
    assert by_login["alice"]["additions"] == 30
    assert by_login["alice"]["is_bot"] == 0
    assert by_login["bob"]["prs_created"] == 3
    assert by_login["bob"]["is_bot"] == 1
    assert "base_ref" not in by_login["alice"]


def test_query_review_rounds_round_trip_filtered_by_base_ref(store):
    store.replace_repo("a/b", [
        _row("2026-01-01", "alice", base_ref="main", review_rounds_sum=5, review_rounds_count=2),
    ], _meta())
    rows = store.query("a/b", "2026-01-01", "2026-01-01", base_ref="main")
    assert rows[0]["review_rounds_sum"] == 5
    assert rows[0]["review_rounds_count"] == 2


def test_query_review_rounds_grouped_sum_across_base_refs(store):
    store.replace_repo("a/b", [
        _row("2026-01-01", "alice", base_ref="main", review_rounds_sum=3, review_rounds_count=1),
        _row("2026-01-01", "alice", base_ref="dev", review_rounds_sum=2, review_rounds_count=1),
    ], _meta())
    rows = store.query("a/b", "2026-01-01", "2026-01-01")
    by_login = {r["login"]: r for r in rows}
    assert by_login["alice"]["review_rounds_sum"] == 5
    assert by_login["alice"]["review_rounds_count"] == 2


def test_query_day_range_filter(store):
    store.replace_repo("a/b", [
        _row("2026-01-01", "alice"), _row("2026-01-15", "alice"), _row("2026-02-01", "alice"),
    ], _meta())
    rows = store.query("a/b", "2026-01-01", "2026-01-31", base_ref="main")
    assert {r["day"] for r in rows} == {"2026-01-01", "2026-01-15"}


# -- earliest_day ------------------------------------------------------------

def test_earliest_day(store):
    store.replace_repo("a/b", [
        _row("2026-03-01", "alice", base_ref="main"),
        _row("2026-01-01", "alice", base_ref="main"),
        _row("2026-02-01", "alice", base_ref="dev"),
    ], _meta())
    assert store.earliest_day("a/b") == "2026-01-01"
    assert store.earliest_day("a/b", base_ref="dev") == "2026-02-01"


def test_earliest_day_no_rows(store):
    assert store.earliest_day("a/b") is None


# -- base_refs ---------------------------------------------------------------

def test_base_refs_ordered_by_count_desc(store):
    store.replace_repo("a/b", [
        _row("2026-01-01", "alice", base_ref="main"),
        _row("2026-01-02", "alice", base_ref="main"),
        _row("2026-01-03", "alice", base_ref="main"),
        _row("2026-01-01", "bob", base_ref="dev"),
    ], _meta())
    assert store.base_refs("a/b") == ["main", "dev"]


# -- clear -------------------------------------------------------------------

def test_clear_single_repo(store):
    store.replace_repo("a/b", [_row("2026-01-01", "alice")], _meta())
    store.replace_repo("c/d", [_row("2026-01-01", "carol")], _meta())
    store.clear("a/b")
    assert store.query("a/b", "2000-01-01", "2100-01-01", base_ref="main") == []
    assert store.get_meta("a/b") is None
    assert store.get_meta("c/d") is not None


def test_clear_all_repos(store):
    store.replace_repo("a/b", [_row("2026-01-01", "alice")], _meta())
    store.replace_repo("c/d", [_row("2026-01-01", "carol")], _meta())
    store.clear()
    assert store.query("a/b", "2000-01-01", "2100-01-01", base_ref="main") == []
    assert store.get_meta("a/b") is None
    assert store.get_meta("c/d") is None
