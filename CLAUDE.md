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
| — Backend Components (Flask) | 117 | Package layout, services, filters, visualizers, cache, 12 route blueprints |
| — Database Module | 186 | DB classes, full SQL schema, per-class method tables |
| — Data Migration Module | 517 | One-time legacy JSON/markdown import |
| — Frontend (React + TS) | 537 | Dir layout, 4-tab + analytics sub-tab architecture |
| — Styling | 572 | Matrix UI design system, CSS conventions |
| **Features** | 591 | (one ### per feature below) |
| — PR List Pagination | 610 | Client-side paging |
| — PR Filtering System | 636 | 5 filter tabs (Basic/Review/People/Dates/Advanced) |
| — Analytics (Stats / Lifecycle / Activity / Contributors / Reviews) | 697–821 | Developer + repo analytics sub-tabs |
| — CI/Workflows Tab | 851 | Workflow runs table, filters, stats |
| — PR Card Status Badges | 915 | Review/CI/divergence/approved-by-me badges |
| — Settings Persistence | 983 | DB-backed filter/selection restore |
| — Repo Stats Tab | 1001 | Repo-level stats, languages, LOC |
| — Review History | 1030 | Past-review browser, score badges |
| — PR Timelines | 1075 | Single-PR event timeline modal |
| — Merge Queue | 1149 | Prioritized cross-repo PR queue |
| — Swimlane Board (Kanban) | 1228 | Lane CRUD, DnD, badge filtering |
| — Code Review System (Claude CLI) | 1374 | Reviewer agents, subprocess flow, review-underway PR comment, split Review/Audit triggers |
| — Inline Comments Posting | 1491 | Post critical issues to GitHub |
| — Review Verdict | 1539 | Approve/Request-Changes/Comment composer, verdict source toggle |
| — Auto Verdicts | 1612 | Armed cards, criteria thresholds, auto approve/changes-requested, watcher threads, auto follow-up reviews |
| **API Endpoints** | 1720 | All REST routes, grouped by domain (auth → cache); Auto Verdicts at 2359 |
| **Configuration** | 3138 | `config.json` options |
| **Technical Details** | 3183 | gh CLI integration, caching, parallel fetch, logging, Review JSON Schema (3442) |
| **Future Considerations** | 3613 | Improvements, known limitations |
| **Appendix** | 3675 | Dependencies, file structure, run instructions |

