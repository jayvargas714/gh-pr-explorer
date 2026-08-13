"""Tests for the auto-verdict criteria evaluator."""

import pytest

from backend.services.auto_verdict_config import (
    DEFAULT_CRITERIA,
    validate_criteria,
)
from backend.services.auto_verdict_service import (
    compose_report_body,
    count_issues,
    evaluate_criteria,
    _load_review_content,
)


def _review(critical=0, major=0, minor=0):
    def issues(n):
        return [
            {
                "title": f"Issue {i}",
                "location": {"file": "src/lib.rs", "start_line": i, "end_line": i},
                "problem": "Something is wrong.",
                "fix": "Fix it.",
            }
            for i in range(n)
        ]

    return {
        "schema_version": "1.0.0",
        "metadata": {"pr_number": 42, "repository": "owner/repo"},
        "summary": "A summary of the review.",
        "sections": [
            {"type": "critical", "display_name": "Critical Issues", "issues": issues(critical)},
            {"type": "major", "display_name": "Major Concerns", "issues": issues(major)},
            {"type": "minor", "display_name": "Minor Issues", "issues": issues(minor)},
        ],
        "score": {"overall": 7},
    }


def _criteria(**overrides):
    criteria = dict(DEFAULT_CRITERIA)
    criteria.update(overrides)
    return criteria


# --- count_issues -----------------------------------------------------------

def test_count_issues_counts_each_severity():
    assert count_issues(_review(critical=2, major=1, minor=5)) == {
        "critical": 2, "major": 1, "minor": 5
    }


def test_count_issues_handles_missing_sections():
    assert count_issues({}) == {"critical": 0, "major": 0, "minor": 0}


def test_count_issues_ignores_unknown_section_types():
    review = {"sections": [{"type": "nitpick", "issues": [{"title": "x"}]}]}
    assert count_issues(review) == {"critical": 0, "major": 0, "minor": 0}


# --- evaluate_criteria: the defaults the user described ----------------------

@pytest.mark.parametrize("critical,major,minor,expected", [
    (0, 0, 0, "pass"),          # clean review
    (1, 0, 0, "request_changes"),  # a single critical blocks
    (0, 1, 0, "request_changes"),  # a single major blocks at maxMajor=0
    (0, 0, 50, "pass"),         # minors are effectively unlimited at 99
    (0, 0, 99, "pass"),         # exactly at the minor limit still passes
    (0, 0, 100, "request_changes"),  # one over the minor limit trips
    (3, 2, 7, "request_changes"),
])
def test_evaluate_criteria_with_defaults(critical, major, minor, expected):
    decision, _, _ = evaluate_criteria(_review(critical, major, minor), _criteria())
    assert decision == expected


def test_thresholds_are_inclusive_upper_bounds():
    """maxMajor=1 means one major is allowed; two is not."""
    criteria = _criteria(maxMajor=1)
    assert evaluate_criteria(_review(major=1), criteria)[0] == "pass"
    assert evaluate_criteria(_review(major=2), criteria)[0] == "request_changes"


def test_tallies_are_returned_alongside_the_decision():
    _, tallies, _ = evaluate_criteria(_review(critical=2, major=1, minor=3), _criteria())
    assert tallies == {"critical": 2, "major": 1, "minor": 3}


def test_reason_names_every_breached_severity():
    _, _, reason = evaluate_criteria(_review(critical=2, major=1), _criteria())
    assert "2 critical > 0 allowed" in reason
    assert "1 major > 0 allowed" in reason


def test_reason_on_pass_reports_counts_and_limits():
    _, _, reason = evaluate_criteria(_review(minor=3), _criteria())
    assert "3 minor" in reason
    assert "within limits (0/0/99)" in reason


# --- content loading guards -------------------------------------------------

def test_error_stub_is_rejected():
    """The stub save_review_to_db writes for failed reviews must not be evaluated."""
    stub = {"schema_version": "1.0.0", "error": True, "sections": [], "score": {"overall": 0}}
    assert _load_review_content({"content_json": stub}) is None


def test_unparsable_content_is_rejected():
    assert _load_review_content({"content_json": "not json"}) is None
    assert _load_review_content({"content_json": None}) is None


def test_valid_content_is_parsed_from_a_json_string():
    import json
    parsed = _load_review_content({"content_json": json.dumps(_review(critical=1))})
    assert count_issues(parsed) == {"critical": 1, "major": 0, "minor": 0}


# --- body composition -------------------------------------------------------

def test_report_body_contains_summary_and_issues():
    body = compose_report_body(_review(critical=1, minor=2))
    assert "A summary of the review." in body
    assert "Critical Issues" in body
    assert "Minor Issues" in body


def test_report_body_excludes_score_metadata_and_empty_sections():
    """The auto verdict body must match a manually posted verdict: no title,
    metadata block, or 0-10 score, and no 'None' entries for empty sections."""
    body = compose_report_body(_review(critical=1))
    assert "Score" not in body
    assert "/10" not in body
    assert "# Code Review" not in body
    assert "**Repository**" not in body
    assert "Major Concerns" not in body  # empty section is omitted, not 'None'


def test_report_body_is_truncated_for_github():
    from backend.services import auto_verdict_service as svc

    huge = _review()
    huge["summary"] = "x" * (svc.MAX_BODY_CHARS + 5000)
    body = compose_report_body(huge)
    assert len(body) <= svc.MAX_BODY_CHARS + len(svc._TRUNCATION_NOTICE)
    assert "truncated" in body


# --- config validation ------------------------------------------------------

def test_validate_criteria_coerces_and_fills_defaults():
    result = validate_criteria({"maxCritical": "2", "enabled": 1})
    assert result["maxCritical"] == 2
    assert result["enabled"] is True
    assert result["maxMinor"] == DEFAULT_CRITERIA["maxMinor"]


def test_validate_criteria_rejects_negative_thresholds():
    with pytest.raises(ValueError):
        validate_criteria({"maxMajor": -1})


def test_validate_criteria_rejects_non_integer_thresholds():
    with pytest.raises(ValueError):
        validate_criteria({"maxCritical": "many"})
