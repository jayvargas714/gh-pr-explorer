"""Sync worker's commits-behind stage, with gh fully mocked."""
from unittest.mock import patch

import pytest

from backend.database.base import Database
from backend.database.synced_commits import SyncedCommitsDB
from backend.database.synced_prs import SyncedPRsDB
from backend.services.pr_sync_worker import sync_behind_counts, sync_cycle

WORKER = "backend.services.pr_sync_worker"
REPO = "acme/widgets"


@pytest.fixture
def store(tmp_path):
    return SyncedPRsDB(Database(tmp_path / "test.db"))


def _pr(number, head="h", base="main", state="OPEN"):
    return {
        "number": number, "title": f"PR {number}", "state": state, "isDraft": False,
        "author": {"login": "alice"}, "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-02T00:00:00Z", "closedAt": None, "mergedAt": None,
        "headRefOid": f"{head}{number}", "baseRefName": base,
    }


def _run(store, base_shas, behind, cfg=None):
    """Run the stage with base-head and compare lookups served from dicts
    (a value that is an Exception is raised). Returns the compare calls."""
    compares = []

    def fake_base(owner, repo, ref):
        value = base_shas[ref]
        if isinstance(value, Exception):
            raise value
        return value

    def fake_compare(owner, repo, base_sha, head_sha):
        compares.append((base_sha, head_sha))
        value = behind[head_sha]
        if isinstance(value, Exception):
            raise value
        return value

    with patch(f"{WORKER}.fetch_branch_head_sha", side_effect=fake_base), \
         patch(f"{WORKER}.fetch_pr_behind_by", side_effect=fake_compare):
        computed = sync_behind_counts(store, REPO, cfg or {"behind_per_cycle": 40})
    return computed, compares


def test_computes_for_open_prs_only(store):
    store.upsert_pr(REPO, _pr(1))
    store.upsert_pr(REPO, _pr(2, state="MERGED"))
    computed, compares = _run(store, {"main": "B1"}, {"h1": 3})
    assert computed == 1
    assert compares == [("B1", "h1")]
    assert store.get_behind_state(REPO)[1] == {
        "behind_by": 3, "behind_base_sha": "B1", "behind_head_sha": "h1",
    }


def test_skips_prs_whose_sha_pair_is_unchanged(store):
    store.upsert_pr(REPO, _pr(1))
    _run(store, {"main": "B1"}, {"h1": 3})
    computed, compares = _run(store, {"main": "B1"}, {"h1": 99})
    assert computed == 0
    assert compares == []
    assert store.get_behind_by(REPO, 1) == 3


def test_recomputes_when_base_moves(store):
    store.upsert_pr(REPO, _pr(1))
    _run(store, {"main": "B1"}, {"h1": 3})
    computed, compares = _run(store, {"main": "B2"}, {"h1": 4})
    assert compares == [("B2", "h1")]
    assert store.get_behind_by(REPO, 1) == 4


def test_recomputes_when_head_moves(store):
    store.upsert_pr(REPO, _pr(1))
    _run(store, {"main": "B1"}, {"h1": 3})
    store.upsert_pr(REPO, _pr(1, head="new"))
    computed, compares = _run(store, {"main": "B1"}, {"new1": 0})
    assert compares == [("B1", "new1")]
    assert store.get_behind_by(REPO, 1) == 0


def test_honours_per_cycle_cap_and_finishes_later(store):
    for n in (1, 2, 3):
        store.upsert_pr(REPO, _pr(n))
    behind = {"h1": 1, "h2": 2, "h3": 3}
    computed, compares = _run(store, {"main": "B"}, behind, {"behind_per_cycle": 2})
    assert computed == 2
    assert [h for _, h in compares] == ["h1", "h2"]
    computed, compares = _run(store, {"main": "B"}, behind, {"behind_per_cycle": 2})
    assert [h for _, h in compares] == ["h3"]
    assert store.get_behind_by(REPO, 3) == 3


def test_base_lookup_failure_skips_only_that_base(store):
    store.upsert_pr(REPO, _pr(1, base="main"))
    store.upsert_pr(REPO, _pr(2, base="release"))
    computed, compares = _run(
        store, {"main": RuntimeError("boom"), "release": "R1"}, {"h2": 5},
    )
    assert compares == [("R1", "h2")]
    assert store.get_behind_by(REPO, 1) is None
    assert store.get_behind_by(REPO, 2) == 5


def test_one_compare_failure_does_not_block_others(store):
    store.upsert_pr(REPO, _pr(1))
    store.upsert_pr(REPO, _pr(2))
    computed, _ = _run(store, {"main": "B"}, {"h1": RuntimeError("404"), "h2": 7})
    assert computed == 1
    assert store.get_behind_by(REPO, 1) is None
    assert store.get_behind_by(REPO, 2) == 7


def test_rate_limit_stops_the_stage(store):
    from backend.services.github_service import RateLimitError
    for n in (1, 2, 3):
        store.upsert_pr(REPO, _pr(n))
    computed, compares = _run(
        store, {"main": "B"}, {"h1": 1, "h2": RateLimitError("rate limit"), "h3": 3},
    )
    assert computed == 1
    assert [h for _, h in compares] == ["h1", "h2"]  # h3 never attempted
    assert store.get_behind_by(REPO, 3) is None


def test_prs_missing_shas_or_base_make_no_gh_calls(store):
    pr = _pr(1)
    del pr["headRefOid"]
    store.upsert_pr(REPO, pr)
    pr2 = _pr(2)
    del pr2["baseRefName"]
    store.upsert_pr(REPO, pr2)
    with patch(f"{WORKER}.fetch_branch_head_sha") as base, \
         patch(f"{WORKER}.fetch_pr_behind_by") as compare:
        assert sync_behind_counts(store, REPO, {"behind_per_cycle": 40}) == 0
    base.assert_not_called()
    compare.assert_not_called()


def test_sync_cycle_runs_behind_stage_after_history(store, tmp_path):
    store.register_repo(REPO)
    store.mark_backfill_done(REPO)
    store.update_last_synced(REPO)
    cfg = {
        "enabled": True, "poll_interval_seconds": 120, "history_days": 180,
        "max_synced_repos": 10, "exclude_repos": [], "retain_days": 0,
        "commit_branches": [], "behind_per_cycle": 40,
    }
    order = []
    with patch(f"{WORKER}.incremental_sync_repo", side_effect=lambda *a, **k: order.append("incremental") or 0), \
         patch(f"{WORKER}.history_backfill_slice", side_effect=lambda s, r, c: order.append("history") or 0), \
         patch(f"{WORKER}.sync_behind_counts", side_effect=lambda s, r, c: order.append("behind") or 0), \
         patch(f"{WORKER}.sync_commits", side_effect=lambda s, cdb, r, c: order.append("commits") or 0), \
         patch(f"{WORKER}.analytics_rollup.needs_rebuild", return_value=False):
        sync_cycle(store=store, cfg=cfg, commits_db=SyncedCommitsDB(Database(tmp_path / "c.db")))
    assert order == ["incremental", "history", "behind", "commits"]


def test_sync_cycle_isolates_behind_stage_failure(store, tmp_path):
    store.register_repo(REPO)
    store.mark_backfill_done(REPO)
    store.update_last_synced(REPO)
    cfg = {
        "enabled": True, "poll_interval_seconds": 120, "history_days": 180,
        "max_synced_repos": 10, "exclude_repos": [], "retain_days": 0,
        "commit_branches": [], "behind_per_cycle": 40,
    }
    order = []

    def boom(*args):
        raise ValueError("unexpected")

    with patch(f"{WORKER}.incremental_sync_repo", return_value=0), \
         patch(f"{WORKER}.history_backfill_slice", return_value=0), \
         patch(f"{WORKER}.sync_behind_counts", side_effect=boom), \
         patch(f"{WORKER}.sync_commits", side_effect=lambda s, cdb, r, c: order.append("commits") or 0), \
         patch(f"{WORKER}.analytics_rollup.needs_rebuild", return_value=False):
        sync_cycle(store=store, cfg=cfg, commits_db=SyncedCommitsDB(Database(tmp_path / "c.db")))
    assert order == ["commits"]
