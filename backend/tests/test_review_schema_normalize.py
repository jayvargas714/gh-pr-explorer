"""Two-tier severity vocabulary and legacy (critical/major/minor) normalization."""

import copy
import json

import pytest

from backend.services.review_schema import (
    DEFAULT_SECTION_NAMES, LEGACY_SEVERITY_MAP, SCHEMA_SPEC_PATH, SCHEMA_VERSION, SECTION_TYPES,
    SEVERITIES, _empty_review, count_issues, format_issue_lines, json_to_markdown,
    load_content_json, markdown_to_json, normalize_legacy_sections, strip_fixes,
    validate_review_json,
)


def _issue(title, **extra):
    base = {"title": title, "location": {"file": "a.rs", "start_line": 1, "end_line": 2},
            "problem": "p"}
    base.update(extra)
    return base


def _legacy(sections, version="1.0.0"):
    return {
        "schema_version": version,
        "metadata": {"pr_number": 1, "repository": "o/r"},
        "summary": "s", "score": {"overall": 7},
        "sections": sections,
    }


def _sec(sec_type, *issues, display_name=None):
    return {"type": sec_type, "display_name": display_name or sec_type.title(), "issues": list(issues)}


# --- vocabulary --------------------------------------------------------------

def test_vocabulary_is_two_tier():
    assert SCHEMA_VERSION == "2.0.0"
    assert SEVERITIES == ("blocking", "non_blocking")
    assert SECTION_TYPES == ("blocking", "non_blocking", "disputed", "deferred")
    assert DEFAULT_SECTION_NAMES["blocking"] == "Blocking Issues"
    assert DEFAULT_SECTION_NAMES["non_blocking"] == "Non-Blocking Issues"
    assert LEGACY_SEVERITY_MAP == {"critical": "blocking", "major": "blocking", "minor": "non_blocking"}


def test_spec_file_matches_code_vocabulary():
    spec = json.loads(SCHEMA_SPEC_PATH.read_text())
    assert spec["properties"]["schema_version"]["const"] == SCHEMA_VERSION
    section = spec["properties"]["sections"]["items"]["properties"]
    assert section["type"]["enum"] == list(SECTION_TYPES)
    assert section["issues"]["items"]["properties"]["severity"]["enum"] == list(SEVERITIES)


# --- normalize_legacy_sections ----------------------------------------------

def test_merges_critical_and_major_into_blocking_in_critical_then_major_order():
    review = _legacy([
        _sec("major", _issue("M1"), _issue("M2")),
        _sec("critical", _issue("C1")),
        _sec("minor", _issue("m1")),
    ])
    out = normalize_legacy_sections(review)
    assert [s["type"] for s in out["sections"]] == ["blocking", "non_blocking"]
    assert [i["title"] for i in out["sections"][0]["issues"]] == ["C1", "M1", "M2"]
    assert [i["title"] for i in out["sections"][1]["issues"]] == ["m1"]
    assert out["sections"][0]["display_name"] == "Blocking Issues"
    assert out["sections"][1]["display_name"] == "Non-Blocking Issues"
    assert out["schema_version"] == "2.0.0"


def test_merged_section_sits_where_the_first_legacy_section_was():
    review = _legacy([_sec("minor", _issue("m1")), _sec("critical", _issue("C1")), _sec("major")])
    out = normalize_legacy_sections(review)
    assert [s["type"] for s in out["sections"]] == ["non_blocking", "blocking"]


def test_remaps_disposition_issue_severity_case_insensitively():
    review = _legacy([
        _sec("critical"), _sec("major"), _sec("minor"),
        _sec("disputed", _issue("D1", severity="Major", disposition="x"),
             _issue("D2", severity="minor", disposition="y")),
        _sec("deferred", _issue("F1", severity="CRITICAL", disposition="PR #9")),
    ])
    out = normalize_legacy_sections(review)
    by_type = {s["type"]: s for s in out["sections"]}
    assert [i["severity"] for i in by_type["disputed"]["issues"]] == ["blocking", "non_blocking"]
    assert by_type["deferred"]["issues"][0]["severity"] == "blocking"
    assert by_type["deferred"]["issues"][0]["disposition"] == "PR #9"


def test_existing_blocking_section_absorbs_a_stray_legacy_section():
    review = _legacy([_sec("blocking", _issue("B1")), _sec("critical", _issue("C1"))], version="2.0.0")
    out = normalize_legacy_sections(review)
    assert [s["type"] for s in out["sections"]] == ["blocking"]
    assert [i["title"] for i in out["sections"][0]["issues"]] == ["B1", "C1"]


def test_already_normalized_input_is_returned_unchanged():
    review = _legacy([_sec("blocking", _issue("B1")), _sec("non_blocking")], version="2.0.0")
    assert normalize_legacy_sections(review) is review


def test_error_stub_only_gets_the_version_bump():
    review = _legacy([])
    out = normalize_legacy_sections(review)
    assert out["sections"] == [] and out["schema_version"] == "2.0.0"


def test_unknown_section_types_are_preserved():
    review = _legacy([_sec("critical", _issue("C1")), _sec("advisory", _issue("A1"))])
    out = normalize_legacy_sections(review)
    assert [s["type"] for s in out["sections"]] == ["blocking", "advisory"]


def test_input_is_not_mutated():
    review = _legacy([_sec("critical", _issue("C1")), _sec("major", _issue("M1")),
                      _sec("disputed", _issue("D", severity="major", disposition="x"))])
    snapshot = copy.deepcopy(review)
    normalize_legacy_sections(review)
    assert review == snapshot


def test_custom_display_names_are_honored():
    review = _legacy([_sec("critical"), _sec("minor")])
    out = normalize_legacy_sections(review, {"blocking": "Must Fix", "non_blocking": "Nits"})
    assert [s["display_name"] for s in out["sections"]] == ["Must Fix", "Nits"]


def test_normalized_output_validates_and_raw_legacy_does_not():
    review = _legacy([_sec("critical", _issue("C1")), _sec("major"), _sec("minor"),
                      _sec("disputed", _issue("D", severity="major", disposition="x"))])
    ok, errors = validate_review_json(review)
    assert not ok and any("schema_version" in e for e in errors), errors
    ok, errors = validate_review_json(normalize_legacy_sections(review))
    assert ok, errors


def test_normalization_is_idempotent():
    review = _legacy([_sec("critical", _issue("C1")), _sec("major", _issue("M1")), _sec("minor")])
    once = normalize_legacy_sections(review)
    assert normalize_legacy_sections(once) is once


# --- read choke points -------------------------------------------------------

def test_load_content_json_parses_and_normalizes():
    raw = json.dumps(_legacy([_sec("critical", _issue("C1")), _sec("major", _issue("M1")), _sec("minor")]))
    out = load_content_json(raw)
    assert [s["type"] for s in out["sections"]] == ["blocking", "non_blocking"]
    assert len(out["sections"][0]["issues"]) == 2


@pytest.mark.parametrize("raw", [None, "", "not json", "[1, 2]", "42"])
def test_load_content_json_returns_none_for_garbage(raw):
    assert load_content_json(raw) is None


def test_count_issues_tallies_legacy_content_as_two_tier():
    review = _legacy([
        _sec("critical", _issue("C1")), _sec("major", _issue("M1"), _issue("M2")), _sec("minor", _issue("m1")),
        _sec("disputed", _issue("D1", severity="major", disposition="x"),
             _issue("D2", severity="minor", disposition="y")),
        _sec("deferred", _issue("F1", severity="critical", disposition="z")),
    ])
    tallies = count_issues(review)
    assert tallies == {"blocking": 3, "non_blocking": 1, "disputed": 2, "deferred": 1, "disputed_blocking": 1}


def test_count_issues_on_two_tier_content():
    review = _legacy([_sec("blocking", _issue("B1")), _sec("non_blocking", _issue("n1"), _issue("n2")),
                      _sec("disputed", _issue("D", severity="blocking", disposition="x"))], version="2.0.0")
    tallies = count_issues(review)
    assert tallies == {"blocking": 1, "non_blocking": 2, "disputed": 1, "deferred": 0, "disputed_blocking": 1}


def test_format_issue_lines_renders_non_blocking_label():
    lines = format_issue_lines([_issue("x", severity="non_blocking", disposition="d")])
    assert "- Severity: Non-Blocking" in lines
    lines = format_issue_lines([_issue("x", severity="blocking", disposition="d")])
    assert "- Severity: Blocking" in lines


# --- markdown fallback parser ------------------------------------------------

def test_empty_review_emits_two_tier_sections():
    assert [s["type"] for s in _empty_review()["sections"]] == ["blocking", "non_blocking"]
    assert _empty_review()["schema_version"] == "2.0.0"


def test_markdown_with_legacy_headings_parses_to_two_tier():
    md = (
        "# Code Review: PR #1\n\n---\n\n**Summary**\n\ns\n\n"
        "---\n\n**Critical Issues**\n\n**1. C1**\n- Location: `a.rs:1`\n- Problem: p\n\n"
        "---\n\n**Major Concerns**\n\n**1. M1**\n- Location: `a.rs:2`\n- Problem: p\n\n"
        "---\n\n**Minor Issues**\n\n**1. m1**\n- Location: `a.rs:3`\n- Problem: p\n\n"
        "---\n\n**Disputed**\n\n**1. D1**\n- Location: `a.rs:4`\n- Severity: Major\n- Disposition: no\n- Problem: p\n\n"
        "---\n\n**Score: 7/10**\n"
    )
    parsed = markdown_to_json(md, {"pr_number": 1, "repository": "o/r"})
    by_type = {s["type"]: s for s in parsed["sections"]}
    assert set(by_type) == {"blocking", "non_blocking", "disputed"}
    assert [i["title"] for i in by_type["blocking"]["issues"]] == ["C1", "M1"]
    assert [i["title"] for i in by_type["non_blocking"]["issues"]] == ["m1"]
    assert by_type["disputed"]["issues"][0]["severity"] == "blocking"
    assert parsed["schema_version"] == "2.0.0"
    ok, errors = validate_review_json(parsed)
    assert ok, errors


def test_markdown_with_two_tier_headings_round_trips():
    review = _legacy([
        _sec("blocking", _issue("B1"), display_name="Blocking Issues"),
        _sec("non_blocking", display_name="Non-Blocking Issues"),
        _sec("deferred", _issue("F1", severity="non_blocking", disposition="PR #9"), display_name="Deferred"),
    ], version="2.0.0")
    md = json_to_markdown(review)
    assert "**Blocking Issues**" in md and "**Non-Blocking Issues**" in md
    parsed = markdown_to_json(md, {"pr_number": 1, "repository": "o/r"})
    assert [s["type"] for s in parsed["sections"]] == ["blocking", "non_blocking", "deferred"]
    assert parsed["sections"][0]["issues"][0]["title"] == "B1"
    assert parsed["sections"][2]["issues"][0]["severity"] == "non_blocking"
    ok, errors = validate_review_json(parsed)
    assert ok, errors


def test_markdown_summary_stops_at_two_tier_heading():
    md = "**Summary**\n\nthe summary\n**Blocking Issues**\n\nNone\n"
    parsed = markdown_to_json(md, {"pr_number": 1, "repository": "o/r"})
    assert parsed["summary"] == "the summary"


# --- strip_fixes: reviewers report problems, never solutions -------------------

def test_strip_fixes_removes_fix_from_every_section():
    review = _legacy([
        _sec("blocking", _issue("B1", fix="do this"), _issue("B2")),
        _sec("non_blocking", _issue("n1", fix="do that")),
        _sec("disputed", _issue("D1", severity="blocking", disposition="no", fix="ignored")),
    ], version="2.0.0")
    out = strip_fixes(review)
    assert all("fix" not in i for s in out["sections"] for i in s["issues"])
    assert out["sections"][0]["issues"][0]["problem"] == "p"
    assert out["sections"][2]["issues"][0]["disposition"] == "no"


def test_strip_fixes_returns_input_unchanged_when_nothing_to_strip():
    review = _legacy([_sec("blocking", _issue("B1")), _sec("non_blocking")], version="2.0.0")
    assert strip_fixes(review) is review


def test_strip_fixes_does_not_mutate_input():
    review = _legacy([_sec("blocking", _issue("B1", fix="do this"))], version="2.0.0")
    snapshot = copy.deepcopy(review)
    strip_fixes(review)
    assert review == snapshot


def test_markdown_parser_still_reads_legacy_fix_lines():
    """History re-parses keep their recommendations; only the save path strips."""
    md = "**Blocking Issues**\n\n**1. B1**\n- Location: `a.rs:1`\n- Problem: p\n- Fix: do this\n"
    parsed = markdown_to_json(md, {"pr_number": 1, "repository": "o/r"})
    assert parsed["sections"][0]["issues"][0]["fix"] == "do this"
