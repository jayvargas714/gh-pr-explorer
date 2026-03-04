# GitHub PR Explorer

A local web application for browsing, filtering, and analyzing GitHub Pull Requests across your personal account and organizations. Built with a Flask API backend and a React + TypeScript frontend.

---

## Prerequisites

- **Python 3.x** with pip
- **Node.js 18+** with npm
- **GitHub CLI** (`gh`) installed and authenticated
- **Claude CLI** (optional) — required only for the automated code review feature

```bash
# Install GitHub CLI (macOS)
brew install gh

# Authenticate
gh auth login
```

---

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/gh-pr-explorer.git
cd gh-pr-explorer

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Install frontend dependencies
cd frontend && npm install && cd ..

# 4. Start the Flask API server (Terminal 1)
python app.py
# API runs on http://127.0.0.1:5714

# 5. Start the Vite dev server (Terminal 2)
cd frontend && npm run dev
# UI runs on http://localhost:3050 (proxies API requests to :5714)
```

Open **http://localhost:3050** in your browser.

---

## Production Mode

Build the frontend and serve everything from Flask:

```bash
cd frontend && npm run build && cd ..
python app.py
# Access at http://127.0.0.1:5714
```

---

## Configuration

Edit `config.json` in the project root:

```json
{
  "port": 5714,
  "host": "localhost",
  "frontend_port": 3050,
  "debug": false,
  "default_per_page": 30,
  "cache_ttl_seconds": 300,
  "workflow_cache_ttl_minutes": 60,
  "workflow_cache_max_runs": 1000,
  "review_sample_limit": 250,
  "reviews_dir": "/path/to/your/code-reviews"
}
```

| Option | Default | Description |
|--------|---------|-------------|
| `port` | `5714` | Flask API server port |
| `host` | `localhost` | Server bind address |
| `frontend_port` | `3050` | Vite dev server port |
| `debug` | `false` | Flask debug mode |
| `default_per_page` | `30` | Default PR results per page |
| `cache_ttl_seconds` | `300` | In-memory cache TTL (seconds) |
| `workflow_cache_ttl_minutes` | `60` | CI/Workflow cache TTL (minutes) |
| `workflow_cache_max_runs` | `1000` | Max workflow runs cached per repo |
| `review_sample_limit` | `250` | Max PRs sampled for lifecycle/review analytics |
| `reviews_dir` | — | Directory where code review output files are saved |

---

## Database

The SQLite database (`pr_explorer.db`) is created automatically on first run. It stores review history, merge queue data, developer stats cache, and user settings.

To pre-seed the CI/Workflow cache for faster first loads:

```bash
# Seed specific repos
python seed_workflow_cache.py owner/repo1 owner/repo2

# Re-seed all previously cached repos
python seed_workflow_cache.py --refresh
```

---

## Code Review Agent Setup

The app can launch automated code reviews via Claude CLI and post the results as inline comments on GitHub PRs. For the inline commenting feature to work, the review output **must** follow a specific format that the parser can extract issues from.

If you use a custom review agent or prompt, ensure its output matches the structure below.

### Required Section Headings

The parser looks for these exact bold headings, separated by `---` horizontal rules:

```
**Critical Issues**

(issues here)

---
**Major Concerns**

(issues here)

---
**Minor Issues**

(issues here)
```

If a section has no issues, include the heading with "None" beneath it.

### Issue Format

Each issue must use a **numbered bold title** followed by exactly three dash-prefixed fields: `Location`, `Problem`, and `Fix`. All three fields are required — issues missing a `Location` field are skipped.

```
**1. Short Descriptive Title**
- Location: `path/to/file.ext:42-58`
- Problem: Clear explanation of what is wrong.
- Fix: Concrete recommendation for how to resolve it.
```

### Location Field Rules

| Format | Example | Result |
|--------|---------|--------|
| Single line | `` `src/auth.py:42` `` | Comment on line 42 |
| Line range | `` `src/auth.py:42-58` `` | Comment spanning lines 42–58 |
| File only | `` `src/auth.py` `` | File-level comment (no line annotation) |

- Wrap file paths in backticks
- Paths must be relative to the repo root (no leading `/` or `./`)
- Use `:` between path and line number, `-` for ranges
- Do not include extra text or multiple paths in the Location field

### Complete Example

```markdown
**Critical Issues**

**1. SQL Injection in User Query**
- Location: `backend/services/user_service.py:87-92`
- Problem: User input interpolated directly into SQL without parameterization.
- Fix: Use parameterized queries with `?` placeholders.

---
**Major Concerns**

**1. Unbounded Query Without Pagination**
- Location: `backend/services/search_service.py:120-135`
- Problem: Search returns all results with no limit, risking memory issues.
- Fix: Add LIMIT clause (e.g., 100) and cursor-based pagination.

---
**Minor Issues**

**1. Unused Import**
- Location: `backend/routes/api.py:3`
- Problem: The `datetime` import is unused.
- Fix: Remove it.
```

Issues that don't match this structure are silently skipped when posting inline comments.

---

## Features

- **PR Browsing & Filtering** — 5-tab filter panel (Basic, Review, People, Dates, Advanced) with 30+ filter options
- **Client-side Pagination** — page through PRs and workflow runs without extra API calls
- **Analytics** — 5 sub-tabs: Developer Stats, PR Lifecycle, Code Activity, Review Responsiveness, Contributor Time Series
- **CI/Workflows** — workflow run history with filters, pass rate, and failure trends
- **Merge Queue** — cross-repo prioritized queue with notes and reordering
- **Code Reviews** — automated reviews via Claude CLI with score tracking and follow-ups
- **Inline Comments** — post critical/major/minor issues from reviews directly to GitHub PRs
- **Review History** — searchable archive of all past reviews with score badges on PR cards
- **Branch Divergence** — badges showing how far behind base each open PR is
- **Settings Persistence** — filters, account selection, and theme saved to SQLite
- **Dark/Light Mode** — full theme support with CSS custom properties

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Flask (Python 3) |
| Frontend | React 18 + TypeScript |
| Build Tool | Vite |
| State Management | Zustand |
| Charts | Recharts + CSS-only bar charts |
| Database | SQLite |
| Styling | CSS custom properties (Matrix UI) |
| GitHub Integration | GitHub CLI (`gh`) |
| Code Reviews | Claude CLI (optional) |

---

## Project Structure

```
gh-pr-explorer/
├── app.py                      # Flask launcher (~25 lines)
├── config.json                 # Application configuration
├── requirements.txt            # Python dependencies
├── pr_explorer.db              # SQLite database (auto-created)
├── seed_workflow_cache.py      # Pre-seed CI cache
├── migrate_data.py             # One-time legacy data migration
├── docs/
│   └── DESIGN.md               # Detailed design document
│
├── backend/                    # Flask backend package
│   ├── __init__.py             # create_app() factory
│   ├── config.py               # Configuration loading
│   ├── extensions.py           # Shared singletons (logger, cache, locks)
│   ├── database/               # SQLite models (reviews, queue, stats, caches)
│   ├── services/               # Business logic (GitHub, reviews, stats, etc.)
│   ├── filters/                # PR filter builder (request args → gh CLI args)
│   ├── cache/                  # In-memory TTL cache decorator
│   ├── visualizers/            # Data transforms for charts and tables
│   └── routes/                 # 11 Flask Blueprints (36+ endpoints)
│
└── frontend/                   # React + TypeScript frontend
    ├── src/
    │   ├── api/                # Type-safe API modules
    │   ├── components/         # React components by feature
    │   ├── stores/             # Zustand state stores
    │   ├── styles/             # CSS styles
    │   └── types/              # TypeScript type definitions
    ├── vite.config.ts          # Vite configuration
    └── package.json            # Frontend dependencies
```

For full architectural details, API endpoint documentation, and database schema, see [docs/DESIGN.md](docs/DESIGN.md).
