# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GitHub PR Explorer is a web application for browsing, filtering, and exploring GitHub Pull Requests. It uses the GitHub CLI (`gh`) for authentication and data fetching, with a Flask backend and React + TypeScript frontend (built with Vite).

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
| — Data Migration Module | 465 | One-time legacy JSON/markdown import |
| — Frontend (React + TS) | 485 | Dir layout, 4-tab + analytics sub-tab architecture |
| — Styling | 520 | Matrix UI design system, CSS conventions |
| **Features** | 539 | (one ### per feature below) |
| — PR List Pagination | 558 | Client-side paging |
| — PR Filtering System | 584 | 5 filter tabs (Basic/Review/People/Dates/Advanced) |
| — Analytics (Stats / Lifecycle / Activity / Contributors / Reviews) | 649–769 | Developer + repo analytics sub-tabs |
| — CI/Workflows Tab | 799 | Workflow runs table, filters, stats |
| — PR Card Status Badges | 863 | Review/CI/divergence/approved-by-me badges |
| — Settings Persistence | 925 | DB-backed filter/selection restore |
| — Repo Stats Tab | 943 | Repo-level stats, languages, LOC |
| — Review History | 972 | Past-review browser, score badges |
| — PR Timelines | 1017 | Single-PR event timeline modal |
| — Merge Queue | 1091 | Prioritized cross-repo PR queue |
| — Swimlane Board (Kanban) | 1170 | Lane CRUD, DnD, badge filtering |
| — Code Review System (Claude CLI) | 1269 | Reviewer agents, subprocess flow |
| — Inline Comments Posting | 1365 | Post critical issues to GitHub |
| — Review Verdict | 1413 | Approve/Request-Changes/Comment composer |
| **API Endpoints** | 1479 | All REST routes, grouped by domain (auth → cache) |
| **Configuration** | 2639 | `config.json` options |
| **Technical Details** | 2679 | gh CLI integration, caching, parallel fetch, logging, Review JSON Schema (2938) |
| **Future Considerations** | 3024 | Improvements, known limitations |
| **Appendix** | 3086 | Dependencies, file structure, run instructions |

