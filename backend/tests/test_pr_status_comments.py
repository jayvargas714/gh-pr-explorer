"""Tests for the per-event PR status comments service.

Every gh-touching dependency is monkeypatched, so these tests assert on the
API calls that *would* be made, never on network or subprocess behavior.
"""

import pytest

from backend.services import pr_status_comments as svc
from backend.services.github_service import RateLimitError

OWNER = "owner"
REPO = "repo"
PR = 42


class GhRecorder:
    """Captures run_gh_command invocations, classified by call shape."""

    def __init__(self):
        self.calls = []
        self.existing_ids = []   # ids the list call reports
        self.errors = {}         # kind ('list'|'post'|'delete') -> exception

    def __call__(self, args, **kwargs):
        kind = self._kind(args)
        self.calls.append({"args": args, "kwargs": kwargs, "kind": kind})
        err = self.errors.get(kind)
        if err:
            raise err
        if kind == "list":
            return "\n".join(str(i) for i in self.existing_ids)
        return ""

    @staticmethod
    def _kind(args):
        if "--method" in args:
            method = args[args.index("--method") + 1]
            return "post" if method == "POST" else "delete"
        return "list"

    @property
    def kinds(self):
        return [c["kind"] for c in self.calls]

    @property
    def body(self):
        """The --field body=... value from the recorded POST call."""
        for c in self.calls:
            if c["kind"] == "post":
                field = c["args"][c["args"].index("--field") + 1]
                assert field.startswith("body=")
                return field[len("body="):]
        raise AssertionError("no POST call recorded")

    @property
    def deleted_endpoints(self):
        return [c["args"][1] for c in self.calls if c["kind"] == "delete"]


@pytest.fixture
def gh(monkeypatch):
    recorder = GhRecorder()
    monkeypatch.setattr(svc, "run_gh_command", recorder)
    set_flag(monkeypatch, True)
    return recorder


def set_flag(monkeypatch, value):
    monkeypatch.setattr(svc, "get_config", lambda: {"post_review_started_comment": value})


TALLIES = {"critical": 1, "major": 2, "minor": 3}


# --- posting mechanics --------------------------------------------------------

def test_marker_is_appended_to_every_body(gh):
    svc.post_review_started_comment(OWNER, REPO, PR)

    assert svc.STATUS_MARKER in gh.body


def test_supersede_lists_posts_then_deletes(gh):
    gh.existing_ids = [101, 102]

    assert svc.post_review_started_comment(OWNER, REPO, PR) is True

    assert gh.kinds == ["list", "post", "delete", "delete"]
    assert gh.deleted_endpoints == [
        f"repos/{OWNER}/{REPO}/issues/comments/101",
        f"repos/{OWNER}/{REPO}/issues/comments/102",
    ]


def test_no_deletes_when_no_prior_status_comment(gh):
    svc.post_review_started_comment(OWNER, REPO, PR)

    assert gh.kinds == ["list", "post"]


def test_delete_failure_is_absorbed_and_post_still_counts(gh):
    gh.existing_ids = [101, 102]
    gh.errors["delete"] = RuntimeError("gh command failed: 404")

    assert svc.post_review_started_comment(OWNER, REPO, PR) is True
    # Both deletes were still attempted despite the first failing.
    assert gh.kinds == ["list", "post", "delete", "delete"]


def test_list_failure_still_posts(gh):
    gh.errors["list"] = RuntimeError("gh command failed: 500")

    assert svc.post_review_started_comment(OWNER, REPO, PR) is True
    assert "post" in gh.kinds


def test_rate_limit_skips_everything_silently(gh):
    gh.errors["list"] = RateLimitError("rate limited")

    assert svc.post_review_started_comment(OWNER, REPO, PR) is False
    assert gh.kinds == ["list"]          # no POST attempted under a drained quota


def test_post_failure_is_swallowed(gh):
    gh.errors["post"] = RuntimeError("gh command failed: 403")

    assert svc.post_review_started_comment(OWNER, REPO, PR) is False


def test_disabled_flag_posts_and_lists_nothing(monkeypatch, gh):
    set_flag(monkeypatch, False)

    assert svc.post_review_started_comment(OWNER, REPO, PR) is False
    assert gh.calls == []


def test_missing_flag_defaults_to_enabled(monkeypatch, gh):
    monkeypatch.setattr(svc, "get_config", dict)

    assert svc.post_review_started_comment(OWNER, REPO, PR) is True


def test_delete_status_comments_deletes_without_posting(gh):
    gh.existing_ids = [77]

    assert svc.delete_status_comments(OWNER, REPO, PR) is True
    assert gh.kinds == ["list", "delete"]
    assert gh.deleted_endpoints == [f"repos/{OWNER}/{REPO}/issues/comments/77"]


def test_delete_status_comments_respects_disabled_flag(monkeypatch, gh):
    set_flag(monkeypatch, False)

    assert svc.delete_status_comments(OWNER, REPO, PR) is False
    assert gh.calls == []


# --- started (A) --------------------------------------------------------------

def test_started_body_reports_reviewer_attempt_sha_and_time(gh):
    svc.post_review_started_comment(
        OWNER, REPO, PR, reviewer_type="security",
        attempt=1, max_attempts=3, head_sha="abcdef1234567890",
    )

    body = gh.body
    assert "Code review in progress" in body
    assert "`security`" in body
    assert "Attempt: 1 of 3" in body
    assert "`abcdef12`" in body
    assert "UTC" in body


def test_started_body_omits_unknown_sha_and_note(gh):
    svc.post_review_started_comment(OWNER, REPO, PR)

    assert "Commit:" not in gh.body
    assert "Note:" not in gh.body


def test_started_note_is_included_when_given(gh):
    svc.post_review_started_comment(OWNER, REPO, PR, note="restarted after new commits")

    assert "Note: restarted after new commits" in gh.body


def test_started_retry_attempt_gets_its_own_lead(gh):
    svc.post_review_started_comment(OWNER, REPO, PR, attempt=2, max_attempts=3)

    assert "Attempt 2 of 3 has been started automatically after a failed attempt." in gh.body


def test_normal_review_body_is_not_labelled_follow_up_or_automatic(gh):
    svc.post_review_started_comment(OWNER, REPO, PR)

    body = gh.body.lower()
    assert "follow-up" not in body
    assert "automatically" not in body


def test_followup_review_body_says_follow_up(gh):
    svc.post_review_started_comment(OWNER, REPO, PR, is_followup=True)

    assert "follow-up" in gh.body.lower()


def test_auto_started_review_body_says_automatically(gh):
    svc.post_review_started_comment(OWNER, REPO, PR, is_followup=True, auto_started=True)

    body = gh.body.lower()
    assert "automatically" in body
    assert "follow-up" in body


# --- retry scheduled (B) ------------------------------------------------------

def test_retry_scheduled_body(gh):
    svc.post_review_retry_scheduled_comment(
        OWNER, REPO, PR, reviewer_type="ed", attempt=1, max_attempts=3,
        delay_seconds=30, reason="nonzero_exit", detail="exit 1",
    )

    body = gh.body
    assert "retry scheduled" in body.lower()
    assert "Attempt 1 of 3" in body
    assert "nonzero_exit — exit 1" in body
    assert "~30s" in body
    assert "no action is needed" in body


# --- gave up (C) ----------------------------------------------------------------

def test_gave_up_body_after_exhausted_attempts(gh):
    svc.post_review_gave_up_comment(
        OWNER, REPO, PR, reviewer_type="ed", attempt=3, max_attempts=3,
        reason="timeout", detail=None,
    )

    body = gh.body
    assert "giving up" in body.lower()
    assert "All 3 review attempts" in body
    assert "Last failure: timeout" in body
    assert "start a new review manually" in body.lower()


def test_gave_up_spawn_failed_variant(gh):
    svc.post_review_gave_up_comment(
        OWNER, REPO, PR, reviewer_type="ed", attempt=2, max_attempts=3,
        reason="spawn_failed", detail="boom", spawn_failed=True,
    )

    body = gh.body
    assert "retry could not be started" in body
    assert "spawn_failed — boom" in body


# --- stopped stale (E) ----------------------------------------------------------

def test_stopped_stale_comment_reports_shas_and_next_step(gh):
    assert svc.post_review_stopped_stale_comment(
        OWNER, REPO, PR,
        old_sha="aaaa1111222233334444", new_sha="bbbb5555666677778888",
        reviewer_type="security",
    ) is True

    body = gh.body
    assert "Code review stopped" in body
    assert "`aaaa1111`" in body
    assert "`bbbb5555`" in body
    assert "`security`" in body
    assert "restart failed" in body.lower()
    assert "manually" in body.lower()


# --- verdict outcomes (F, G, H, I) ---------------------------------------------

def test_verdict_suppressed_body(gh):
    svc.post_verdict_suppressed_comment(
        OWNER, REPO, PR, tallies=TALLIES, reason="within limits (0/2/99)",
    )

    body = gh.body
    assert "approval needs manual action" in body.lower()
    assert "1 critical, 2 major, 3 minor" in body
    assert "within limits (0/2/99)" in body
    assert "post the verdict manually" in body.lower()


def test_verdict_deferred_body(gh):
    svc.post_verdict_deferred_comment(
        OWNER, REPO, PR, event="REQUEST_CHANGES", tallies=TALLIES,
    )

    body = gh.body
    assert "rate limit" in body.lower()
    assert "REQUEST_CHANGES" in body
    assert "1 critical, 2 major, 3 minor" in body
    assert "no action is needed" in body.lower()


def test_verdict_error_body(gh):
    svc.post_verdict_error_comment(
        OWNER, REPO, PR, event="APPROVE", tallies=TALLIES, error_detail="GitHub said no",
    )

    body = gh.body
    assert "could not be posted" in body.lower()
    assert "APPROVE" in body
    assert "GitHub said no" in body
    assert "manually" in body.lower()


def test_verdict_skipped_body(gh):
    svc.post_verdict_skipped_comment(OWNER, REPO, PR, reason="Review has no usable structured content")

    body = gh.body
    assert "skipped" in body.lower()
    assert "no usable structured content" in body


# --- orphaned / automation (K, L, M, N, O, P) ------------------------------------

def test_orphaned_requeued_body(gh):
    svc.post_review_orphaned_requeued_comment(OWNER, REPO, PR)

    body = gh.body
    assert "interrupted" in body.lower()
    assert "requeued" in body.lower()
    assert "no action is needed" in body.lower()


def test_automation_enrolled_body(gh):
    svc.post_automation_enrolled_comment(OWNER, REPO, PR)

    body = gh.body
    assert "enrolled" in body.lower()
    assert "gates" in body.lower()


def test_automation_waiting_body(gh):
    svc.post_automation_waiting_comment(OWNER, REPO, PR, reason="CI status is pending")

    body = gh.body
    assert "waiting" in body.lower()
    assert "CI status is pending" in body
    assert "starts the review automatically" in body


def test_automation_window_expired_body(gh):
    svc.post_automation_window_expired_comment(OWNER, REPO, PR, timeout_hours=48)

    body = gh.body
    assert "expired" in body.lower()
    assert "48h" in body
    assert "manually" in body.lower()


def test_automation_failed_body(gh):
    svc.post_automation_failed_comment(OWNER, REPO, PR, attempts=5, detail="budget exhausted")

    body = gh.body
    assert "could not start a review" in body
    assert "5 attempts" in body
    assert "budget exhausted" in body


def test_automation_unidentified_body(gh):
    svc.post_automation_unidentified_comment(
        OWNER, REPO, PR, matched_rules=["rust", "docs"], unmatched_count=3,
    )

    body = gh.body
    assert "manual routing" in body.lower()
    assert "rust, docs" in body
    assert "3" in body


def test_long_detail_is_truncated(gh):
    svc.post_verdict_error_comment(
        OWNER, REPO, PR, event="APPROVE", tallies=TALLIES, error_detail="x" * 1000,
    )

    assert "x" * 301 not in gh.body
