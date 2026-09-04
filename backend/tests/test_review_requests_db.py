"""Tests for ReviewRequestsDB — the review-request follow-up demand ledger."""

import pytest

from backend.database.base import Database
from backend.database.review_requests import ReviewRequestsDB

REPO = "owner/repo"


@pytest.fixture
def requests(tmp_path):
    return ReviewRequestsDB(Database(tmp_path / "review_requests_test.db"))


def _age(requests, pr_number, offset):
    with requests.db.connection() as conn:
        conn.execute(
            "UPDATE review_requests SET requested_at = datetime('now', ?), "
            "updated_at = datetime('now', ?) WHERE repo = ? AND pr_number = ?",
            (offset, offset, REPO, pr_number),
        )


def test_record_inserts_pending_row(requests):
    assert requests.record(REPO, 1) is True
    row = requests.get_by_pr(REPO, 1)
    assert row["status"] == "pending"
    assert row["attempts"] == 0
    assert row["requested_at"] is not None


def test_record_is_noop_while_pending(requests):
    requests.record(REPO, 1)
    _age(requests, 1, "-3 hours")
    before = requests.get_by_pr(REPO, 1)

    assert requests.record(REPO, 1) is False

    after = requests.get_by_pr(REPO, 1)
    assert after["requested_at"] == before["requested_at"]
    assert requests.count_pending() == 1


@pytest.mark.parametrize("terminal", ["fulfilled", "skipped", "failed"])
def test_record_revives_terminal_row_with_fresh_clock(requests, terminal):
    requests.record(REPO, 1)
    row = requests.get_by_pr(REPO, 1)
    requests.set_status(row["id"], terminal, detail="done")
    requests.increment_attempts(row["id"])
    _age(requests, 1, "-3 hours")
    old = requests.get_by_pr(REPO, 1)

    assert requests.record(REPO, 1) is True

    fresh = requests.get_by_pr(REPO, 1)
    assert fresh["status"] == "pending"
    assert fresh["attempts"] == 0
    assert fresh["detail"] is None
    assert fresh["requested_at"] > old["requested_at"]
    assert fresh["id"] == old["id"]  # one row per PR, ever


def test_get_pending_orders_least_recently_evaluated_first(requests):
    for n in (1, 2, 3):
        requests.record(REPO, n)
    _age(requests, 2, "-2 hours")
    _age(requests, 3, "-1 hours")

    assert [r["pr_number"] for r in requests.get_pending(3)] == [2, 3, 1]

    row2 = requests.get_by_pr(REPO, 2)
    requests.set_status(row2["id"], "pending", detail="waiting: CI pending")
    assert [r["pr_number"] for r in requests.get_pending(3)] == [3, 1, 2]
    assert len(requests.get_pending(2)) == 2


def test_set_status_rejects_unknown_status(requests):
    requests.record(REPO, 1)
    row = requests.get_by_pr(REPO, 1)
    with pytest.raises(ValueError):
        requests.set_status(row["id"], "bogus")


def test_set_status_keeps_detail_when_not_given(requests):
    requests.record(REPO, 1)
    row = requests.get_by_pr(REPO, 1)
    requests.set_status(row["id"], "pending", detail="waiting: draft")
    requests.set_status(row["id"], "fulfilled")
    fresh = requests.get_by_pr(REPO, 1)
    assert fresh["detail"] == "waiting: draft"


def test_attempt_counters(requests):
    requests.record(REPO, 1)
    row = requests.get_by_pr(REPO, 1)
    assert requests.increment_attempts(row["id"]) == 1
    assert requests.increment_attempts(row["id"]) == 2
    requests.reset_attempts(row["id"])
    assert requests.get_by_pr(REPO, 1)["attempts"] == 0


def test_get_for_prs_batch_lookup(requests):
    requests.record(REPO, 1)
    requests.record(REPO, 3)
    result = requests.get_for_prs([(REPO, 1), (REPO, 2), (REPO, 3)])
    assert set(result) == {(REPO, 1), (REPO, 3)}
    assert requests.get_for_prs([]) == {}
