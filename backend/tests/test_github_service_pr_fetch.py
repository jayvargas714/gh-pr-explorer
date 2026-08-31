"""Tests for shared PR fetch helpers."""
from unittest.mock import patch

import pytest

from backend.services.github_service import (
    PR_LIST_JSON_FIELDS, fetch_full_pr, fetch_pr_numbers,
)
from backend.filters.pr_filter_builder import PRFilterParams, PRFilterBuilder


def test_field_constant_covers_todays_fields():
    for field in ("number", "reviews", "statusCheckRollup", "milestone", "body"):
        assert field in PR_LIST_JSON_FIELDS


def test_fetch_full_pr_builds_view_command():
    with patch("backend.services.github_service.run_gh_command") as mock_run:
        mock_run.return_value = '{"number": 7, "state": "OPEN"}'
        pr = fetch_full_pr("acme", "widgets", 7)
    assert pr["number"] == 7
    args = mock_run.call_args[0][0]
    assert args[:3] == ["pr", "view", "7"]
    assert "-R" in args and "acme/widgets" in args
    assert PR_LIST_JSON_FIELDS in args


def test_fetch_full_pr_propagates_errors():
    with patch("backend.services.github_service.run_gh_command", side_effect=RuntimeError("gh command failed: Not Found")):
        with pytest.raises(RuntimeError):
            fetch_full_pr("acme", "widgets", 7)


def test_fetch_pr_numbers_parses_and_orders():
    with patch("backend.services.github_service.run_gh_command") as mock_run:
        mock_run.return_value = '[{"number": 5}, {"number": 3}]'
        numbers = fetch_pr_numbers("acme", "widgets", state="all", search="updated:>=2026-01-01")
    assert numbers == [5, 3]
    args = mock_run.call_args[0][0]
    assert "--json" in args and "number" in args
    assert "--search" in args and "updated:>=2026-01-01" in args
    assert "--limit" in args and "1000" in args


def test_builder_json_fields_override():
    params = PRFilterParams()
    args = PRFilterBuilder("acme", "widgets", params).build(json_fields="number")
    json_idx = args.index("--json")
    assert args[json_idx + 1] == "number"
    default_args = PRFilterBuilder("acme", "widgets", params).build()
    default_idx = default_args.index("--json")
    assert default_args[default_idx + 1] == PR_LIST_JSON_FIELDS


def test_fetch_pr_files_returns_paths():
    from backend.services.github_service import fetch_pr_files
    with patch("backend.services.github_service.run_gh_command") as mock_run:
        mock_run.return_value = "briefs/PB-008-a.md\nbriefs/PB-000-index.md"
        files = fetch_pr_files("acme", "widgets", 7)
    assert files == ["briefs/PB-008-a.md", "briefs/PB-000-index.md"]
    args = mock_run.call_args[0][0]
    assert args[0] == "api"
    assert "repos/acme/widgets/pulls/7/files" in args
    assert "--paginate" in args


def test_fetch_pr_files_empty_pr():
    from backend.services.github_service import fetch_pr_files
    with patch("backend.services.github_service.run_gh_command") as mock_run:
        mock_run.return_value = ""
        assert fetch_pr_files("acme", "widgets", 7) == []


def test_fetch_pr_files_propagates_errors():
    from backend.services.github_service import fetch_pr_files
    with patch("backend.services.github_service.run_gh_command", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            fetch_pr_files("acme", "widgets", 7)
