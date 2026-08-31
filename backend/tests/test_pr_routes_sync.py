"""Route dispatch tests: DB path, hybrid path, live fallback."""
import json
from unittest.mock import patch

import pytest

from backend import create_app
from backend.database.base import Database
from backend.database.synced_prs import SyncedPRsDB


@pytest.fixture
def store(tmp_path):
    return SyncedPRsDB(Database(tmp_path / "test.db"))


@pytest.fixture
def dispatches(tmp_path):
    from backend.database.automation_dispatches import AutomationDispatchesDB
    return AutomationDispatchesDB(Database(tmp_path / "test.db"))


@pytest.fixture
def client(store, dispatches, monkeypatch):
    import backend.routes.pr_routes as pr_routes
    monkeypatch.setattr(pr_routes, "get_synced_prs_db", lambda: store)
    monkeypatch.setattr(pr_routes, "get_automation_dispatches_db", lambda: dispatches)
    monkeypatch.setattr(pr_routes, "get_pr_sync_config", lambda: {
        "enabled": True, "poll_interval_seconds": 120, "history_days": 180,
        "max_synced_repos": 10, "exclude_repos": ["acme/excluded"],
    })
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _pr(number, state="OPEN", **over):
    pr = {
        "number": number, "title": f"PR {number}", "state": state, "isDraft": False,
        "author": {"login": "alice"}, "assignees": [], "labels": [],
        "reviewRequests": [], "reviews": [], "reviewDecision": None,
        "statusCheckRollup": [], "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-02T00:00:00Z", "closedAt": None, "mergedAt": None,
        "url": "", "body": "", "headRefName": f"f{number}", "baseRefName": "main",
        "mergeable": "MERGEABLE", "additions": 1, "deletions": 1,
        "changedFiles": 1, "milestone": None,
    }
    pr.update(over)
    return pr


def test_db_path_serves_from_store_without_gh(client, store):
    store.register_repo("acme/widgets")
    store.mark_backfill_done("acme/widgets")
    store.update_last_synced("acme/widgets")
    store.upsert_pr("acme/widgets", _pr(1))
    store.upsert_pr("acme/widgets", _pr(2, state="MERGED"))

    with patch("backend.routes.pr_routes.run_gh_command") as mock_gh:
        resp = client.get("/api/repos/acme/widgets/prs?state=open")
    assert resp.status_code == 200
    body = resp.get_json()
    assert [p["number"] for p in body["prs"]] == [1]
    assert body["sync"]["status"] == "ready"
    assert body["prs"][0]["fetchedAt"]
    assert body["prs"][0]["reviewStatus"]  # computed at serve time
    mock_gh.assert_not_called()


def test_pr_list_carries_automation_pipeline_state(client, store, dispatches):
    """PR list rows get the same `automation` field queue cards have, so the
    pipeline badge can render on the main PR list."""
    store.register_repo("acme/widgets")
    store.mark_backfill_done("acme/widgets")
    store.update_last_synced("acme/widgets")
    store.upsert_pr("acme/widgets", _pr(1))
    store.upsert_pr("acme/widgets", _pr(2))
    dispatches.record_candidate("acme/widgets", 1)

    with patch("backend.routes.pr_routes.run_gh_command"):
        resp = client.get("/api/repos/acme/widgets/prs?state=open")

    prs = {p["number"]: p for p in resp.get_json()["prs"]}
    assert prs[1]["automation"]["status"] == "pending"
    assert prs[2]["automation"] is None


def test_visit_registers_repo(client, store):
    with patch("backend.routes.pr_routes.run_gh_command", return_value="[]"):
        client.get("/api/repos/acme/newrepo/prs")
    assert store.get_repo("acme/newrepo") is not None


def test_live_path_when_backfill_pending(client, store):
    store.register_repo("acme/widgets")  # not backfilled yet
    with patch("backend.routes.pr_routes.run_gh_command", return_value=json.dumps([_pr(5)])) as mock_gh:
        resp = client.get("/api/repos/acme/widgets/prs")
    body = resp.get_json()
    assert [p["number"] for p in body["prs"]] == [5]
    assert body["sync"]["status"] == "backfilling"
    mock_gh.assert_called_once()


def test_excluded_repo_stays_live(client, store):
    with patch("backend.routes.pr_routes.run_gh_command", return_value="[]"):
        resp = client.get("/api/repos/acme/excluded/prs")
    assert resp.get_json()["sync"]["status"] == "live"
    assert store.get_repo("acme/excluded") is None  # never registered


def test_hybrid_path_numbers_only_join_preserves_github_order(client, store):
    store.register_repo("acme/widgets")
    store.mark_backfill_done("acme/widgets")
    for n in (1, 2, 3):
        store.upsert_pr("acme/widgets", _pr(n))
    with patch("backend.routes.pr_routes.run_gh_command",
               return_value='[{"number": 3}, {"number": 1}]') as mock_gh:
        resp = client.get("/api/repos/acme/widgets/prs?mentions=bob")
    body = resp.get_json()
    assert [p["number"] for p in body["prs"]] == [3, 1]
    args = mock_gh.call_args[0][0]
    json_idx = args.index("--json")
    assert args[json_idx + 1] == "number"


def test_transient_error_mid_backfill_serves_partial(client, store):
    from backend.services.github_service import TransientGitHubError
    store.register_repo("acme/widgets")   # backfill pending
    store.upsert_pr("acme/widgets", _pr(1))
    with patch("backend.routes.pr_routes.run_gh_command",
               side_effect=TransientGitHubError("504")):
        resp = client.get("/api/repos/acme/widgets/prs")
    assert resp.status_code == 200
    body = resp.get_json()
    assert [p["number"] for p in body["prs"]] == [1]
    assert body["sync"]["status"] == "backfilling"


def test_transient_error_no_rows_still_503(client, store):
    from backend.services.github_service import TransientGitHubError
    with patch("backend.routes.pr_routes.run_gh_command",
               side_effect=TransientGitHubError("504")):
        resp = client.get("/api/repos/acme/empty/prs")
    assert resp.status_code == 503


def test_refresh_endpoint_upserts_and_returns(client, store):
    store.register_repo("acme/widgets")
    with patch("backend.routes.pr_routes.fetch_full_pr", return_value=_pr(7, state="MERGED")):
        resp = client.post("/api/repos/acme/widgets/prs/7/refresh")
    assert resp.status_code == 200
    pr = resp.get_json()["pr"]
    assert pr["number"] == 7 and pr["state"] == "MERGED"
    assert pr["fetchedAt"]
    assert store.get_prs_by_numbers("acme/widgets", [7])


def test_refresh_404_deletes_row(client, store):
    store.upsert_pr("acme/widgets", _pr(7))
    with patch("backend.routes.pr_routes.fetch_full_pr",
               side_effect=RuntimeError("gh command failed: Not Found (HTTP 404)")):
        resp = client.post("/api/repos/acme/widgets/prs/7/refresh")
    assert resp.status_code == 404
    assert not store.get_prs_by_numbers("acme/widgets", [7])


def test_refresh_transient_503(client, store):
    from backend.services.github_service import TransientGitHubError
    with patch("backend.routes.pr_routes.fetch_full_pr", side_effect=TransientGitHubError("504")):
        resp = client.post("/api/repos/acme/widgets/prs/7/refresh")
    assert resp.status_code == 503


def test_pr_list_carries_auto_verdict_arming(client, store, monkeypatch, tmp_path):
    """PR list rows carry the merge-queue arming state so the PR list can show
    the armed checkmark, not just the pipeline badge."""
    import backend.routes.pr_routes as pr_routes
    from backend.database.merge_queue import MergeQueueDB
    queue_db = MergeQueueDB(Database(tmp_path / "queue.db"))
    monkeypatch.setattr(pr_routes, "get_queue_db", lambda: queue_db)

    store.register_repo("acme/widgets")
    store.mark_backfill_done("acme/widgets")
    store.update_last_synced("acme/widgets")
    store.upsert_pr("acme/widgets", _pr(1))
    store.upsert_pr("acme/widgets", _pr(2))
    queue_db.add_to_queue(1, "acme/widgets")
    queue_db.set_auto_verdict(1, "acme/widgets", True, "ed", mode="comment")

    with patch("backend.routes.pr_routes.run_gh_command"):
        resp = client.get("/api/repos/acme/widgets/prs?state=open")

    prs = {p["number"]: p for p in resp.get_json()["prs"]}
    assert prs[1]["autoVerdict"] == {"enabled": True, "reviewerType": "ed", "mode": "comment"}
    assert prs[2]["autoVerdict"] is None
