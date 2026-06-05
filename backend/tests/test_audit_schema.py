"""Tests for the audit JSON schema: validation + tally computation."""

import pytest

from backend.services.audit_schema import (
    AUDIT_SCHEMA_VERSION,
    validate_audit_json,
    compute_audit_tallies,
    audit_json_to_markdown,
)


def _good_audit():
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "format": "audit",
        "audit_type": "pb_ed",
        "metadata": {"pr_number": 1630, "repository": "owner/repo"},
        "executive_summary": "Strong, disciplined ED set.",
        "audits": [
            {
                "key": "A",
                "name": "Cross-ED consistency",
                "verdict": "Highly coherent.",
                "findings": [
                    {"id": "CE-1", "severity": "INCONSISTENCY", "blocking": False,
                     "summary": "M4 poll loop dependency undeclared"},
                    {"id": "CE-2", "severity": "INFO", "summary": "config staleness"},
                ],
            },
            {
                "key": "B",
                "name": "PB↔ED parity",
                "verdict": "Faithful.",
                "findings": [
                    {"id": "PE-1", "severity": "SCOPE-VIOLATION",
                     "summary": "health latency_ms exceeds liveness-only"},
                ],
            },
        ],
    }


def test_valid_audit_passes():
    ok, errors = validate_audit_json(_good_audit())
    assert ok, errors


def test_missing_format_fails():
    data = _good_audit()
    del data["format"]
    ok, errors = validate_audit_json(data)
    assert not ok
    assert any("format" in e for e in errors)


def test_wrong_format_value_fails():
    data = _good_audit()
    data["format"] = "review"
    ok, errors = validate_audit_json(data)
    assert not ok


def test_missing_metadata_pr_number_fails():
    data = _good_audit()
    del data["metadata"]["pr_number"]
    ok, errors = validate_audit_json(data)
    assert not ok
    assert any("pr_number" in e for e in errors)


def test_finding_missing_required_fields_fails():
    data = _good_audit()
    data["audits"][0]["findings"][0] = {"id": "CE-1"}  # missing severity + summary
    ok, errors = validate_audit_json(data)
    assert not ok


def test_tallies_count_findings_and_blocking_from_flag_and_severity():
    # CE-1 not blocking, CE-2 not blocking, PE-1 SCOPE-VIOLATION => blocking by severity
    tallies = compute_audit_tallies(_good_audit())
    assert tallies["finding_count"] == 3
    assert tallies["blocking_count"] == 1


def test_explicit_blocking_flag_counts():
    data = _good_audit()
    data["audits"][0]["findings"][0]["blocking"] = True   # CE-1 explicitly blocking
    tallies = compute_audit_tallies(data)
    assert tallies["blocking_count"] == 2  # CE-1 (flag) + PE-1 (severity)


def test_markdown_renders_key_blocks():
    md = audit_json_to_markdown(_good_audit())
    # Header + PR
    assert "PR #1630" in md or "PR-1630" in md
    # Both audits rendered by name
    assert "Cross-ED consistency" in md
    assert "PB↔ED parity" in md
    # Executive summary present
    assert "Strong, disciplined ED set." in md
    # Findings rendered by id + severity
    assert "CE-1" in md
    assert "INCONSISTENCY" in md
    assert "PE-1" in md
    assert "SCOPE-VIOLATION" in md


def test_markdown_handles_empty_audits():
    data = _good_audit()
    data["audits"] = []
    md = audit_json_to_markdown(data)
    assert isinstance(md, str)
    assert "PR #1630" in md or "PR-1630" in md


def test_findings_null_fails():
    data = _good_audit()
    data["audits"][0]["findings"] = None
    ok, errors = validate_audit_json(data)
    assert not ok
    assert any("findings" in e for e in errors)


def test_markdown_file_only_location_has_no_none():
    data = _good_audit()
    data["audits"][0]["findings"][0]["locations"] = [{"file": "docs/designs/ED-010.md"}]
    md = audit_json_to_markdown(data)
    assert ":None" not in md
    assert "docs/designs/ED-010.md" in md


def test_tallies_ignore_non_dict_findings():
    data = _good_audit()
    data["audits"][0]["findings"] = [None, "bad", {"id": "x", "severity": "INFO", "summary": "s"}]
    data["audits"].append("not-a-dict")
    tallies = compute_audit_tallies(data)
    # 1 valid finding in audit A + 1 in audit B; non-dict audit/findings skipped
    assert tallies["finding_count"] == 2
