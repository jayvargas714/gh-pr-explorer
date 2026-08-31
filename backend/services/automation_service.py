"""Pure classification engine for full automation.

Given a PR's changed file paths and the automation config, decide which
reviewer rule applies. No I/O here — dispatch lives in
automation_dispatch_worker.py.

Glob semantics: fnmatch (case-sensitive), tested against both the full
repo-relative path and the basename, so `PB-[0-9]*` and `docs/designs/*`
both behave intuitively. Note `*` crosses `/` in fnmatch.
"""

import posixpath
from fnmatch import fnmatchcase
from typing import Any, Dict, List


def matches(path: str, pattern: str) -> bool:
    """True if the glob matches the full path or its basename."""
    return fnmatchcase(path, pattern) or fnmatchcase(posixpath.basename(path), pattern)


def classify_files(files: List[str], config: Dict[str, Any]) -> Dict[str, Any]:
    """Classify a PR's changed files against the configured routing rules.

    Returns a dict:
        outcome: 'matched' (single rule), 'default' (no rule matched anything),
                 or 'unidentified' (files span rules, or mix rule + unmatched)
        rule: the winning rule dict ('matched'), the defaultRule ('default'),
              or None ('unidentified')
        matched_rules: names of rules that matched at least one file
        unmatched_count / ignored_count: for operator-facing detail
    """
    ignore_patterns = config.get("ignorePatterns", [])
    rules = config.get("rules", [])

    considered = []
    ignored_count = 0
    for path in files:
        if any(matches(path, pattern) for pattern in ignore_patterns):
            ignored_count += 1
        else:
            considered.append(path)

    matched_rule_names: List[str] = []
    winning_rule = None
    unmatched_count = 0
    for path in considered:
        rule = next((r for r in rules if any(matches(path, p) for p in r["patterns"])), None)
        if rule is None:
            unmatched_count += 1
        else:
            if rule["name"] not in matched_rule_names:
                matched_rule_names.append(rule["name"])
                winning_rule = rule

    if len(matched_rule_names) == 1 and unmatched_count == 0:
        outcome, rule = "matched", winning_rule
    elif not matched_rule_names:
        outcome, rule = "default", config.get("defaultRule")
    else:
        outcome, rule = "unidentified", None

    return {
        "outcome": outcome,
        "rule": rule,
        "matched_rules": matched_rule_names,
        "unmatched_count": unmatched_count,
        "ignored_count": ignored_count,
    }
