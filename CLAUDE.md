# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GitHub PR Explorer is a web application for browsing, filtering, and exploring GitHub Pull Requests. It uses the GitHub CLI (`gh`) for authentication and data fetching, with a Flask backend and React + TypeScript frontend (built with Vite).

## Development Workflow

This is an internal productivity tool — it will not run in production. Favor velocity over heavyweight gates.

1. **Brainstorming and design stay interactive.** Continue the collaborative, question-and-confirmation workflow when exploring an idea: ask clarifying questions one topic at a time, propose approaches with trade-offs, and confirm the design with the user before writing the spec.
2. **No spec approval gate.** Once the design document (spec) is written, do **not** stop to ask the user to review or approve it. Proceed straight to creating the implementation plan and begin implementation immediately.

## Commands

### Development Mode
```bash
# Terminal 1: Start Flask API server
python app.py                    # API on http://127.0.0.1:5714

# Terminal 2: Start Vite dev server
cd frontend && npm run dev       # UI on http://localhost:3050 (proxies API to :5714)
```

### Production Mode
```bash
cd frontend && npm run build     # Build React app to frontend/dist/
python app.py                    # Serves both API and React UI on :5714
```

### Install Dependencies
```bash
pip install -r requirements.txt
cd frontend && npm install
```

### Prerequisites
- GitHub CLI (`gh`) must be installed and authenticated via `gh auth login`
- Python 3.x with Flask
- Node.js 18+ with npm

## Design Document

The full design lives at `docs/DESIGN.md` (~3,200 lines). **Do not read it in its entirety** — it is large enough to exhaust context. Instead, use the index below to locate the relevant section and read only that slice (e.g. `Read docs/DESIGN.md offset=1091 limit=80`, or `grep -n "### Merge Queue" docs/DESIGN.md` for the exact line if numbers have drifted).

Keep `docs/DESIGN.md` updated whenever any design aspect changes, and update the line numbers in this index if you add or remove sections.

### DESIGN.md Index

| Section | Line | Covers |
|---------|------|--------|
| **Overview** | 15 | Purpose, value props, target users |
| **Architecture** | 41 | System diagram, data flow |
| — Backend Components (Flask) | 117 | Package layout, services, filters, visualizers, cache, 14 route blueprints |
| — Database Module | 186 | DB classes, full SQL schema, per-class method tables |
| — Data Migration Module | 576 | One-time legacy JSON/markdown import |
| — Frontend (React + TS) | 596 | Dir layout, 6-tab + analytics sub-tab architecture |
| — Styling | 633 | Matrix UI design system, CSS conventions |
| **Features** | 652 | (one ### per feature below) |
| — PR List Pagination | 671 | Client-side paging |
| — PR Filtering System | 697 | 5 filter tabs (Basic/Review/People/Dates/Advanced) |
| — Analytics (Stats / Lifecycle / Activity / Contributors / Reviews) | 758–882 | Developer + repo analytics sub-tabs |
| — CI/Workflows Tab | 912 | Workflow runs table, filters, stats |
| — PR Card Status Badges | 976 | Review/CI/divergence/approved-by-me badges |
| — Settings Persistence | 1045 | DB-backed filter/selection restore |
| — Repo Stats Tab | 1063 | Repo-level stats, languages, LOC |
| — Review History | 1092 | Past-review browser, score badges |
| — PR Timelines | 1137 | Single-PR event timeline modal |
| — Merge Queue | 1211 | Prioritized cross-repo PR queue |
| — Swimlane Board (Kanban) | 1290 | Lane CRUD, DnD, badge + auto-mode filtering, auto/manual header counts, protected Auto lane |
| — Code Review System (Claude CLI) | 1447 | Reviewer agents, subprocess flow, foreground-dispatch requirement, per-event PR status comments (supersede-delete, marker, single kill-switch flag), stale-review cancellation & restart, startup reconciliation of orphaned reviews (budget-paced requeue), review workspace + runaway-process guardrails (prescribed snapshot recipe, process-group kills, wall-clock timeout, systemd cgroup caps), split Review/Audit triggers |
| — Inline Comments Posting | 1628 | Post critical issues to GitHub |
| — Review Verdict | 1676 | Approve/Request-Changes/Comment composer, verdict source toggle |
| — Auto Verdicts | 1749 | Armed cards, verdict vs comment mode, criteria thresholds, per-PR criteria overrides, auto approve/changes-requested, watcher threads, auto follow-up reviews (one batched head-SHA fetch per repo), rate-limit deferral + retry sweep, optimistic arming |
| — Review Event Log | 1912 | Per-attempt event log, run_id grouping, closed event/reason vocabularies, verdict posted/not-posted events, day-paginated Review Logs tab (Running-now strip, day navigator, calendar jump, load-older), run hover panel w/ issue counts |
| — PR List Sync | 2167 | DB-backed PR list: synced_repos/synced_prs tables, background sync worker (backfill + incremental), three-way route dispatch (DB/hybrid/live), per-card refresh, `pr_sync` config |
| — Automation (Full Auto Pipeline) | 2250 | Automation tab (active-config summary strip, pipeline table w/ Remove/Re-enroll), reviewer registry, routing rules + ignore patterns, seed + backfill scripts, dispatch condition gates (base branch must be `requireBaseBranch` (default main), CI pass, behind-base limit, non-draft; open PRs wait indefinitely unless `dispatchTimeoutHours` is set, drafts off the board), unified concurrency budget in begin_review, pipeline size cap, manual enroll/opt-out control + badge on all card surfaces, automation_dispatches, dispatch worker, protected Auto lane, `automation_config` |
| **API Endpoints** | 2475 | All REST routes, grouped by domain (auth → cache); Auto Verdicts at 3139, Automation/Reviewers at 3251, Review Logs at 4007 |
| **Configuration** | 4125 | `config.json` options, incl. review retry + log retention, `log_retention_days`, `pr_sync` block; DB-backed settings keys note |
| **Technical Details** | 4197 | gh CLI integration, caching, parallel fetch, logging (4403: UTC per-run files + error.log), attempt outcome + retry policy (4461), follow-up parent selection (4514), Review JSON Schema (4547) |
| **Future Considerations** | 4718 | Improvements, known limitations |
| **Appendix** | 4780 | Dependencies, file structure, run instructions |

