# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GitHub PR Explorer is a lightweight web application for browsing, filtering, and exploring GitHub Pull Requests. It uses the GitHub CLI (`gh`) for authentication and data fetching, with a Flask backend and Vue.js 3 frontend.

## Commands

### Run the Application
```bash
python app.py
```
The server runs on `http://127.0.0.1:5050` by default (configurable in `config.json`).

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Prerequisites
- GitHub CLI (`gh`) must be installed and authenticated via `gh auth login`
- Python 3.x with Flask

## Architecture

### Backend (Flask)
- **`app.py`**: Single-file Flask application containing all routes and business logic
  - Routes serve the frontend and provide REST API endpoints
  - Uses `subprocess` to invoke `gh` CLI commands for GitHub data
  - In-memory caching with configurable TTL (`cache_ttl_seconds` in config.json)
  - Builds GitHub search queries from filter parameters passed by frontend

### Frontend (Vue.js 3)
- **`templates/index.html`**: Jinja2 template with Vue.js single-file component (uses Composition API)
- **`static/js/app.js`**: Vue.js application logic with reactive state management
- **`static/css/styles.css`**: CSS with custom properties for theming (light/dark mode support)

### Data Flow
1. Frontend makes API calls to Flask backend
2. Backend translates requests into `gh` CLI commands
3. GitHub CLI handles authentication and fetches data from GitHub API
4. Backend parses JSON output and returns to frontend

## Key API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/api/orgs` | List user's organizations and personal account |
| `/api/repos` | List repositories for an owner |
| `/api/repos/<owner>/<repo>/prs` | Get PRs with extensive filtering |
| `/api/repos/<owner>/<repo>/contributors` | Get repo contributors |
| `/api/repos/<owner>/<repo>/labels` | Get repo labels |
| `/api/repos/<owner>/<repo>/branches` | Get repo branches |
| `/api/repos/<owner>/<repo>/milestones` | Get repo milestones |
| `/api/repos/<owner>/<repo>/teams` | Get teams with repo access |
| `/api/clear-cache` | Clear in-memory cache (POST) |

## Configuration

`config.json` controls:
- `port`: Server port (default: 5050)
- `host`: Server host (default: 127.0.0.1)
- `debug`: Flask debug mode
- `default_per_page`: Default PR results limit (default: 30)
- `cache_ttl_seconds`: Cache time-to-live (default: 300)

## PR Filtering

The `/api/repos/<owner>/<repo>/prs` endpoint supports extensive GitHub search syntax:
- Basic: state, author, assignee, labels, branches, draft status
- Review: status, reviewed-by, review-requested
- People: involves, mentions, commenter
- Dates: created/updated/merged/closed before/after
- Advanced: reactions, interactions, sorting, exclusions (via `--search` flag)

Results are capped at 100 to avoid GraphQL node limits.
