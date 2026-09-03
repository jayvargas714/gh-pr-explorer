"""Tests for AutoVerdictArmingDB — the per-PR arming store decoupled from merge_queue."""

import json

import pytest

from backend.database.auto_verdict_arming import AutoVerdictArmingDB
from backend.database.base import Database

REPO = "owner/repo"


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "arming.db")


@pytest.fixture
def arming(db):
    return AutoVerdictArmingDB(db)


def test_get_returns_none_for_unknown_pr(arming):
    assert arming.get(REPO, 1) is None


def test_set_arming_inserts_and_returns_row(arming):
    row = arming.set_arming(REPO, 1, True, "ed", "comment")
    assert row["repo"] == REPO
    assert row["pr_number"] == 1
    assert row["auto_verdict_enabled"] == 1
    assert row["auto_verdict_reviewer"] == "ed"
    assert row["auto_verdict_mode"] == "comment"
    assert row["auto_verdict_criteria"] is None
    assert arming.get(REPO, 1) == row


def test_set_arming_upserts_existing_row(arming):
    arming.set_arming(REPO, 1, True, "ed", "comment")
    row = arming.set_arming(REPO, 1, True, "pb", "verdict")
    assert row["auto_verdict_reviewer"] == "pb"
    assert row["auto_verdict_mode"] == "verdict"
    assert len(arming.get_armed()) == 1


def test_disarming_keeps_the_row_and_its_criteria(arming):
    arming.set_criteria(REPO, 1, {"maxCritical": 3})
    arming.set_arming(REPO, 1, True, "default", "verdict")
    row = arming.set_arming(REPO, 1, False, "default", "verdict")
    assert row["auto_verdict_enabled"] == 0
    assert json.loads(row["auto_verdict_criteria"]) == {"maxCritical": 3}
    assert arming.get(REPO, 1) is not None


def test_set_criteria_creates_row_without_arming(arming):
    row = arming.set_criteria(REPO, 2, {"maxCritical": 1})
    assert row["auto_verdict_enabled"] == 0
    assert json.loads(row["auto_verdict_criteria"]) == {"maxCritical": 1}
    assert arming.get_armed() == []


def test_set_criteria_none_clears_override(arming):
    arming.set_criteria(REPO, 2, {"maxCritical": 1})
    row = arming.set_criteria(REPO, 2, None)
    assert row["auto_verdict_criteria"] is None


def test_get_armed_returns_only_enabled_rows(arming):
    arming.set_arming(REPO, 1, True, "default", "verdict")
    arming.set_arming(REPO, 2, False, "default", "verdict")
    arming.set_arming("other/repo", 3, True, "pb", "comment")
    armed = {(r["repo"], r["pr_number"]) for r in arming.get_armed()}
    assert armed == {(REPO, 1), ("other/repo", 3)}


def test_get_for_prs_batches_by_pair(arming):
    arming.set_arming(REPO, 1, True, "default", "verdict")
    arming.set_arming(REPO, 2, False, "default", "verdict")
    result = arming.get_for_prs([(REPO, 1), (REPO, 2), (REPO, 3), ("other/repo", 1)])
    assert set(result) == {(REPO, 1), (REPO, 2)}
    assert result[(REPO, 1)]["auto_verdict_enabled"] == 1
    assert arming.get_for_prs([]) == {}


def test_get_for_prs_handles_large_batches(arming):
    for n in range(1, 901):
        arming.set_arming(REPO, n, True, "default", "verdict")
    result = arming.get_for_prs([(REPO, n) for n in range(1, 901)])
    assert len(result) == 900


def test_clear_deletes_row(arming):
    arming.set_arming(REPO, 1, True, "default", "verdict")
    assert arming.clear(REPO, 1) is True
    assert arming.get(REPO, 1) is None
    assert arming.clear(REPO, 1) is False


# ----- Migration: copy arming off merge_queue -----


def _legacy_queue_row(db, pr_number, enabled, criteria=None, reviewer=None, mode=None):
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO merge_queue (pr_number, repo, position, auto_verdict_enabled, "
            "auto_verdict_reviewer, auto_verdict_mode, auto_verdict_criteria) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pr_number, REPO, pr_number, 1 if enabled else 0, reviewer, mode,
             json.dumps(criteria) if criteria is not None else None),
        )


def test_migration_copies_armed_and_overridden_queue_rows(tmp_path):
    path = tmp_path / "legacy.db"
    db = Database(path)
    _legacy_queue_row(db, 1, True, reviewer="ed", mode="comment")
    _legacy_queue_row(db, 2, False, criteria={"maxCritical": 5})
    _legacy_queue_row(db, 3, False)  # neither armed nor overridden: not copied
    # Pretend this DB predates the migration, then re-open it.
    with db.connection() as conn:
        conn.execute("DELETE FROM migrations WHERE name = 'copy_arming_from_merge_queue'")

    reopened = Database(path)
    arming = AutoVerdictArmingDB(reopened)

    armed = arming.get(REPO, 1)
    assert armed["auto_verdict_enabled"] == 1
    assert armed["auto_verdict_reviewer"] == "ed"
    assert armed["auto_verdict_mode"] == "comment"
    overridden = arming.get(REPO, 2)
    assert overridden["auto_verdict_enabled"] == 0
    assert json.loads(overridden["auto_verdict_criteria"]) == {"maxCritical": 5}
    assert arming.get(REPO, 3) is None
    assert reopened.is_migration_done("copy_arming_from_merge_queue")


def test_migration_runs_once_and_never_overwrites_new_rows(tmp_path):
    path = tmp_path / "legacy_once.db"
    db = Database(path)
    _legacy_queue_row(db, 1, True, reviewer="ed", mode="comment")
    AutoVerdictArmingDB(db).set_arming(REPO, 1, False, "pb", "verdict")

    # Migration already marked done at first init: the queue row is not re-copied.
    reopened = AutoVerdictArmingDB(Database(path))
    row = reopened.get(REPO, 1)
    assert row["auto_verdict_enabled"] == 0
    assert row["auto_verdict_reviewer"] == "pb"
