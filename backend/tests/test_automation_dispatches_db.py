"""Tests for AutomationDispatchesDB — the durable dispatch/idempotence ledger."""

import json

import pytest

from backend.database.base import Database
from backend.database.automation_dispatches import AutomationDispatchesDB

REPO = "owner/repo"


@pytest.fixture
def dispatches(tmp_path):
    return AutomationDispatchesDB(Database(tmp_path / "dispatches_test.db"))


def test_record_candidate_inserts_pending_row(dispatches):
    assert dispatches.record_candidate(REPO, 1) is True
    row = dispatches.get_by_pr(REPO, 1)
    assert row["status"] == "pending"
    assert row["attempts"] == 0


def test_record_candidate_is_idempotent(dispatches):
    assert dispatches.record_candidate(REPO, 1) is True
    assert dispatches.record_candidate(REPO, 1) is False
    assert len(dispatches.get_pending(10)) == 1


def _set_updated_at(dispatches, pr_number, offset):
    with dispatches.db.connection() as conn:
        conn.execute(
            "UPDATE automation_dispatches SET updated_at = datetime('now', ?) "
            "WHERE repo = ? AND pr_number = ?",
            (offset, REPO, pr_number),
        )


def test_get_pending_returns_oldest_first_and_respects_limit(dispatches):
    for n in (1, 2, 3):
        dispatches.record_candidate(REPO, n)
    pending = dispatches.get_pending(2)
    assert [r["pr_number"] for r in pending] == [1, 2]


def test_get_pending_round_robins_by_last_evaluation(dispatches):
    """Least-recently-evaluated rows come first, so perpetual waiters can't
    starve rows behind them once evaluation bumps updated_at."""
    for n in (1, 2, 3):
        dispatches.record_candidate(REPO, n)
    _set_updated_at(dispatches, 2, "-2 hours")
    _set_updated_at(dispatches, 3, "-1 hours")

    assert [r["pr_number"] for r in dispatches.get_pending(3)] == [2, 3, 1]

    # Evaluating row 2 (set_status bumps updated_at) sends it to the back.
    row2 = dispatches.get_by_pr(REPO, 2)
    dispatches.set_status(row2["id"], "pending", detail="waiting: CI pending")
    assert [r["pr_number"] for r in dispatches.get_pending(3)] == [3, 1, 2]


def test_count_pending(dispatches):
    for n in (1, 2, 3):
        dispatches.record_candidate(REPO, n)
    row = dispatches.get_by_pr(REPO, 3)
    dispatches.set_status(row["id"], "dispatched")
    assert dispatches.count_pending() == 2


def test_reset_attempts(dispatches):
    dispatches.record_candidate(REPO, 1)
    row = dispatches.get_by_pr(REPO, 1)
    dispatches.increment_attempts(row["id"])
    dispatches.increment_attempts(row["id"])
    dispatches.reset_attempts(row["id"])
    assert dispatches.get_by_pr(REPO, 1)["attempts"] == 0


def test_requeue_repends_row_and_clears_attempts_and_detail(dispatches):
    dispatches.record_candidate(REPO, 1)
    row = dispatches.get_by_pr(REPO, 1)
    dispatches.increment_attempts(row["id"])
    dispatches.set_status(row["id"], "failed", detail="metadata fetch failed")

    dispatches.requeue(row["id"], detail="revived by backfill")

    updated = dispatches.get_by_pr(REPO, 1)
    assert updated["status"] == "pending"
    assert updated["attempts"] == 0
    assert updated["detail"] == "revived by backfill"


def test_list_dispatches_filters_by_status_newest_first(dispatches):
    for n in (1, 2, 3):
        dispatches.record_candidate(REPO, n)
    row3 = dispatches.get_by_pr(REPO, 3)
    dispatches.set_status(row3["id"], "dispatched", reviewer_key="pb")
    _set_updated_at(dispatches, 1, "-2 hours")
    _set_updated_at(dispatches, 2, "-1 hours")

    rows = dispatches.list_dispatches(statuses=["pending"], limit=10)
    assert [r["pr_number"] for r in rows] == [2, 1]

    everything = dispatches.list_dispatches(limit=10)
    assert len(everything) == 3
    assert everything[0]["pr_number"] == 3

    assert len(dispatches.list_dispatches(limit=2)) == 2


def test_set_status_transitions_and_stores_outcome(dispatches):
    dispatches.record_candidate(REPO, 1)
    row = dispatches.get_by_pr(REPO, 1)
    dispatches.set_status(row["id"], "unidentified",
                          outcome_json=json.dumps({"matched_rules": ["PB", "ED"]}),
                          detail="files span rules")
    updated = dispatches.get_by_pr(REPO, 1)
    assert updated["status"] == "unidentified"
    assert json.loads(updated["outcome_json"])["matched_rules"] == ["PB", "ED"]
    assert updated["detail"] == "files span rules"
    assert dispatches.get_pending(10) == []


def test_set_status_records_reviewer_key(dispatches):
    dispatches.record_candidate(REPO, 1)
    row = dispatches.get_by_pr(REPO, 1)
    dispatches.set_status(row["id"], "dispatched", reviewer_key="pb")
    assert dispatches.get_by_pr(REPO, 1)["reviewer_key"] == "pb"


def test_set_status_rejects_unknown_status(dispatches):
    dispatches.record_candidate(REPO, 1)
    row = dispatches.get_by_pr(REPO, 1)
    with pytest.raises(ValueError):
        dispatches.set_status(row["id"], "exploded")


def test_increment_attempts(dispatches):
    dispatches.record_candidate(REPO, 1)
    row = dispatches.get_by_pr(REPO, 1)
    assert dispatches.increment_attempts(row["id"]) == 1
    assert dispatches.increment_attempts(row["id"]) == 2
    assert dispatches.get_by_pr(REPO, 1)["attempts"] == 2


def test_get_for_prs_batch_lookup(dispatches):
    dispatches.record_candidate(REPO, 1)
    dispatches.record_candidate("other/repo", 2)
    rows = dispatches.get_for_prs([(REPO, 1), ("other/repo", 2), (REPO, 99)])
    assert set(rows.keys()) == {(REPO, 1), ("other/repo", 2)}
