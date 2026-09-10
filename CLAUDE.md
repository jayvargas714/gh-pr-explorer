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

The full design lives at `docs/DESIGN.md` (~5,200 lines). **Do not read it in its entirety** — it is large enough to exhaust context. Instead, use the index below to locate the relevant section and read only that slice (e.g. `Read docs/DESIGN.md offset=1091 limit=80`, or `grep -n "### Merge Queue" docs/DESIGN.md` for the exact line if numbers have drifted).

Keep `docs/DESIGN.md` updated whenever any design aspect changes, and update the line numbers in this index if you add or remove sections.

### DESIGN.md Index

| Section | Line | Covers |
|---------|------|--------|
| **Overview** | 15 | Purpose, value props, target users |
| **Architecture** | 40 | System diagram, data flow |
| — Backend Components (Flask) | 116 | Package layout, services, filters, visualizers, cache, 14 route blueprints |
| — Database Module | 180 | DB classes, full SQL schema, per-class method tables |
| — Data Migration Module | 616 | One-time legacy JSON/markdown import |
| — Frontend (React + TS) | 636 | Dir layout, 6-tab + analytics sub-tab architecture |
| — Styling | 671 | Matrix UI design system, CSS conventions |
| **Features** | 689 | (one ### per feature below) |
| — PR List Pagination | 708 | Client-side paging |
| — PR Filtering System | 734 | 5 filter tabs (Basic/Review/People/Dates/Advanced) |
| — Analytics (Stats / Activity / Contributors) | 795–894 | Windowed daily rollup shared by all 3 sub-tabs, one endpoint, bot exclusion, `#### Metric Semantics` bucketing rules |
| — CI/Workflows Tab | 895 | Workflow runs table, filters, stats |
| — PR Card Status Badges | 959 | Review/CI/divergence/approved-by-me badges |
| — Settings Persistence | 1028 | DB-backed filter/selection restore |
| — Repo Stats Tab | 1046 | Repo-level stats, languages, LOC |
| — Review History | 1075 | Past-review browser, score badges |
| — PR Timelines | 1120 | Single-PR event timeline modal |
| — Merge Queue | 1194 | Prioritized cross-repo PR queue |
| — Swimlane Board (Kanban) | 1273 | Lane CRUD, DnD, badge + auto-mode filtering, auto/manual header counts; operator-owned watch list (automation never places cards; former Auto lane retired) |
| — Code Review System (Claude CLI) | 1429 | Reviewer agents, subprocess flow, foreground-dispatch requirement, per-event PR status comments (supersede-delete, marker, single kill-switch flag), stale-review cancellation & restart, startup reconciliation of orphaned reviews (budget-paced requeue), review workspace + runaway-process guardrails (prescribed snapshot recipe, process-group kills, wall-clock timeout, systemd cgroup caps), split Review/Audit triggers |
| — Inline Comments Posting | 1624 | Post critical issues to GitHub |
| — Review Verdict | 1672 | Approve/Request-Changes/Comment composer, verdict source toggle |
| — Auto Verdicts | 1744 | Per-PR `auto_verdict_arming` table (independent of merge-queue membership), armed cards, verdict vs comment mode, criteria thresholds, per-PR criteria overrides, auto approve/changes-requested, **Disputed/Deferred set-aside sections excluded from tallies, mediation outcome (`mediationDisputedThreshold` → COMMENT + disarm + status comment), follow-up scope rule, no-verdict rule for agents**, watcher threads, auto follow-up reviews (one batched head-SHA fetch per repo), rate-limit deferral + retry sweep, optimistic arming |
| — Review Requests | 1948 | GitHub review request → pipeline: zero-cost detection (sync-worker `reviewRequests` diff + per-cycle sweep of open rows for standing untracked requests, incl. GitHub's remove+add re-request), routing by dispatch-row status (enroll / requeue incl. opt-out / follow-up demand in `review_requests`), fulfilment under the same dispatch gates regardless of arming, conversation-since-review + disposition rules in every follow-up prompt (`withdrawn`/`disputed`), Dispositions section in verdict bodies, 🙋 badges, status comments |
| — Review Event Log | 2045 | Per-attempt event log, run_id grouping, closed event/reason vocabularies, verdict posted/not-posted events, day-paginated Review Logs tab (Running-now strip, day navigator, calendar jump, load-older), run hover panel w/ issue counts |
| — PR List Sync | 2300 | DB-backed PR list: synced_repos/synced_prs tables, background sync worker (backfill + incremental), inception history walk (`history_cursor`, adaptive 1000-cap split, `history_backfill_budget`), commit sync (`synced_commits`, REST paging, `commit_pages_per_cycle`), `retain_days` prune (0 = never), three-way route dispatch (DB/hybrid/live), per-card refresh, `pr_sync` config |
| — Automation (Full Auto Pipeline) | 2458 | Automation tab (config only: active-config summary strip), reviewer registry, routing rules + ignore patterns, seed + backfill scripts, dispatch condition gates (base branch must be `requireBaseBranch` (default main), CI pass, behind-base limit, non-draft; open PRs wait indefinitely unless `dispatchTimeoutHours` is set, drafts off the board), unified concurrency budget in begin_review, pipeline size cap, manual enroll/opt-out control + badge on all card surfaces, automation_dispatches, dispatch worker (never touches merge_queue/swimlanes), `automation_config` |
| — Pipeline Management (Pipeline overlay) | 2678 | Header 🤖 overlay: DB-only in-memory snapshot (`pipeline_snapshot.py`, version-based cheap polling, dirty-flag rebuilds), derived `stage` (incl. sticky `mediation`), sortable/filterable table w/ Rounds + rev-log hover, expandable detail panel, bulk actions, Watch on board, per-row refresh, freshness indicator |
| **API Endpoints** | 2750 | All REST routes, grouped by domain (auth → cache); Analytics Daily at 3134, Auto Verdicts at 3316, Automation/Reviewers (incl. `/api/automation/pipeline`) at 3424, Review Logs at 4192 |
| **Configuration** | 4310 | `config.json` options, incl. review retry + log retention, `log_retention_days`, `pr_sync` block (incl. `retain_days`, history walk + commit sync keys), `analytics` block (`bot_logins`); DB-backed settings keys note |
| **Technical Details** | 4400 | gh CLI integration, caching, parallel fetch, logging (4609: UTC per-run files + error.log), attempt outcome + retry policy (4674), follow-up parent selection (4727), Review JSON Schema (4760: incl. `disputed`/`deferred` sections, per-issue `severity`/`disposition`) |
| **Future Considerations** | 4930 | Improvements, known limitations |
| **Appendix** | 4991 | Dependencies, file structure, run instructions |

