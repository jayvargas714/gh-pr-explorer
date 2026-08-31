"""Tests for the pure file-classification engine behind full automation."""

import pytest

from backend.services.automation_service import classify_files, matches


def _config(rules=None, ignore=None):
    return {
        "ignorePatterns": ignore or [],
        "defaultRule": {"reviewerKey": "default", "autoVerdict": False, "autoVerdictMode": "verdict"},
        "rules": rules if rules is not None else [
            {"name": "PB", "patterns": ["PB-[0-9]*"], "reviewerKey": "pb",
             "autoVerdict": True, "autoVerdictMode": "verdict"},
            {"name": "ED", "patterns": ["ED-[0-9]*"], "reviewerKey": "ed",
             "autoVerdict": True, "autoVerdictMode": "comment"},
        ],
    }


# --- matches() ---

def test_matches_basename_and_full_path():
    assert matches("briefs/PB-008-chart-shell.md", "PB-[0-9]*")
    assert matches("PB-008-chart-shell.md", "PB-[0-9]*")
    assert matches("docs/designs/ED-052-gateway.md", "docs/designs/*")
    assert not matches("src/main.py", "PB-[0-9]*")


def test_matches_is_case_sensitive():
    assert not matches("pb-008-brief.md", "PB-[0-9]*")


# --- classify_files() ---

def test_all_files_matching_one_rule():
    result = classify_files(["briefs/PB-008-a.md", "briefs/PB-009-b.md"], _config())
    assert result["outcome"] == "matched"
    assert result["rule"]["name"] == "PB"
    assert result["rule"]["reviewerKey"] == "pb"


def test_no_files_matching_any_rule_falls_to_default():
    result = classify_files(["src/app.py", "README.md"], _config())
    assert result["outcome"] == "default"
    assert result["rule"]["reviewerKey"] == "default"


def test_files_spanning_two_rules_is_unidentified():
    result = classify_files(["briefs/PB-008-a.md", "docs/designs/ED-052-b.md"], _config())
    assert result["outcome"] == "unidentified"
    assert result["rule"] is None
    assert set(result["matched_rules"]) == {"PB", "ED"}


def test_rule_plus_unmatched_files_is_unidentified():
    result = classify_files(["briefs/PB-008-a.md", "src/app.py"], _config())
    assert result["outcome"] == "unidentified"
    assert result["unmatched_count"] == 1


def test_ignore_patterns_strip_index_files():
    files = ["briefs/PB-008-a.md", "briefs/PB-000-index.md"]
    result = classify_files(files, _config(ignore=["*PB-000-index*"]))
    assert result["outcome"] == "matched"
    assert result["rule"]["name"] == "PB"
    assert result["ignored_count"] == 1


def test_without_ignore_pattern_index_file_still_matches_pb():
    # PB-000-index matches the PB pattern itself, so PB + index is still PB.
    result = classify_files(["briefs/PB-008-a.md", "briefs/PB-000-index.md"], _config())
    assert result["outcome"] == "matched"
    assert result["rule"]["name"] == "PB"


def test_all_files_ignored_falls_to_default():
    result = classify_files(["briefs/PB-000-index.md"], _config(ignore=["*PB-000-index*"]))
    assert result["outcome"] == "default"


def test_empty_file_list_falls_to_default():
    result = classify_files([], _config())
    assert result["outcome"] == "default"


def test_rule_order_wins_for_a_file_matching_two_rules():
    rules = [
        {"name": "First", "patterns": ["*.md"], "reviewerKey": "pb",
         "autoVerdict": False, "autoVerdictMode": "verdict"},
        {"name": "Second", "patterns": ["PB-[0-9]*"], "reviewerKey": "ed",
         "autoVerdict": False, "autoVerdictMode": "verdict"},
    ]
    result = classify_files(["PB-008-a.md"], _config(rules=rules))
    assert result["outcome"] == "matched"
    assert result["rule"]["name"] == "First"


def test_empty_rules_list_falls_to_default():
    result = classify_files(["anything.py"], _config(rules=[]))
    assert result["outcome"] == "default"
