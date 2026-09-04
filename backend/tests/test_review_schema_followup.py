"""Follow-up resolution statuses in the review schema, incl. author dispositions."""

import json

import pytest

from backend.services.review_schema import (
    RESOLUTION_STATUSES, _parse_followup, format_resolution_lines, json_to_markdown,
    validate_review_json,
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


def test_status_vocabulary_has_six_values():
    assert set(RESOLUTION_STATUSES) == {
        "resolved", "partially_addressed", "not_addressed", "wont_fix", "withdrawn", "disputed"}


def test_spec_file_enum_matches_code_vocabulary():
    from backend.services.review_schema import SCHEMA_SPEC_PATH
    spec = json.loads(SCHEMA_SPEC_PATH.read_text())
    enum = spec["properties"]["followup"]["properties"]["resolution_status"]["items"]["properties"]["status"]["enum"]
    assert enum == list(RESOLUTION_STATUSES)


def test_validation_still_accepts_disposition_statuses():
    ok, errors = validate_review_json(_review(["withdrawn", "disputed"]))
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
