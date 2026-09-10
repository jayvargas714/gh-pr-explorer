"""Tests for the REST commit sync (`sync_commits`)."""
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from backend.database.base import Database
from backend.database.synced_commits import SyncedCommitsDB
from backend.services.pr_sync_worker import sync_commits

WORKER = "backend.services.pr_sync_worker"

_EPOCH = datetime(2026, 6, 1, tzinfo=timezone.utc)


@pytest.fixture
def commits_db(tmp_path):
    return SyncedCommitsDB(Database(tmp_path / "commits.db"))


def _cfg(**overrides):
    cfg = {"commit_branches": ["main"], "commit_pages_per_cycle": 40}
    cfg.update(overrides)
    return cfg


def _ts(days_ago):
    return (_EPOCH - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(sha, committed_at, login="alice", name="Alice", email="a@x.com", parents=1):
    return {
        "sha": sha, "login": login, "name": name, "email": email,
        "authored_at": committed_at, "committed_at": committed_at, "parents": parents,
    }


def _rows(n, start_days_ago):
    """n commits, newest-first: commit i is (start_days_ago + i) days before the epoch."""
    return [_row(f"sha{start_days_ago + i}", _ts(start_days_ago + i)) for i in range(n)]


def test_empty_commit_branches_makes_no_calls(commits_db):
    with patch(f"{WORKER}.fetch_commits_page") as fetch:
        total = sync_commits(None, commits_db, "acme/widgets", _cfg(commit_branches=[]))
    assert total == 0
    fetch.assert_not_called()


def test_backfill_pages_until_short_page_and_marks_done(commits_db):
    page1 = _rows(100, 0)   # newest 100 commits
    page2 = _rows(30, 100)  # older 30, short page -> completes
    seen_until = []

    def fake(owner, repo, branch, page, since=None, until=None, per_page=100):
        seen_until.append(until)
        return page1 if page == 1 else page2

    with patch(f"{WORKER}.fetch_commits_page", side_effect=fake):
        total = sync_commits(None, commits_db, "acme/widgets", _cfg())

    # Page 1 observes true HEAD (no anchor yet); every later page in this
    # cycle is pinned to page 1's max so a push mid-walk can't shift them.
    assert seen_until == [None, _ts(0)]
    assert total == 130
    assert commits_db.count("acme/widgets", "main") == 130
    state = commits_db.get_branch_state("acme/widgets", "main")
    assert state["backfill_done"] is True
    assert state["backfill_until"] is None
    assert state["last_committed_at"] == _ts(0)  # newest commit seen
    assert state["error"] is None


def test_backfill_pages_2_through_n_use_page_1_max_as_fixed_anchor(commits_db):
    """Important #1: pages are offset-relative to `until`, so a push landing
    mid-walk must not shift them. Page 1 runs with until=None; every later
    page this cycle must reuse page 1's max, not a moving "now"."""
    page1 = _rows(100, 0)    # newest 100 -> max is _ts(0)
    page2 = _rows(100, 100)  # still full -> another page follows
    page3 = _rows(10, 200)   # short -> completes
    seen_until = []

    def fake(owner, repo, branch, page, since=None, until=None, per_page=100):
        seen_until.append(until)
        return {1: page1, 2: page2, 3: page3}[page]

    with patch(f"{WORKER}.fetch_commits_page", side_effect=fake):
        sync_commits(None, commits_db, "acme/widgets", _cfg())

    assert seen_until == [None, _ts(0), _ts(0)]


def test_backfill_first_cycle_high_water_mark_survives_a_later_page_failure(commits_db):
    """Important #2: last_committed_at must be written right after page 1,
    not only at loop completion, so a page-2 failure can't leave it NULL."""
    page1 = _rows(100, 0)  # full page -> anchors and more pages follow

    def fake(owner, repo, branch, page, since=None, until=None, per_page=100):
        if page == 1:
            return page1
        raise RuntimeError("gh api failed on page 2")

    with patch(f"{WORKER}.fetch_commits_page", side_effect=fake):
        sync_commits(None, commits_db, "acme/widgets", _cfg())

    state = commits_db.get_branch_state("acme/widgets", "main")
    assert state["last_committed_at"] == _ts(0)  # captured from page 1, not lost
    assert "gh api failed on page 2" in state["error"]
    assert state["backfill_done"] is False


def test_backfill_checkpoints_and_resumes_with_same_until_param(commits_db):
    """Cap the per-cycle page budget below what's needed; the next cycle must
    resume from the checkpointed `backfill_until`, using it as a fixed `until`
    for that cycle's own page walk."""
    page1 = _rows(100, 0)

    def cycle1(owner, repo, branch, page, since=None, until=None, per_page=100):
        assert until is None
        assert page == 1
        return page1

    with patch(f"{WORKER}.fetch_commits_page", side_effect=cycle1):
        total1 = sync_commits(None, commits_db, "acme/widgets", _cfg(commit_pages_per_cycle=1))

    assert total1 == 100
    state = commits_db.get_branch_state("acme/widgets", "main")
    assert state["backfill_done"] is False
    checkpoint = state["backfill_until"]
    assert checkpoint == _ts(99)  # oldest commit seen so far

    seen_until = []

    def cycle2(owner, repo, branch, page, since=None, until=None, per_page=100):
        seen_until.append(until)
        assert until == checkpoint  # fixed for the whole page walk this cycle
        if page == 1:
            return _rows(50, 100)  # continues where cycle1 left off; short page
        raise AssertionError("should have stopped at the short page")

    with patch(f"{WORKER}.fetch_commits_page", side_effect=cycle2):
        total2 = sync_commits(None, commits_db, "acme/widgets", _cfg(commit_pages_per_cycle=40))

    assert total2 == 50
    assert len(seen_until) == 1  # short page on page 1 -> no further pages requested
    state = commits_db.get_branch_state("acme/widgets", "main")
    assert state["backfill_done"] is True
    assert state["last_committed_at"] == _ts(0)  # cycle-1 high-water mark preserved


def test_incremental_uses_since_ten_minutes_before_last_committed_at(commits_db):
    commits_db.upsert_branch_state(
        "acme/widgets", "main", backfill_done=1, backfill_until=None,
        last_committed_at="2026-03-01T12:00:00Z", error=None,
    )
    seen = {}

    def fake(owner, repo, branch, page, since=None, until=None, per_page=100):
        seen["since"] = since
        if page == 1:
            return [_row("newsha", "2026-03-01T13:00:00Z")]
        return []

    with patch(f"{WORKER}.fetch_commits_page", side_effect=fake):
        total = sync_commits(None, commits_db, "acme/widgets", _cfg())

    assert total == 1
    assert seen["since"] == "2026-03-01T11:50:00Z"  # 10 min slack
    state = commits_db.get_branch_state("acme/widgets", "main")
    assert state["last_committed_at"] == "2026-03-01T13:00:00Z"


def test_incremental_cap_hit_without_short_page_logs_warning(commits_db, caplog):
    """Important #3: a backlog bigger than pages_cap*100 exits by exhausting
    the page budget, not a short page. last_committed_at still advances (the
    brief's single since-based walk design), but the gap must be observable."""
    commits_db.upsert_branch_state(
        "acme/widgets", "main", backfill_done=1, backfill_until=None,
        last_committed_at=_ts(50), error=None,
    )
    full_page = _rows(100, 0)  # always a full page -> cap is hit, never a short page

    with patch(f"{WORKER}.fetch_commits_page", return_value=full_page), \
         caplog.at_level(logging.WARNING):
        total = sync_commits(None, commits_db, "acme/widgets", _cfg(commit_pages_per_cycle=2))

    assert total == 200
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("acme/widgets" in m and "main" in m and "2" in m for m in warnings)
    state = commits_db.get_branch_state("acme/widgets", "main")
    assert state["last_committed_at"] == _ts(0)  # still advances per the brief's design


def test_null_author_login_rows_still_stored(commits_db):
    row = _row("shanull", _ts(5), login=None, name="Bot Person", email="bot@x.com")
    with patch(f"{WORKER}.fetch_commits_page", side_effect=[[row], []]):
        sync_commits(None, commits_db, "acme/widgets", _cfg())
    rows = commits_db.get_rollup_rows("acme/widgets")
    assert any(r["login"] == "Bot Person" for r in rows)  # falls back to name


def test_sha_upsert_idempotent_across_overlapping_pages(commits_db):
    page1 = _rows(100, 0)
    overlap_row = page1[-1]           # duplicate boundary row (same sha as page1's last)
    new_row = _row("sha100", _ts(100))
    page2 = [overlap_row, new_row]    # short page -> completes

    with patch(f"{WORKER}.fetch_commits_page", side_effect=[page1, page2]):
        total = sync_commits(None, commits_db, "acme/widgets", _cfg())

    assert total == 102                                    # rows processed, dup included
    assert commits_db.count("acme/widgets", "main") == 101  # sha is unique -> dedup


def test_per_branch_isolation(commits_db):
    def fake(owner, repo, branch, page, since=None, until=None, per_page=100):
        if branch == "main":
            return [_row("m1", _ts(1))] if page == 1 else []
        return [_row("d1", _ts(2))] if page == 1 else []

    with patch(f"{WORKER}.fetch_commits_page", side_effect=fake):
        total = sync_commits(None, commits_db, "acme/widgets", _cfg(commit_branches=["main", "dev"]))

    assert total == 2
    assert commits_db.count("acme/widgets", "main") == 1
    assert commits_db.count("acme/widgets", "dev") == 1


def test_error_on_one_branch_does_not_block_the_other(commits_db):
    def fake(owner, repo, branch, page, since=None, until=None, per_page=100):
        if branch == "main":
            raise RuntimeError("gh api failed")
        return [_row("d1", _ts(2))] if page == 1 else []

    with patch(f"{WORKER}.fetch_commits_page", side_effect=fake):
        total = sync_commits(None, commits_db, "acme/widgets", _cfg(commit_branches=["main", "dev"]))

    assert total == 1
    main_state = commits_db.get_branch_state("acme/widgets", "main")
    assert "gh api failed" in main_state["error"]
    dev_state = commits_db.get_branch_state("acme/widgets", "dev")
    assert dev_state["error"] is None


def test_empty_first_page_completes_backfill_with_zero_commits(commits_db):
    with patch(f"{WORKER}.fetch_commits_page", return_value=[]):
        total = sync_commits(None, commits_db, "acme/widgets", _cfg())
    assert total == 0
    state = commits_db.get_branch_state("acme/widgets", "main")
    assert state["backfill_done"] is True
