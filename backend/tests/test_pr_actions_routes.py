"""Draft toggle + merge endpoints, with gh fully mocked."""
import json

import pytest

from backend import create_app
from backend.database.base import Database
from backend.database.synced_prs import SyncedPRsDB
from backend.services.github_service import RateLimitError, TransientGitHubError

REPO = "acme/widgets"


@pytest.fixture
def store(tmp_path):
    return SyncedPRsDB(Database(tmp_path / "test.db"))


@pytest.fixture
def gh(monkeypatch):
    """Records gh args; set gh.error to make the next call raise it."""
    class FakeGh:
        calls = []
        error = None

        def __call__(self, args, **kwargs):
            self.calls.append(args)
            if self.error:
                raise self.error
            return ""

    fake = FakeGh()
    fake.calls = []
    import backend.routes.pr_routes as pr_routes
    monkeypatch.setattr(pr_routes, "run_gh_command", fake)
    return fake


@pytest.fixture
def dirty(monkeypatch):
    calls = []
    monkeypatch.setattr("backend.services.pipeline_snapshot.mark_dirty", lambda: calls.append(1))
    return calls


@pytest.fixture
def client(store, gh, dirty, monkeypatch):
    import backend.routes.pr_routes as pr_routes
    monkeypatch.setattr(pr_routes, "get_synced_prs_db", lambda: store)
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _pr(number, **over):
    pr = {"number": number, "state": "OPEN", "isDraft": False, "author": {"login": "a"}}
    pr.update(over)
    return pr


# -- draft toggle --------------------------------------------------------------

def test_convert_to_draft_runs_ready_undo_and_writes_through(client, store, gh, dirty):
    store.upsert_pr(REPO, _pr(7))
    resp = client.post(f"/api/repos/{REPO}/prs/7/draft", json={"draft": True})
    assert resp.status_code == 200
    assert resp.get_json() == {"isDraft": True}
    assert gh.calls == [["pr", "ready", "7", "-R", REPO, "--undo"]]
    assert store.get_prs_by_numbers(REPO, [7])[7]["isDraft"] is True
    assert dirty


def test_mark_ready_runs_ready_without_undo(client, store, gh):
    store.upsert_pr(REPO, _pr(7, isDraft=True))
    resp = client.post(f"/api/repos/{REPO}/prs/7/draft", json={"draft": False})
    assert resp.status_code == 200
    assert gh.calls == [["pr", "ready", "7", "-R", REPO]]
    assert store.get_prs_by_numbers(REPO, [7])[7]["isDraft"] is False


def test_draft_toggle_for_unsynced_pr_still_succeeds(client, gh):
    resp = client.post(f"/api/repos/{REPO}/prs/8/draft", json={"draft": False})
    assert resp.status_code == 200


@pytest.mark.parametrize("body", [None, {}, {"draft": "yes"}, {"draft": 1}])
def test_draft_toggle_rejects_bad_body(client, gh, body):
    resp = client.post(f"/api/repos/{REPO}/prs/7/draft", json=body)
    assert resp.status_code == 400
    assert gh.calls == []


def test_draft_toggle_surfaces_github_refusal(client, store, gh, dirty):
    store.upsert_pr(REPO, _pr(7))
    gh.error = RuntimeError("gh command failed: GraphQL: Resource not accessible by integration")
    resp = client.post(f"/api/repos/{REPO}/prs/7/draft", json={"draft": True})
    assert resp.status_code == 422
    assert resp.get_json()["error"] == "GraphQL: Resource not accessible by integration"
    assert store.get_prs_by_numbers(REPO, [7])[7]["isDraft"] is False
    assert not dirty


# -- merge -----------------------------------------------------------------------

def test_merge_defaults_to_squash_and_delete_branch(client, store, gh, dirty):
    store.upsert_pr(REPO, _pr(7))
    resp = client.post(f"/api/repos/{REPO}/prs/7/merge", json={})
    assert resp.status_code == 200
    assert resp.get_json() == {"merged": True}
    assert gh.calls == [["pr", "merge", "7", "-R", REPO, "--squash", "--delete-branch"]]
    assert store.get_prs_by_numbers(REPO, [7])[7]["state"] == "MERGED"
    assert dirty


@pytest.mark.parametrize("method", ["merge", "rebase", "squash"])
def test_merge_method_flag(client, gh, method):
    resp = client.post(f"/api/repos/{REPO}/prs/7/merge",
                       json={"method": method, "deleteBranch": False})
    assert resp.status_code == 200
    assert gh.calls == [["pr", "merge", "7", "-R", REPO, f"--{method}"]]


def test_merge_pins_head_commit_when_given(client, gh):
    resp = client.post(f"/api/repos/{REPO}/prs/7/merge",
                       json={"method": "squash", "deleteBranch": True, "headSha": "abc1234def"})
    assert resp.status_code == 200
    assert gh.calls == [["pr", "merge", "7", "-R", REPO, "--squash", "--delete-branch",
                         "--match-head-commit", "abc1234def"]]


@pytest.mark.parametrize("body", [
    {"method": "octopus"}, {"method": "--admin"}, {"deleteBranch": "yes"},
    {"headSha": "not a sha!"}, {"headSha": 5},
])
def test_merge_rejects_bad_body(client, gh, body):
    resp = client.post(f"/api/repos/{REPO}/prs/7/merge", json=body)
    assert resp.status_code == 400
    assert gh.calls == []


def test_merge_surfaces_github_refusal_and_keeps_state(client, store, gh, dirty):
    store.upsert_pr(REPO, _pr(7))
    gh.error = RuntimeError("gh command failed: Pull request is not mergeable: the base branch policy prohibits the merge.\n")
    resp = client.post(f"/api/repos/{REPO}/prs/7/merge", json={})
    assert resp.status_code == 422
    assert resp.get_json()["error"] == (
        "Pull request is not mergeable: the base branch policy prohibits the merge."
    )
    assert store.get_prs_by_numbers(REPO, [7])[7]["state"] == "OPEN"
    assert not dirty


def test_merge_transient_and_rate_limit_errors(client, gh):
    gh.error = TransientGitHubError("gh command failed: HTTP 502")
    assert client.post(f"/api/repos/{REPO}/prs/7/merge", json={}).status_code == 503
    gh.error = RateLimitError("gh command failed: API rate limit exceeded")
    assert client.post(f"/api/repos/{REPO}/prs/7/merge", json={}).status_code == 429


def test_merge_passes_custom_subject_and_body(client, gh):
    resp = client.post(f"/api/repos/{REPO}/prs/7/merge", json={
        "method": "squash", "deleteBranch": False,
        "subject": "Ship it (#7)", "body": "Line one\n\nLine two",
    })
    assert resp.status_code == 200
    assert gh.calls == [["pr", "merge", "7", "-R", REPO, "--squash",
                         "--subject", "Ship it (#7)", "--body", "Line one\n\nLine two"]]


def test_merge_empty_body_is_sent_as_is(client, gh):
    """An operator who clears the body wants an empty message, not GitHub's default."""
    resp = client.post(f"/api/repos/{REPO}/prs/7/merge",
                       json={"method": "merge", "deleteBranch": False, "body": ""})
    assert resp.status_code == 200
    assert gh.calls == [["pr", "merge", "7", "-R", REPO, "--merge", "--body", ""]]


@pytest.mark.parametrize("body", [
    {"method": "rebase", "subject": "x"}, {"method": "rebase", "body": "x"},
    {"subject": ""}, {"subject": "   "}, {"subject": 5}, {"body": ["x"]},
])
def test_merge_rejects_bad_message(client, gh, body):
    resp = client.post(f"/api/repos/{REPO}/prs/7/merge", json=body)
    assert resp.status_code == 400
    assert gh.calls == []


# -- merge info ------------------------------------------------------------------

def _merge_info_payload(pr=True):
    return json.dumps({"data": {"repository": {
        "squashMergeAllowed": True, "mergeCommitAllowed": False, "rebaseMergeAllowed": True,
        "pullRequest": {
            "sqHead": "Add widgets (#7)", "sqBody": "* commit one\n* commit two",
            "mHead": "Merge pull request #7 from acme/widgets-branch", "mBody": "Add widgets",
        } if pr else None,
    }}})


def test_merge_info_returns_prefilled_messages_and_allowed_methods(client, gh, monkeypatch):
    import backend.services.github_service as gs
    calls = []
    monkeypatch.setattr(gs, "run_gh_command", lambda args, **kw: (calls.append(args), _merge_info_payload())[1])
    resp = client.get(f"/api/repos/{REPO}/prs/7/merge-info")
    assert resp.status_code == 200
    assert resp.get_json() == {"methods": {
        "squash": {"allowed": True, "subject": "Add widgets (#7)", "body": "* commit one\n* commit two"},
        "merge": {"allowed": False, "subject": "Merge pull request #7 from acme/widgets-branch",
                  "body": "Add widgets"},
        "rebase": {"allowed": True},
    }}
    args = calls[0]
    assert args[:2] == ["api", "graphql"]
    assert "owner=acme" in args and "name=widgets" in args and "number=7" in args


def test_merge_info_unknown_pr_is_404(client, monkeypatch):
    import backend.services.github_service as gs
    monkeypatch.setattr(gs, "run_gh_command", lambda args, **kw: _merge_info_payload(pr=False))
    assert client.get(f"/api/repos/{REPO}/prs/7/merge-info").status_code == 404


def test_merge_info_gh_errors_are_mapped(client, monkeypatch):
    import backend.services.github_service as gs

    def boom(args, **kw):
        raise TransientGitHubError("gh command failed: HTTP 502")

    monkeypatch.setattr(gs, "run_gh_command", boom)
    assert client.get(f"/api/repos/{REPO}/prs/7/merge-info").status_code == 503


def test_merge_info_unresolvable_pr_error_is_404(client, monkeypatch):
    """Real gh reports an unknown PR as a GraphQL error (non-zero exit), not a null."""
    import backend.services.github_service as gs

    def not_found(args, **kw):
        raise RuntimeError("gh command failed: gh: Could not resolve to a PullRequest with the number of 99.")

    monkeypatch.setattr(gs, "run_gh_command", not_found)
    assert client.get(f"/api/repos/{REPO}/prs/99/merge-info").status_code == 404
