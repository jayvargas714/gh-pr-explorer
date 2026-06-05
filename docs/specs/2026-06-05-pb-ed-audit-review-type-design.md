# PB↔ED Audit as a First-Class Review Output — Design Spec

**Date:** 2026-06-05
**Branch:** `worktree-pb-ed-audit-review-type`
**Status:** Approved design, pending spec review

## Problem

The app's review system produces one shape of output: a standard code review (0–10 score,
`critical`/`major`/`minor` issue sections), driven by the `elite-code-reviewer`,
`product-brief-reviewer`, and `ed-reviewer` agents. A new kind of output is needed: a
**PB↔ED Audit** — the report produced by the `/pb-ed-audit` skill, which checks that a PR's
Engineering Design documents (EDs) have parity with their parent Product Brief (PB) and are
internally consistent with each other.

An audit is structurally unlike a code review:

- It is a **two-part report** — *Audit A: Cross-ED consistency* and *Audit B: PB↔ED parity* —
  each with its own verdict, findings table, and detailed finding blocks.
- Findings carry **IDs** (`CE-1`, `PE-1`), **severity labels** that are not critical/major/minor
  (`CONTRADICTION`, `INCONSISTENCY`, `INFO`, `SCOPE-VIOLATION`, `UN-ANCHORED`, `UNDER-COVERAGE`),
  **rule IDs** with an **authority** (e.g. `ED.COHERE.DRIFT` [SPEC-AUTH-0013]), doc-section
  **locations** (`ED-010 §10:389`), a "why it conflicts/assessment", and a
  "reconciliation/recommendation".
- It has **no 0–10 score**. It has an **executive summary** and an **action map** instead.
- It operates on **documents** (EDs/PBs), not a code diff.

Reference sample: `~/code-reviews/PR1630-ed-audit-2026-06-05-0715.md`.

## Goals

1. A versioned **audit JSON schema** (formal spec + Python validation + `json_to_markdown`),
   parallel to the existing review schema.
2. Audits become a **new output type of the review system** — selectable from the review-type
   picker as **"PB ED Audit"**.
3. A standardized format that can be **rendered in the app UI** and **posted to the PR**
   (whole-report comment **and** per-finding inline comments where locations map to file+line).
4. The **Verdict view supports two formats** — the existing standard review, and the new audit.
5. All work happens in an **isolated worktree** so the app running on `main` is undisturbed.

## Non-goals

- No `markdown_to_json` back-importer for the four existing sample `.md` audits. New audits emit
  JSON natively. (Flagged; can be added later if wanted.)
- No new audit *kinds* beyond `pb_ed` in this iteration (schema is future-proofed via `audit_type`).

---

## Architecture

The audit subsystem is built as a **parallel track** to the review subsystem rather than by
overloading the `reviews` table / `critical|major|minor` section model. This was a deliberate
choice (see Decisions) because the audit shape diverges enough that discriminating inside the
existing tables would spread `if format == 'audit'` branches through every review code path and
add audit-only columns to the reviews schema.

### 1. Audit JSON schema (core deliverable)

New files, mirroring `review_schema.py` / `review_schema_spec.json`:

- `backend/services/audit_schema.py` — `AUDIT_SCHEMA_VERSION`, `validate_audit_json(data)`,
  `audit_json_to_markdown(data)`, and a `compute_audit_tallies(data)` helper that derives
  `finding_count` and `blocking_count`.
- `backend/services/audit_schema_spec.json` — formal JSON Schema (draft-07) for external
  tools/agents (the `/pb-ed-audit` skill targets this).

Schema shape (v1.0.0):

```jsonc
{
  "schema_version": "1.0.0",
  "format": "audit",          // discriminator vs standard reviews
  "audit_type": "pb_ed",      // future-proofs other audit kinds
  "metadata": {
    "pr_number": 1630,
    "repository": "owner/repo",
    "pr_url": "https://github.com/owner/repo/pull/1630",
    "pr_title": "orch EDs MVP",
    "head_ref": "sxing/orch-eds-mvp",
    "base_ref": "main",
    "parent_pb": { "id": "PB-017", "title": "Sim Orchestrator", "status": "Approved 2026-06-04" },
    "eds": [ { "id": "ED-008", "title": "Simulation Job State Machine" } ],
    "auditor": "Claude (pb-ed-audit skill)",
    "date": "2026-06-05",
    "scope": "PB↔ED parity (Audit B) and cross-ED consistency (Audit A)"
  },
  "executive_summary": "markdown string",
  "audits": [                  // list (not hardcoded A/B) so the schema is flexible
    {
      "key": "A",
      "name": "Cross-ED consistency",
      "verdict": "markdown string",
      "tally": { "contradiction": 0, "inconsistency": 3, "info": 2 },
      "findings": [
        {
          "id": "CE-1",
          "severity": "INCONSISTENCY",       // free uppercase token per audit
          "blocking": false,                  // true => drives the red chip
          "rule_id": "ED.COHERE.DRIFT",
          "rule_authority": "SPEC-AUTH-0013",
          "concept": "Milestone dependency",
          "lens": "Consistency",
          "summary": "one-line summary",
          "locations": [
            { "file": "docs/designs/ED-010-job-dispatch.md", "line": 389, "ref": "ED-010 §10:389", "quote": "…" }
          ],
          "detail": "why it conflicts (markdown)",
          "recommendation": "reconciliation (markdown)"
        }
      ]
    }
  ],
  "verified_clean": "markdown string",   // the "Verified consistent / Clean-correctly-scoped" prose
  "supplementary_notes": "markdown string",
  "action_map": [
    { "priority": "Fix in-doc", "finding_ids": ["CE-1", "CE-3"], "nature": "Correct the milestone graph…" }
  ]
}
```

**Required** top-level keys: `schema_version`, `format` (== `"audit"`), `audit_type`, `metadata`,
`audits`. **Required** `metadata`: `pr_number`, `repository`. **Required** per-audit: `key`,
`name`, `findings`. **Required** per-finding: `id`, `severity`, `summary`. Everything else is
optional so partial/cheaper audits still validate.

**Locations & inline comments (load-bearing):** each finding's `locations[]` carries a resolved
`file` (repo-relative path) + `line` in addition to the human display `ref`. This is what makes
per-finding inline GitHub comments possible. Findings whose locations lack a resolvable `file`+`line`
are still rendered in the whole-report comment but are not offered for inline posting.

**`blocking` derivation:** the schema lets the agent set `blocking` explicitly. As a safety net,
`compute_audit_tallies` also treats severities `CONTRADICTION` and `SCOPE-VIOLATION` as blocking
when the flag is absent, so the chip color is correct even if the agent omits the flag.

### 2. Storage — `audits` table + `AuditsDB`

New table (tracked migration in `backend/database/base.py`) and a new `AuditsDB` class in
`backend/database/audits.py`, registered via a `get_audits_db()` singleton in
`backend/database/__init__.py`:

```sql
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
);
```

No `score` column — the chip is computed from `blocking_count` / `finding_count`.

`AuditsDB` methods (mirroring the relevant `ReviewsDB` surface): `add_audit()`, `get_audit()`,
`get_audits_for_pr()`, `get_latest_audit_for_pr()`, `search_audits()` (repo/author/date/text
filters over `content_json`), `check_pr_audited()`, `update_audit()` (e.g. mark inline comments
posted), and `get_stats()`.

### 3. Running the audit

- **Shared subprocess machinery.** Extract the generic "spawn a `claude -p` review subprocess,
  track it, poll it, persist on completion" flow from `review_service.py` into a reusable helper
  so both reviews and audits use one implementation. The audit path differs only in: the prompt,
  the allowed tools, the output schema, and the destination table.
- **Trigger.** The review-type picker gains a **"PB ED Audit"** option. Because audit lifecycle
  (start/status/cancel/history) is a separate surface, the frontend calls a new
  `POST /api/audits` (not `/api/reviews`). Internally that handler reuses the shared subprocess
  helper.
- **Active tracking.** Audits get their own `active_audits` dict + `audits_lock` in
  `backend/extensions.py`, keyed `owner/repo/pr`, so an audit and a code review can run on the same
  PR concurrently without key collision.
- **Prompt.** The audit prompt instructs Claude to invoke the `/pb-ed-audit` skill for the PR and
  to write structured JSON conforming to `audit_schema_spec.json` to the `.json` output path
  (and a generated `.md`). `--allowedTools` adds `Skill` and `Task` (the skill dispatches
  parallel subagents) on top of the existing `Bash(git*)`, `Bash(gh*)`, `Read`, `Glob`, `Grep`,
  `Write`.
- **The `/pb-ed-audit` skill must emit the JSON.** Updating the skill's output contract to write
  the structured audit JSON (resolved `file`+`line` locations included) is part of this work.
  Output file naming follows the existing convention, e.g.
  `{owner}-{repo}-pr-{number}-audit.json` / `.md` under the configured reviews dir.

### 4. Read / history / rendering

- **Routes.** New `audit_bp` blueprint at `backend/routes/audit_routes.py`:
  - `POST /api/audits` — start an audit (returns running status)
  - `GET /api/audits` — active/recent audits (for the spinner polling, mirrors `/api/reviews`)
  - `GET /api/audits/<owner>/<repo>/<pr_number>/status`
  - `DELETE /api/audits/<owner>/<repo>/<pr_number>` — cancel
  - `GET /api/audit-history` — list with filters (repo/author/date/text)
  - `GET /api/audit-history/<id>` — detail; returns both `content_json` and generated `content`
    (markdown via `audit_json_to_markdown`)
  - `GET /api/audit-history/check/<owner>/<repo>/<pr_number>` — has-been-audited + latest
  - `POST /api/audits/<audit_id>/post-inline-comments` — post mappable findings inline
- **Frontend API + types.** `frontend/src/api/audits.ts` and audit types in `api/types.ts`
  (`AuditJSON`, `AuditFinding`, `AuditSection`, `AuditDetail`, `AuditHistoryItem`).
- **History.** A separate **Audits** history list in the UI (its own tab/section in the history
  panel), distinct from the review history list.
- **Viewer.** A dedicated `AuditViewer` modal renders the generated markdown (same render path as
  `ReviewViewer`) with an audit-appropriate header (PB/EDs, scope, tallies).
- **Badge/chip.** PR cards and the audit history rows show an **audit chip** instead of a score
  badge: green `Audit · 0 blocking` when no blocking finding fired, red
  `Audit · N <severity>` (e.g. `1 scope-violation`) when one did. Colors derive from existing
  Matrix UI success/error custom properties.

### 5. Verdict — two formats

`VerdictModal` branches on the review/audit format of the item it was opened for:

- **Standard mode** — unchanged (toggle Critical/Major/Minor sections, inline eligibility,
  manual override).
- **Audit mode** — toggleable blocks are: **Executive Summary**, **each Audit** (A/B …) findings,
  and **Action Map**. Per-finding **inline-comment selection** is offered for findings whose
  locations resolve to `file`+`line`. The existing **manual-override textarea** still applies.
  The composed body and inline comments post through the existing verdict + inline-comment GitHub
  paths (audit findings carry `file`/`line`/`body`, the same shape inline posting already
  consumes).

The Verdict button appears on queue/PR items that have a completed audit (analogous to the
existing "has review" gating, but checking audit existence).

### 6. Isolation

All implementation occurs in the `worktree-pb-ed-audit-review-type` worktree. The DESIGN.md
documentation is updated to describe the audit subsystem (new DB class, routes, schema, UI).

---

## Component boundaries

| Unit | Responsibility | Depends on |
|------|----------------|------------|
| `audit_schema_spec.json` | Formal contract the skill targets | — |
| `audit_schema.py` | Validate, JSON→markdown, tally computation | spec, config (section/severity labels) |
| `audits.py` (DB) | Persist/query audits | `base.py` |
| shared subprocess helper | Spawn/track/poll/persist a `claude -p` job | extensions, github_service |
| `audit_service.py` | Audit-specific prompt, output parse, persist to `AuditsDB` | subprocess helper, audit_schema |
| `audit_routes.py` | Thin HTTP surface | audit_service, AuditsDB |
| `audit_inline_comments` | Map findings → GitHub inline comments | inline_comments_service patterns |
| `api/audits.ts` + types | Type-safe FE access | — |
| `AuditViewer` | Render an audit | api/audits |
| audit chip | Show blocking outcome | audit content_json |
| `VerdictModal` (audit mode) | Compose + post audit verdict | api/audits, types |

---

## Testing

- **Schema unit tests** (`backend/tests/test_audit_schema.py`): `validate_audit_json` accepts a
  good audit (built from the PR-1630 sample, hand-translated to JSON) and rejects each missing
  required field; `audit_json_to_markdown` round-trips the key blocks (header, both audits,
  findings tables, action map); `compute_audit_tallies` derives correct `finding_count` /
  `blocking_count`, including the `blocking`-from-severity fallback.
- **AuditsDB tests** (`backend/tests/test_audits_db.py`): add/get/latest/search/check against a
  temp SQLite DB; migration creates the table on a fresh DB.
- **Inline mapping test**: findings with resolvable `file`+`line` produce inline comment entries;
  findings without are skipped.
- Run the full `backend/tests` suite; keep it green (baseline: 27 passing).
- Frontend: `npm run build` must pass (TypeScript types compile).

---

## Decisions (resolved with the user)

1. **Storage:** new dedicated `audits` table + `AuditsDB` + `/api/audits` routes + separate
   history list (not a discriminator on the reviews table).
2. **PR posting:** whole-report comment **and** per-finding inline comments (locations carry
   resolved `file`+`line`).
3. **Badge:** finding-count / blocking chip (green `0 blocking` / red `N <severity>`), not a
   0–10 score and not a plain label.
4. **Verdict composition:** toggleable audit blocks (Exec Summary · Audit A · Audit B · Action
   Map) plus manual override.

## Open risks / flags

- The `/pb-ed-audit` skill emitting resolved `file`+`line` in `locations[]` is required for inline
  comments; if a run can't resolve a path, that finding degrades to report-only (no inline).
- The audit only makes sense for repos that carry PB/ED docs; the picker offers it everywhere but
  it is the user's call when to run it (same as the PB/ED reviewer options today).
- Severity vocabularies differ between Audit A and Audit B; the schema treats `severity` as a free
  uppercase token rather than a closed enum to avoid over-fitting.
