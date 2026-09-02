"""Tests for GitHub rate-limit detection and the 429 verdict-post path.

A drained GraphQL quota must surface as a distinct, retryable condition —
not as the generic RuntimeError that gets swallowed into "Could not fetch
PR head commit SHA" and permanently loses an auto verdict.
"""

import subprocess
from unittest.mock import patch

import pytest

from backend.services.github_service import (
    RateLimitError,
    fetch_open_prs_head_shas,
    fetch_pr_head_sha,
    is_rate_limit_error,
    run_gh_command,
)
from backend.services import verdict_service


RATE_LIMIT_STDERR = (
    "GraphQL: API rate limit already exceeded for user ID 54078139."
)


def _called_process_error(stderr):
    return subprocess.CalledProcessError(1, ["gh"], output="", stderr=stderr)


# --- is_rate_limit_error ------------------------------------------------------

@pytest.mark.parametrize("message", [
    RATE_LIMIT_STDERR,
    "API rate limit exceeded for installation",
    "You have exceeded a secondary rate limit. Please wait.",
])
def test_rate_limit_messages_are_recognized(message):
    assert is_rate_limit_error(message) is True


@pytest.mark.parametrize("message", [None, "", "HTTP 502", "Not Found", "422 Unprocessable"])
def test_other_errors_are_not_rate_limits(message):
    assert is_rate_limit_error(message) is False


# --- run_gh_command -----------------------------------------------------------

def test_run_gh_command_raises_rate_limit_error_without_retrying():
    """Local backoff is pointless against an hourly quota window — the caller
    must get the distinct error immediately, without sleep-retry loops."""
    with patch("backend.services.github_service.subprocess.run",
               side_effect=_called_process_error(RATE_LIMIT_STDERR)) as mock_run, \
         patch("backend.services.github_service.time.sleep") as mock_sleep:
        with pytest.raises(RateLimitError):
            run_gh_command(["pr", "view", "1"])
    assert mock_run.call_count == 1
    mock_sleep.assert_not_called()


def test_rate_limit_error_is_a_runtime_error():
    """Existing callers catch RuntimeError; the subclass must not escape them."""
    assert issubclass(RateLimitError, RuntimeError)


# --- fetch_pr_head_sha --------------------------------------------------------

def test_fetch_pr_head_sha_swallows_rate_limit_by_default():
    with patch("backend.services.github_service.run_gh_command",
               side_effect=RateLimitError("rate limited")):
        assert fetch_pr_head_sha("acme", "widgets", 7) is None


def test_fetch_pr_head_sha_raises_when_asked():
    with patch("backend.services.github_service.run_gh_command",
               side_effect=RateLimitError("rate limited")):
        with pytest.raises(RateLimitError):
            fetch_pr_head_sha("acme", "widgets", 7, raise_on_rate_limit=True)


def test_fetch_pr_head_sha_still_swallows_other_errors_when_raising():
    with patch("backend.services.github_service.run_gh_command",
               side_effect=RuntimeError("gh command failed: Not Found")):
        assert fetch_pr_head_sha("acme", "widgets", 7, raise_on_rate_limit=True) is None


# --- fetch_open_prs_head_shas -------------------------------------------------

def test_fetch_open_prs_head_shas_maps_number_to_sha():
    with patch("backend.services.github_service.run_gh_command") as mock_run:
        mock_run.return_value = (
            '[{"number": 7, "headRefOid": "abc123"},'
            ' {"number": 8, "headRefOid": "def456"}]'
        )
        shas = fetch_open_prs_head_shas("acme", "widgets")

    assert shas == {7: "abc123", 8: "def456"}
    args = mock_run.call_args[0][0]
    assert args[:2] == ["pr", "list"]
    assert "--state" in args and "open" in args
    json_idx = args.index("--json")
    assert args[json_idx + 1] == "number,headRefOid"


def test_fetch_open_prs_head_shas_returns_none_on_error():
    """None means 'unknown', never 'no open PRs' — the follow-up watcher must
    skip the cycle rather than treat every armed PR as closed."""
    with patch("backend.services.github_service.run_gh_command",
               side_effect=RateLimitError("rate limited")):
        assert fetch_open_prs_head_shas("acme", "widgets") is None


# --- post_verdict -------------------------------------------------------------

def test_post_verdict_returns_429_when_sha_fetch_is_rate_limited(monkeypatch):
    def raise_rate_limit(*args, **kwargs):
        raise RateLimitError("rate limited")
    monkeypatch.setattr(verdict_service, "fetch_pr_head_sha", raise_rate_limit)

    result, status = verdict_service.post_verdict("acme", "widgets", 7, "APPROVE", "body")

    assert status == 429
    assert result.get("rate_limited") is True


def test_post_verdict_returns_429_when_github_post_is_rate_limited(monkeypatch):
    monkeypatch.setattr(verdict_service, "fetch_pr_head_sha", lambda *a, **k: "sha123")
    with patch("backend.services.verdict_service.subprocess.run",
               side_effect=_called_process_error("API rate limit exceeded")):
        result, status = verdict_service.post_verdict("acme", "widgets", 7, "APPROVE", "body")

    assert status == 429
    assert result.get("rate_limited") is True


def test_post_verdict_other_post_failures_stay_500(monkeypatch):
    monkeypatch.setattr(verdict_service, "fetch_pr_head_sha", lambda *a, **k: "sha123")
    with patch("backend.services.verdict_service.subprocess.run",
               side_effect=_called_process_error("HTTP 403: Forbidden")):
        result, status = verdict_service.post_verdict("acme", "widgets", 7, "APPROVE", "body")

    assert status == 500
    assert "rate_limited" not in result
