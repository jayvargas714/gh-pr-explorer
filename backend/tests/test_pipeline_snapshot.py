"""Tests for the pipeline snapshot: stage derivation, the batched row builder,
the in-memory snapshot + version short-circuit, and the pipeline routes.

Every gh-touching path is patched to raise, so a passing suite proves the
pipeline view is served from the database alone.
"""

import json
from unittest.mock import patch

import pytest

import backend.database as db_pkg
from backend import create_app
from backend.database.audits import AuditsDB
from backend.database.auto_verdict_arming import AutoVerdictArmingDB
from backend.database.auto_verdicts import AutoVerdictsDB
from backend.database.automation_dispatches import AutomationDispatchesDB
from backend.database.review_requests import ReviewRequestsDB
from backend.database.base import Database
from backend.database.merge_queue import MergeQueueDB
from backend.database.reviews import ReviewsDB
from backend.database.swimlanes import SwimlanesDB
from backend.database.synced_prs import SyncedPRsDB
from backend.services import pipeline_snapshot as ps
from backend.services.pipeline_snapshot import PipelineSnapshot, build_rows, derive_stage

REPO = "acme/widgets"

# The PipelineRow contract (spec §5.2 + headSha/hasNewCommits), in emit order.
ROW_KEYS = [
    "key", "repo", "prNumber", "title", "author", "url", "prState", "isDraft",
    "baseRefName", "additions", "deletions", "prUpdatedAt", "prSyncedAt", "headSha",
    "stage", "dispatch", "automation", "autoVerdict", "reviewDecision",
    "currentReviewers", "ciStatus", "statusCheckRollup", "running", "review",
    "hasNewCommits", "revLog", "rounds", "onBoard", "queueItemId", "notesCount",
    "reviewRequest", "reviewRequestedFromMe",
]


def _gh_forbidden(*args, **kwargs):
    raise AssertionError(f"run_gh_command must not be called by the pipeline view: {args}")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """One temp DB behind every singleton getter, a fresh snapshot, and gh sealed off."""
    db = Database(tmp_path / "pipeline_snapshot_test.db")
    stores = {
        "db": db,
        "dispatches": AutomationDispatchesDB(db),
        "synced": SyncedPRsDB(db),
        "reviews": ReviewsDB(db),
        "audits": AuditsDB(db),
        "verdicts": AutoVerdictsDB(db),
        "arming": AutoVerdictArmingDB(db),
        "queue": MergeQueueDB(db),
        "swimlanes": SwimlanesDB(db),
        "requests": ReviewRequestsDB(db),
    }
    stores["swimlanes"].ensure_default_lane()
    for name, getter in (
        ("dispatches", "get_automation_dispatches_db"), ("synced", "get_synced_prs_db"),
        ("reviews", "get_reviews_db"), ("audits", "get_audits_db"),
        ("verdicts", "get_auto_verdicts_db"), ("arming", "get_auto_verdict_arming_db"),
        ("queue", "get_queue_db"), ("swimlanes", "get_swimlanes_db"),
        ("requests", "get_review_requests_db"),
    ):
        monkeypatch.setattr(db_pkg, getter, lambda s=stores[name]: s)
    monkeypatch.setattr(ps, "snapshot", PipelineSnapshot())
    monkeypatch.setattr("backend.services.github_service.run_gh_command", _gh_forbidden)
    monkeypatch.setattr("backend.services.github_service.get_authenticated_login", lambda: "me")

    from backend.extensions import active_reviews
    active_reviews.clear()
    stores["synced"].register_repo(REPO)
    return stores


@pytest.fixture
def client(env, monkeypatch):
    import backend.routes.automation_routes as ar
    monkeypatch.setattr(ar, "get_automation_dispatches_db", lambda: env["dispatches"])
    monkeypatch.setattr(ar, "get_synced_prs_db", lambda: env["synced"])
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _pr(number, state="OPEN", **over):
    pr = {
        "number": number, "title": f"PR {number}", "state": state, "isDraft": False,
        "author": {"login": "alice"}, "url": f"https://github.com/{REPO}/pull/{number}",
        "reviews": [], "reviewDecision": None, "statusCheckRollup": [],
        "createdAt": "2026-08-01T00:00:00Z", "updatedAt": "2026-08-02T00:00:00Z",
        "closedAt": None, "mergedAt": None, "headRefName": f"f{number}", "headRefOid": "head111",
        "baseRefName": "main", "additions": 12, "deletions": 3,
    }
    pr.update(over)
    return pr


def _content(critical=1, major=0, minor=2):
    def issues(n, prefix):
        return [{"title": f"{prefix} {i}", "location": {"file": "a.py", "start_line": 1, "end_line": 1},
                 "problem": "p", "fix": "f"} for i in range(n)]
    return json.dumps({
        "sections": [
            {"type": "critical", "issues": issues(critical, "Crit")},
            {"type": "major", "issues": issues(major, "Maj")},
            {"type": "minor", "issues": issues(minor, "Min")},
        ],
        "score": {"overall": 7},
    })


def _dispatch(env, number, status=None, **kwargs):
    env["dispatches"].record_candidate(REPO, number)
    row = env["dispatches"].get_by_pr(REPO, number)
    if status:
        env["dispatches"].set_status(row["id"], status, **kwargs)
    return env["dispatches"].get_by_pr(REPO, number)


# ----- derive_stage -----


@pytest.mark.parametrize("status,detail,pr_state,running,expected", [
    ("dispatched", None, "MERGED", False, "closed"),
    ("pending", "waiting: CI pending", "CLOSED", True, "closed"),
    ("dispatched", None, "OPEN", True, "reviewing"),
    ("pending", None, None, True, "reviewing"),
    ("failed", "file fetch failed", "OPEN", False, "failed"),
    ("unidentified", "files span multiple rules", "OPEN", False, "unidentified"),
    ("skipped", "manual opt-out", "OPEN", False, "opted_out"),
    ("skipped", "review already in progress", "OPEN", False, "skipped"),
    ("skipped", None, None, False, "skipped"),
    ("pending", "waiting: CI pending", "OPEN", False, "waiting"),
    ("pending", "waiting: PR is a draft", None, False, "waiting"),
    ("pending", None, "OPEN", False, "ready"),
    ("pending", "manually re-enrolled", "OPEN", False, "ready"),
    ("dispatched", None, "OPEN", False, "reviewed"),
    ("dispatched", None, None, False, "reviewed"),
])
def test_derive_stage_matrix(status, detail, pr_state, running, expected):
    assert derive_stage(status, detail, pr_state, running) == expected


# ----- build_rows -----


def test_build_rows_joins_every_source(env):
    env["synced"].upsert_pr(REPO, _pr(7, reviewDecision="APPROVED",
                                      reviews=[{"author": {"login": "bob"}, "state": "APPROVED"}],
                                      statusCheckRollup=[{"name": "ci", "conclusion": "SUCCESS"}]))
    dispatch = _dispatch(env, 7, "dispatched", reviewer_key="pb", outcome_json=json.dumps({
        "outcome": "matched", "rule": "PB", "matched_rules": ["PB"],
        "unmatched_count": 0, "ignored_count": 0,
    }))
    old = env["reviews"].save_review(pr_number=7, repo=REPO, status="completed", score=5.0,
                                     content_json="{}", head_commit_sha="old000")
    rid = env["reviews"].save_review(pr_number=7, repo=REPO, status="completed",
                                     content_json=_content(), is_followup=True,
                                     head_commit_sha="head111")
    env["reviews"].update_section_posted(rid, "critical", True, posted_count=1, found_count=1)
    env["audits"].add_audit(pr_number=7, repo=REPO, finding_count=2, blocking_count=1)
    env["verdicts"].claim(REPO, 7, rid)
    env["verdicts"].finalize(rid, "posted", event="REQUEST_CHANGES", reason="1 critical",
                             tallies={"critical": 1, "major": 0, "minor": 2})
    env["arming"].set_arming(REPO, 7, True, "pb", "comment")
    env["arming"].set_criteria(REPO, 7, {"maxCritical": 3})
    item = env["queue"].add_to_queue(7, REPO, "t", "alice", "u", 1, 1)
    env["queue"].add_note(item["id"], "first")
    env["queue"].add_note(item["id"], "second")

    rows = build_rows()

    assert len(rows) == 1
    row = rows[0]
    assert list(row.keys()) == ROW_KEYS
    assert row["key"] == f"{REPO}#7"
    assert row["repo"] == REPO and row["prNumber"] == 7
    assert row["title"] == "PR 7" and row["author"] == "alice"
    assert row["url"] == f"https://github.com/{REPO}/pull/7"
    assert row["prState"] == "OPEN" and row["isDraft"] is False
    assert row["baseRefName"] == "main"
    assert (row["additions"], row["deletions"]) == (12, 3)
    assert row["prUpdatedAt"] == "2026-08-02T00:00:00Z"
    assert row["prSyncedAt"]
    assert row["headSha"] == "head111"
    assert row["stage"] == "reviewed"
    assert row["dispatch"] == {
        "status": "dispatched", "detail": None, "reviewerKey": "pb", "ruleName": "PB",
        "matchedRules": ["PB"], "attempts": 0,
        "createdAt": dispatch["created_at"], "updatedAt": dispatch["updated_at"],
    }
    assert row["automation"]["status"] == "dispatched"
    assert row["autoVerdict"]["enabled"] is True
    assert row["autoVerdict"]["reviewerType"] == "pb"
    assert row["autoVerdict"]["mode"] == "comment"
    assert row["autoVerdict"]["criteriaOverride"] == {"maxCritical": 3}
    assert row["autoVerdict"]["last"]["event"] == "REQUEST_CHANGES"
    assert row["reviewDecision"] == "APPROVED"
    assert [(r["login"], r["state"]) for r in row["currentReviewers"]] == [("bob", "APPROVED")]
    assert row["ciStatus"] == "success"
    assert row["statusCheckRollup"] == [{"name": "ci", "conclusion": "SUCCESS"}]
    assert row["running"] is False
    assert row["review"]["reviewId"] == rid
    assert row["review"]["score"] == 7.0
    assert row["review"]["isFollowup"] is True
    assert row["review"]["inlineCommentsPosted"] is True
    assert row["review"]["critical"] == {"posted": 1, "found": 1, "titles": ["Crit 0"]}
    assert row["review"]["minor"] == {"posted": None, "found": None, "titles": ["Min 0", "Min 1"]}
    assert row["hasNewCommits"] is False
    assert [e["kind"] for e in row["revLog"]] == ["audit", "review", "review"]
    assert row["revLog"][1]["id"] == rid and row["revLog"][1]["verdictEvent"] == "REQUEST_CHANGES"
    assert row["revLog"][2]["id"] == old
    assert row["rounds"] == 2
    assert row["onBoard"] is True
    assert row["queueItemId"] == item["id"]
    assert row["notesCount"] == 2


def test_build_rows_without_synced_data_or_history(env):
    _dispatch(env, 9)

    row = build_rows()[0]

    assert list(row.keys()) == ROW_KEYS
    assert row["title"] is None and row["author"] is None and row["prState"] is None
    assert row["url"] == f"https://github.com/{REPO}/pull/9"
    assert row["headSha"] is None and row["hasNewCommits"] is False
    assert row["stage"] == "ready"
    assert row["automation"]["status"] == "pending"
    assert row["autoVerdict"] is None
    assert row["review"] is None and row["revLog"] == [] and row["rounds"] == 0
    assert row["reviewDecision"] is None and row["ciStatus"] is None
    assert row["onBoard"] is False and row["queueItemId"] is None and row["notesCount"] == 0


def test_has_new_commits_needs_both_shas(env):
    env["synced"].upsert_pr(REPO, _pr(1, headRefOid="new222"))
    env["synced"].upsert_pr(REPO, _pr(2, headRefOid=None))
    env["synced"].upsert_pr(REPO, _pr(3, headRefOid="new222"))
    for n in (1, 2, 3):
        _dispatch(env, n, "dispatched")
    env["reviews"].save_review(pr_number=1, repo=REPO, status="completed", head_commit_sha="old111")
    env["reviews"].save_review(pr_number=2, repo=REPO, status="completed", head_commit_sha="old111")
    env["reviews"].save_review(pr_number=3, repo=REPO, status="completed", head_commit_sha=None)

    by_pr = {r["prNumber"]: r for r in build_rows()}

    assert by_pr[1]["hasNewCommits"] is True
    assert by_pr[2]["hasNewCommits"] is False  # head unknown
    assert by_pr[3]["hasNewCommits"] is False  # reviewed SHA unknown


def test_running_review_sets_stage_and_flag(env):
    _dispatch(env, 7, "dispatched")
    from backend.extensions import active_reviews, reviews_lock
    with reviews_lock:
        active_reviews[f"{REPO}/7"] = {"status": "running", "process": None}
    try:
        row = build_rows()[0]
    finally:
        with reviews_lock:
            del active_reviews[f"{REPO}/7"]
    assert row["running"] is True
    assert row["stage"] == "reviewing"


def test_build_rows_batches_many_prs(env):
    for n in range(1, 451):
        env["synced"].upsert_pr(REPO, _pr(n))
        _dispatch(env, n)
    rows = build_rows()
    assert len(rows) == 450
    assert all(r["title"] == f"PR {r['prNumber']}" for r in rows)


# ----- snapshot: includeClosed + version -----


def test_snapshot_filters_closed_unless_requested(env):
    env["synced"].upsert_pr(REPO, _pr(1, state="OPEN"))
    env["synced"].upsert_pr(REPO, _pr(2, state="MERGED"))
    env["synced"].upsert_pr(REPO, _pr(3, state="CLOSED"))
    for n in (1, 2, 3, 4):  # 4 unknown to the store: stays visible
        _dispatch(env, n)

    open_only = ps.snapshot.payload(include_closed=False)
    everything = ps.snapshot.payload(include_closed=True)

    assert sorted(r["prNumber"] for r in open_only["rows"]) == [1, 4]
    assert sorted(r["prNumber"] for r in everything["rows"]) == [1, 2, 3, 4]
    assert {r["prNumber"]: r["stage"] for r in everything["rows"]}[2] == "closed"
    assert open_only["version"] == everything["version"] == 1
    assert open_only["generatedAt"] and "prDataSyncedAt" in open_only


def test_snapshot_version_short_circuit(env):
    _dispatch(env, 1)
    first = ps.snapshot.payload(False)
    assert first["version"] == 1
    assert ps.snapshot.payload(False, known_version=1) == {"unchanged": True, "version": 1}

    ps.snapshot.rebuild()
    second = ps.snapshot.payload(False, known_version=1)
    assert second["version"] == 2 and "rows" in second


def test_dao_writers_mark_snapshot_dirty(env):
    ps.snapshot.payload(False)
    assert ps.snapshot.is_dirty() is False
    _dispatch(env, 1)
    assert ps.snapshot.is_dirty() is True
    ps.snapshot.rebuild()
    assert ps.snapshot.is_dirty() is False
    env["arming"].set_arming(REPO, 1, True, "default", "verdict")
    assert ps.snapshot.is_dirty() is True
    ps.snapshot.rebuild()
    env["queue"].add_to_queue(1, REPO, "t", "a", "u", 1, 1)
    assert ps.snapshot.is_dirty() is True


def test_pr_data_synced_at_is_the_latest_repo_sync(env):
    # Per-PR fetched_at is NOT the freshness signal (an unchanged PR keeps an
    # old stamp); the sync worker's last completed cycle for the repo is.
    env["synced"].upsert_pr(REPO, _pr(1))
    with env["db"].connection() as conn:
        conn.execute("UPDATE synced_prs SET fetched_at = '2026-01-01T00:00:00Z' WHERE pr_number = 1")
    _dispatch(env, 1)
    assert ps.snapshot.payload(True)["prDataSyncedAt"] is None  # repo never synced

    env["synced"].register_repo(REPO)
    with env["db"].connection() as conn:
        conn.execute(
            "UPDATE synced_repos SET last_synced_at = '2026-03-04 05:06:07' WHERE repo = ?", (REPO,)
        )
    ps.snapshot.rebuild()
    assert ps.snapshot.payload(True)["prDataSyncedAt"] == "2026-03-04T05:06:07Z"


# ----- routes -----


def test_get_pipeline_never_calls_gh(client, env):
    """The fixture makes run_gh_command raise; a 200 proves the view is DB-only."""
    env["synced"].upsert_pr(REPO, _pr(1))
    _dispatch(env, 1, "dispatched")
    _dispatch(env, 2)

    resp = client.get("/api/automation/pipeline")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["version"] == 1
    assert sorted(r["prNumber"] for r in body["rows"]) == [1, 2]
    assert sorted(body["rows"][0].keys()) == sorted(ROW_KEYS)


def test_get_pipeline_query_params(client, env):
    env["synced"].upsert_pr(REPO, _pr(1, state="MERGED"))
    _dispatch(env, 1)
    _dispatch(env, 2)

    assert [r["prNumber"] for r in client.get("/api/automation/pipeline").get_json()["rows"]] == [2]
    assert sorted(r["prNumber"] for r in
                  client.get("/api/automation/pipeline?includeClosed=1").get_json()["rows"]) == [1, 2]
    assert client.get("/api/automation/pipeline?version=1").get_json() == {"unchanged": True, "version": 1}
    assert client.get("/api/automation/pipeline?version=0").get_json()["version"] == 1


def test_refresh_row_upserts_and_returns_row(client, env):
    _dispatch(env, 7, "dispatched")
    ps.snapshot.payload(False)
    assert ps.snapshot.is_dirty() is False

    with patch("backend.routes.automation_routes.fetch_full_pr",
               return_value=_pr(7, title="Fresh title", headRefOid="fresh")) as mock_fetch:
        resp = client.post(f"/api/automation/pipeline/{REPO}/7/refresh")

    assert resp.status_code == 200
    assert mock_fetch.call_args.args == ("acme", "widgets", 7)
    row = resp.get_json()["row"]
    assert sorted(row.keys()) == sorted(ROW_KEYS)
    assert row["title"] == "Fresh title" and row["headSha"] == "fresh"
    assert env["synced"].get_prs_by_numbers(REPO, [7])[7]["title"] == "Fresh title"
    assert ps.snapshot.is_dirty() is True


def test_refresh_row_404_when_not_in_pipeline(client, env):
    with patch("backend.routes.automation_routes.fetch_full_pr") as mock_fetch:
        resp = client.post(f"/api/automation/pipeline/{REPO}/7/refresh")
    assert resp.status_code == 404
    assert mock_fetch.call_count == 0


def test_refresh_row_maps_upstream_errors(client, env):
    from backend.services.github_service import TransientGitHubError
    _dispatch(env, 7)
    with patch("backend.routes.automation_routes.fetch_full_pr", side_effect=TransientGitHubError("504")):
        assert client.post(f"/api/automation/pipeline/{REPO}/7/refresh").status_code == 503
    with patch("backend.routes.automation_routes.fetch_full_pr",
               side_effect=RuntimeError("gh command failed: Not Found (HTTP 404)")):
        assert client.post(f"/api/automation/pipeline/{REPO}/7/refresh").status_code == 404


def test_enroll_and_optout_return_the_row(client, env):
    env["synced"].upsert_pr(REPO, _pr(5))

    enrolled = client.post(f"/api/automation/dispatches/{REPO}/5/enroll")
    assert enrolled.status_code == 201
    row = enrolled.get_json()["row"]
    assert sorted(row.keys()) == sorted(ROW_KEYS)
    assert row["stage"] == "ready" and row["title"] == "PR 5"

    again = client.post(f"/api/automation/dispatches/{REPO}/5/enroll")
    assert again.status_code == 200 and again.get_json()["row"]["stage"] == "ready"

    opted = client.post(f"/api/automation/dispatches/{REPO}/5/optout")
    assert opted.status_code == 200
    assert opted.get_json()["row"]["stage"] == "opted_out"

    revived = client.post(f"/api/automation/dispatches/{REPO}/5/enroll")
    assert revived.status_code == 200
    assert revived.get_json()["row"]["dispatch"]["detail"] == "manually re-enrolled"


def test_build_rows_carries_review_request_state(env):
    env["dispatches"].record_candidate(REPO, 1)
    row1 = env["dispatches"].get_by_pr(REPO, 1)
    env["dispatches"].set_status(row1["id"], "dispatched")
    env["synced"].upsert_pr(REPO, _pr(1, reviewRequests=[{"__typename": "User", "login": "me"}]))
    env["requests"].record(REPO, 1)
    req = env["requests"].get_by_pr(REPO, 1)
    env["requests"].set_status(req["id"], "pending", detail="waiting: CI pending")

    env["dispatches"].record_candidate(REPO, 2)
    env["synced"].upsert_pr(REPO, _pr(2, reviewRequests=[{"__typename": "User", "login": "bob"}]))

    rows = {r["prNumber"]: r for r in ps.build_rows()}
    assert rows[1]["reviewRequest"] == {
        "status": "pending", "detail": "waiting: CI pending",
        "requestedAt": req["requested_at"], "attempts": 0,
    }
    assert rows[1]["reviewRequestedFromMe"] is True
    assert rows[2]["reviewRequest"] is None
    assert rows[2]["reviewRequestedFromMe"] is False
