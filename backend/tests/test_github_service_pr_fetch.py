"""Tests for shared PR fetch helpers."""
from unittest.mock import patch

import pytest

from backend.services.github_service import (
    PR_LIST_JSON_FIELDS, fetch_full_pr, fetch_open_prs_queue_data, fetch_pr_numbers,
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


def test_fetch_open_prs_queue_data_maps_by_number():
    with patch("backend.services.github_service.run_gh_command") as mock_run:
        mock_run.return_value = (
            '[{"number": 7, "state": "OPEN", "isDraft": true, "statusCheckRollup": []},'
            ' {"number": 8, "state": "OPEN", "isDraft": false,'
            '  "statusCheckRollup": [{"name": "ci", "conclusion": "SUCCESS"}]}]'
        )
        data = fetch_open_prs_queue_data("acme", "widgets")

    args = mock_run.call_args[0][0]
    assert args[:2] == ["pr", "list"]
    assert "--state" in args and "open" in args
    assert set(data) == {7, 8}
    assert data[7]["isDraft"] is True
    assert data[7]["state"] == "OPEN"
    assert data[8]["statusCheckRollup"][0]["conclusion"] == "SUCCESS"


def test_fetch_open_prs_queue_data_returns_none_on_error():
    """A failed batch fetch must be distinguishable from a repo with no open
    PRs — callers would otherwise mass-skip the whole pipeline."""
    with patch("backend.services.github_service.run_gh_command",
               side_effect=RuntimeError("gh command failed: rate limited")):
        assert fetch_open_prs_queue_data("acme", "widgets") is None


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


def test_fetch_pr_behind_by_parses_compare():
    from backend.services.github_service import fetch_pr_behind_by
    with patch("backend.services.github_service.run_gh_command") as mock_run:
        mock_run.return_value = "7"
        behind = fetch_pr_behind_by("acme", "widgets", "main", "feature-x")
    assert behind == 7
    args = mock_run.call_args[0][0]
    assert args[0] == "api"
    assert "repos/acme/widgets/compare/main...feature-x" in args


def test_fetch_pr_behind_by_propagates_errors():
    from backend.services.github_service import fetch_pr_behind_by
    with patch("backend.services.github_service.run_gh_command", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            fetch_pr_behind_by("acme", "widgets", "main", "feature-x")
