"""Tests for the auto-verdict criteria evaluator."""

import json

import pytest

from backend.services.auto_verdict_config import (
    DEFAULT_CRITERIA,
    OVERRIDE_KEYS,
    apply_override,
    get_criteria,
    upgrade_legacy_criteria,
    validate_criteria,
    validate_override,
)
from backend.services.auto_verdict_service import (
    compose_report_body,
    count_issues,
    evaluate_criteria,
    _load_review_content,
)


def _issues(n):
    return [
        {
            "title": f"Issue {i}",
            "location": {"file": "src/lib.rs", "start_line": i, "end_line": i},
            "problem": "Something is wrong.",
            "fix": "Fix it.",
        }
        for i in range(n)
    ]


def _set_aside(severities, kind):
    return [
        dict(issue, title=f"{kind} {i}", severity=sev, disposition=f"author: {kind} {i}")
        for i, (issue, sev) in enumerate(zip(_issues(len(severities)), severities))
    ]


def _review(blocking=0, non_blocking=0, disputed=(), deferred=()):
    """Build a two-tier review; `disputed`/`deferred` are tuples of the original
    severities of the issues set aside in those sections."""
    sections = [
        {"type": "blocking", "display_name": "Blocking Issues", "issues": _issues(blocking)},
        {"type": "non_blocking", "display_name": "Non-Blocking Issues", "issues": _issues(non_blocking)},
    ]
    if disputed:
        sections.append({"type": "disputed", "display_name": "Disputed",
                         "issues": _set_aside(disputed, "Disputed")})
    if deferred:
        sections.append({"type": "deferred", "display_name": "Deferred",
                         "issues": _set_aside(deferred, "Deferred")})
    return {
        "schema_version": "2.0.0",
        "metadata": {"pr_number": 42, "repository": "owner/repo"},
        "summary": "A summary of the review.",
        "sections": sections,
        "score": {"overall": 7},
    }


def _legacy_review(critical=0, major=0, minor=0, disputed=()):
    """A pre-2.0.0 document as still stored in old backups / emitted by
    not-yet-updated agents."""
    sections = [
        {"type": "critical", "display_name": "Critical Issues", "issues": _issues(critical)},
        {"type": "major", "display_name": "Major Concerns", "issues": _issues(major)},
        {"type": "minor", "display_name": "Minor Issues", "issues": _issues(minor)},
    ]
    if disputed:
        sections.append({"type": "disputed", "display_name": "Disputed",
                         "issues": _set_aside(disputed, "Disputed")})
    return {
        "schema_version": "1.0.0",
        "metadata": {"pr_number": 42, "repository": "owner/repo"},
        "summary": "A summary of the review.",
        "sections": sections,
        "score": {"overall": 7},
    }


def _tallies(blocking=0, non_blocking=0, disputed=0, disputed_blocking=0, deferred=0):
    return {"blocking": blocking, "non_blocking": non_blocking,
            "disputed": disputed, "disputed_blocking": disputed_blocking, "deferred": deferred}


def _criteria(**overrides):
    criteria = dict(DEFAULT_CRITERIA)
    criteria.update(overrides)
    return criteria


# --- count_issues -----------------------------------------------------------

def test_count_issues_counts_each_tier():
    assert count_issues(_review(blocking=2, non_blocking=5)) == _tallies(2, 5)


def test_count_issues_handles_missing_sections():
    assert count_issues({}) == _tallies()


def test_count_issues_ignores_unknown_section_types():
    review = {"sections": [{"type": "nitpick", "issues": [{"title": "x"}]}]}
    assert count_issues(review) == _tallies()


def test_count_issues_keeps_deferred_findings_out_of_the_tally():
    """3 blocking findings, 2 of them properly deferred -> 1 against maxBlocking."""
    review = _review(blocking=1, deferred=("blocking", "blocking"))
    assert count_issues(review) == _tallies(blocking=1, deferred=2)


def test_count_issues_counts_disputed_blocking_findings():
    review = _review(disputed=("blocking", "blocking", "non_blocking"))
    assert count_issues(review) == _tallies(disputed=3, disputed_blocking=2)


def test_count_issues_reads_severity_case_insensitively():
    review = _review(disputed=("Blocking",))
    assert count_issues(review)["disputed_blocking"] == 1


def test_count_issues_folds_legacy_tiers():
    review = _legacy_review(critical=1, major=2, minor=3, disputed=("major", "minor"))
    assert count_issues(review) == _tallies(blocking=3, non_blocking=3, disputed=2, disputed_blocking=1)


# --- evaluate_criteria: the defaults ------------------------------------------

@pytest.mark.parametrize("blocking,non_blocking,expected", [
    (0, 0, "pass"),                 # clean review
    (1, 0, "request_changes"),      # a single blocking finding trips maxBlocking=0
    (0, 50, "pass"),                # non-blocking is unlimited by default
    (0, 500, "pass"),
    (3, 7, "request_changes"),
])
def test_evaluate_criteria_with_defaults(blocking, non_blocking, expected):
    decision, _, _ = evaluate_criteria(_review(blocking, non_blocking), _criteria())
    assert decision == expected


def test_thresholds_are_inclusive_upper_bounds():
    """maxBlocking=1 means one blocking finding is allowed; two are not."""
    criteria = _criteria(maxBlocking=1)
    assert evaluate_criteria(_review(blocking=1), criteria)[0] == "pass"
    assert evaluate_criteria(_review(blocking=2), criteria)[0] == "request_changes"


def test_non_blocking_limit_is_enforced_when_set():
    criteria = _criteria(maxNonBlocking=2)
    assert evaluate_criteria(_review(non_blocking=2), criteria)[0] == "pass"
    decision, _, reason = evaluate_criteria(_review(non_blocking=3), criteria)
    assert decision == "request_changes"
    assert "3 non-blocking > 2 allowed" in reason


def test_legacy_content_is_evaluated_as_two_tier():
    decision, tallies, _ = evaluate_criteria(_legacy_review(major=1), _criteria())
    assert decision == "request_changes"
    assert tallies["blocking"] == 1


def test_tallies_are_returned_alongside_the_decision():
    _, tallies, _ = evaluate_criteria(_review(blocking=2, non_blocking=3), _criteria())
    assert tallies == _tallies(2, 3)


# --- disputed / deferred and the mediation threshold ------------------------

def test_disputed_findings_below_the_threshold_do_not_count():
    criteria = _criteria(maxBlocking=1)
    decision, _, _ = evaluate_criteria(_review(blocking=1, disputed=("blocking", "blocking")), criteria)
    assert decision == "pass"


def test_deferred_findings_never_count():
    criteria = _criteria(maxBlocking=1)
    decision, _, _ = evaluate_criteria(
        _review(blocking=1, deferred=("blocking", "blocking", "blocking")), criteria)
    assert decision == "pass"


def test_three_disputed_blocking_findings_route_to_mediation():
    criteria = _criteria(maxBlocking=1)
    decision, tallies, reason = evaluate_criteria(
        _review(blocking=1, disputed=("blocking", "blocking", "blocking")), criteria)
    assert decision == "mediation"
    assert tallies["disputed_blocking"] == 3
    assert "3 disputed blocking" in reason and "mediation" in reason


def test_disputed_non_blocking_findings_never_trigger_mediation():
    decision, _, _ = evaluate_criteria(_review(disputed=("non_blocking",) * 5), _criteria())
    assert decision == "pass"


def test_mediation_is_checked_before_severity_thresholds():
    decision, _, _ = evaluate_criteria(_review(blocking=8, disputed=("blocking",) * 3), _criteria())
    assert decision == "mediation"


def test_mediation_threshold_is_configurable():
    criteria = _criteria(mediationDisputedThreshold=5)
    assert evaluate_criteria(_review(disputed=("blocking",) * 4), criteria)[0] == "pass"
    assert evaluate_criteria(_review(disputed=("blocking",) * 5), criteria)[0] == "mediation"


def test_pass_reason_mentions_set_aside_counts_only_when_present():
    _, _, reason = evaluate_criteria(
        _review(disputed=("blocking",), deferred=("non_blocking", "non_blocking")), _criteria())
    assert "1 disputed" in reason and "2 deferred" in reason
    _, _, clean = evaluate_criteria(_review(), _criteria())
    assert "disputed" not in clean and "deferred" not in clean


def test_reason_names_the_breached_tier():
    _, _, reason = evaluate_criteria(_review(blocking=2), _criteria())
    assert "2 blocking > 0 allowed" in reason


def test_reason_on_pass_reports_counts_and_limits():
    _, _, reason = evaluate_criteria(_review(non_blocking=3), _criteria())
    assert "0 blocking, 3 non-blocking" in reason
    assert "within limits (0/unlimited)" in reason
    _, _, capped = evaluate_criteria(_review(non_blocking=3), _criteria(maxNonBlocking=5))
    assert "within limits (0/5)" in capped


# --- content loading guards -------------------------------------------------

def test_error_stub_is_rejected():
    """The stub save_review_to_db writes for failed reviews must not be evaluated."""
    stub = {"schema_version": "2.0.0", "error": True, "sections": [], "score": {"overall": 0}}
    assert _load_review_content({"content_json": stub}) is None


def test_unparsable_content_is_rejected():
    assert _load_review_content({"content_json": "not json"}) is None
    assert _load_review_content({"content_json": None}) is None


def test_valid_content_is_parsed_from_a_json_string():
    parsed = _load_review_content({"content_json": json.dumps(_review(blocking=1))})
    assert count_issues(parsed) == _tallies(blocking=1)


def test_legacy_content_is_normalized_on_load():
    parsed = _load_review_content({"content_json": json.dumps(_legacy_review(critical=1, major=1))})
    assert [s["type"] for s in parsed["sections"]] == ["blocking", "non_blocking"]
    assert parsed["schema_version"] == "2.0.0"


# --- body composition -------------------------------------------------------

def test_report_body_contains_summary_and_issues():
    body = compose_report_body(_review(blocking=1, non_blocking=2))
    assert "A summary of the review." in body
    assert "Blocking Issues" in body
    assert "Non-Blocking Issues" in body


def test_report_body_excludes_score_metadata_and_empty_sections():
    """The auto verdict body must match a manually posted verdict: no title,
    metadata block, or 0-10 score, and no 'None' entries for empty sections."""
    body = compose_report_body(_review(blocking=1))
    assert "Score" not in body
    assert "/10" not in body
    assert "# Code Review" not in body
    assert "**Repository**" not in body
    assert "Non-Blocking Issues" not in body  # empty section is omitted, not 'None'


def test_report_body_is_truncated_for_github():
    from backend.services import auto_verdict_service as svc

    huge = _review()
    huge["summary"] = "x" * (svc.MAX_BODY_CHARS + 5000)
    body = compose_report_body(huge)
    assert len(body) <= svc.MAX_BODY_CHARS + len(svc._TRUNCATION_NOTICE)
    assert "truncated" in body


# --- config validation ------------------------------------------------------

def test_default_criteria_are_two_tier():
    assert DEFAULT_CRITERIA["maxBlocking"] == 0
    assert DEFAULT_CRITERIA["maxNonBlocking"] is None
    assert not {"maxCritical", "maxMajor", "maxMinor"} & set(DEFAULT_CRITERIA)
    assert OVERRIDE_KEYS == (
        "maxBlocking", "maxNonBlocking", "allowAutoApprove", "autoFollowupReview",
        "mediationDisputedThreshold")


def test_validate_criteria_coerces_and_fills_defaults():
    result = validate_criteria({"maxBlocking": "2", "enabled": 1})
    assert result["maxBlocking"] == 2
    assert result["enabled"] is True
    assert result["maxNonBlocking"] is None


@pytest.mark.parametrize("value,expected", [(None, None), ("", None), ("5", 5), (0, 0)])
def test_validate_criteria_accepts_nullable_non_blocking_limit(value, expected):
    assert validate_criteria({"maxNonBlocking": value})["maxNonBlocking"] == expected


def test_validate_criteria_rejects_null_blocking_limit():
    with pytest.raises(ValueError):
        validate_criteria({"maxBlocking": None})


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


@pytest.mark.parametrize("payload", [{"maxBlocking": -1}, {"maxNonBlocking": -1}])
def test_validate_criteria_rejects_negative_thresholds(payload):
    with pytest.raises(ValueError):
        validate_criteria(payload)


@pytest.mark.parametrize("payload", [{"maxBlocking": "many"}, {"maxNonBlocking": "many"}])
def test_validate_criteria_rejects_non_integer_thresholds(payload):
    with pytest.raises(ValueError):
        validate_criteria(payload)


# --- legacy criteria upgrade --------------------------------------------------

def test_upgrade_legacy_criteria_sums_critical_and_major_and_unlimits_non_blocking():
    upgraded = upgrade_legacy_criteria(
        {"enabled": True, "maxCritical": 0, "maxMajor": 1, "maxMinor": 99, "allowAutoApprove": True})
    assert upgraded == {"enabled": True, "maxBlocking": 1, "maxNonBlocking": None, "allowAutoApprove": True}


def test_upgrade_legacy_criteria_treats_missing_legacy_keys_as_zero():
    assert upgrade_legacy_criteria({"maxCritical": 5})["maxBlocking"] == 5
    assert upgrade_legacy_criteria({"maxMajor": 2})["maxBlocking"] == 2
    assert upgrade_legacy_criteria({"maxMinor": 3}) == {"maxBlocking": 0, "maxNonBlocking": None}


def test_upgrade_legacy_criteria_passes_two_tier_input_through():
    current = {"maxBlocking": 2, "maxNonBlocking": 4, "enabled": False}
    assert upgrade_legacy_criteria(current) == current


def test_get_criteria_upgrades_a_legacy_stored_config(monkeypatch):
    import backend.database as db_pkg

    class FakeSettings:
        def get_setting(self, key):
            return {"enabled": True, "maxCritical": 0, "maxMajor": 1, "maxMinor": 99,
                    "allowAutoApprove": True, "autoFollowupReview": True}

    monkeypatch.setattr(db_pkg, "get_settings_db", lambda: FakeSettings())
    criteria = get_criteria()
    assert criteria["maxBlocking"] == 1
    assert criteria["maxNonBlocking"] is None
    assert criteria["enabled"] is True
    assert "maxMajor" not in criteria


def test_validate_criteria_upgrades_a_legacy_payload():
    assert validate_criteria({"maxCritical": 1, "maxMajor": 1, "maxMinor": 9})["maxBlocking"] == 2


# --- per-PR overrides ---------------------------------------------------------

def test_validate_override_excludes_the_master_switch():
    override = validate_override({"maxBlocking": 2, "enabled": True})
    assert "enabled" not in override
    assert override["maxBlocking"] == 2


def test_validate_override_fills_defaults_for_missing_fields():
    override = validate_override({"maxBlocking": 3})
    assert override["maxBlocking"] == 3
    assert override["maxNonBlocking"] is None
    assert override["allowAutoApprove"] is False


def test_validate_override_rejects_negative_thresholds():
    with pytest.raises(ValueError):
        validate_override({"maxBlocking": -1})


def test_apply_override_without_stored_override_returns_base_unchanged():
    base = _criteria(enabled=True, maxBlocking=1)
    assert apply_override(base, {"auto_verdict_criteria": None}) == base
    assert apply_override(base, {}) == base


def test_apply_override_replaces_thresholds_and_flags():
    base = _criteria(enabled=True, maxBlocking=0, allowAutoApprove=False)
    item = {"auto_verdict_criteria": json.dumps(
        {"maxBlocking": 5, "maxNonBlocking": 10,
         "allowAutoApprove": True, "autoFollowupReview": True}
    )}
    effective = apply_override(base, item)
    assert effective["maxBlocking"] == 5
    assert effective["maxNonBlocking"] == 10
    assert effective["allowAutoApprove"] is True
    assert effective["autoFollowupReview"] is True


def test_apply_override_can_lift_a_global_non_blocking_cap():
    base = _criteria(maxNonBlocking=2)
    effective = apply_override(base, {"auto_verdict_criteria": json.dumps({"maxNonBlocking": None})})
    assert effective["maxNonBlocking"] is None


def test_apply_override_upgrades_a_legacy_stored_override():
    base = _criteria(maxBlocking=0)
    item = {"auto_verdict_criteria": json.dumps({"maxCritical": 2, "maxMajor": 3, "maxMinor": 10})}
    effective = apply_override(base, item)
    assert effective["maxBlocking"] == 5
    assert effective["maxNonBlocking"] is None
    assert "maxCritical" not in effective


def test_apply_override_never_overrides_enabled():
    base = _criteria(enabled=False)
    item = {"auto_verdict_criteria": json.dumps({"enabled": True, "maxBlocking": 5})}
    assert apply_override(base, item)["enabled"] is False


def test_apply_override_ignores_malformed_json():
    base = _criteria(enabled=True)
    assert apply_override(base, {"auto_verdict_criteria": "not json"}) == base
    assert apply_override(base, {"auto_verdict_criteria": '["a-list"]'}) == base


def test_apply_override_does_not_mutate_the_base():
    base = _criteria(maxBlocking=0)
    apply_override(base, {"auto_verdict_criteria": json.dumps({"maxBlocking": 9})})
    assert base["maxBlocking"] == 0


def _with_followup(review, statuses):
    review = dict(review)
    review["followup"] = {"previous_review_id": 1, "resolution_status": [
        {"issue": f"Issue {i}", "status": s, "notes": f"note {i}"} for i, s in enumerate(statuses)
    ]}
    return review


def test_report_body_includes_dispositions_for_followups():
    body = compose_report_body(_with_followup(_review(blocking=1), ["withdrawn", "disputed", "resolved"]))
    assert "**Dispositions**" in body
    assert "Withdrawn" in body and "Disputed" in body and "Resolved" in body
    assert "Issue 0" in body and "note 1" in body
    # Dispositions follow the findings so the author reads the verdict first.
    assert body.index("**Blocking Issues**") < body.index("**Dispositions**")


def test_report_body_has_no_dispositions_section_without_followup():
    assert "Dispositions" not in compose_report_body(_review(blocking=1))


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
    review = _review(non_blocking=1)
    review["summary"] = "Solid design.\n\n**Verdict-leaning: Approved-leaning** — zero Critical findings\n"
    body = compose_report_body(review)
    assert "Solid design." in body
    assert "Approved-leaning" not in body and "Verdict" not in body
