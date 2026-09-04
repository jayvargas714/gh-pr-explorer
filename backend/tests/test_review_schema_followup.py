"""Follow-up resolution statuses in the review schema, incl. author dispositions."""

import json

import pytest

from backend.services.review_schema import (
    RESOLUTION_STATUSES, _parse_followup, format_issue_lines, format_resolution_lines,
    json_to_markdown, markdown_to_json, validate_review_json,
)


def _review(statuses):
    return {
        "schema_version": "1.0.0",
        "metadata": {"pr_number": 1, "repository": "o/r"},
        "summary": "s", "score": {"overall": 7},
        "sections": [],
        "followup": {"previous_review_id": 1, "resolution_status": [
            {"issue": f"Issue {i}", "status": s, "notes": "n"} for i, s in enumerate(statuses)]},
    }


def test_status_vocabulary_has_seven_values():
    assert set(RESOLUTION_STATUSES) == {
        "resolved", "partially_addressed", "not_addressed", "wont_fix", "withdrawn", "disputed",
        "deferred"}


def test_spec_file_enum_matches_code_vocabulary():
    from backend.services.review_schema import SCHEMA_SPEC_PATH
    spec = json.loads(SCHEMA_SPEC_PATH.read_text())
    enum = spec["properties"]["followup"]["properties"]["resolution_status"]["items"]["properties"]["status"]["enum"]
    assert enum == list(RESOLUTION_STATUSES)


def test_validation_still_accepts_disposition_statuses():
    ok, errors = validate_review_json(_review(["withdrawn", "disputed", "deferred"]))
    assert ok, errors


def test_markdown_renders_disposition_statuses():
    md = json_to_markdown(_review(["withdrawn", "disputed"]))
    assert "Withdrawn" in md and "Disputed" in md


def test_markdown_parser_reads_disposition_statuses():
    content = (
        "# Review\n\nThis is a follow-up review.\n\n"
        "- **Null check**: Disputed - author claims upstream guard; guard is not on this path\n"
        "- **Log noise**: Withdrawn - rationale accepted\n"
    )
    followup = _parse_followup(content, {"is_followup": True})
    assert [r["status"] for r in followup["resolution_status"]] == ["disputed", "withdrawn"]


def test_format_resolution_lines():
    lines = format_resolution_lines([
        {"issue": "A", "status": "disputed", "notes": "still wrong"},
        {"issue": "B", "status": "withdrawn"},
    ])
    assert lines == ["- **Disputed** — A: still wrong", "- **Withdrawn** — B"]


# --- disputed / deferred sections ------------------------------------------

def _issue(**extra):
    base = {"title": "Null check", "location": {"file": "a.rs", "start_line": 1, "end_line": 2},
            "problem": "p"}
    base.update(extra)
    return base


def _review_with_sections(sections):
    return {
        "schema_version": "1.0.0",
        "metadata": {"pr_number": 1, "repository": "o/r"},
        "summary": "s", "score": {"overall": 7},
        "sections": sections,
    }


def test_validation_accepts_disputed_and_deferred_sections_with_severity_and_disposition():
    review = _review_with_sections([
        {"type": "disputed", "display_name": "Disputed",
         "issues": [_issue(severity="major", disposition="author: upstream guard covers it")]},
        {"type": "deferred", "display_name": "Deferred",
         "issues": [_issue(severity="Minor", disposition="follow-up PR #99")]},
    ])
    ok, errors = validate_review_json(review)
    assert ok, errors


@pytest.mark.parametrize("bad_issue", [
    _issue(disposition="x"),                          # missing severity
    _issue(severity="nitpick", disposition="x"),      # unknown severity
    _issue(severity="major"),                         # missing disposition
    _issue(severity="major", disposition="  "),       # blank disposition
])
def test_validation_rejects_malformed_disposition_section_issues(bad_issue):
    review = _review_with_sections([{"type": "disputed", "display_name": "Disputed", "issues": [bad_issue]}])
    ok, errors = validate_review_json(review)
    assert not ok
    assert any("sections[0].issues[0]" in e for e in errors), errors


def test_validation_rejects_severity_on_a_severity_section_issue():
    review = _review_with_sections([{"type": "major", "display_name": "Major Concerns",
                                     "issues": [_issue(severity="major")]}])
    ok, errors = validate_review_json(review)
    assert not ok
    assert any("severity" in e for e in errors), errors


def test_format_issue_lines_renders_severity_and_disposition():
    lines = format_issue_lines([_issue(severity="major", disposition="follow-up PR #99")])
    assert "- Severity: Major" in lines
    assert "- Disposition: follow-up PR #99" in lines


def test_format_issue_lines_omits_severity_and_disposition_when_absent():
    lines = format_issue_lines([_issue()])
    assert not any(l.startswith("- Severity") or l.startswith("- Disposition") for l in lines)


def test_markdown_round_trips_disputed_and_deferred_sections():
    review = _review_with_sections([
        {"type": "critical", "display_name": "Critical Issues", "issues": []},
        {"type": "major", "display_name": "Major Concerns", "issues": [_issue(title="Real major")]},
        {"type": "minor", "display_name": "Minor Issues", "issues": []},
        {"type": "disputed", "display_name": "Disputed",
         "issues": [_issue(title="Guard", severity="major", disposition="author says upstream")]},
        {"type": "deferred", "display_name": "Deferred",
         "issues": [_issue(title="Rename", severity="minor", disposition="PR #99")]},
    ])
    md = json_to_markdown(review)
    assert "**Disputed**" in md and "**Deferred**" in md
    parsed = markdown_to_json(md, {"pr_number": 1, "repository": "o/r"})
    by_type = {s["type"]: s for s in parsed["sections"]}
    assert by_type["major"]["issues"][0]["title"] == "Real major"
    assert "severity" not in by_type["major"]["issues"][0]
    disputed = by_type["disputed"]["issues"][0]
    assert (disputed["title"], disputed["severity"], disputed["disposition"]) == (
        "Guard", "major", "author says upstream")
    deferred = by_type["deferred"]["issues"][0]
    assert (deferred["severity"], deferred["disposition"]) == ("minor", "PR #99")
    ok, errors = validate_review_json(parsed)
    assert ok, errors


def test_markdown_parser_emits_disposition_sections_only_when_present():
    md = json_to_markdown(_review_with_sections([
        {"type": "critical", "display_name": "Critical Issues", "issues": []},
        {"type": "major", "display_name": "Major Concerns", "issues": []},
        {"type": "minor", "display_name": "Minor Issues", "issues": []},
    ]))
    parsed = markdown_to_json(md, {"pr_number": 1, "repository": "o/r"})
    assert [s["type"] for s in parsed["sections"]] == ["critical", "major", "minor"]


def test_markdown_parser_reads_deferred_status():
    content = "This is a follow-up review.\n\n- **Rename**: Deferred - PR #99\n"
    followup = _parse_followup(content, {"is_followup": True})
    assert [r["status"] for r in followup["resolution_status"]] == ["deferred"]
