"""Tests for the auto-verdict criteria evaluator."""

import pytest

from backend.services.auto_verdict_config import (
    DEFAULT_CRITERIA,
    apply_override,
    validate_criteria,
    validate_override,
)
from backend.services.auto_verdict_service import (
    compose_report_body,
    count_issues,
    evaluate_criteria,
    _load_review_content,
)


def _review(critical=0, major=0, minor=0, disputed=(), deferred=()):
    """Build a review; `disputed`/`deferred` are tuples of the original
    severities of the issues set aside in those sections."""
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

    def set_aside(severities, kind):
        return [
            dict(issue, title=f"{kind} {i}", severity=sev, disposition=f"author: {kind} {i}")
            for i, (issue, sev) in enumerate(zip(issues(len(severities)), severities))
        ]

    sections = [
        {"type": "critical", "display_name": "Critical Issues", "issues": issues(critical)},
        {"type": "major", "display_name": "Major Concerns", "issues": issues(major)},
        {"type": "minor", "display_name": "Minor Issues", "issues": issues(minor)},
    ]
    if disputed:
        sections.append({"type": "disputed", "display_name": "Disputed",
                         "issues": set_aside(disputed, "Disputed")})
    if deferred:
        sections.append({"type": "deferred", "display_name": "Deferred",
                         "issues": set_aside(deferred, "Deferred")})
    return {
        "schema_version": "1.0.0",
        "metadata": {"pr_number": 42, "repository": "owner/repo"},
        "summary": "A summary of the review.",
        "sections": sections,
        "score": {"overall": 7},
    }


def _tallies(critical=0, major=0, minor=0, disputed=0, disputed_blocking=0, deferred=0):
    return {"critical": critical, "major": major, "minor": minor,
            "disputed": disputed, "disputed_blocking": disputed_blocking, "deferred": deferred}


def _criteria(**overrides):
    criteria = dict(DEFAULT_CRITERIA)
    criteria.update(overrides)
    return criteria


# --- count_issues -----------------------------------------------------------

def test_count_issues_counts_each_severity():
    assert count_issues(_review(critical=2, major=1, minor=5)) == _tallies(2, 1, 5)


def test_count_issues_handles_missing_sections():
    assert count_issues({}) == _tallies()


def test_count_issues_ignores_unknown_section_types():
    review = {"sections": [{"type": "nitpick", "issues": [{"title": "x"}]}]}
    assert count_issues(review) == _tallies()


def test_count_issues_keeps_deferred_findings_out_of_the_severity_tally():
    """3 majors, 2 of them properly deferred -> 1 major against maxMajor."""
    review = _review(major=1, deferred=("major", "major"))
    assert count_issues(review) == _tallies(major=1, deferred=2)


def test_count_issues_counts_disputed_critical_and_major_as_blocking():
    review = _review(disputed=("critical", "major", "minor"))
    assert count_issues(review) == _tallies(disputed=3, disputed_blocking=2)


def test_count_issues_reads_severity_case_insensitively():
    review = _review(disputed=("Major",))
    assert count_issues(review)["disputed_blocking"] == 1


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
    assert tallies == _tallies(2, 1, 3)


# --- disputed / deferred and the mediation threshold ------------------------

def test_disputed_findings_below_the_threshold_do_not_count():
    criteria = _criteria(maxMajor=1)
    decision, _, _ = evaluate_criteria(_review(major=1, disputed=("major", "major")), criteria)
    assert decision == "pass"


def test_deferred_findings_never_count():
    criteria = _criteria(maxMajor=1)
    decision, _, _ = evaluate_criteria(_review(major=1, deferred=("critical", "major", "major")), criteria)
    assert decision == "pass"


def test_three_disputed_blocking_findings_route_to_mediation():
    criteria = _criteria(maxMajor=1)
    decision, tallies, reason = evaluate_criteria(
        _review(major=1, disputed=("major", "major", "critical")), criteria)
    assert decision == "mediation"
    assert tallies["disputed_blocking"] == 3
    assert "3 disputed" in reason and "mediation" in reason


def test_disputed_minors_never_trigger_mediation():
    decision, _, _ = evaluate_criteria(_review(disputed=("minor",) * 5), _criteria())
    assert decision == "pass"


def test_mediation_is_checked_before_severity_thresholds():
    decision, _, _ = evaluate_criteria(_review(critical=8, disputed=("major",) * 3), _criteria())
    assert decision == "mediation"


def test_mediation_threshold_is_configurable():
    criteria = _criteria(mediationDisputedThreshold=5)
    assert evaluate_criteria(_review(disputed=("major",) * 4), criteria)[0] == "pass"
    assert evaluate_criteria(_review(disputed=("major",) * 5), criteria)[0] == "mediation"


def test_pass_reason_mentions_set_aside_counts_only_when_present():
    _, _, reason = evaluate_criteria(_review(disputed=("major",), deferred=("minor", "minor")), _criteria())
    assert "1 disputed" in reason and "2 deferred" in reason
    _, _, clean = evaluate_criteria(_review(), _criteria())
    assert "disputed" not in clean and "deferred" not in clean


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
    assert count_issues(parsed) == _tallies(critical=1)


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


def test_validate_criteria_coerces_auto_followup_review():
    assert validate_criteria({})["autoFollowupReview"] is False
    assert validate_criteria({"autoFollowupReview": 1})["autoFollowupReview"] is True


def test_validate_criteria_defaults_mediation_threshold_to_three():
    assert DEFAULT_CRITERIA["mediationDisputedThreshold"] == 3
    assert validate_criteria({})["mediationDisputedThreshold"] == 3


@pytest.mark.parametrize("value", [0, -1])
def test_validate_criteria_rejects_mediation_threshold_below_one(value):
    with pytest.raises(ValueError):
        validate_criteria({"mediationDisputedThreshold": value})


def test_mediation_threshold_is_per_pr_overridable():
    assert validate_override({"mediationDisputedThreshold": "4"})["mediationDisputedThreshold"] == 4
    effective = apply_override(_criteria(), {"auto_verdict_criteria": '{"mediationDisputedThreshold": 4}'})
    assert effective["mediationDisputedThreshold"] == 4


def test_validate_criteria_rejects_negative_thresholds():
    with pytest.raises(ValueError):
        validate_criteria({"maxMajor": -1})


def test_validate_criteria_rejects_non_integer_thresholds():
    with pytest.raises(ValueError):
        validate_criteria({"maxCritical": "many"})


# --- per-PR overrides ---------------------------------------------------------

def test_validate_override_excludes_the_master_switch():
    override = validate_override({"maxCritical": 2, "enabled": True})
    assert "enabled" not in override
    assert override["maxCritical"] == 2


def test_validate_override_fills_defaults_for_missing_fields():
    override = validate_override({"maxMajor": 3})
    assert override["maxMajor"] == 3
    assert override["maxMinor"] == DEFAULT_CRITERIA["maxMinor"]
    assert override["allowAutoApprove"] is False


def test_validate_override_rejects_negative_thresholds():
    with pytest.raises(ValueError):
        validate_override({"maxMajor": -1})


def test_apply_override_without_stored_override_returns_base_unchanged():
    base = _criteria(enabled=True, maxCritical=1)
    assert apply_override(base, {"auto_verdict_criteria": None}) == base
    assert apply_override(base, {}) == base


def test_apply_override_replaces_thresholds_and_flags():
    import json
    base = _criteria(enabled=True, maxCritical=0, allowAutoApprove=False)
    item = {"auto_verdict_criteria": json.dumps(
        {"maxCritical": 5, "maxMajor": 2, "maxMinor": 10,
         "allowAutoApprove": True, "autoFollowupReview": True}
    )}
    effective = apply_override(base, item)
    assert effective["maxCritical"] == 5
    assert effective["allowAutoApprove"] is True
    assert effective["autoFollowupReview"] is True


def test_apply_override_never_overrides_enabled():
    import json
    base = _criteria(enabled=False)
    item = {"auto_verdict_criteria": json.dumps({"enabled": True, "maxCritical": 5})}
    assert apply_override(base, item)["enabled"] is False


def test_apply_override_ignores_malformed_json():
    base = _criteria(enabled=True)
    assert apply_override(base, {"auto_verdict_criteria": "not json"}) == base
    assert apply_override(base, {"auto_verdict_criteria": '["a-list"]'}) == base


def test_apply_override_does_not_mutate_the_base():
    import json
    base = _criteria(maxCritical=0)
    apply_override(base, {"auto_verdict_criteria": json.dumps({"maxCritical": 9})})
    assert base["maxCritical"] == 0


def _with_followup(review, statuses):
    review = dict(review)
    review["followup"] = {"previous_review_id": 1, "resolution_status": [
        {"issue": f"Issue {i}", "status": s, "notes": f"note {i}"} for i, s in enumerate(statuses)
    ]}
    return review


def test_report_body_includes_dispositions_for_followups():
    body = compose_report_body(_with_followup(_review(critical=1), ["withdrawn", "disputed", "resolved"]))
    assert "**Dispositions**" in body
    assert "Withdrawn" in body and "Disputed" in body and "Resolved" in body
    assert "Issue 0" in body and "note 1" in body
    # Dispositions follow the findings so the author reads the verdict first.
    assert body.index("**Critical Issues**") < body.index("**Dispositions**")


def test_report_body_has_no_dispositions_section_without_followup():
    assert "Dispositions" not in compose_report_body(_review(critical=1))


# --- verdict lines never reach GitHub --------------------------------------

from backend.services.auto_verdict_service import strip_verdict_lines


@pytest.mark.parametrize("line", [
    "**Verdict-leaning: Approved-leaning** — zero Critical findings",
    "Verdict-leaning: Needs Revision",
    "- Verdict: Approved-leaning (zero Critical)",
    "**Verdict:** ready for live review",
    "Approved-leaning — the ED may proceed to live review.",
    "Recommendation: approve and merge.",
    "LGTM",
])
def test_strip_verdict_lines_drops_a_verdict_line(line):
    summary = f"The ED covers PB-017 §3.\n\n{line}\n\nFive passes ran."
    assert strip_verdict_lines(summary) == "The ED covers PB-017 §3.\n\nFive passes ran."


def test_strip_verdict_lines_keeps_ordinary_prose_that_mentions_a_verdict():
    summary = ("The design is solid.\n"
               "Disputed items are settled at live review, not by this verdict.\n"
               "Two findings were deferred.")
    assert strip_verdict_lines(summary) == summary


def test_report_body_never_carries_a_verdict_line():
    review = _review(minor=1)
    review["summary"] = "Solid design.\n\n**Verdict-leaning: Approved-leaning** — zero Critical findings\n"
    body = compose_report_body(review)
    assert "Solid design." in body
    assert "Approved-leaning" not in body and "Verdict" not in body
