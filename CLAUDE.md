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
| — Data Migration Module | 577 | One-time legacy JSON/markdown import |
| — Frontend (React + TS) | 597 | Dir layout, 6-tab + analytics sub-tab architecture |
| — Styling | 634 | Matrix UI design system, CSS conventions |
| **Features** | 653 | (one ### per feature below) |
| — PR List Pagination | 672 | Client-side paging |
| — PR Filtering System | 698 | 5 filter tabs (Basic/Review/People/Dates/Advanced) |
| — Analytics (Stats / Lifecycle / Activity / Contributors / Reviews) | 759–883 | Developer + repo analytics sub-tabs |
| — CI/Workflows Tab | 913 | Workflow runs table, filters, stats |
| — PR Card Status Badges | 977 | Review/CI/divergence/approved-by-me badges |
| — Settings Persistence | 1046 | DB-backed filter/selection restore |
| — Repo Stats Tab | 1064 | Repo-level stats, languages, LOC |
| — Review History | 1093 | Past-review browser, score badges |
| — PR Timelines | 1138 | Single-PR event timeline modal |
| — Merge Queue | 1212 | Prioritized cross-repo PR queue |
| — Swimlane Board (Kanban) | 1291 | Lane CRUD, DnD, badge + auto-mode filtering, auto/manual header counts; operator-owned watch list (automation never places cards; former Auto lane retired) |
| — Code Review System (Claude CLI) | 1447 | Reviewer agents, subprocess flow, foreground-dispatch requirement, per-event PR status comments (supersede-delete, marker, single kill-switch flag), stale-review cancellation & restart, startup reconciliation of orphaned reviews (budget-paced requeue), review workspace + runaway-process guardrails (prescribed snapshot recipe, process-group kills, wall-clock timeout, systemd cgroup caps), split Review/Audit triggers |
| — Inline Comments Posting | 1628 | Post critical issues to GitHub |
| — Review Verdict | 1676 | Approve/Request-Changes/Comment composer, verdict source toggle |
| — Auto Verdicts | 1749 | Per-PR `auto_verdict_arming` table (independent of merge-queue membership), armed cards, verdict vs comment mode, criteria thresholds, per-PR criteria overrides, auto approve/changes-requested, watcher threads, auto follow-up reviews (one batched head-SHA fetch per repo), rate-limit deferral + retry sweep, optimistic arming |
| — Review Event Log | 1920 | Per-attempt event log, run_id grouping, closed event/reason vocabularies, verdict posted/not-posted events, day-paginated Review Logs tab (Running-now strip, day navigator, calendar jump, load-older), run hover panel w/ issue counts |
| — PR List Sync | 2175 | DB-backed PR list: synced_repos/synced_prs tables, background sync worker (backfill + incremental), three-way route dispatch (DB/hybrid/live), per-card refresh, `pr_sync` config |
| — Automation (Full Auto Pipeline) | 2258 | Automation tab (config only: active-config summary strip), reviewer registry, routing rules + ignore patterns, seed + backfill scripts, dispatch condition gates (base branch must be `requireBaseBranch` (default main), CI pass, behind-base limit, non-draft; open PRs wait indefinitely unless `dispatchTimeoutHours` is set, drafts off the board), unified concurrency budget in begin_review, pipeline size cap, manual enroll/opt-out control + badge on all card surfaces, automation_dispatches, dispatch worker (never touches merge_queue/swimlanes), `automation_config` |
| — Pipeline Management (Pipeline overlay) | 2472 | Header 🤖 overlay: DB-only in-memory snapshot (`pipeline_snapshot.py`, version-based cheap polling, dirty-flag rebuilds), derived `stage`, sortable/filterable table w/ Rounds + rev-log hover, expandable detail panel, bulk actions, Watch on board, per-row refresh, freshness indicator |
| **API Endpoints** | 2543 | All REST routes, grouped by domain (auth → cache); Auto Verdicts at 3207, Automation/Reviewers (incl. `/api/automation/pipeline`) at 3313, Review Logs at 4082 |
| **Configuration** | 4200 | `config.json` options, incl. review retry + log retention, `log_retention_days`, `pr_sync` block; DB-backed settings keys note |
| **Technical Details** | 4272 | gh CLI integration, caching, parallel fetch, logging (4478: UTC per-run files + error.log), attempt outcome + retry policy (4536), follow-up parent selection (4589), Review JSON Schema (4622) |
| **Future Considerations** | 4793 | Improvements, known limitations |
| **Appendix** | 4855 | Dependencies, file structure, run instructions |

