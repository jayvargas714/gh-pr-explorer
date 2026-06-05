"""Audit JSON schema: validation, tally computation, JSON→markdown.

Parallel to review_schema.py but for the two-part PB↔ED audit format
produced by the /pb-ed-audit skill.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

AUDIT_SCHEMA_VERSION = "1.0.0"

# Path to the formal JSON Schema spec (for external tools/agents)
AUDIT_SCHEMA_SPEC_PATH = Path(__file__).parent / "audit_schema_spec.json"

# Severities that count as blocking even when the `blocking` flag is absent.
BLOCKING_SEVERITIES = {"CONTRADICTION", "SCOPE-VIOLATION", "SCOPE_VIOLATION"}


def validate_audit_json(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate an audit dict against the schema. Returns (is_valid, errors)."""
    errors: List[str] = []

    if not isinstance(data, dict):
        return False, ["Root must be a JSON object"]

    for key in ("schema_version", "format", "audit_type", "metadata", "audits"):
        if key not in data:
            errors.append(f"Missing required key: {key}")

    if data.get("schema_version") and data["schema_version"] != AUDIT_SCHEMA_VERSION:
        errors.append(
            f"Unknown schema_version: {data['schema_version']} (expected {AUDIT_SCHEMA_VERSION})"
        )

    if "format" in data and data["format"] != "audit":
        errors.append(f"format must be 'audit', got {data['format']!r}")

    meta = data.get("metadata")
    if isinstance(meta, dict):
        if "pr_number" not in meta:
            errors.append("metadata.pr_number is required")
        if "repository" not in meta:
            errors.append("metadata.repository is required")
    elif meta is not None:
        errors.append("metadata must be an object")

    audits = data.get("audits")
    if isinstance(audits, list):
        for i, audit in enumerate(audits):
            if not isinstance(audit, dict):
                errors.append(f"audits[{i}] must be an object")
                continue
            for k in ("key", "name", "findings"):
                if k not in audit:
                    errors.append(f"audits[{i}].{k} is required")
            findings = audit.get("findings")
            if not isinstance(findings, list):
                errors.append(f"audits[{i}].findings must be an array")
                continue
            for j, f in enumerate(findings):
                if not isinstance(f, dict):
                    errors.append(f"audits[{i}].findings[{j}] must be an object")
                    continue
                for fk in ("id", "severity", "summary"):
                    if fk not in f:
                        errors.append(f"audits[{i}].findings[{j}].{fk} is required")
    elif audits is not None:
        errors.append("audits must be an array")

    return len(errors) == 0, errors


def _finding_is_blocking(finding: Dict[str, Any]) -> bool:
    # Explicit blocking flag wins; fall back to severity only when absent.
    explicit = finding.get("blocking")
    if explicit is True:
        return True
    if explicit is False:
        return False
    sev = str(finding.get("severity", "")).strip().upper()
    return sev in BLOCKING_SEVERITIES


def compute_audit_tallies(data: Dict[str, Any]) -> Dict[str, int]:
    """Return {finding_count, blocking_count} across all audits."""
    finding_count = 0
    blocking_count = 0
    for audit in data.get("audits", []):
        for finding in (audit.get("findings") or []):
            finding_count += 1
            if _finding_is_blocking(finding):
                blocking_count += 1
    return {"finding_count": finding_count, "blocking_count": blocking_count}


def _loc_ref(loc: Dict[str, Any]) -> str:
    if loc.get("ref"):
        return loc["ref"]
    if loc.get("file"):
        line = loc.get("line")
        return f"{loc['file']}:{line}" if line is not None else loc["file"]
    return ""


def audit_json_to_markdown(data: Dict[str, Any]) -> str:
    """Render an audit JSON dict to markdown matching the PR-1630 sample layout."""
    lines: List[str] = []
    meta = data.get("metadata", {})
    pr_num = meta.get("pr_number", "?")

    # Title
    title = meta.get("pr_title", "")
    heading = f"# PR #{pr_num} — ED Audit (PB↔ED parity + cross-ED consistency)"
    lines.append(heading)
    lines.append("")

    # Header block
    if title:
        lines.append(f"**PR:** #{pr_num} *\"{title}\"*"
                     + (f" (head `{meta['head_ref']}`, base `{meta.get('base_ref', '')}`)"
                        if meta.get("head_ref") else ""))
    pb = meta.get("parent_pb") or {}
    if pb.get("id"):
        pb_line = f"**Parent PB:** {pb['id']}"
        if pb.get("title"):
            pb_line += f" *{pb['title']}*"
        if pb.get("status"):
            pb_line += f" ({pb['status']})"
        lines.append(pb_line)
    eds = meta.get("eds") or []
    if eds:
        ed_str = " · ".join(
            f"{e.get('id', '')}{(' ' + e['title']) if e.get('title') else ''}".strip()
            for e in eds
        )
        lines.append(f"**EDs:** {ed_str}")
    if meta.get("auditor"):
        line = f"**Auditor:** {meta['auditor']}"
        if meta.get("date"):
            line += f"  ·  **Date:** {meta['date']}"
        lines.append(line)
    if meta.get("scope"):
        lines.append(f"**Scope:** {meta['scope']}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Executive summary
    if data.get("executive_summary"):
        lines.append("## Executive summary")
        lines.append("")
        lines.append(data["executive_summary"])
        lines.append("")
        lines.append("---")
        lines.append("")

    # Each audit
    for audit in data.get("audits", []):
        name = audit.get("name", audit.get("key", "Audit"))
        lines.append(f"# Audit {audit.get('key', '')} — {name}".rstrip())
        lines.append("")
        if audit.get("verdict"):
            lines.append(f"**Verdict:** {audit['verdict']}")
            lines.append("")
        findings = audit.get("findings", [])
        if findings:
            lines.append("| ID | Severity | Rule | One-line |")
            lines.append("|---|---|---|---|")
            for f in findings:
                rule = f.get("rule_id", "")
                if f.get("rule_authority"):
                    rule = f"`{rule}` [{f['rule_authority']}]" if rule else f"[{f['rule_authority']}]"
                elif rule:
                    rule = f"`{rule}`"
                lines.append(
                    f"| {f.get('id', '')} | {f.get('severity', '')} | {rule} | "
                    f"{f.get('summary', '')} |"
                )
            lines.append("")
            for f in findings:
                lines.append(f"### {f.get('id', '')} — {f.get('severity', '')} — {f.get('summary', '')}")
                if f.get("rule_id") or f.get("rule_authority"):
                    lines.append(
                        f"- **Rule:** {f.get('rule_id', '')}"
                        + (f" [{f['rule_authority']}]" if f.get("rule_authority") else "")
                        + (f"  ·  **Lens:** {f['lens']}" if f.get("lens") else "")
                    )
                for loc in f.get("locations", []):
                    ref = _loc_ref(loc)
                    if ref:
                        quote = f" — *{loc['quote']}*" if loc.get("quote") else ""
                        lines.append(f"- **Location:** `{ref}`{quote}")
                if f.get("detail"):
                    lines.append(f"- **Why:** {f['detail']}")
                if f.get("recommendation"):
                    lines.append(f"- **Recommendation:** {f['recommendation']}")
                lines.append("")
        lines.append("---")
        lines.append("")

    # Verified clean
    if data.get("verified_clean"):
        lines.append("### Verified clean")
        lines.append("")
        lines.append(data["verified_clean"])
        lines.append("")

    # Supplementary notes
    if data.get("supplementary_notes"):
        lines.append("## Supplementary notes")
        lines.append("")
        lines.append(data["supplementary_notes"])
        lines.append("")

    # Action map
    action_map = data.get("action_map") or []
    if action_map:
        lines.append("## Action map")
        lines.append("")
        lines.append("| Priority | Items | Nature |")
        lines.append("|---|---|---|")
        for row in action_map:
            items = ", ".join(row.get("finding_ids", []))
            lines.append(f"| {row.get('priority', '')} | {items} | {row.get('nature', '')} |")
        lines.append("")

    return "\n".join(lines)
