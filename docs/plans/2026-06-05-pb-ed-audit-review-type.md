# PB↔ED Audit Review Type — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "PB ED Audit" review type that runs the `/pb-ed-audit` skill, stores its two-part report (Audit A cross-ED consistency + Audit B PB↔ED parity) under a new audit JSON schema, and surfaces it in the app UI, on the PR (whole-report + per-finding inline comments), and in the Verdict view.

**Architecture:** A parallel "audit" subsystem alongside the existing review subsystem — new `audits` table + `AuditsDB`, a new `audit_schema` (spec + validation + JSON→markdown), a focused `audit_service` (Claude CLI subprocess that invokes the `/pb-ed-audit` skill), and a new `/api/audits` + `/api/audit-history` blueprint. The frontend gets an audit picker option, an `AuditViewer`, an audit history list, an audit chip (blocking-count, not a score), and an audit branch in `VerdictModal`. PR posting reuses the existing reviewer-agnostic `post_verdict()` (its `inline_comments` list already takes generic `{path, body, start_line, end_line, title, section}` entries).

**Tech Stack:** Python 3 / Flask / SQLite (backend), React 18 + TypeScript + Vite + Zustand (frontend), `claude` + `gh` CLIs, pytest.

**Spec:** `docs/specs/2026-06-05-pb-ed-audit-review-type-design.md`

**Reference sample audit:** `~/code-reviews/PR1630-ed-audit-2026-06-05-0715.md`

---

## Design deviation from spec (intentional, lower-risk)

The spec proposed extracting a *shared* subprocess helper used by both reviews and audits. To stay surgical and avoid destabilizing the live review path (the app runs off `main`), this plan instead adds a **focused `audit_service.py`** that mirrors the small subprocess poll/save pattern, with its own `active_audits` tracking. The ~40 lines of duplication are deliberate; a later DRY pass can unify them once both paths are proven. Likewise, **audit inline posting reuses `post_verdict()`** rather than a new posting service — no `audit_inline_service.py` is needed.

---

## File structure

**Backend — create:**
- `backend/services/audit_schema_spec.json` — formal JSON Schema (draft-07) for the audit format
- `backend/services/audit_schema.py` — `AUDIT_SCHEMA_VERSION`, `validate_audit_json`, `compute_audit_tallies`, `audit_json_to_markdown`
- `backend/database/audits.py` — `AuditsDB`
- `backend/services/audit_service.py` — `start_audit_process`, `save_audit_to_db`, `check_audit_status`
- `backend/routes/audit_routes.py` — `audit_bp` (start/status/cancel/list + history list/detail/check + post-inline)
- `backend/tests/test_audit_schema.py`, `backend/tests/test_audits_db.py`, `backend/tests/test_audit_routes.py`

**Backend — modify:**
- `backend/database/base.py` — add `audits` table + index to `_init_db`
- `backend/database/__init__.py` — import/export `AuditsDB` + `get_audits_db()`
- `backend/extensions.py` — add `active_audits` + `audits_lock`
- `backend/routes/__init__.py` — register `audit_bp`

**Frontend — create:**
- `frontend/src/api/audits.ts` — audit API module
- `frontend/src/stores/useAuditStore.ts` — active-audit polling store
- `frontend/src/components/audits/AuditChip.tsx` — blocking/finding chip
- `frontend/src/components/audits/AuditViewer.tsx` — audit detail modal
- `frontend/src/components/audits/AuditHistoryList.tsx` — audit history list
- `frontend/src/styles/audits.css` — audit chip + viewer styles

**Frontend — modify:**
- `frontend/src/api/types.ts` — add audit types
- `frontend/src/api/reviews.ts` — extend `ReviewerType` to include `'audit'`
- `frontend/src/components/reviews/ReviewerPickerMenu.tsx` — add "PB ED Audit" option
- `frontend/src/components/reviews/ReviewButton.tsx` + `QueueReviewButton.tsx` — branch `'audit'` → `startAudit`
- `frontend/src/components/queue/VerdictModal.tsx` — branch standard vs audit composition
- the review-history panel component — add an "Audits" tab rendering `AuditHistoryList`

**Docs — modify:**
- `docs/DESIGN.md` — document the audit subsystem
- The `/pb-ed-audit` skill (`~/.claude/skills/pb-ed-audit/SKILL.md`) — emit JSON per the new spec

---

## PHASE 1 — Audit JSON schema

### Task 1: Formal JSON Schema spec file

**Files:**
- Create: `backend/services/audit_schema_spec.json`

- [ ] **Step 1: Write the spec file**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "PB-ED Audit JSON Schema",
  "description": "Structured JSON format for PB↔ED audits produced by the /pb-ed-audit skill",
  "type": "object",
  "required": ["schema_version", "format", "audit_type", "metadata", "audits"],
  "properties": {
    "schema_version": { "type": "string", "const": "1.0.0" },
    "format": { "type": "string", "const": "audit" },
    "audit_type": { "type": "string", "enum": ["pb_ed"] },
    "metadata": {
      "type": "object",
      "required": ["pr_number", "repository"],
      "properties": {
        "pr_number": { "type": "integer" },
        "repository": { "type": "string", "description": "owner/repo format" },
        "pr_url": { "type": "string" },
        "pr_title": { "type": "string" },
        "head_ref": { "type": "string" },
        "base_ref": { "type": "string" },
        "parent_pb": {
          "type": "object",
          "properties": {
            "id": { "type": "string" },
            "title": { "type": "string" },
            "status": { "type": "string" }
          }
        },
        "eds": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": { "id": { "type": "string" }, "title": { "type": "string" } }
          }
        },
        "auditor": { "type": "string" },
        "date": { "type": "string" },
        "scope": { "type": "string" }
      }
    },
    "executive_summary": { "type": "string" },
    "audits": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["key", "name", "findings"],
        "properties": {
          "key": { "type": "string", "description": "Short label, e.g. 'A' or 'B'" },
          "name": { "type": "string" },
          "verdict": { "type": "string" },
          "tally": { "type": "object", "additionalProperties": { "type": "integer" } },
          "findings": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["id", "severity", "summary"],
              "properties": {
                "id": { "type": "string" },
                "severity": { "type": "string", "description": "Uppercase token, e.g. CONTRADICTION, SCOPE-VIOLATION, INCONSISTENCY, UN-ANCHORED, UNDER-COVERAGE, INFO" },
                "blocking": { "type": "boolean" },
                "rule_id": { "type": "string" },
                "rule_authority": { "type": "string" },
                "concept": { "type": "string" },
                "lens": { "type": "string" },
                "summary": { "type": "string" },
                "locations": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "file": { "type": "string", "description": "repo-relative path; enables inline comments" },
                      "line": { "type": ["integer", "null"] },
                      "ref": { "type": "string", "description": "human display ref, e.g. 'ED-010 §10:389'" },
                      "quote": { "type": "string" }
                    }
                  }
                },
                "detail": { "type": "string" },
                "recommendation": { "type": "string" }
              }
            }
          }
        }
      }
    },
    "verified_clean": { "type": "string" },
    "supplementary_notes": { "type": "string" },
    "action_map": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "priority": { "type": "string" },
          "finding_ids": { "type": "array", "items": { "type": "string" } },
          "nature": { "type": "string" }
        }
      }
    }
  }
}
```

- [ ] **Step 2: Verify it parses**

Run: `python -c "import json; json.load(open('backend/services/audit_schema_spec.json')); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/services/audit_schema_spec.json
git commit -m "Add formal JSON Schema spec for PB↔ED audits"
```

---

### Task 2: `audit_schema.py` — validation + tallies

**Files:**
- Create: `backend/services/audit_schema.py`
- Test: `backend/tests/test_audit_schema.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_audit_schema.py`:

```python
"""Tests for the audit JSON schema: validation + tally computation."""

import pytest

from backend.services.audit_schema import (
    AUDIT_SCHEMA_VERSION,
    validate_audit_json,
    compute_audit_tallies,
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_audit_schema.py -q`
Expected: FAIL with `ModuleNotFoundError: backend.services.audit_schema`

- [ ] **Step 3: Write the implementation**

Create `backend/services/audit_schema.py`:

```python
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
                if findings is not None:
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
    if finding.get("blocking") is True:
        return True
    sev = str(finding.get("severity", "")).strip().upper()
    return sev in BLOCKING_SEVERITIES


def compute_audit_tallies(data: Dict[str, Any]) -> Dict[str, int]:
    """Return {finding_count, blocking_count} across all audits."""
    finding_count = 0
    blocking_count = 0
    for audit in data.get("audits", []):
        for finding in audit.get("findings", []):
            finding_count += 1
            if _finding_is_blocking(finding):
                blocking_count += 1
    return {"finding_count": finding_count, "blocking_count": blocking_count}
```

(`audit_json_to_markdown` is added in Task 3.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_audit_schema.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/audit_schema.py backend/tests/test_audit_schema.py
git commit -m "Add audit schema validation and tally computation"
```

---

### Task 3: `audit_json_to_markdown`

**Files:**
- Modify: `backend/services/audit_schema.py`
- Test: `backend/tests/test_audit_schema.py`

- [ ] **Step 1: Add the failing test**

Append to `backend/tests/test_audit_schema.py`:

```python
from backend.services.audit_schema import audit_json_to_markdown


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_audit_schema.py::test_markdown_renders_key_blocks -q`
Expected: FAIL with `ImportError: cannot import name 'audit_json_to_markdown'`

- [ ] **Step 3: Implement `audit_json_to_markdown`**

Append to `backend/services/audit_schema.py`:

```python
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
                    ref = loc.get("ref") or (
                        f"{loc.get('file', '')}:{loc.get('line')}" if loc.get("file") else ""
                    )
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_audit_schema.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/audit_schema.py backend/tests/test_audit_schema.py
git commit -m "Render audit JSON to markdown"
```

---

## PHASE 2 — Database

### Task 4: `audits` table in schema init

**Files:**
- Modify: `backend/database/base.py` (inside `_init_db`, after the `swimlane_assignments` block around line 289, before the migration blocks)

- [ ] **Step 1: Add the table creation**

In `backend/database/base.py`, after the `idx_swl_assign_lane` index creation (line ~289) and before the `# Migration: Add is_pinned column` block, insert:

```python
            # Create audits table (PB↔ED audits — parallel to reviews)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pr_number INTEGER NOT NULL,
                    repo TEXT NOT NULL,
                    pr_title TEXT,
                    pr_author TEXT,
                    pr_url TEXT,
                    head_ref TEXT,
                    base_ref TEXT,
                    audit_type TEXT NOT NULL DEFAULT 'pb_ed',
                    audit_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL DEFAULT 'completed',
                    content_json TEXT NOT NULL,
                    finding_count INTEGER DEFAULT 0,
                    blocking_count INTEGER DEFAULT 0,
                    inline_comments_posted BOOLEAN DEFAULT FALSE,
                    audit_file_path TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_audits_repo_pr
                ON audits(repo, pr_number)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_audits_timestamp
                ON audits(audit_timestamp DESC)
            """)
```

- [ ] **Step 2: Verify the table is created on a fresh DB**

Run:
```bash
python -c "
import tempfile, os
from pathlib import Path
from backend.database.base import Database
p = Path(tempfile.mkdtemp()) / 'test.db'
db = Database(p)
with db.connection() as c:
    rows = c.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='audits'\").fetchall()
    print('audits table:', [r[0] for r in rows])
"
```
Expected: `audits table: ['audits']`

- [ ] **Step 3: Run the full suite (no regressions)**

Run: `python -m pytest backend/tests -q`
Expected: PASS (all prior tests still green)

- [ ] **Step 4: Commit**

```bash
git add backend/database/base.py
git commit -m "Add audits table to database schema"
```

---

### Task 5: `AuditsDB` + singleton

**Files:**
- Create: `backend/database/audits.py`
- Modify: `backend/database/__init__.py`
- Test: `backend/tests/test_audits_db.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_audits_db.py`:

```python
"""Tests for AuditsDB."""

import json
import tempfile
from pathlib import Path

import pytest

from backend.database.base import Database
from backend.database.audits import AuditsDB


@pytest.fixture
def audits_db():
    p = Path(tempfile.mkdtemp()) / "audits_test.db"
    return AuditsDB(Database(p))


def _content(pr=1630):
    return json.dumps({
        "schema_version": "1.0.0", "format": "audit", "audit_type": "pb_ed",
        "metadata": {"pr_number": pr, "repository": "owner/repo"},
        "audits": [{"key": "A", "name": "Cross-ED consistency", "findings": []}],
    })


def test_add_and_get_audit(audits_db):
    audit_id = audits_db.add_audit(
        pr_number=1630, repo="owner/repo", pr_title="orch EDs MVP",
        pr_author="sxing", pr_url="https://github.com/owner/repo/pull/1630",
        head_ref="sxing/orch-eds-mvp", base_ref="main",
        content_json=_content(), finding_count=12, blocking_count=0,
    )
    assert isinstance(audit_id, int)
    got = audits_db.get_audit(audit_id)
    assert got["pr_number"] == 1630
    assert got["finding_count"] == 12
    assert got["blocking_count"] == 0
    assert got["audit_type"] == "pb_ed"


def test_get_latest_audit_for_pr(audits_db):
    audits_db.add_audit(pr_number=1630, repo="owner/repo", content_json=_content())
    audits_db.add_audit(pr_number=1630, repo="owner/repo", content_json=_content())
    latest = audits_db.get_latest_audit_for_pr("owner/repo", 1630)
    assert latest is not None
    all_for_pr = audits_db.get_audits_for_pr("owner/repo", 1630)
    assert len(all_for_pr) == 2


def test_check_pr_audited(audits_db):
    assert audits_db.check_pr_audited("owner/repo", 1630)["audited"] is False
    audits_db.add_audit(pr_number=1630, repo="owner/repo", content_json=_content())
    res = audits_db.check_pr_audited("owner/repo", 1630)
    assert res["audited"] is True
    assert res["audit_count"] == 1
    assert res["latest_audit"]["id"] is not None


def test_list_and_search(audits_db):
    audits_db.add_audit(pr_number=1630, repo="owner/repo", pr_title="orch EDs MVP",
                        content_json=_content(1630))
    audits_db.add_audit(pr_number=99, repo="other/repo", pr_title="something else",
                        content_json=_content(99))
    assert len(audits_db.list_audits(repo="owner/repo")) == 1
    assert len(audits_db.list_audits()) == 2
    assert len(audits_db.search_audits("orch")) == 1


def test_update_inline_comments_posted(audits_db):
    audit_id = audits_db.add_audit(pr_number=1630, repo="owner/repo", content_json=_content())
    audits_db.update_inline_comments_posted(audit_id, True)
    assert audits_db.get_audit(audit_id)["inline_comments_posted"] == 1


def test_singleton_factory():
    from backend.database import get_audits_db, AuditsDB as ExportedAuditsDB
    db = get_audits_db()
    assert isinstance(db, ExportedAuditsDB)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_audits_db.py -q`
Expected: FAIL with `ModuleNotFoundError: backend.database.audits`

- [ ] **Step 3: Write `AuditsDB`**

Create `backend/database/audits.py`:

```python
"""AuditsDB - Database operations for PB↔ED audits (JSON-primary storage)."""

import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class AuditsDB:
    """Database operations for PB↔ED audits.

    Audits are stored with content_json as the primary content column.
    There is no score; finding_count / blocking_count drive the UI chip.
    """

    def __init__(self, db):
        self.db = db

    def add_audit(
        self,
        pr_number: int,
        repo: str,
        pr_title: Optional[str] = None,
        pr_author: Optional[str] = None,
        pr_url: Optional[str] = None,
        head_ref: Optional[str] = None,
        base_ref: Optional[str] = None,
        audit_type: str = "pb_ed",
        status: str = "completed",
        content_json: Optional[str] = None,
        finding_count: int = 0,
        blocking_count: int = 0,
        audit_file_path: Optional[str] = None,
        audit_timestamp: Optional[datetime] = None,
    ) -> int:
        """Insert an audit. Returns the new audit ID."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            if content_json is None:
                content_json = "{}"
            timestamp = audit_timestamp or datetime.now()
            cursor.execute("""
                INSERT INTO audits (
                    pr_number, repo, pr_title, pr_author, pr_url,
                    head_ref, base_ref, audit_type, status, content_json,
                    finding_count, blocking_count, audit_file_path, audit_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pr_number, repo, pr_title, pr_author, pr_url,
                head_ref, base_ref, audit_type, status, content_json,
                finding_count, blocking_count, audit_file_path, timestamp,
            ))
            audit_id = cursor.lastrowid
            logger.info(f"Saved audit {audit_id} for PR #{pr_number} in {repo}")
            return audit_id

    def update_inline_comments_posted(self, audit_id: int, posted: bool = True):
        with self.db.connection() as conn:
            conn.cursor().execute(
                "UPDATE audits SET inline_comments_posted = ? WHERE id = ?",
                (posted, audit_id),
            )
            logger.info(f"Updated inline_comments_posted for audit {audit_id} to {posted}")

    def get_audit(self, audit_id: int) -> Optional[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM audits WHERE id = ?", (audit_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_audits_for_pr(self, repo: str, pr_number: int) -> List[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM audits WHERE repo = ? AND pr_number = ?
                ORDER BY audit_timestamp DESC, id DESC
            """, (repo, pr_number))
            return [dict(r) for r in cursor.fetchall()]

    def get_latest_audit_for_pr(self, repo: str, pr_number: int) -> Optional[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM audits WHERE repo = ? AND pr_number = ?
                ORDER BY audit_timestamp DESC, id DESC LIMIT 1
            """, (repo, pr_number))
            row = cursor.fetchone()
            return dict(row) if row else None

    def check_pr_audited(self, repo: str, pr_number: int) -> Dict[str, Any]:
        audits = self.get_audits_for_pr(repo, pr_number)
        if not audits:
            return {"audited": False, "audit_count": 0, "latest_audit": None}
        latest = audits[0]
        return {
            "audited": True,
            "audit_count": len(audits),
            "latest_audit": {
                "id": latest["id"],
                "audit_timestamp": latest["audit_timestamp"],
                "finding_count": latest["finding_count"],
                "blocking_count": latest["blocking_count"],
            },
        }

    def list_audits(
        self,
        repo: Optional[str] = None,
        author: Optional[str] = None,
        pr_number: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            conditions, params = [], []
            if repo:
                conditions.append("repo = ?"); params.append(repo)
            if author:
                conditions.append("pr_author = ?"); params.append(author)
            if pr_number:
                conditions.append("pr_number = ?"); params.append(pr_number)
            if status:
                conditions.append("status = ?"); params.append(status)
            where = "WHERE " + " AND ".join(conditions) if conditions else ""
            params.extend([limit, offset])
            cursor.execute(
                f"SELECT * FROM audits {where} ORDER BY audit_timestamp DESC LIMIT ? OFFSET ?",
                params,
            )
            return [dict(r) for r in cursor.fetchall()]

    def count_all(self) -> int:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as total FROM audits")
            return cursor.fetchone()["total"]

    def search_audits(self, search_text: str, limit: int = 20) -> List[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            pattern = f"%{search_text}%"
            cursor.execute("""
                SELECT * FROM audits
                WHERE pr_title LIKE ? OR content_json LIKE ?
                ORDER BY audit_timestamp DESC LIMIT ?
            """, (pattern, pattern, limit))
            return [dict(r) for r in cursor.fetchall()]
```

- [ ] **Step 4: Register the singleton**

In `backend/database/__init__.py`:

After `from backend.database.reviews import ReviewsDB` (line 7) add:
```python
from backend.database.audits import AuditsDB
```

After `_reviews_db: Optional[ReviewsDB] = None` (line 26) add:
```python
_audits_db: Optional["AuditsDB"] = None
```

After the `get_reviews_db()` function (line 56) add:
```python
def get_audits_db() -> AuditsDB:
    global _audits_db
    if _audits_db is None:
        db = get_database()
        with _db_lock:
            if _audits_db is None:
                _audits_db = AuditsDB(db)
    return _audits_db
```

In `__all__`, add `"AuditsDB"` next to `"ReviewsDB"` and `"get_audits_db"` next to `"get_reviews_db"`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_audits_db.py -q`
Expected: PASS (6 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/database/audits.py backend/database/__init__.py backend/tests/test_audits_db.py
git commit -m "Add AuditsDB with CRUD, search, and singleton factory"
```

---

## PHASE 3 — Audit service (Claude CLI subprocess)

### Task 6: active-audit tracking globals

**Files:**
- Modify: `backend/extensions.py`

- [ ] **Step 1: Add the globals**

After `reviews_lock = threading.Lock()` (line 25) in `backend/extensions.py`, add:

```python
# In-memory tracking of active audit processes (parallel to active_reviews)
# key: "owner/repo/pr_number", value: {"process": Popen, "status": str, ...}
active_audits = {}
audits_lock = threading.Lock()
```

- [ ] **Step 2: Verify import**

Run: `python -c "from backend.extensions import active_audits, audits_lock; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/extensions.py
git commit -m "Add active_audits tracking globals"
```

---

### Task 7: `audit_service.py`

**Files:**
- Create: `backend/services/audit_service.py`
- Test: `backend/tests/test_audit_service.py`

The `start_audit_process` subprocess launch can't be unit-tested without the `claude` CLI, so the test targets `save_audit_to_db` (the parse/validate/tally/persist path) with a temp DB and a fixture JSON file.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_audit_service.py`:

```python
"""Tests for audit_service.save_audit_to_db (parse → validate → tally → persist)."""

import json
import tempfile
from pathlib import Path

import pytest

from backend.database.base import Database
from backend.database.audits import AuditsDB
from backend.services.audit_service import save_audit_to_db


@pytest.fixture
def audits_db():
    p = Path(tempfile.mkdtemp()) / "svc_test.db"
    return AuditsDB(Database(p))


def _write_audit_json(tmpdir, pr=1630, blocking=False):
    data = {
        "schema_version": "1.0.0", "format": "audit", "audit_type": "pb_ed",
        "metadata": {"pr_number": pr, "repository": "owner/repo"},
        "audits": [
            {"key": "A", "name": "Cross-ED consistency", "findings": [
                {"id": "CE-1", "severity": "INCONSISTENCY", "summary": "x"},
            ]},
            {"key": "B", "name": "PB↔ED parity", "findings": [
                {"id": "PE-1",
                 "severity": "SCOPE-VIOLATION" if blocking else "UN-ANCHORED",
                 "summary": "y"},
            ]},
        ],
    }
    md = Path(tmpdir) / "owner-repo-pr-1630-audit.md"
    js = Path(tmpdir) / "owner-repo-pr-1630-audit.json"
    md.write_text("# audit", encoding="utf-8")
    js.write_text(json.dumps(data), encoding="utf-8")
    return str(md)


def test_save_completed_audit_persists_tallies(audits_db, monkeypatch):
    # Avoid network in fetch_pr_head_sha / fetch_pr_state
    monkeypatch.setattr("backend.services.audit_service.fetch_pr_head_sha", lambda *a, **k: "abc")
    monkeypatch.setattr("backend.services.audit_service.fetch_pr_state", lambda *a, **k: "OPEN")
    tmp = tempfile.mkdtemp()
    audit_file = _write_audit_json(tmp, blocking=True)
    audit = {"audit_file": audit_file, "pr_url": "https://github.com/owner/repo/pull/1630",
             "pr_title": "orch EDs MVP", "pr_author": "sxing",
             "head_ref": "sxing/orch-eds-mvp", "base_ref": "main"}
    save_audit_to_db("owner/repo/1630", audit, "completed", audits_db)

    latest = audits_db.get_latest_audit_for_pr("owner/repo", 1630)
    assert latest is not None
    assert latest["finding_count"] == 2
    assert latest["blocking_count"] == 1   # SCOPE-VIOLATION
    assert latest["status"] == "completed"


def test_failed_audit_persists_stub(audits_db, monkeypatch):
    monkeypatch.setattr("backend.services.audit_service.fetch_pr_head_sha", lambda *a, **k: "abc")
    monkeypatch.setattr("backend.services.audit_service.fetch_pr_state", lambda *a, **k: "OPEN")
    audit = {"audit_file": None, "pr_url": "", "pr_title": None, "pr_author": None}
    save_audit_to_db("owner/repo/1630", audit, "failed", audits_db)
    latest = audits_db.get_latest_audit_for_pr("owner/repo", 1630)
    assert latest["status"] == "failed"
    assert latest["finding_count"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_audit_service.py -q`
Expected: FAIL with `ModuleNotFoundError: backend.services.audit_service`

- [ ] **Step 3: Write `audit_service.py`**

Create `backend/services/audit_service.py`:

```python
"""Claude CLI subprocess management for PB↔ED audits: start, cancel, poll, save."""

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from backend.config import get_reviews_dir
from backend.services.github_service import fetch_pr_head_sha, fetch_pr_state
from backend.services.audit_schema import (
    AUDIT_SCHEMA_VERSION,
    validate_audit_json,
    compute_audit_tallies,
)

logger = logging.getLogger(__name__)

# Compact schema instructions embedded in the audit prompt.
_AUDIT_SCHEMA_INSTRUCTIONS = (
    "The JSON must have these top-level keys: "
    '"schema_version" (set to "1.0.0"), "format" (set to "audit"), '
    '"audit_type" (set to "pb_ed"), '
    '"metadata" (object with pr_number, repository, pr_url, pr_title, head_ref, base_ref, '
    "parent_pb {id, title, status}, eds (array of {id, title}), auditor, date, scope), "
    '"executive_summary" (markdown string), '
    '"audits" (array of {key, name, verdict, tally, findings}), '
    '"verified_clean" (markdown), "supplementary_notes" (markdown), '
    '"action_map" (array of {priority, finding_ids, nature}). '
    "Each finding MUST have: id (e.g. 'CE-1'), severity (uppercase token such as "
    "CONTRADICTION, SCOPE-VIOLATION, INCONSISTENCY, UN-ANCHORED, UNDER-COVERAGE, INFO), "
    "summary (one-line), and optionally blocking (boolean), rule_id, rule_authority, "
    "concept, lens, detail, recommendation, and locations (array of "
    "{file, line, ref, quote}). For locations, file MUST be a repo-relative path and "
    "line an integer so the finding can be posted as an inline PR comment; ref is the "
    "human display reference like 'ED-010 §10:389'. "
)


def save_audit_to_db(key, audit, status, audits_db):
    """Save a completed/failed audit to the database (reads the .json output file)."""
    try:
        parts = key.split("/")
        if len(parts) < 3:
            return
        owner, repo, pr_number = parts[0], parts[1], int(parts[2])
        full_repo = f"{owner}/{repo}"

        audit_json_data = None
        audit_file = audit.get("audit_file")

        if status == "completed" and audit_file:
            json_path = Path(audit_file).with_suffix(".json")
            if json_path.exists():
                try:
                    parsed = json.loads(json_path.read_text(encoding="utf-8"))
                    valid, errs = validate_audit_json(parsed)
                    if valid:
                        audit_json_data = parsed
                        logger.info(f"Loaded validated audit JSON from {json_path}")
                    else:
                        logger.warning(f"Audit JSON at {json_path} failed validation: {errs[:3]}")
                        audit_json_data = parsed  # keep it; still renderable
                except Exception as e:
                    logger.warning(f"Could not read/parse audit JSON {json_path}: {e}")

        if audit_json_data is None:
            audit_json_data = {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "format": "audit",
                "audit_type": "pb_ed",
                "error": True,
                "metadata": {"pr_number": pr_number, "repository": full_repo},
                "audits": [],
            }

        tallies = compute_audit_tallies(audit_json_data)
        content_json_str = json.dumps(audit_json_data, ensure_ascii=False)

        meta = audit_json_data.get("metadata", {})
        pr_title = audit.get("pr_title") or meta.get("pr_title") or f"PR #{pr_number} Audit"
        pr_author = audit.get("pr_author")
        pr_url = audit.get("pr_url") or meta.get("pr_url", "")
        head_ref = audit.get("head_ref") or meta.get("head_ref")
        base_ref = audit.get("base_ref") or meta.get("base_ref")

        audits_db.add_audit(
            pr_number=pr_number,
            repo=full_repo,
            pr_title=pr_title,
            pr_author=pr_author,
            pr_url=pr_url,
            head_ref=head_ref,
            base_ref=base_ref,
            status=status,
            content_json=content_json_str,
            finding_count=tallies["finding_count"],
            blocking_count=tallies["blocking_count"],
            audit_file_path=audit_file,
        )
        logger.info(f"Saved audit to database for {key}")
    except Exception as e:
        logger.error(f"Failed to save audit to database for {key}: {e}")


def check_audit_status(key, active_audits, audits_lock, audits_db):
    """Poll the subprocess for a running audit and persist on completion."""
    with audits_lock:
        if key not in active_audits:
            return None
        audit = active_audits[key]
        process = audit.get("process")
        if process and audit["status"] == "running":
            exit_code = process.poll()
            if exit_code is not None:
                try:
                    stdout, stderr = process.communicate(timeout=1)
                    if stderr:
                        audit["error_output"] = stderr.strip()[-2000:]
                except subprocess.TimeoutExpired:
                    pass
                except Exception as e:
                    logger.error(f"Error reading audit process output for {key}: {e}")

                status = "completed" if exit_code == 0 else "failed"
                audit["status"] = status
                audit["exit_code"] = exit_code
                audit["completed_at"] = datetime.now(timezone.utc).isoformat()
                if exit_code == 0:
                    logger.info(f"Audit completed successfully: {key}")
                else:
                    logger.error(f"Audit failed: {key} (exit {exit_code})")
                save_audit_to_db(key, audit, status, audits_db)
        return audit


def start_audit_process(pr_url, owner, repo, pr_number):
    """Start a Claude CLI audit process (invokes the /pb-ed-audit skill) in the background.

    Returns: (process, audit_file_path_or_error)
    """
    reviews_dir = get_reviews_dir()
    reviews_dir.mkdir(parents=True, exist_ok=True)

    repo_safe = repo.replace("/", "-")
    audit_file = reviews_dir / f"{owner}-{repo_safe}-pr-{pr_number}-audit.md"
    json_file = str(audit_file).replace(".md", ".json")

    prompt = (
        f"Run a PB↔ED audit on PR #{pr_number} at {pr_url}. "
        f"Use the /pb-ed-audit skill to audit the Engineering Design (ED) documents touched "
        f"in this PR against their parent Product Brief (PB) for parity, and against each "
        f"other for cross-ED consistency. "
        f"Write the human-readable audit report to {audit_file}. "
        f"ALSO write a structured JSON version to {json_file} following this schema: "
        f"{_AUDIT_SCHEMA_INSTRUCTIONS}"
    )

    cmd = [
        "claude",
        "-p", prompt,
        "--allowedTools", (
            "Bash(git status*),Bash(git log*),Bash(git show*),"
            "Bash(git diff*),Bash(git blame*),Bash(git branch*),"
            "Bash(gh pr view*),Bash(gh pr diff*),Bash(gh pr checks*),"
            "Bash(gh api*),Read,Glob,Grep,Write,Task,Skill"
        ),
        "--dangerously-skip-permissions",
    ]

    logger.info(f"Starting PB↔ED audit for PR #{pr_number} ({owner}/{repo})")
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        logger.info(f"Audit process started with PID {process.pid} for {owner}/{repo}/#{pr_number}")
        return process, str(audit_file)
    except FileNotFoundError:
        msg = "Claude CLI not found. Please ensure 'claude' is installed and in PATH."
        logger.error(f"Failed to start audit: {msg}")
        return None, msg
    except Exception as e:
        logger.error(f"Failed to start audit process: {e}")
        return None, str(e)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_audit_service.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/audit_service.py backend/tests/test_audit_service.py
git commit -m "Add audit_service: start/poll/save Claude CLI audit subprocess"
```

---

## PHASE 4 — Routes

### Task 8: `audit_routes.py` blueprint + registration

**Files:**
- Create: `backend/routes/audit_routes.py`
- Modify: `backend/routes/__init__.py`
- Test: `backend/tests/test_audit_routes.py`

The post-inline endpoint reuses `post_verdict` (reviewer-agnostic). The route maps each finding's first location with a resolvable `file`+`line` to an inline comment.

- [ ] **Step 1: Write the blueprint**

Create `backend/routes/audit_routes.py`:

```python
"""Audit routes: start, cancel, status, list active, history, detail, check, post-inline."""

import json
import subprocess
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from backend.extensions import logger, active_audits, audits_lock
from backend.database import get_audits_db
from backend.services.audit_service import (
    start_audit_process,
    check_audit_status,
)
from backend.services.audit_schema import audit_json_to_markdown
from backend.services.verdict_service import post_verdict
from backend.routes import error_response

audit_bp = Blueprint("audit", __name__)


def _audit_row_to_summary(row):
    return {
        "id": row["id"],
        "pr_number": row["pr_number"],
        "repo": row["repo"],
        "pr_title": row.get("pr_title"),
        "pr_author": row.get("pr_author"),
        "pr_url": row.get("pr_url"),
        "audit_timestamp": row.get("audit_timestamp"),
        "status": row.get("status"),
        "finding_count": row.get("finding_count", 0),
        "blocking_count": row.get("blocking_count", 0),
        "inline_comments_posted": bool(row.get("inline_comments_posted")),
    }


@audit_bp.route("/api/audits", methods=["GET"])
def get_audits():
    """Active/recent audits with refreshed statuses (drives the spinner)."""
    audits_db = get_audits_db()
    out = []
    with audits_lock:
        keys = list(active_audits.keys())
    for key in keys:
        check_audit_status(key, active_audits, audits_lock, audits_db)
        with audits_lock:
            audit = active_audits.get(key)
            if audit is None:
                continue
            parts = key.split("/")
            out.append({
                "key": key,
                "owner": parts[0] if len(parts) >= 1 else "",
                "repo": parts[1] if len(parts) >= 2 else "",
                "pr_number": int(parts[2]) if len(parts) >= 3 else 0,
                "status": audit["status"],
                "started_at": audit.get("started_at", ""),
                "completed_at": audit.get("completed_at", ""),
                "pr_url": audit.get("pr_url", ""),
                "audit_file": audit.get("audit_file", ""),
                "exit_code": audit.get("exit_code"),
                "error_output": audit.get("error_output", ""),
            })
    return jsonify({"audits": out})


@audit_bp.route("/api/audits", methods=["POST"])
def start_audit():
    """Start a PB↔ED audit for a PR."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        for field in ("number", "url", "owner", "repo"):
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        pr_number = data["number"]
        owner, repo = data["owner"], data["repo"]
        key = f"{owner}/{repo}/{pr_number}"

        with audits_lock:
            existing = active_audits.get(key)
            if existing and existing["status"] == "running":
                return jsonify({"error": "Audit already in progress for this PR"}), 409

        process, result = start_audit_process(data["url"], owner, repo, pr_number)
        if process is None:
            return jsonify({"error": result}), 500

        with audits_lock:
            active_audits[key] = {
                "process": process,
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "pr_url": data["url"],
                "audit_file": result,
                "pr_title": data.get("title"),
                "pr_author": data.get("author"),
                "head_ref": data.get("head_ref"),
                "base_ref": data.get("base_ref"),
            }
        return jsonify({
            "message": "Audit started", "key": key, "status": "running",
            "audit_file": result,
        }), 201
    except Exception as e:
        return error_response("Internal server error", 500, f"Error starting audit: {e}")


@audit_bp.route("/api/audits/<owner>/<repo>/<int:pr_number>", methods=["DELETE"])
def cancel_audit(owner, repo, pr_number):
    key = f"{owner}/{repo}/{pr_number}"
    with audits_lock:
        if key not in active_audits:
            return jsonify({"error": "Audit not found"}), 404
        audit = active_audits[key]
        process = audit.get("process")
        if process and audit["status"] == "running":
            try:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                audit["status"] = "cancelled"
            except Exception as e:
                return error_response("Failed to terminate audit process", 500,
                                      f"Failed to terminate audit for {key}: {e}")
        del active_audits[key]
    return jsonify({"message": "Audit cancelled", "key": key})


@audit_bp.route("/api/audits/<owner>/<repo>/<int:pr_number>/status", methods=["GET"])
def get_audit_status_endpoint(owner, repo, pr_number):
    key = f"{owner}/{repo}/{pr_number}"
    audit = check_audit_status(key, active_audits, audits_lock, get_audits_db())
    if audit is None:
        return jsonify({"error": "Audit not found"}), 404
    return jsonify({
        "key": key,
        "status": audit["status"],
        "started_at": audit.get("started_at", ""),
        "completed_at": audit.get("completed_at", ""),
        "pr_url": audit.get("pr_url", ""),
        "audit_file": audit.get("audit_file", ""),
        "exit_code": audit.get("exit_code"),
        "error_output": audit.get("error_output", ""),
    })


@audit_bp.route("/api/audit-history", methods=["GET"])
def list_audit_history():
    audits_db = get_audits_db()
    repo = request.args.get("repo")
    author = request.args.get("author")
    pr_number = request.args.get("pr_number", type=int)
    search = request.args.get("search")
    limit = request.args.get("limit", default=50, type=int)
    offset = request.args.get("offset", default=0, type=int)

    if search:
        rows = audits_db.search_audits(search, limit=limit)
    else:
        rows = audits_db.list_audits(repo=repo, author=author, pr_number=pr_number,
                                     limit=limit, offset=offset)
    return jsonify({
        "audits": [_audit_row_to_summary(r) for r in rows],
        "total": audits_db.count_all(),
    })


@audit_bp.route("/api/audit-history/<int:audit_id>", methods=["GET"])
def get_audit_detail(audit_id):
    audits_db = get_audits_db()
    row = audits_db.get_audit(audit_id)
    if not row:
        return jsonify({"error": "Audit not found"}), 404
    content_json = None
    content_md = ""
    try:
        content_json = json.loads(row["content_json"]) if row.get("content_json") else None
        if content_json:
            content_md = audit_json_to_markdown(content_json)
    except (json.JSONDecodeError, TypeError):
        pass
    summary = _audit_row_to_summary(row)
    summary["content_json"] = content_json
    summary["content"] = content_md
    summary["head_ref"] = row.get("head_ref")
    summary["base_ref"] = row.get("base_ref")
    summary["audit_file_path"] = row.get("audit_file_path")
    return jsonify({"audit": summary})


@audit_bp.route("/api/audit-history/check/<owner>/<repo>/<int:pr_number>", methods=["GET"])
def check_audit(owner, repo, pr_number):
    audits_db = get_audits_db()
    return jsonify(audits_db.check_pr_audited(f"{owner}/{repo}", pr_number))


def _findings_to_inline_comments(content_json):
    """Map findings with a resolvable file+line to verdict inline_comments entries."""
    comments = []
    for audit in content_json.get("audits", []):
        for f in audit.get("findings", []):
            for loc in f.get("locations", []):
                file = loc.get("file")
                line = loc.get("line")
                if file and isinstance(line, int) and line >= 1:
                    body_parts = [f"**[{f.get('id', '')}] {f.get('summary', '')}**"]
                    if f.get("severity"):
                        body_parts.append(f"_Severity: {f['severity']}_")
                    if f.get("detail"):
                        body_parts.append(f["detail"])
                    if f.get("recommendation"):
                        body_parts.append(f"**Recommendation:** {f['recommendation']}")
                    comments.append({
                        "path": file,
                        "start_line": line,
                        "end_line": line,
                        "body": "\n\n".join(body_parts),
                        "title": f.get("id", ""),
                    })
                    break  # one inline comment per finding (first mappable location)
    return comments


@audit_bp.route("/api/audits/<int:audit_id>/post-inline-comments", methods=["POST"])
def post_audit_inline_comments(audit_id):
    """Post audit findings with file+line locations as inline PR comments."""
    audits_db = get_audits_db()
    row = audits_db.get_audit(audit_id)
    if not row:
        return jsonify({"error": "Audit not found"}), 404
    if row.get("inline_comments_posted"):
        return jsonify({"error": "Inline comments already posted for this audit"}), 409
    try:
        content_json = json.loads(row["content_json"])
    except (json.JSONDecodeError, TypeError):
        return jsonify({"error": "Audit has no parseable content"}), 400

    comments = _findings_to_inline_comments(content_json)
    if not comments:
        return jsonify({"message": "No findings with mappable file+line locations",
                        "issues_posted": 0, "issues_found": 0}), 200

    repo_parts = (row.get("repo") or "").split("/")
    if len(repo_parts) != 2:
        return jsonify({"error": f"Invalid repo format: {row.get('repo')}"}), 400
    owner, repo_name = repo_parts

    body = f"**PB↔ED Audit** — {len(comments)} finding(s) posted inline."
    result, status_code = post_verdict(
        owner, repo_name, row["pr_number"], "COMMENT", body, inline_comments=comments,
    )
    if status_code == 200:
        audits_db.update_inline_comments_posted(audit_id, True)
    return jsonify(result), status_code
```

- [ ] **Step 2: Register the blueprint**

In `backend/routes/__init__.py`:

After `from backend.routes.review_routes import review_bp` (line 23) add:
```python
from backend.routes.audit_routes import audit_bp
```
After `app.register_blueprint(review_bp)` (line 40) add:
```python
    app.register_blueprint(audit_bp)
```

- [ ] **Step 3: Write the route tests**

Create `backend/tests/test_audit_routes.py`:

```python
"""Integration tests for audit routes via the Flask test client."""

import json
import tempfile
from pathlib import Path

import pytest

import backend.database as db_pkg
from backend.database.base import Database
from backend.database.audits import AuditsDB
from backend import create_app


@pytest.fixture
def client(monkeypatch):
    # Point the audits singleton at a temp DB
    tmp = Path(tempfile.mkdtemp()) / "routes_test.db"
    audits_db = AuditsDB(Database(tmp))
    monkeypatch.setattr(db_pkg, "get_audits_db", lambda: audits_db)
    import backend.routes.audit_routes as ar
    monkeypatch.setattr(ar, "get_audits_db", lambda: audits_db)
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client(), audits_db


def _content(pr=1630):
    return json.dumps({
        "schema_version": "1.0.0", "format": "audit", "audit_type": "pb_ed",
        "metadata": {"pr_number": pr, "repository": "owner/repo", "pr_title": "orch EDs MVP"},
        "executive_summary": "Strong set.",
        "audits": [{"key": "A", "name": "Cross-ED consistency", "findings": [
            {"id": "CE-1", "severity": "INCONSISTENCY", "summary": "x"}]}],
    })


def test_start_audit_requires_fields(client):
    c, _ = client
    resp = c.post("/api/audits", json={"number": 1})
    assert resp.status_code == 400


def test_audit_history_list_and_detail(client):
    c, audits_db = client
    audit_id = audits_db.add_audit(pr_number=1630, repo="owner/repo",
                                   pr_title="orch EDs MVP", content_json=_content(),
                                   finding_count=1, blocking_count=0)
    resp = c.get("/api/audit-history")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total"] == 1
    assert body["audits"][0]["pr_number"] == 1630

    resp = c.get(f"/api/audit-history/{audit_id}")
    assert resp.status_code == 200
    detail = resp.get_json()["audit"]
    assert detail["content_json"]["metadata"]["pr_number"] == 1630
    assert "Cross-ED consistency" in detail["content"]


def test_check_audit(client):
    c, audits_db = client
    resp = c.get("/api/audit-history/check/owner/repo/1630")
    assert resp.get_json()["audited"] is False
    audits_db.add_audit(pr_number=1630, repo="owner/repo", content_json=_content())
    resp = c.get("/api/audit-history/check/owner/repo/1630")
    assert resp.get_json()["audited"] is True
```

- [ ] **Step 4: Run the route tests**

Run: `python -m pytest backend/tests/test_audit_routes.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full backend suite**

Run: `python -m pytest backend/tests -q`
Expected: PASS (all green — baseline 27 + new audit tests)

- [ ] **Step 6: Commit**

```bash
git add backend/routes/audit_routes.py backend/routes/__init__.py backend/tests/test_audit_routes.py
git commit -m "Add /api/audits routes: start, status, cancel, history, detail, check, post-inline"
```

---

## PHASE 5 — Frontend API + types

### Task 9: Audit TypeScript types

**Files:**
- Modify: `frontend/src/api/types.ts` (append near the review JSON types, ~line 458)

- [ ] **Step 1: Add the types**

Append to `frontend/src/api/types.ts`:

```typescript
// ----- PB↔ED Audit types -----

export interface AuditLocation {
  file?: string
  line?: number | null
  ref?: string
  quote?: string
}

export interface AuditFinding {
  id: string
  severity: string
  blocking?: boolean
  rule_id?: string
  rule_authority?: string
  concept?: string
  lens?: string
  summary: string
  locations?: AuditLocation[]
  detail?: string
  recommendation?: string
}

export interface AuditSection {
  key: string
  name: string
  verdict?: string
  tally?: Record<string, number>
  findings: AuditFinding[]
}

export interface AuditJSONMetadata {
  pr_number: number
  repository: string
  pr_url?: string
  pr_title?: string
  head_ref?: string
  base_ref?: string
  parent_pb?: { id?: string; title?: string; status?: string }
  eds?: { id?: string; title?: string }[]
  auditor?: string
  date?: string
  scope?: string
}

export interface AuditActionRow {
  priority?: string
  finding_ids?: string[]
  nature?: string
}

export interface AuditJSON {
  schema_version: string
  format: 'audit'
  audit_type: string
  metadata: AuditJSONMetadata
  executive_summary?: string
  audits: AuditSection[]
  verified_clean?: string
  supplementary_notes?: string
  action_map?: AuditActionRow[]
}

export interface AuditHistoryItem {
  id: number
  pr_number: number
  repo: string
  pr_title?: string | null
  pr_author?: string | null
  pr_url?: string | null
  audit_timestamp?: string
  status?: string
  finding_count: number
  blocking_count: number
  inline_comments_posted: boolean
}

export interface AuditDetail extends AuditHistoryItem {
  content_json?: AuditJSON | null
  content?: string
  head_ref?: string | null
  base_ref?: string | null
  audit_file_path?: string | null
}

export interface AuditHistoryResponse {
  audits: AuditHistoryItem[]
  total: number
}

export interface ActiveAudit {
  key: string
  owner: string
  repo: string
  pr_number: number
  status: string
  started_at: string
  completed_at: string
  pr_url: string
  audit_file: string
  exit_code: number | null
  error_output: string
}

export interface ActiveAuditsResponse {
  audits: ActiveAudit[]
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit && cd ..`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/types.ts
git commit -m "Add frontend audit TypeScript types"
```

---

### Task 10: Audit API module

**Files:**
- Create: `frontend/src/api/audits.ts`

- [ ] **Step 1: Write the module**

Create `frontend/src/api/audits.ts`:

```typescript
import { api } from './client'
import {
  ActiveAuditsResponse,
  AuditHistoryResponse,
  AuditDetail,
  MessageResponse,
} from './types'

/** Fetch active/recent audits (drives the spinner). */
export async function fetchActiveAudits(): Promise<ActiveAuditsResponse> {
  return api.get<ActiveAuditsResponse>('/audits')
}

/** Start a PB↔ED audit for a PR. */
export async function startAudit(data: {
  number: number
  url: string
  owner: string
  repo: string
  title?: string
  author?: string
  head_ref?: string
  base_ref?: string
}): Promise<{ message: string; key: string; status: string; audit_file: string }> {
  return api.post('/audits', data)
}

/** Cancel a running audit. */
export async function cancelAudit(
  owner: string,
  repo: string,
  prNumber: number,
): Promise<MessageResponse> {
  return api.delete<MessageResponse>(`/audits/${owner}/${repo}/${prNumber}`)
}

/** Fetch audit history with filters. */
export async function fetchAuditHistory(params: {
  repo?: string
  author?: string
  pr_number?: number
  search?: string
  limit?: number
  offset?: number
}): Promise<AuditHistoryResponse> {
  const qp = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') qp.append(k, String(v))
  })
  const qs = qp.toString()
  return api.get<AuditHistoryResponse>(`/audit-history${qs ? `?${qs}` : ''}`)
}

/** Get an audit detail by ID. */
export async function getAuditDetail(auditId: number): Promise<AuditDetail> {
  const response = await api.get<{ audit: AuditDetail }>(`/audit-history/${auditId}`)
  return response.audit
}

/** Check whether a PR has been audited. */
export async function checkPRAudited(owner: string, repo: string, prNumber: number) {
  return api.get(`/audit-history/check/${owner}/${repo}/${prNumber}`)
}

/** Post audit findings (with file+line) as inline PR comments. */
export async function postAuditInlineComments(auditId: number): Promise<MessageResponse> {
  return api.post<MessageResponse>(`/audits/${auditId}/post-inline-comments`, {})
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit && cd ..`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/audits.ts
git commit -m "Add frontend audit API module"
```

---

## PHASE 6 — Picker + start wiring

### Task 11: Extend ReviewerType + picker option + active-audit store

**Files:**
- Modify: `frontend/src/api/reviews.ts:23` (`ReviewerType`)
- Modify: `frontend/src/components/reviews/ReviewerPickerMenu.tsx`
- Create: `frontend/src/stores/useAuditStore.ts`

- [ ] **Step 1: Extend `ReviewerType`**

In `frontend/src/api/reviews.ts`, change line 23:
```typescript
export type ReviewerType = 'default' | 'pb' | 'ed' | 'audit'
```

- [ ] **Step 2: Add the picker option**

In `frontend/src/components/reviews/ReviewerPickerMenu.tsx`, after the Engineering Design Reviewer `<button>` block (closing `</button>` at line 71), add:

```tsx
      <button
        type="button"
        role="menuitem"
        className="mx-reviewer-picker__option"
        onClick={() => onSelect('audit')}
      >
        <span className="mx-reviewer-picker__icon">🔎</span>
        <span className="mx-reviewer-picker__label">
          <strong>PB ED Audit</strong>
          <small>pb-ed-audit skill</small>
        </span>
      </button>
```

- [ ] **Step 3: Create the active-audit store**

Create `frontend/src/stores/useAuditStore.ts`:

```typescript
import { create } from 'zustand'
import { fetchActiveAudits, startAudit as apiStartAudit, cancelAudit as apiCancelAudit } from '../api/audits'
import type { ActiveAudit } from '../api/types'

interface AuditStartArgs {
  number: number
  url: string
  owner: string
  repo: string
  title?: string
  author?: string
  head_ref?: string
  base_ref?: string
}

interface AuditStoreState {
  activeAudits: ActiveAudit[]
  startAudit: (args: AuditStartArgs) => Promise<void>
  cancelAudit: (owner: string, repo: string, prNumber: number) => Promise<void>
  refreshActiveAudits: () => Promise<void>
  /** True if an audit is running/recent for this PR. */
  auditStatusFor: (owner: string, repo: string, prNumber: number) => string | null
}

export const useAuditStore = create<AuditStoreState>((set, get) => ({
  activeAudits: [],

  startAudit: async (args) => {
    await apiStartAudit(args)
    await get().refreshActiveAudits()
  },

  cancelAudit: async (owner, repo, prNumber) => {
    await apiCancelAudit(owner, repo, prNumber)
    await get().refreshActiveAudits()
  },

  refreshActiveAudits: async () => {
    try {
      const resp = await fetchActiveAudits()
      set({ activeAudits: resp.audits })
    } catch {
      // transient; leave prior state
    }
  },

  auditStatusFor: (owner, repo, prNumber) => {
    const key = `${owner}/${repo}/${prNumber}`
    const found = get().activeAudits.find((a) => a.key === key)
    return found ? found.status : null
  },
}))
```

- [ ] **Step 4: Branch the picker callers to start an audit**

Open `frontend/src/components/reviews/ReviewButton.tsx`. It currently handles the picker `onSelect` by calling `startReview(...)` (around line 37). Replace the select handler body so an `'audit'` selection routes to the audit store instead. Concretely, find where the picker's `onSelect` calls the review start, and wrap it:

```tsx
// near the top, with the other store imports:
import { useAuditStore } from '../../stores/useAuditStore'

// inside the component:
const startAudit = useAuditStore((s) => s.startAudit)

// the picker select handler (replace the existing one that called startReview):
const handleReviewerSelect = (reviewer: ReviewerType) => {
  setPickerOpen(false)
  if (reviewer === 'audit') {
    startAudit({
      number: pr.number,
      url: pr.url,
      owner,
      repo,
      title: pr.title,
      author: pr.author?.login,
      head_ref: pr.headRefName,
      base_ref: pr.baseRefName,
    })
    return
  }
  startReview({
    number: pr.number,
    url: pr.url,
    owner,
    repo,
    title: pr.title,
    author: pr.author?.login,
    reviewer_type: reviewer,
  })
}
```

> Note: use the prop/variable names already present in `ReviewButton.tsx` (it already has `pr`, `owner`, `repo`, and a `startReview` call — mirror those exact names; only add the `reviewer === 'audit'` branch and the `useAuditStore` import). Do the same in `QueueReviewButton.tsx`, using its existing queue-item fields for `number/url/owner/repo/title/author` and passing `head_ref`/`base_ref` if available on the queue item (omit if not).

- [ ] **Step 5: Poll active audits where active reviews are already polled**

Find where the app polls `fetchActiveReviews` on an interval (search: `grep -rn "fetchActiveReviews\|refreshActiveReviews\|setInterval" frontend/src`). In that same interval/effect, also call `useAuditStore.getState().refreshActiveAudits()` so audit spinners update on the same cadence. Add one line next to the existing reviews refresh call.

- [ ] **Step 6: Verify the build**

Run: `cd frontend && npm run build && cd ..`
Expected: build succeeds (no TypeScript errors)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/reviews.ts frontend/src/components/reviews/ReviewerPickerMenu.tsx frontend/src/stores/useAuditStore.ts frontend/src/components/reviews/ReviewButton.tsx frontend/src/components/reviews/QueueReviewButton.tsx
git commit -m "Add PB ED Audit picker option and wire audit start/polling"
```

---

## PHASE 7 — Viewer, chip, history list

### Task 12: AuditChip + styles

**Files:**
- Create: `frontend/src/components/audits/AuditChip.tsx`
- Create: `frontend/src/styles/audits.css`
- Modify: the styles entry (where other CSS is imported — search `grep -rn "timeline.css" frontend/src` and add `audits.css` next to it)

- [ ] **Step 1: Write the chip**

Create `frontend/src/components/audits/AuditChip.tsx`:

```tsx
interface AuditChipProps {
  findingCount: number
  blockingCount: number
  /** Optional dominant blocking severity label, e.g. "scope-violation". */
  blockingLabel?: string
  onClick?: () => void
  title?: string
}

export function AuditChip({ findingCount, blockingCount, blockingLabel, onClick, title }: AuditChipProps) {
  const blocking = blockingCount > 0
  const label = blocking
    ? `Audit · ${blockingCount} ${blockingLabel || 'blocking'}`
    : `Audit · 0 blocking`
  return (
    <button
      type="button"
      className={`mx-audit-chip ${blocking ? 'mx-audit-chip--blocking' : 'mx-audit-chip--clean'}`}
      onClick={onClick}
      title={title || `${findingCount} finding(s), ${blockingCount} blocking`}
    >
      {label}
    </button>
  )
}
```

- [ ] **Step 2: Write the styles**

Create `frontend/src/styles/audits.css`:

```css
.mx-audit-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  border: 1px solid transparent;
  cursor: pointer;
  white-space: nowrap;
}
.mx-audit-chip--clean {
  color: var(--mx-color-success);
  background: var(--mx-color-success-bg);
  border-color: var(--mx-color-success);
}
.mx-audit-chip--blocking {
  color: var(--mx-color-error);
  background: var(--mx-color-error-bg);
  border-color: var(--mx-color-error);
}

.mx-audit-viewer__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.mx-audit-viewer__meta {
  font-size: 12px;
  opacity: 0.8;
}
.mx-audit-viewer__body {
  max-height: 70vh;
  overflow-y: auto;
}
```

> If `--mx-color-error-bg` / `--mx-color-success-bg` don't exist, reuse the variables the existing score badge / approved-by-me highlight uses (search `grep -rn "mx-color-success-bg\|mx-color-error" frontend/src/styles`); substitute the closest existing custom properties.

- [ ] **Step 3: Import the stylesheet**

Add `import './styles/audits.css'` (or the project's CSS import convention) next to the existing `timeline.css` import.

- [ ] **Step 4: Verify the build**

Run: `cd frontend && npm run build && cd ..`
Expected: build succeeds

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/audits/AuditChip.tsx frontend/src/styles/audits.css
git commit -m "Add AuditChip component and audit styles"
```

---

### Task 13: AuditViewer modal

**Files:**
- Create: `frontend/src/components/audits/AuditViewer.tsx`

Reuse the markdown rendering approach `ReviewViewer.tsx` uses (`react-markdown` + `remark-gfm` + `rehype-highlight`). Open `ReviewViewer.tsx` for the exact import lines and modal shell classes, then mirror them.

- [ ] **Step 1: Write the viewer**

Create `frontend/src/components/audits/AuditViewer.tsx`:

```tsx
import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { getAuditDetail } from '../../api/audits'
import type { AuditDetail } from '../../api/types'
import { AuditChip } from './AuditChip'

interface AuditViewerProps {
  auditId: number
  onClose: () => void
}

export function AuditViewer({ auditId, onClose }: AuditViewerProps) {
  const [audit, setAudit] = useState<AuditDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getAuditDetail(auditId)
      .then((d) => { if (!cancelled) setAudit(d) })
      .catch((e) => { if (!cancelled) setError(String(e)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [auditId])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const meta = audit?.content_json?.metadata

  return (
    <div className="mx-modal-overlay" onClick={onClose}>
      <div className="mx-modal" onClick={(e) => e.stopPropagation()}>
        <div className="mx-audit-viewer__header">
          <div>
            <h2>PB↔ED Audit{meta ? ` — PR #${meta.pr_number}` : ''}</h2>
            {meta && (
              <div className="mx-audit-viewer__meta">
                {meta.parent_pb?.id ? `Parent: ${meta.parent_pb.id}` : ''}
                {meta.eds?.length ? ` · EDs: ${meta.eds.map((e) => e.id).join(', ')}` : ''}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {audit && (
              <AuditChip
                findingCount={audit.finding_count}
                blockingCount={audit.blocking_count}
              />
            )}
            <button type="button" className="mx-btn" onClick={onClose}>✕</button>
          </div>
        </div>
        <div className="mx-audit-viewer__body">
          {loading && <p>Loading audit…</p>}
          {error && <p className="mx-error">Failed to load audit: {error}</p>}
          {audit?.content && (
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
              {audit.content}
            </ReactMarkdown>
          )}
        </div>
      </div>
    </div>
  )
}
```

> Use the exact overlay/modal class names from `ReviewViewer.tsx` (e.g. it may use different class names than `mx-modal-overlay`/`mx-modal`/`mx-btn`); substitute the project's actual ones so styling is consistent.

- [ ] **Step 2: Verify the build**

Run: `cd frontend && npm run build && cd ..`
Expected: build succeeds

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/audits/AuditViewer.tsx
git commit -m "Add AuditViewer modal"
```

---

### Task 14: Audit history list + tab

**Files:**
- Create: `frontend/src/components/audits/AuditHistoryList.tsx`
- Modify: the review history panel component to add an "Audits" tab (search: `grep -rln "review-history\|ReviewHistory\|History" frontend/src/components`)

- [ ] **Step 1: Write the history list**

Create `frontend/src/components/audits/AuditHistoryList.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { fetchAuditHistory } from '../../api/audits'
import type { AuditHistoryItem } from '../../api/types'
import { AuditChip } from './AuditChip'
import { AuditViewer } from './AuditViewer'

export function AuditHistoryList() {
  const [items, setItems] = useState<AuditHistoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [openId, setOpenId] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchAuditHistory({ search: search || undefined, limit: 50 })
      .then((r) => { if (!cancelled) setItems(r.audits) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [search])

  return (
    <div className="mx-audit-history">
      <input
        type="text"
        placeholder="Search audits…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="mx-input"
      />
      {loading && <p>Loading audits…</p>}
      {!loading && items.length === 0 && <p>No audits yet.</p>}
      <ul className="mx-audit-history__list">
        {items.map((a) => (
          <li key={a.id} className="mx-audit-history__row">
            <button type="button" className="mx-link" onClick={() => setOpenId(a.id)}>
              PR #{a.pr_number} — {a.pr_title || a.repo}
            </button>
            <span className="mx-audit-history__meta">{a.repo}</span>
            <AuditChip
              findingCount={a.finding_count}
              blockingCount={a.blocking_count}
              onClick={() => setOpenId(a.id)}
            />
          </li>
        ))}
      </ul>
      {openId !== null && <AuditViewer auditId={openId} onClose={() => setOpenId(null)} />}
    </div>
  )
}
```

- [ ] **Step 2: Add the "Audits" tab**

In the history panel component, add a tab toggle (`'reviews' | 'audits'`) and render `<AuditHistoryList />` when `'audits'` is selected, mirroring the existing review-history list rendering. Use the panel's existing tab markup/classes.

- [ ] **Step 3: Verify the build**

Run: `cd frontend && npm run build && cd ..`
Expected: build succeeds

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/audits/AuditHistoryList.tsx
git add <the history panel component file>
git commit -m "Add audit history list and Audits tab in the history panel"
```

---

## PHASE 8 — Verdict audit mode

### Task 15: VerdictModal — branch standard vs audit

**Files:**
- Modify: `frontend/src/components/queue/VerdictModal.tsx`

The modal is opened for a queue/PR item. It needs to know whether to compose from a standard review or an audit. Decision rule: if the item has an audit (checked via `checkPRAudited` / a passed-in `auditId`) the modal renders **audit mode**; otherwise standard mode. To keep the change contained, add a `mode?: 'review' | 'audit'` + `auditId?: number` to the modal props; the opener passes `mode="audit"` when launched from an audit context (AuditViewer / audit chip / queue item with an audit).

- [ ] **Step 1: Add audit-mode composition helpers**

In `VerdictModal.tsx`, add (near the existing `composeBody`/`buildInlineComments` helpers) audit-specific builders. These consume `AuditDetail.content_json`:

```tsx
import { getAuditDetail, postAuditInlineComments } from '../../api/audits'
import type { AuditDetail, AuditJSON } from '../../api/types'

// Toggleable audit blocks
type AuditBlockKey = 'exec' | 'action_map' | string  // plus one per audit key

function composeAuditBody(audit: AuditJSON, enabled: Set<string>): string {
  const parts: string[] = []
  if (enabled.has('exec') && audit.executive_summary) {
    parts.push(`**Executive summary**\n\n${audit.executive_summary}`)
  }
  for (const section of audit.audits) {
    const key = `audit:${section.key}`
    if (!enabled.has(key)) continue
    const lines = [`**Audit ${section.key} — ${section.name}**`]
    if (section.verdict) lines.push(section.verdict)
    for (const f of section.findings) {
      lines.push(`- **[${f.id}] ${f.severity}** — ${f.summary}`)
    }
    parts.push(lines.join('\n'))
  }
  if (enabled.has('action_map') && audit.action_map?.length) {
    const rows = audit.action_map
      .map((r) => `| ${r.priority || ''} | ${(r.finding_ids || []).join(', ')} | ${r.nature || ''} |`)
      .join('\n')
    parts.push(`**Action map**\n\n| Priority | Items | Nature |\n|---|---|---|\n${rows}`)
  }
  return parts.join('\n\n---\n\n')
}

function auditInlineComments(audit: AuditJSON): {
  path: string; start_line: number; end_line: number; body: string; title: string
}[] {
  const out: { path: string; start_line: number; end_line: number; body: string; title: string }[] = []
  for (const section of audit.audits) {
    for (const f of section.findings) {
      const loc = (f.locations || []).find((l) => l.file && typeof l.line === 'number' && (l.line as number) >= 1)
      if (!loc) continue
      const bodyParts = [`**[${f.id}] ${f.summary}**`, `_Severity: ${f.severity}_`]
      if (f.detail) bodyParts.push(f.detail)
      if (f.recommendation) bodyParts.push(`**Recommendation:** ${f.recommendation}`)
      out.push({
        path: loc.file as string,
        start_line: loc.line as number,
        end_line: loc.line as number,
        body: bodyParts.join('\n\n'),
        title: f.id,
      })
    }
  }
  return out
}
```

- [ ] **Step 2: Branch the modal render on mode**

When `mode === 'audit'`:
1. On open, `getAuditDetail(auditId)` and store the `AuditDetail`.
2. Render toggle checkboxes: **Executive summary** (`exec`), one per `content_json.audits[]` (`audit:A`, `audit:B`, …), **Action map** (`action_map`).
3. The composed body = `composeAuditBody(content_json, enabledSet)` (feeding the existing manual-override textarea — reuse the existing `manualBodyOverride` machinery verbatim).
4. Inline comments = `auditInlineComments(content_json)` (offered with a checkbox "Post N findings inline").
5. On submit, call the existing `postVerdict(owner, repo, prNumber, { event, body, inline_comments, review_id: undefined })`. (Do **not** pass `review_id` for audits — section-count tracking is review-only.)

Keep the standard-mode code path entirely unchanged; gate the new UI behind `mode === 'audit'`.

- [ ] **Step 3: Verify the build**

Run: `cd frontend && npm run build && cd ..`
Expected: build succeeds

- [ ] **Step 4: Manual smoke (optional, if a dev server is run)**

Open the VerdictModal in audit mode and confirm the toggles compose the body and the inline-comment count reflects findings with `file`+`line`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/queue/VerdictModal.tsx
git commit -m "Add audit-mode composition to VerdictModal (toggleable blocks + inline from findings)"
```

---

## PHASE 9 — Skill output contract + docs + verification

### Task 16: Update the `/pb-ed-audit` skill to emit JSON

**Files:**
- Modify: `~/.claude/skills/pb-ed-audit/SKILL.md` (and any referenced output-template file in that skill dir)

The skill currently writes a markdown report. The backend prompt (Task 7) asks it to ALSO write a JSON file conforming to `audit_schema_spec.json`. Make that a first-class part of the skill's output contract so audits run from the app produce valid JSON with resolved `file`+`line` locations.

- [ ] **Step 1: Read the skill**

Run: `sed -n '1,120p' ~/.claude/skills/pb-ed-audit/SKILL.md` (and `ls ~/.claude/skills/pb-ed-audit/`) to see its current output section.

- [ ] **Step 2: Add a JSON-output section**

Add a section to the skill instructing: when an output JSON path is provided in the prompt, after writing the markdown report also write a JSON file conforming to the audit schema. Document the required keys (mirror `_AUDIT_SCHEMA_INSTRUCTIONS`), and emphasize that each finding's `locations[]` must include the resolved repo-relative `file` and integer `line` (not only the `ED-010 §10:389` display ref) so the app can post inline comments. Include a compact example finding object.

- [ ] **Step 3: Sanity check the skill file is valid markdown**

Run: `head -5 ~/.claude/skills/pb-ed-audit/SKILL.md`
Expected: frontmatter intact (`---` / `name:` / `description:`)

- [ ] **Step 4: Commit (skill lives outside the repo)**

The skill is under `~/.claude/skills/`, not in this repo. Note the change in the PR description instead of committing it here. If the skill dir is itself a git repo, commit there separately:
```bash
cd ~/.claude/skills/pb-ed-audit && git add -A && git commit -m "Emit audit JSON (with resolved file+line) for app integration" 2>/dev/null || true
cd - >/dev/null
```

---

### Task 17: Update DESIGN.md

**Files:**
- Modify: `docs/DESIGN.md`

- [ ] **Step 1: Document the audit subsystem**

Add to `docs/DESIGN.md`:
- Database Module table: add `AuditsDB` row.
- Database Schema: add the `audits` CREATE TABLE.
- A new "PB↔ED Audit" feature subsection under Features (how it runs, the chip, the viewer, the two-part report).
- API Endpoints: add the `/api/audits` + `/api/audit-history` routes.
- Code Review System: note the picker's fourth option "PB ED Audit" → `reviewer_type`/audit path and the audit JSON schema.
- Review JSON Schema section: add a sibling "Audit JSON Schema" subsection summarizing the shape and pointing to `backend/services/audit_schema_spec.json`.

- [ ] **Step 2: Commit**

```bash
git add docs/DESIGN.md
git commit -m "Document PB↔ED audit subsystem in DESIGN.md"
```

---

### Task 18: Full verification

- [ ] **Step 1: Backend suite green**

Run: `python -m pytest backend/tests -q`
Expected: PASS (baseline 27 + audit schema (9) + audits DB (6) + audit service (2) + audit routes (3))

- [ ] **Step 2: Frontend builds + typechecks**

Run: `cd frontend && npm run build && cd ..`
Expected: build succeeds with no TypeScript errors

- [ ] **Step 3: App boots**

Run: `python -c "from backend import create_app; app = create_app(); print('routes:', len([r for r in app.url_map.iter_rules() if 'audit' in r.rule]))"`
Expected: prints a non-zero audit route count (≥ 7)

- [ ] **Step 4: Final commit (if anything uncommitted)**

```bash
git status --short
```

---

## Self-review (completed during planning)

**Spec coverage:**
- Audit JSON schema → Tasks 1–3 ✓
- `audits` table + `AuditsDB` + `/api/audits` routes + separate history → Tasks 4, 5, 8 ✓
- Picker "PB ED Audit" + run via `/pb-ed-audit` skill → Tasks 7, 11, 16 ✓
- Per-finding inline comments (file+line) + whole-report comment → Task 8 (`post-inline`), Task 15 (verdict inline), reuse `post_verdict` ✓
- Audit chip (blocking-count) → Tasks 12, 13, 14 ✓
- AuditViewer + separate history list → Tasks 13, 14 ✓
- Verdict two formats (toggleable audit blocks) → Task 15 ✓
- Isolation in worktree → already done ✓
- DESIGN.md update → Task 17 ✓

**Type consistency:** `AuditsDB.add_audit(...)` signature is used identically in `save_audit_to_db` and tests; `compute_audit_tallies` returns `{finding_count, blocking_count}` used by the service and persisted to the same-named columns; frontend `AuditJSON`/`AuditDetail`/`AuditFinding` names are reused across `audits.ts`, `AuditViewer`, `AuditHistoryList`, and `VerdictModal`.

**Known frontend integration points the implementer must resolve against the live code** (called out inline, not placeholders): the exact prop names in `ReviewButton.tsx`/`QueueReviewButton.tsx`, the modal shell class names in `ReviewViewer.tsx`, the CSS custom-property names for success/error backgrounds, the active-reviews polling site, and the history panel's tab markup.
