"""Tests for the "review underway" PR comment posted when a review starts.

Every gh-touching dependency is monkeypatched, so these tests assert on the
API call that *would* be made, never on network or subprocess behavior.
"""

import pytest

from backend.services import review_started_service as svc

OWNER = "owner"
REPO = "repo"
PR = 42


class GhRecorder:
    """Captures run_gh_command invocations and optionally raises instead."""

    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def __call__(self, args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        if self.error:
            raise self.error
        return ""

    @property
    def body(self):
        """The --field body=... value from the single recorded call."""
        args = self.calls[0]["args"]
        field = args[args.index("--field") + 1]
        assert field.startswith("body=")
        return field[len("body="):]


@pytest.fixture
def gh(monkeypatch):
    recorder = GhRecorder()
    monkeypatch.setattr(svc, "run_gh_command", recorder)
    return recorder


def set_flag(monkeypatch, value):
    monkeypatch.setattr(svc, "get_config", lambda: {"post_review_started_comment": value})


def test_disabled_flag_posts_nothing(monkeypatch, gh):
    set_flag(monkeypatch, False)

    assert svc.post_review_started_comment(OWNER, REPO, PR) is False
    assert gh.calls == []


def test_missing_flag_defaults_to_enabled(monkeypatch, gh):
    monkeypatch.setattr(svc, "get_config", dict)

    assert svc.post_review_started_comment(OWNER, REPO, PR) is True
    assert len(gh.calls) == 1


def test_posts_issue_comment_to_correct_endpoint(monkeypatch, gh):
    set_flag(monkeypatch, True)

    assert svc.post_review_started_comment(OWNER, REPO, PR) is True

    args = gh.calls[0]["args"]
    assert args[0] == "api"
    assert args[1] == f"repos/{OWNER}/{REPO}/issues/{PR}/comments"
    assert "--method" in args and args[args.index("--method") + 1] == "POST"


def test_body_reports_reviewer_and_start_time(monkeypatch, gh):
    set_flag(monkeypatch, True)

    svc.post_review_started_comment(OWNER, REPO, PR, reviewer_type="security")

    body = gh.body
    assert "Code review in progress" in body
    assert "`security`" in body
    assert "UTC" in body


def test_normal_review_body_is_not_labelled_follow_up_or_automatic(monkeypatch, gh):
    set_flag(monkeypatch, True)

    svc.post_review_started_comment(OWNER, REPO, PR)

    body = gh.body.lower()
    assert "follow-up" not in body
    assert "automatically" not in body


def test_followup_review_body_says_follow_up(monkeypatch, gh):
    set_flag(monkeypatch, True)

    svc.post_review_started_comment(OWNER, REPO, PR, is_followup=True)

    assert "follow-up" in gh.body.lower()


def test_auto_started_review_body_says_automatically(monkeypatch, gh):
    set_flag(monkeypatch, True)

    svc.post_review_started_comment(OWNER, REPO, PR, is_followup=True, auto_started=True)

    body = gh.body.lower()
    assert "automatically" in body
    assert "follow-up" in body


def test_gh_failure_is_swallowed(monkeypatch):
    set_flag(monkeypatch, True)
    recorder = GhRecorder(error=RuntimeError("gh command failed: 403"))
    monkeypatch.setattr(svc, "run_gh_command", recorder)

    assert svc.post_review_started_comment(OWNER, REPO, PR) is False
    assert len(recorder.calls) == 1
