"""Tests for the commit-sync + history-walk GitHub fetchers."""
from unittest.mock import patch

import pytest

from backend.services.github_service import (
    fetch_commits_page, fetch_graphql_remaining, fetch_repo_created_at,
)


def test_fetch_repo_created_at_returns_stripped_string():
    with patch("backend.services.github_service.run_gh_command") as mock_run:
        mock_run.return_value = "2015-03-04T12:00:00Z"
        assert fetch_repo_created_at("acme", "widgets") == "2015-03-04T12:00:00Z"
    args = mock_run.call_args[0][0]
    assert args == ["api", "repos/acme/widgets", "--jq", ".created_at"]


def test_fetch_repo_created_at_returns_none_on_error():
    with patch("backend.services.github_service.run_gh_command", side_effect=RuntimeError("boom")):
        assert fetch_repo_created_at("acme", "widgets") is None


def test_fetch_repo_created_at_returns_none_on_empty_output():
    with patch("backend.services.github_service.run_gh_command", return_value=""):
        assert fetch_repo_created_at("acme", "widgets") is None


def test_fetch_graphql_remaining_returns_int():
    with patch("backend.services.github_service.run_gh_command", return_value="4321"):
        assert fetch_graphql_remaining() == 4321


def test_fetch_graphql_remaining_returns_none_on_error():
    with patch("backend.services.github_service.run_gh_command", side_effect=RuntimeError("boom")):
        assert fetch_graphql_remaining() is None


def test_fetch_graphql_remaining_returns_none_on_garbage_output():
    with patch("backend.services.github_service.run_gh_command", return_value="not-a-number"):
        assert fetch_graphql_remaining() is None


def test_fetch_commits_page_builds_url_and_parses():
    with patch("backend.services.github_service.run_gh_command") as mock_run:
        mock_run.return_value = (
            '[{"sha": "abc", "login": "alice", "name": "Alice", "email": "a@x.com",'
            ' "authored_at": "2026-01-01T00:00:00Z", "committed_at": "2026-01-01T00:00:00Z",'
            ' "parents": 1}]'
        )
        rows = fetch_commits_page("acme", "widgets", "main", 2)
    assert rows[0]["sha"] == "abc"
    args = mock_run.call_args[0][0]
    assert args[0] == "api"
    url = args[1]
    assert url.startswith("repos/acme/widgets/commits?sha=main&per_page=100&page=2")
    assert "--jq" in args


def test_fetch_commits_page_encodes_since_and_until():
    with patch("backend.services.github_service.run_gh_command") as mock_run:
        mock_run.return_value = "[]"
        fetch_commits_page(
            "acme", "widgets", "main", 1,
            since="2026-01-01T00:00:00Z", until="2026-02-01T00:00:00Z",
        )
    url = mock_run.call_args[0][0][1]
    assert "since=2026-01-01T00%3A00%3A00Z" in url
    assert "until=2026-02-01T00%3A00%3A00Z" in url


def test_fetch_commits_page_encodes_branch():
    with patch("backend.services.github_service.run_gh_command") as mock_run:
        mock_run.return_value = "[]"
        fetch_commits_page("acme", "widgets", "feature/foo", 1)
    url = mock_run.call_args[0][0][1]
    assert "sha=feature%2Ffoo" in url


def test_fetch_commits_page_returns_empty_list_when_no_commits():
    with patch("backend.services.github_service.run_gh_command", return_value=""):
        assert fetch_commits_page("acme", "widgets", "main", 1) == []


def test_fetch_commits_page_propagates_errors():
    with patch("backend.services.github_service.run_gh_command", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            fetch_commits_page("acme", "widgets", "main", 1)
