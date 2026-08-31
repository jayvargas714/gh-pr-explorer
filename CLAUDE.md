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
| — Data Migration Module | 575 | One-time legacy JSON/markdown import |
| — Frontend (React + TS) | 595 | Dir layout, 6-tab + analytics sub-tab architecture |
| — Styling | 632 | Matrix UI design system, CSS conventions |
| **Features** | 651 | (one ### per feature below) |
| — PR List Pagination | 670 | Client-side paging |
| — PR Filtering System | 696 | 5 filter tabs (Basic/Review/People/Dates/Advanced) |
| — Analytics (Stats / Lifecycle / Activity / Contributors / Reviews) | 757–881 | Developer + repo analytics sub-tabs |
| — CI/Workflows Tab | 911 | Workflow runs table, filters, stats |
| — PR Card Status Badges | 975 | Review/CI/divergence/approved-by-me badges |
| — Settings Persistence | 1043 | DB-backed filter/selection restore |
| — Repo Stats Tab | 1061 | Repo-level stats, languages, LOC |
| — Review History | 1090 | Past-review browser, score badges |
| — PR Timelines | 1135 | Single-PR event timeline modal |
| — Merge Queue | 1209 | Prioritized cross-repo PR queue |
| — Swimlane Board (Kanban) | 1288 | Lane CRUD, DnD, badge + auto-mode filtering, auto/manual header counts, protected Auto lane |
| — Code Review System (Claude CLI) | 1445 | Reviewer agents, subprocess flow, foreground-dispatch requirement, review-underway PR comment, stale-review cancellation & restart, startup reconciliation of orphaned reviews, split Review/Audit triggers |
| — Inline Comments Posting | 1590 | Post critical issues to GitHub |
| — Review Verdict | 1638 | Approve/Request-Changes/Comment composer, verdict source toggle |
| — Auto Verdicts | 1711 | Armed cards, verdict vs comment mode, criteria thresholds, per-PR criteria overrides, auto approve/changes-requested, watcher threads, auto follow-up reviews, optimistic arming |
| — Review Event Log | 1862 | Per-attempt event log, run_id grouping, closed event/reason vocabularies, verdict posted/not-posted events, day-paginated Review Logs tab (day navigator, calendar jump, load-older), run hover panel w/ issue counts |
| — PR List Sync | 2110 | DB-backed PR list: synced_repos/synced_prs tables, background sync worker (backfill + incremental), three-way route dispatch (DB/hybrid/live), per-card refresh, `pr_sync` config |
| — Automation (Full Auto Pipeline) | 2193 | Automation tab (active-config summary strip, pipeline table w/ Remove/Re-enroll), reviewer registry, routing rules + ignore patterns, seed + backfill scripts, dispatch condition gates (CI pass, behind-base limit, non-draft; open PRs wait indefinitely, drafts off the board), pipeline size cap, manual enroll/opt-out control + badge on all card surfaces, automation_dispatches, dispatch worker, protected Auto lane, `automation_config` |
| **API Endpoints** | 2389 | All REST routes, grouped by domain (auth → cache); Auto Verdicts at 3053, Automation/Reviewers at 3165, Review Logs at 3900 |
| **Configuration** | 4018 | `config.json` options, incl. review retry + log retention, `pr_sync` block; DB-backed settings keys note |
| **Technical Details** | 4075 | gh CLI integration, caching, parallel fetch, logging, attempt outcome + retry policy (4338), follow-up parent selection (4384), Review JSON Schema (4417) |
| **Future Considerations** | 4588 | Improvements, known limitations |
| **Appendix** | 4650 | Dependencies, file structure, run instructions |

