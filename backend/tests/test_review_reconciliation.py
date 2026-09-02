"""Tests for startup reconciliation of orphaned review runs.

A service restart kills in-flight Claude CLI reviews and wipes the in-memory
registry. Reconciliation closes each lost run with a cancelled event (reason "orphaned")
and restarts it: auto-dispatched PRs via a dispatch-row requeue, manual runs
via begin_review. Everything gh/process-touching is stubbed.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend.database.base import Database
from backend.database.automation_dispatches import AutomationDispatchesDB
from backend.database.review_events import ReviewEventsDB
from backend.database.reviews import ReviewsDB
from backend.services import review_reconciliation as recon

REPO = "owner/repo"


class Harness:
    def __init__(self, db):
        self.events = ReviewEventsDB(db)
        self.reviews = ReviewsDB(db)
        self.dispatches = AutomationDispatchesDB(db)
        self.pr_states = {}       # pr_number -> state (default OPEN)
        self.killed = []
        self.restarted = []
        self.begin_result = ({"message": "Review started"}, 201)

    def fetch_pr_state(self, owner, repo, pr_number):
        return self.pr_states.get(pr_number, "OPEN")

    def kill_if_alive(self, pid):
        self.killed.append(pid)

    def begin_review(self, owner, repo, pr_number, pr_url, reviews_db, **kwargs):
        self.restarted.append({"key": f"{owner}/{repo}/{pr_number}", "pr_url": pr_url, **kwargs})
        return self.begin_result


@pytest.fixture
def h(tmp_path, monkeypatch):
    db = Database(tmp_path / "reconciliation_test.db")
    harness = Harness(db)
    import backend.database as db_pkg
    monkeypatch.setattr(db_pkg, "get_review_events_db", lambda: harness.events)
    monkeypatch.setattr(db_pkg, "get_reviews_db", lambda: harness.reviews)
    monkeypatch.setattr(db_pkg, "get_automation_dispatches_db", lambda: harness.dispatches)
    # The recorder module resolves its own DB getter.
    from backend.services import review_event_log as rel
    monkeypatch.setattr(rel, "get_review_events_db", lambda: harness.events)
    monkeypatch.setattr("backend.services.github_service.fetch_pr_state", harness.fetch_pr_state)
    monkeypatch.setattr("backend.services.review_service.begin_review", harness.begin_review)
    monkeypatch.setattr(recon, "_kill_if_alive", harness.kill_if_alive)
    return harness


def orphan(h, pr_number, run_id, *, reviewer="default", is_followup=False,
           auto_started=False, pid=999999):
    h.events.log_event("started", REPO, pr_number, run_id, attempt=1, pid=pid,
                       reviewer_agent=reviewer, is_followup=is_followup,
                       auto_started=auto_started)


def orphan_events(h, pr_number):
    events, _ = h.events.list_events(repo=REPO, pr_number=pr_number, event="cancelled")
    return [e for e in events if e["reason"] == "orphaned"]


def test_orphaned_auto_run_is_closed_and_dispatch_requeued(h):
    orphan(h, 7, "run-1", auto_started=True, pid=4242)
    h.dispatches.record_candidate(REPO, 7)
    h.dispatches.set_status(h.dispatches.get_by_pr(REPO, 7)["id"], "dispatched",
                            reviewer_key="pb")

    summary = recon.reconcile_orphaned_reviews()

    assert h.killed == [4242]
    closed = orphan_events(h, 7)
    assert len(closed) == 1
    assert closed[0]["run_id"] == "run-1"

    row = h.dispatches.get_by_pr(REPO, 7)
    assert row["status"] == "pending"
    assert "restart" in row["detail"]
    assert h.restarted == []  # the dispatch worker owns the restart
    assert summary["requeued"] == 1


def test_orphaned_manual_run_is_restarted_directly(h):
    orphan(h, 8, "run-2", reviewer="ed", is_followup=True)

    summary = recon.reconcile_orphaned_reviews()

    assert len(orphan_events(h, 8)) == 1
    assert len(h.restarted) == 1
    start = h.restarted[0]
    assert start["key"] == f"{REPO}/8"
    assert start["pr_url"] == f"https://github.com/{REPO}/pull/8"
    assert start["reviewer_type"] == "ed"
    assert start["is_followup"] is True
    assert start["auto_started"] is False
    assert summary["restarted"] == 1


def test_orphaned_auto_run_without_dispatch_row_gets_a_pending_row(h):
    """An auto orphan the pipeline never tracked (e.g. a watcher follow-up)
    still goes back through the dispatch worker, never a direct restart —
    direct restarts here spawned unbounded bursts after a service crash."""
    orphan(h, 17, "run-17", auto_started=True, is_followup=True)

    summary = recon.reconcile_orphaned_reviews()

    row = h.dispatches.get_by_pr(REPO, 17)
    assert row is not None
    assert row["status"] == "pending"
    assert h.restarted == []
    assert summary["requeued"] == 1


def test_orphaned_auto_run_with_terminal_dispatch_row_is_requeued(h):
    orphan(h, 18, "run-18", auto_started=True)
    h.dispatches.record_candidate(REPO, 18)
    h.dispatches.set_status(h.dispatches.get_by_pr(REPO, 18)["id"], "skipped",
                            detail="review already in progress")

    summary = recon.reconcile_orphaned_reviews()

    row = h.dispatches.get_by_pr(REPO, 18)
    assert row["status"] == "pending"
    assert h.restarted == []
    assert summary["requeued"] == 1


def test_orphan_with_newer_completed_review_is_not_restarted(h):
    orphan(h, 9, "run-3")
    # A follow-up watcher already recovered this PR after the restart.
    h.reviews.save_review(pr_number=9, repo=REPO, status="completed", content_json="{}")

    summary = recon.reconcile_orphaned_reviews()

    assert len(orphan_events(h, 9)) == 1
    assert h.restarted == []
    assert summary["restarted"] == 0
    assert summary["already_recovered"] == 1


def test_orphan_on_closed_pr_is_not_restarted(h):
    orphan(h, 10, "run-4")
    h.pr_states[10] = "MERGED"

    summary = recon.reconcile_orphaned_reviews()

    assert len(orphan_events(h, 10)) == 1
    assert h.restarted == []
    assert summary["pr_closed"] == 1


def test_no_orphans_is_a_quiet_noop(h):
    h.events.log_event("started", REPO, 11, "run-5", attempt=1)
    h.events.log_event("completed", REPO, 11, "run-5", attempt=1, review_id=1)

    summary = recon.reconcile_orphaned_reviews()

    assert summary["orphans"] == 0
    assert h.restarted == []


def test_second_run_is_idempotent(h):
    """The recorded cancelled event makes the run terminal, so a second
    reconciliation (e.g. the next restart) finds nothing."""
    orphan(h, 12, "run-6", auto_started=True)
    h.dispatches.record_candidate(REPO, 12)
    h.dispatches.set_status(h.dispatches.get_by_pr(REPO, 12)["id"], "dispatched")

    recon.reconcile_orphaned_reviews()
    summary = recon.reconcile_orphaned_reviews()

    assert summary["orphans"] == 0
    assert len(orphan_events(h, 12)) == 1


def test_reconciliation_never_raises(h, monkeypatch):
    orphan(h, 13, "run-7")
    monkeypatch.setattr("backend.services.github_service.fetch_pr_state",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("gh down")))

    recon.reconcile_orphaned_reviews()  # must not raise


# --- PR status comments -------------------------------------------------------

@pytest.fixture
def requeued_comments(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "backend.services.pr_status_comments.post_review_orphaned_requeued_comment",
        lambda owner, repo, pr_number: calls.append(f"{owner}/{repo}/{pr_number}"),
    )
    return calls


def test_requeued_orphan_is_announced_on_the_pr(h, requeued_comments):
    orphan(h, 7, "run-1", auto_started=True)
    h.dispatches.record_candidate(REPO, 7)

    recon.reconcile_orphaned_reviews()

    assert requeued_comments == [f"{REPO}/7"]


def test_fresh_requeue_row_is_marked_so_enrollment_stays_silent(h, requeued_comments):
    """The dispatch worker announces enrollment for detail-less rows; a row
    created by reconciliation must carry the requeue detail instead."""
    orphan(h, 17, "run-17", auto_started=True)

    recon.reconcile_orphaned_reviews()

    row = h.dispatches.get_by_pr(REPO, 17)
    assert "restart" in (row["detail"] or "")
    assert requeued_comments == [f"{REPO}/17"]


def test_manual_restart_carries_the_restart_note(h, requeued_comments):
    orphan(h, 8, "run-2")

    recon.reconcile_orphaned_reviews()

    assert "service restart" in h.restarted[0]["comment_note"]
    assert requeued_comments == []
