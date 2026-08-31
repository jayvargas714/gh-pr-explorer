# GitHub PR Explorer - Design Document

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Features](#features)
4. [API Endpoints](#api-endpoints)
5. [Configuration](#configuration)
6. [Technical Details](#technical-details)
7. [Future Considerations](#future-considerations)

---

## Overview

### Purpose

GitHub PR Explorer is a lightweight web application designed for browsing, filtering, and exploring GitHub Pull Requests. It provides a unified interface for developers and teams to efficiently review PR activity across multiple repositories and organizations.

### Key Value Propositions

- **Unified PR View**: Browse PRs across personal accounts and organizations from a single interface
- **Advanced Filtering**: Comprehensive filter system supporting GitHub's full search syntax
- **Developer Analytics**: Aggregated statistics showing contribution patterns and review activity
- **CI/Workflow Monitoring**: View workflow runs, pass rates, and failure trends
- **PR Lifecycle Insights**: Track time-to-merge, time-to-first-review, and stale PR detection
- **Code Activity Visualization**: Weekly commit frequency, code churn, and owner vs. community participation
- **Zero Authentication Setup**: Leverages existing GitHub CLI (`gh`) authentication
- **Lightweight Deployment**: React + Vite frontend with Flask API backend

### Target Users

- Individual developers tracking their PR activity
- Team leads monitoring team contributions and review velocity
- Project managers assessing repository health
- Code reviewers managing their review queues

---

## Architecture

### System Diagram

```
+-------------------+     +-------------------+     +-------------------+
|                   |     |                   |     |                   |
|   Browser/Client  |<--->|   Flask Backend   |<--->|   GitHub CLI      |
|   (React SPA)     |     |   (backend/)      |     |   (gh)            |
|                   |     |                   |     |                   |
+-------------------+     +-------------------+     +-------------------+
        |                         |                         |
        |                         |                         |
        v                         v                         v
+-------------------+     +-------------------+     +-------------------+
|                   |     |                   |     |                   |
|   frontend/dist/  |     |   In-Memory       |     |   GitHub API      |
|   (Vite build)    |     |   - Cache (TTL)   |     |   (via gh CLI)    |
|                   |     |   - Active Reviews|     |                   |
|                   |     |                   |     |                   |
+-------------------+     +-------------------+     +-------------------+
        |                         |
        |                         v
        |                 +-------------------+     +-------------------+
        |                 |                   |     |                   |
        |                 |   SQLite Database |     |   Claude CLI      |
        |                 |   (backend/db/)   |<----|   (code reviews)  |
        |                 |   - reviews       |     |                   |
        |                 |   - merge_queue   |     |                   |
        |                 |   - lifecycle_cache|    |                   |
        |                 |   - migrations    |     |                   |
        +---------------->+-------------------+     +-------------------+
                                  |
                                  v
                          +-------------------+
                          |                   |
                          |   pr_explorer.db  |
                          |   (SQLite file)   |
                          |                   |
                          +-------------------+
```

### Data Flow

```
1. User Action (e.g., select repository)
         |
         v
2. React Frontend
   - Updates Zustand stores
   - Constructs API request with filters
         |
         v
3. Flask Backend (backend/ package)
   - Receives HTTP request via Blueprint route
   - Checks in-memory cache
   - If cache miss: service layer builds gh CLI command
         |
         v
4. GitHub CLI (gh)
   - Executes API request with user's credentials
   - Returns JSON response
         |
         v
5. Flask Backend
   - Parses JSON output
   - Post-processes data (e.g., adds review status)
   - Caches result with TTL
   - Returns JSON to frontend
         |
         v
6. React Frontend
   - Updates Zustand stores
   - Renders React components
```

### Backend Components (Flask)

**Package**: `/Users/jvargas714/Documents/dev/gh-pr-explorer/backend/`

The backend is organized as a Python package with clear separation of concerns:

| Module | Description |
|--------|-------------|
| `backend/__init__.py` | `create_app()` factory, `startup_refresh_workflow_caches()` |
| `backend/config.py` | `load_config()`, `get_config()`, `PROJECT_ROOT`, `REVIEWS_DIR`, `DB_PATH` |
| `backend/extensions.py` | Shared singletons: `logger`, `cache`, `active_reviews`, `reviews_lock`, refresh tracking sets/locks |

**Services** (`backend/services/`):

| Module | Key Functions |
|--------|--------------|
| `github_service.py` | `run_gh_command()`, `parse_json_output()`, `fetch_github_stats_api()`, `fetch_pr_state()`, `fetch_pr_head_sha()`, `fetch_pr_state_and_sha()` |
| `pr_service.py` | `get_review_status()`, `get_ci_status()` |
| `stats_service.py` | `fetch_and_compute_stats()`, `add_avg_pr_scores()`, `stats_to_cache_format()`, `cached_stats_to_api_format()` |
| `review_service.py` | `save_review_to_db()`, `check_review_status()`, `start_review_process()` |
| `inline_comments_service.py` | `parse_critical_issues()`, `post_inline_comments()` |
| `lifecycle_service.py` | `fetch_pr_review_times()` |
| `workflow_service.py` | `fetch_workflow_data()` |
| `activity_service.py` | `fetch_code_activity_data()` |
| `contributor_service.py` | `fetch_contributor_timeseries()` |
| `timeline_service.py` | `normalize_timeline_events()`, `fetch_pr_timeline_from_api()`, `get_timeline()` |
| `review_schema.py` | `validate_review_json()`, `json_to_markdown()`, `markdown_to_json()`, `get_section_display_names()`, `SCHEMA_VERSION` |

**Filters** (`backend/filters/`):

| Module | Key Components |
|--------|---------------|
| `pr_filter_builder.py` | `PRFilterParams` dataclass + `PRFilterBuilder` class for translating request args to gh CLI args |

**Visualizers** (`backend/visualizers/`):

| Module | Key Functions |
|--------|--------------|
| `activity_visualizer.py` | `compute_activity_summary()`, `slice_and_summarize()` |
| `workflow_visualizer.py` | `filter_and_compute_stats()` |
| `lifecycle_visualizer.py` | `compute_lifecycle_metrics()` |
| `responsiveness_visualizer.py` | `compute_responsiveness_metrics()` |

**Cache** (`backend/cache/`):

| Module | Key Components |
|--------|---------------|
| `memory_cache.py` | `@cached(ttl_seconds=N)` decorator for in-memory TTL caching |

**Routes** (`backend/routes/`):

12 Flask Blueprints organized by domain. Each route handler is thin (parse request → call service → convert → jsonify).

| Blueprint | Routes |
|-----------|--------|
| `static_bp` | `/`, `/assets/<path>` |
| `auth_bp` | `/api/user`, `/api/orgs` |
| `repo_bp` | `/api/repos`, contributors, labels, branches, milestones, teams |
| `pr_bp` | `/api/repos/.../prs`, `/api/repos/.../prs/divergence` + /prs/:n/timeline |
| `analytics_bp` | `/api/repos/.../stats`, lifecycle-metrics, review-responsiveness, code-activity, contributor-timeseries |
| `workflow_bp` | `/api/repos/.../workflow-runs` |
| `queue_bp` | `/api/merge-queue` CRUD, reorder, notes |
| `swimlane_bp` | `/api/swimlanes` lane CRUD, reorder, default, board, cards/move |
| `review_bp` | `/api/reviews` CRUD, status, inline-comments, check-new-commits |
| `history_bp` | `/api/review-history` list, detail, PR reviews, stats, check |
| `settings_bp` | `/api/settings` CRUD |
| `cache_bp` | `/api/clear-cache` |
| `repo_stats_bp` | `/api/repos/.../repo-stats`, `/api/repos/.../repo-stats/loc` |

### Database Module

**Package**: `/Users/jvargas714/Documents/dev/gh-pr-explorer/backend/database/`

The database module provides SQLite-based persistence for reviews and merge queue data, replacing the previous JSON file storage. A thin re-export layer at `database.py` (root) provides backward compatibility for scripts.

#### Database Classes

| Class | Description |
|-------|-------------|
| `Database` | Base class managing SQLite connection and schema initialization |
| `ReviewsDB` | Handles review storage, retrieval, and search operations |
| `ReviewEventsDB` | Appends and queries review lifecycle events (start/completion/failure/retry) for the Review Logs tab |
| `AuditsDB` | Handles PB↔ED audit storage, retrieval, and search operations (parallel to `ReviewsDB`) |
| `MergeQueueDB` | Manages merge queue persistence and ordering |
| `SwimlanesDB` | Manages swimlane definitions and per-card lane assignments (including pin state and the protected Auto lane) for the Kanban view of the merge queue |
| `ReviewersDB` | Configurable reviewer registry (key → label, Claude agent name, prompt context); seeds and locks the three builtins |
| `AutomationDispatchesDB` | Durable ledger of automation pipeline decisions; `UNIQUE(repo, pr_number)` is the auto-dispatch idempotence guard |
| `DevStatsDB` | Caches developer statistics with 4-hour TTL for improved performance |
| `LifecycleCacheDB` | Caches PR lifecycle and review timing data with 2-hour TTL |
| `WorkflowCacheDB` | Caches workflow runs data with configurable TTL (default 1 hour) for stale-while-revalidate serving |
| `ContributorTimeSeriesCacheDB` | Caches per-contributor weekly time series data with 24-hour TTL for stale-while-revalidate serving |
| `CodeActivityCacheDB` | Caches full 52-week code activity data with 24-hour TTL for stale-while-revalidate serving |
| `RepoStatsCacheDB` | Caches aggregated repository statistics with 4-hour TTL |
| `RepoLOCCacheDB` | Caches lines-of-code analysis results with 24-hour TTL |
| `TimelineCacheDB` | Caches per-PR timeline events with state-aware TTL (no TTL for closed/merged, 5-min for open) |

#### Database Schema

```sql
-- Reviews table: Stores code review history and structured JSON content
CREATE TABLE reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_number INTEGER NOT NULL,
    repo TEXT NOT NULL,
    pr_title TEXT,
    pr_author TEXT,
    pr_url TEXT,
    review_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'completed',
    review_file_path TEXT,
    score INTEGER CHECK(score >= 0 AND score <= 10),
    content_json TEXT NOT NULL,              -- Structured JSON review content (see Review JSON Schema)
    is_followup BOOLEAN DEFAULT FALSE,
    parent_review_id INTEGER,
    head_commit_sha TEXT,
    inline_comments_posted BOOLEAN DEFAULT FALSE,
    auto_started BOOLEAN DEFAULT FALSE,      -- Started by the auto follow-up review watcher
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_review_id) REFERENCES reviews(id)
);

-- Review events table: Append-only operational log of review attempts.
-- One row per lifecycle event; all attempts of one review share a run_id.
CREATE TABLE IF NOT EXISTS review_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,                -- ISO8601 UTC
    run_id TEXT NOT NULL,                    -- Groups every attempt of one review
    event TEXT NOT NULL,                     -- started|completed|failed|retry_scheduled|gave_up|cancelled
    repo TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    reviewer_agent TEXT,                     -- default|pb|ed
    is_followup BOOLEAN DEFAULT FALSE,
    auto_started BOOLEAN DEFAULT FALSE,
    attempt INTEGER,
    max_attempts INTEGER,
    exit_code INTEGER,
    reason TEXT,                             -- NULL unless the event is a failure
    detail TEXT,                             -- stderr tail or human-readable specifics
    review_file TEXT,
    review_id INTEGER,                       -- reviews.id when an attempt was persisted
    score REAL,
    pid INTEGER
);
CREATE INDEX IF NOT EXISTS idx_review_events_repo_pr ON review_events(repo, pr_number);
CREATE INDEX IF NOT EXISTS idx_review_events_run ON review_events(run_id);
CREATE INDEX IF NOT EXISTS idx_review_events_created ON review_events(created_at DESC);

-- Audits table: Stores PB↔ED audit history and structured JSON content (parallel to reviews)
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
    content_json TEXT NOT NULL,              -- Structured JSON audit content (see Audit JSON Schema)
    finding_count INTEGER DEFAULT 0,
    blocking_count INTEGER DEFAULT 0,
    inline_comments_posted BOOLEAN DEFAULT FALSE,
    audit_file_path TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_audits_repo_pr ON audits(repo, pr_number);
CREATE INDEX idx_audits_timestamp ON audits(audit_timestamp DESC);

-- Merge queue table: Persists prioritized PR queue
CREATE TABLE merge_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_number INTEGER NOT NULL,
    repo TEXT NOT NULL,
    pr_title TEXT,
    pr_author TEXT,
    pr_url TEXT,
    additions INTEGER DEFAULT 0,
    deletions INTEGER DEFAULT 0,
    position INTEGER NOT NULL,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    auto_verdict_enabled INTEGER NOT NULL DEFAULT 0,  -- armed for auto verdicts
    auto_verdict_reviewer TEXT,                       -- 'default' | 'pb' | 'ed'
    UNIQUE(pr_number, repo)
);

-- Auto verdicts table: One row per review the auto-verdict evaluator handled.
-- review_id is UNIQUE and claimed before GitHub is contacted, which is what
-- makes a double post impossible when several callers notice one completion.
CREATE TABLE auto_verdicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    review_id INTEGER UNIQUE,
    event TEXT,                     -- APPROVE | REQUEST_CHANGES | COMMENT | NULL
    outcome TEXT NOT NULL DEFAULT 'pending',
                                    -- pending | posted | suppressed | skipped | error
    reason TEXT,                    -- human-readable criteria evaluation
    critical_count INTEGER,
    major_count INTEGER,
    minor_count INTEGER,
    criteria_json TEXT,             -- threshold snapshot at decision time
    head_commit_sha TEXT,
    error_detail TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (review_id) REFERENCES reviews(id)
);

CREATE INDEX idx_auto_verdicts_repo_pr ON auto_verdicts(repo, pr_number);

-- Queue notes table: Stores notes attached to merge queue items
CREATE TABLE queue_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_item_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (queue_item_id) REFERENCES merge_queue(id) ON DELETE CASCADE
);

-- Migrations table: Tracks executed database migrations
CREATE TABLE migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    executed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Developer stats table: Caches contributor statistics
CREATE TABLE developer_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL,
    username TEXT NOT NULL,
    total_prs INTEGER DEFAULT 0,
    open_prs INTEGER DEFAULT 0,
    merged_prs INTEGER DEFAULT 0,
    closed_prs INTEGER DEFAULT 0,
    total_additions INTEGER DEFAULT 0,
    total_deletions INTEGER DEFAULT 0,
    avg_pr_score REAL,
    reviewed_pr_count INTEGER DEFAULT 0,
    commits INTEGER DEFAULT 0,
    avatar_url TEXT,
    reviews_given INTEGER DEFAULT 0,
    approvals INTEGER DEFAULT 0,
    changes_requested INTEGER DEFAULT 0,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(repo, username)
);

-- Stats metadata table: Tracks last update times for stats cache
CREATE TABLE stats_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL UNIQUE,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- PR lifecycle cache table: Caches enriched PR data for lifecycle/review metrics
CREATE TABLE pr_lifecycle_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL UNIQUE,
    data TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Workflow cache table: Caches unfiltered workflow runs for fast filtered queries
CREATE TABLE workflow_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL UNIQUE,
    data TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Contributor time series cache table: Caches per-contributor weekly stats
CREATE TABLE contributor_timeseries_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL UNIQUE,
    data TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Code activity cache table: Caches full 52-week code activity data
CREATE TABLE code_activity_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL UNIQUE,
    data TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Repo stats cache table: Caches aggregated repository statistics
CREATE TABLE IF NOT EXISTS repo_stats_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL UNIQUE,
    data TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Repo LOC cache table: Caches lines-of-code analysis results
CREATE TABLE IF NOT EXISTS repo_loc_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL UNIQUE,
    data TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- PR timeline cache table: Caches normalized issue-timeline events per (repo, pr_number)
CREATE TABLE IF NOT EXISTS pr_timeline_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    pr_state TEXT,
    data TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(repo, pr_number)
);

-- Swimlanes table: User-defined columns for the Kanban view of the merge queue
CREATE TABLE IF NOT EXISTS swimlanes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    color TEXT NOT NULL,            -- one of: success, warning, error, info, primary, accent, violet, slate
    position INTEGER NOT NULL,
    is_default INTEGER DEFAULT 0,   -- exactly one row may have is_default=1
    is_protected INTEGER NOT NULL DEFAULT 0,  -- protected lanes (the Auto lane) refuse delete/rename
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_swimlanes_position ON swimlanes(position);

-- Swimlane assignments table: Which lane each merge queue card sits in
CREATE TABLE IF NOT EXISTS swimlane_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_item_id INTEGER NOT NULL UNIQUE,
    swimlane_id INTEGER,
    position_in_lane INTEGER NOT NULL,
    is_pinned INTEGER NOT NULL DEFAULT 0,   -- pinned cards anchor to the top of their lane
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (queue_item_id) REFERENCES merge_queue(id) ON DELETE CASCADE,
    FOREIGN KEY (swimlane_id) REFERENCES swimlanes(id) ON DELETE SET NULL
);
CREATE INDEX idx_swl_assign_lane ON swimlane_assignments(swimlane_id);

-- Reviewer registry: configurable reviewer agents (builtins seeded + locked)
CREATE TABLE IF NOT EXISTS reviewers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,       -- slug: ^[a-z0-9_-]{1,32}$
    label TEXT NOT NULL,
    agent_name TEXT NOT NULL,       -- Claude agent name used in the review prompt
    prompt_context TEXT,            -- optional prefix injected into the review prompt
    is_builtin INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Automation dispatches: one row per PR the automation pipeline has seen.
-- UNIQUE(repo, pr_number) is the restart-proof auto-dispatch idempotence guard.
CREATE TABLE IF NOT EXISTS automation_dispatches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|dispatched|unidentified|skipped|failed
    outcome_json TEXT,              -- classify_files result (rule, matched_rules, counts)
    reviewer_key TEXT,              -- routed reviewer for matched/default outcomes
    detail TEXT,                    -- error / skip reason
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(repo, pr_number)
);
CREATE INDEX idx_automation_dispatches_status ON automation_dispatches(status);
```

#### ReviewsDB Methods

| Method | Description |
|--------|-------------|
| `add_review()` | Creates a new review record with `content_json` and optional follow-up linking |
| `get_review()` | Retrieves a single review by ID |
| `get_reviews_for_pr()` | Gets all reviews for a specific PR |
| `get_latest_review_for_pr()` | Gets the most recent review for a specific PR |
| `search_reviews()` | Searches reviews with filters (repo, author, date range); searches within `content_json` |
| `get_stats()` | Returns aggregate review statistics |
| `check_pr_reviewed()` | Checks if a PR has existing reviews |
| `update_review()` | Updates review fields including `content_json` (e.g., marking inline comments as posted) |

**Note**: Score is extracted directly from the JSON content at `content_json["score"]["overall"]` rather than using regex parsing.

#### MergeQueueDB Methods

| Method | Description |
|--------|-------------|
| `get_queue()` | Returns all queued items ordered by position |
| `add_to_queue()` | Adds a PR to the queue at the end |
| `remove_from_queue()` | Removes a PR from the queue |
| `reorder_queue()` | Moves an item from one position to another |
| `is_in_queue()` | Checks if a PR is already in the queue |

#### DevStatsDB Methods

| Method | Description |
|--------|-------------|
| `get_stats()` | Returns cached stats for a repository |
| `save_stats()` | Saves developer stats with timestamp |
| `get_last_updated()` | Gets the last update timestamp for a repo |
| `is_stale()` | Checks if cached stats are older than TTL (4 hours) |

#### LifecycleCacheDB Methods

| Method | Description |
|--------|-------------|
| `get_cached()` | Returns cached lifecycle data (JSON blob) for a repository |
| `save_cache()` | Saves enriched PR lifecycle data with upsert (INSERT ON CONFLICT UPDATE) |
| `is_stale()` | Checks if cached data is older than TTL (default 2 hours) |

#### WorkflowCacheDB Methods

| Method | Description |
|--------|-------------|
| `get_cached()` | Returns cached workflow data (JSON blob with runs, workflows, all_time_total) for a repository |
| `save_cache()` | Saves workflow data with upsert (INSERT ON CONFLICT UPDATE) |
| `is_stale()` | Checks if cached data is older than configurable TTL (default 60 minutes) |
| `get_all_repos()` | Returns list of all repos with cached data (used by startup refresh and seed script) |
| `clear()` | Removes all workflow cache entries (called by clear-cache endpoint) |

#### ContributorTimeSeriesCacheDB Methods

| Method | Description |
|--------|-------------|
| `get_cached()` | Returns cached per-contributor weekly time series data (JSON blob) for a repository |
| `save_cache()` | Saves contributor time series data with upsert (INSERT ON CONFLICT UPDATE) |
| `is_stale()` | Checks if cached data is older than TTL (default 24 hours) |
| `clear()` | Removes all contributor time series cache entries |

#### CodeActivityCacheDB Methods

| Method | Description |
|--------|-------------|
| `get_cached()` | Returns cached code activity data (JSON blob with weekly_commits, code_changes, owner_commits, community_commits) for a repository |
| `save_cache()` | Saves code activity data with upsert (INSERT ON CONFLICT UPDATE) |
| `is_stale()` | Checks if cached data is older than TTL (default 24 hours) |
| `clear()` | Removes all code activity cache entries |

#### TimelineCacheDB Methods

| Method | Description |
|--------|-------------|
| `get_cached()` | Returns cached timeline data (events + pr_state) for a (repo, pr_number) key |
| `save_cache()` | Upserts timeline data and pr_state |
| `is_stale()` | Checks staleness; ttl_minutes=None means "never stale" (closed/merged) |
| `clear()` | Removes all timeline cache entries |

**Note**: When returning cached stats, the backend transforms field names to match the frontend expectations:
- `username` → `login`
- `total_prs` → `prs_authored`
- `total_additions` → `lines_added`
- `total_deletions` → `lines_deleted`

#### Score Extraction

Scores are extracted directly from the JSON content: `content_json["score"]["overall"]`. No regex parsing needed.

### Data Migration Module

**File**: `/Users/jvargas714/Documents/dev/gh-pr-explorer/migrate_data.py`

The migration module handles one-time import of existing data into the SQLite database.

#### Migration Sources

| Source | Destination | Description |
|--------|-------------|-------------|
| `/Users/jvargas714/Documents/code-reviews/past-reviews/*.md` | `reviews` table | Historical review markdown files |
| `MQ/merge_queue.json` | `merge_queue` table | Legacy JSON queue data |

#### Migration Features

- **Follow-up Detection**: Identifies review files with `-followup` suffix and links them to parent reviews
- **Score Extraction**: Parses review content to extract numerical scores
- **Metadata Parsing**: Extracts PR number, repo, and timestamp from file names
- **Idempotent Execution**: Tracks migrations in `migrations` table to prevent duplicate runs

### Frontend (React + TypeScript)

**Directory**: `/Users/jvargas714/Documents/dev/gh-pr-explorer/frontend/src/`

The frontend uses React 18 with TypeScript, built via Vite. State management uses Zustand stores.

| Directory | Description |
|-----------|-------------|
| `api/` | Type-safe API layer matching all backend endpoints |
| `components/` | React components organized by feature area |
| `stores/` | Zustand stores for state management |
| `styles/` | CSS modules and global styles |
| `types/` | TypeScript type definitions |

#### Main Tab Architecture

The application uses a 6-tab layout as the primary navigation (Pull Requests,
Analytics, CI/Workflows, Repo Stats, Review Logs, Automation):

| Tab | View Key | Description |
|-----|----------|-------------|
| Pull Requests | `prs` | PR list with filters, pagination, and action buttons |
| Analytics | `analytics` | 5 sub-tabs for developer and repository analytics |
| CI/Workflows | `workflows` | Workflow run history with filters and aggregate stats |
| Repo Stats | `repo-stats` | Repository-level statistics, language breakdown, LOC analysis |
| Review Logs | `review-logs` | Review lifecycle event log: starts, attempts, failures and reasons |

#### Analytics Sub-tabs

| Sub-tab | Tab Key | Description |
|---------|---------|-------------|
| Stats | `stats` | Developer contribution statistics table |
| Lifecycle | `lifecycle` | PR lifecycle metrics, merge time distribution, stale PR detection |
| Activity | `activity` | Code activity charts: commits, code changes, top 5 contributors |
| Reviews | `responsiveness` | Per-reviewer response times, leaderboard, bottleneck detection |
| Contributors | `contributors` | Interactive per-contributor time series charts (commits, additions, deletions) |

### Styling

**Directory**: `/Users/jvargas714/Documents/dev/gh-pr-explorer/frontend/src/styles/`

The CSS uses a modern design system with:

- **CSS Custom Properties**: Comprehensive variable system for theming
- **Dark/Light Mode**: Full theme support via `.dark-mode` class
- **Responsive Design**: Mobile-first with breakpoint at 768px
- **Component Styles**: Modular styling for cards, buttons, tables, modals
- **CSS-only Charts**: Bar charts and stacked charts using pure CSS with native tooltips
- **Recharts Line Charts**: Interactive line charts for contributor time series and top-5 activity view
- **Column Tooltips**: `th[title]` cursor set to `help` for non-sortable headers; sortable headers use `pointer` cursor
- **Reusable `.stat-cards` Grid**: 4-column responsive grid for summary stat cards
- **Divergence Badges**: Color-coded branch behind indicators (green/yellow/red)
- **Workflow Status Classes**: `.wf-success`, `.wf-failure`, `.wf-cancelled`, `.wf-in-progress`

---

## Features

### Account/Organization Selection

Users can switch between their personal GitHub account and any organizations they belong to. The interface displays:

- Avatar image
- Account/organization login name
- Type indicator (Personal/Org)

Selection triggers a repository list refresh for the chosen context.

### Repository Browsing

- **Searchable Dropdown**: Type-ahead filtering of repository list
- **Visibility Indicator**: Public/Private badge for each repo
- **Lazy Loading**: Repositories loaded on-demand per account
- **Limit**: Fetches up to 200 repositories per account

### PR List Pagination

The PR list implements client-side pagination for improved performance and navigation:

- **Page Size**: 20 PRs displayed per page
- **Fetch Size**: Always fetches 100 PRs from the API for client-side pagination
- **Navigation**: Previous/Next buttons with disabled states at boundaries
- **Page Info**: "Page X of Y (Z PRs)" display showing current position
- **Auto-reset**: Pagination resets to page 1 when filters change
- **Smooth Scroll**: Page changes scroll to top of PR list section

#### UI Components

| Component | Description |
|-----------|-------------|
| Previous Button | Navigate to previous page (disabled on page 1) |
| Next Button | Navigate to next page (disabled on last page) |
| Page Info | Shows current page, total pages, and total PR count |

#### Implementation Details

- **Client-side**: Pagination is handled entirely in the browser using React state and memoized selectors
- **paginatedPRs**: Derived from the full PR array, sliced for the current page
- **Performance**: Avoids additional API calls when navigating pages
- **State Reset**: `currentPage` resets to 1 when `fetchPRs()` is called

### PR Filtering System

The filter panel is organized into five tabs:

#### Basic Filters Tab

| Filter | Type | Options |
|--------|------|---------|
| State | Button group | Open, Closed, Merged, All |
| Draft Status | Button group | Any, Ready, Draft |
| Author | Select dropdown | Contributors list |
| Assignee | Select dropdown | Contributors list |
| Base Branch | Select dropdown | Branch list |
| Head Branch | Select dropdown | Branch list |
| Labels | Multi-select chips | Repository labels |
| No Labels | Checkbox | PRs without any labels |
| Milestone | Select dropdown | Milestones + "No milestone" |
| Linked to Issue | Button group | Any, Linked, Not linked |

#### Review Filters Tab

| Filter | Type | Options |
|--------|------|---------|
| Review Status | Multi-checkbox (OR logic) | No reviews, Required, Approved, Changes requested |
| CI Status | Multi-checkbox (OR logic) | Pending, Success, Failure |
| Reviewed By | Select dropdown | Contributors list |
| Review Requested From | Select dropdown | Contributors list |

#### People Filters Tab

| Filter | Type | Options |
|--------|------|---------|
| Involves | Select dropdown | Contributors (author, assignee, mentions, commenter) |
| Mentions | Select dropdown | Contributors list |
| Commenter | Select dropdown | Contributors list |

#### Dates Filters Tab

| Filter | Type | Format |
|--------|------|--------|
| Created After/Before | Date picker | YYYY-MM-DD |
| Updated After/Before | Date picker | YYYY-MM-DD |
| Merged After/Before | Date picker | YYYY-MM-DD |
| Closed After/Before | Date picker | YYYY-MM-DD |

#### Advanced Filters Tab

| Filter | Type | Description |
|--------|------|-------------|
| Text Search | Text input | Keyword search in title/body/comments |
| Search In | Checkboxes | Title, Body, Comments |
| Comments Count | Text input | Comparison operators (>5, >=10, 0) |
| Results Limit | Select dropdown | 25, 30, 50, 100 |
| Reactions Count | Toggle + number input | Filter by total reactions |
| Interactions Count | Toggle + number input | Filter by reactions + comments |
| Team Review Requested | Toggle + select | Filter by team review request |
| Exclude Labels | Toggle + multi-select | NOT logic for labels |
| Exclude Author | Toggle + select | Hide PRs from specific author |
| Exclude Milestone | Toggle + select | Hide PRs with specific milestone |
| Custom Sort | Toggle + select + direction | Sort by created, updated, comments, reactions, interactions |

### Analytics Tab

The Analytics tab provides four sub-views for repository and team analytics. Data is lazy-loaded when each sub-tab is first selected.

### Developer Stats (Analytics > Stats)

The Stats view provides aggregated metrics for all contributors to a repository.

#### Metrics Displayed

| Metric | Description |
|--------|-------------|
| Commits | Total commits to the repository |
| PRs | Total PRs authored |
| Merged | Number of merged PRs |
| Closed | Number of closed (not merged) PRs |
| Merge % | Percentage of authored PRs that were merged |
| Reviews | Total reviews given |
| Approvals | Number of approval reviews |
| Changes Req. | Number of "changes requested" reviews |
| Lines + | Total lines added |
| Lines - | Total lines deleted |

#### Features

- **Sortable Columns**: Click any column header to sort ascending/descending with visual indicators (▼/▲/⇅)
- **Column Tooltips**: Hover any column header for a description of the metric
- **Sticky Developer Column**: First column stays visible while scrolling horizontally
- **Formatted Numbers**: Large numbers displayed with K/M suffixes
- **Color-coded Values**: Merge rate and stat types use semantic colors
- **Avatar Display**: Developer avatars shown inline

### PR Lifecycle Metrics (Analytics > Lifecycle)

The Lifecycle sub-tab shows how long PRs take to move through the review and merge pipeline.

#### Summary Cards

| Metric | Description |
|--------|-------------|
| Median Time to Merge | Median hours from PR creation to merge |
| Avg Time to Merge | Average hours from PR creation to merge |
| Median Time to First Review | Median hours from PR creation to first review |
| Avg Time to First Review | Average hours from PR creation to first review |

#### Merge Time Distribution

A bucket-based histogram showing the distribution of time-to-merge values:

| Bucket | Range |
|--------|-------|
| < 1h | Merged within 1 hour |
| 1-4h | Merged within 1-4 hours |
| 4-24h | Merged within 4-24 hours |
| 1-3d | Merged within 1-3 days |
| 3-7d | Merged within 3-7 days |
| > 7d | Merged after more than 7 days |

#### Stale PR Detection

Identifies open PRs with no activity in the last 14 days. Displays a warning list with PR number, title, author, and age in days.

#### PR Lifecycle Table

Fully sortable table of all analyzed PRs. All six columns (PR#, Author, State, Time to Review, Time to Merge, First Reviewer) support click-to-sort with ascending/descending toggle and visual sort indicators. Column headers include tooltips describing each metric. Null values are pushed to the bottom of sorted results. Sorting is performed client-side.

### Code Activity (Analytics > Activity)

The Activity sub-tab visualizes repository code activity over a configurable timeframe using CSS-only bar charts and a recharts line chart.

#### Timeframe Toggle

Users can select the analysis window: 1 month (4 weeks), 3 months (13 weeks), 6 months (26 weeks), or 1 year (52 weeks).

#### Summary Cards

| Metric | Description |
|--------|-------------|
| Total Commits | Total commits in the selected timeframe |
| Avg Weekly Commits | Average commits per week |
| Lines Added | Total lines added across all weeks |
| Lines Deleted | Total lines deleted across all weeks |
| Peak Week | Week with the highest commit count |
| Owner % | Percentage of commits from repository owner |

#### Visualizations

| Chart | Type | Description |
|-------|------|-------------|
| Weekly Commits | Bar chart (CSS) | Vertical bars showing commit count per week |
| Code Changes | Stacked bar chart (CSS) | Additions (green) and deletions (red) per week |
| Top 5 Contributors | Line chart (recharts) | Weekly commit counts for the top 5 contributors by total commits |

Weekly Commits and Code Changes charts are implemented with pure CSS. The Top 5 Contributors chart uses recharts `LineChart` with interactive tooltip and legend.

#### Data Sources

Uses three GitHub Stats API endpoints fetched via the `fetch_github_stats_api()` helper:

| Endpoint | Data Provided |
|----------|---------------|
| `stats/code_frequency` | Weekly additions and deletions |
| `stats/commit_activity` | Weekly commit totals and per-day breakdowns |
| `stats/participation` | Owner vs. all-contributor weekly commit counts |

Data is cached in SQLite with a 24-hour TTL using stale-while-revalidate. The full 52-week dataset is cached once; the `?weeks=N` parameter slices the cached data in Python, so switching timeframes does not trigger re-fetches.

### Per-Contributor Time Series (Analytics > Contributors)

The Contributors sub-tab provides interactive line charts showing per-contributor weekly activity over time. Data is sourced from the GitHub `stats/contributors` API and cached in SQLite with a 24-hour TTL using stale-while-revalidate.

#### Controls

- **Timeframe Selector**: 1 month (4 weeks), 3 months (13 weeks), 6 months (26 weeks), 1 year (52 weeks)
- **Metric Selector**: Commits, Lines Added, Lines Deleted
- **Legend Toggle**: Click a contributor in the legend to show/hide their line

#### Chart

A recharts `LineChart` at 400px height with:
- One `Line` per contributor with distinct colors from a 10-color palette
- `CartesianGrid`, `XAxis` (week dates), `YAxis`, interactive `Tooltip`, and clickable `Legend`
- Theme-aware colors adapting to dark/light mode

### Review Responsiveness (Analytics > Reviews)

The Reviews sub-tab shows per-reviewer response times and identifies review bottlenecks.

#### Team Summary

| Metric | Description |
|--------|-------------|
| Avg Team Response | Average response time across all reviewers |
| Fastest Reviewer | Reviewer with the lowest average response time |
| PRs Awaiting Review | Count of open PRs with no reviews |

#### Reviewer Leaderboard

Fully sortable table of all reviewers. All columns support click-to-sort with ascending/descending toggle, visual sort indicators, and active column highlighting. Column headers include tooltips. Sorting is performed client-side. Columns:

| Column | Description |
|--------|-------------|
| Reviewer | GitHub username |
| Avg Response Time | Average hours from PR creation to review submission |
| Median Response Time | Median hours from PR creation to review submission |
| Total Reviews | Number of reviews given |
| Approvals | Number of approval reviews |
| Changes Requested | Number of "changes requested" reviews |
| Approval Rate | Percentage of reviews that are approvals |

#### Bottleneck Detection

Lists the top 10 open PRs that have been waiting longest for a review, sorted by wait time in descending order. Each bottleneck entry shows PR number, title, author, and hours waiting.

### CI/Workflows Tab

The CI/Workflows tab provides visibility into GitHub Actions workflow runs for the selected repository.

#### Workflow Filters

| Filter | Type | Description |
|--------|------|-------------|
| Workflow | Select dropdown | Filter by specific workflow |
| Branch | Select dropdown | Filter by branch |
| Event | Select dropdown | Filter by trigger event (push, pull_request, schedule, etc.) |
| Conclusion | Select dropdown | Filter by outcome (success, failure, cancelled, skipped) |

#### Aggregate Stats Cards

| Metric | Description |
|--------|-------------|
| Total Runs | Number of workflow runs in the result set |
| Pass Rate | Percentage of completed runs that succeeded |
| Avg Duration | Average duration of completed runs |
| Failures | Total number of failed runs |

#### Workflow Runs Table

All columns are sortable with click-to-sort, ascending/descending toggle, and visual sort indicators. Column headers include tooltips. Default sort is by Started (descending).

| Column | Description |
|--------|-------------|
| Workflow | Workflow name and display title |
| Status/Conclusion | Run outcome with color-coded badge |
| Branch | Head branch that triggered the run |
| Event | Trigger event type |
| Actor | User who triggered the run |
| Duration | Computed from created_at to updated_at |
| Started | Timestamp of run creation |

#### Workflow Pagination

The workflow runs table implements client-side pagination over server-fetched data:

- **Page Size**: 25 runs per page
- **Fetch Size**: Backend fetches up to 3 pages from GitHub API (300 runs max)
- **Navigation**: Previous/Next buttons with disabled states at boundaries
- **Page Info**: "Page X of Y (Z runs)" display
- **Auto-reset**: Page resets to 1 when filters change or new data is fetched
- **Sorting**: Pagination operates on the sorted result set

#### Conclusion Color Coding

| Conclusion | CSS Class | Color |
|------------|-----------|-------|
| success | `wf-success` | Green |
| failure | `wf-failure` | Red |
| cancelled | `wf-cancelled` | Gray |
| in_progress | `wf-in-progress` | Yellow |
| skipped | `wf-skipped` | Gray |

### Dark/Light Theme Support

- Theme preference persisted to localStorage
- Toggle button in header
- Full CSS variable system for seamless switching
- Respects system preference on first load

### PR Card Status Badges

PR cards display multiple status badges to provide at-a-glance information about each pull request.

#### GitHub Review Status Badge

Shows the current review status from GitHub's review system:

| Status | Color | Description |
|--------|-------|-------------|
| Approved | Green | Changes have been approved by reviewers |
| Changes Requested | Red | Reviewers have requested changes |
| Review Required | Yellow | PR requires review before merging |

#### CI Status Badge

Shows the status of CI/CD checks (GitHub Actions, etc.):

| Status | Color | Description |
|--------|-------|-------------|
| CI passed | Green | All checks have passed |
| CI failed | Red | One or more checks failed |
| CI running | Yellow | Checks are in progress |
| CI skipped | Gray | Checks were skipped or neutral |

The CI status is derived from the `statusCheckRollup` field which aggregates all check runs and status contexts for the PR.

When the badge shows **CI failed**, hovering it opens a portal-rendered popover listing the individual checks that failed. Each row displays the check name, an optional workflow/description subtitle, the failure type (`Failed` / `Timed out` / `Action required`), an optional duration, and — when GitHub provides a `detailsUrl` or `targetUrl` — the entire row becomes a clickable link to the failing run on GitHub. Checks are deduplicated client-side using the same "latest run per check name" rule the backend uses to compute `ciStatus`, so superseded reruns never appear. The same component (`CIStatusBadge`) is shared by the PR list, the merge queue panel, and the swimlane board, and the merge queue API now includes `statusCheckRollup` on each enriched queue item to power it.

#### Other PR Card Badges

| Badge | Description |
|-------|-------------|
| Draft | Orange badge for draft PRs |
| Review Score | Color-coded score from Claude code review (0-10) |
| New Commits | Indicates commits added since last review |
| Posted | Shows inline comments have been posted to GitHub |
| Branch Divergence | Shows how many commits behind the base branch (open PRs only) |

#### Rev Log Badge (queue + swimlane cards)

Merge-queue and swimlane cards carry a neutral **`rev log (N)`** badge in the title row (after the CI badge), shown only when the PR has at least one review or audit. Hovering it opens a portal-rendered popover (same hover/positioning mechanics as `CIStatusBadge`) that lists every review **and** audit run for the PR, newest-first. Each row shows a `REVIEW`/`AUDIT` tag, the result (review → color-coded `N/10` plus a `follow-up` marker when applicable; audit → `N findings · M blocking`, blocking count in red when non-zero), a **reviewer-agent chip** (`Code`/`PB`/`ED` for reviews, `PB/ED` for audits), and the absolute date + time the run completed. The agent chip is driven by the `reviewer_agent` column persisted on each review (the reviewer-picker choice) and by the fixed `pb_ed` audit type; reviews recorded before the column existed have no stored agent and render no chip. Non-`completed` runs show their status (`running`, `failed`, `cancelled`) in place of a result. Rows are clickable: review rows open the review viewer (`openReviewViewer`), audit rows open the `AuditViewer`.

The data is bundled into each card payload by `backend/services/queue_enrichment.py` via the pure `build_rev_log(reviews, audits, auto_verdicts)` helper (merges `reviews_db.get_reviews_for_pr` + `audits_db.get_audits_for_pr` + `auto_verdicts_db.get_for_pr` into a newest-first `revLog` array), so the popover renders without an extra fetch. Auto verdicts are folded into the review entry they were derived from (`verdictOutcome`/`verdictEvent`/`verdictReason` on the review entry), so each review round occupies a single popover row; a verdict only becomes its own `AUTO`-tagged entry when its parent review is not in the list. Rendered by the shared `RevLogBadge` component, so the merge queue panel and the swimlane board behave identically.

#### Branch Divergence Badge

Shows how far behind the base branch each open PR's head branch is:

| State | Color | Commits Behind | CSS Class |
|-------|-------|----------------|-----------|
| Current | Green | 0 | `divergence-current` |
| Slightly Behind | Yellow | 1-10 | `divergence-slightly-behind` |
| Far Behind | Red | 11+ | `divergence-far-behind` |

Divergence data is automatically fetched after the PR list loads. The backend uses `ThreadPoolExecutor` (5 workers) to batch-fetch the GitHub compare API for all open PRs in parallel. The badge displays the `behind_by` count from the GitHub compare endpoint.

#### Approved-by-Me Card Highlight

PR cards in the Pull Requests list and merge queue items are tinted with a subtle neon-green background, border, and glow when the current user has an `APPROVED` review on the PR. Approval is detected by cross-referencing the personal account's `login` (from `useAccountStore.accounts.find(a => a.is_personal)`) against `currentReviewers[].login` with `state === 'APPROVED'`.

| Surface | Modifier class |
|---------|----------------|
| PR card (list) | `mx-pr-card--approved-by-me` |
| Queue item (merge queue) | `mx-queue-item--approved-by-me` |

Tint colors derive from `--mx-color-success` / `--mx-color-success-bg`, so the highlight adapts to both dark and light themes.

### Settings Persistence

User settings are automatically saved to the SQLite database and restored on page load:

#### Persisted Settings

- **Selected Account**: Last selected GitHub account/organization
- **Selected Repository**: Last selected repository
- **All Filter Settings**: State, draft status, review filters, people filters, date filters, advanced filters

#### How It Works

1. Settings are saved with a 1-second debounce after any change
2. On page load, settings are fetched from `/api/settings/filter_settings`
3. Account and repository selections are restored first
4. Filter settings are restored after selections complete (to avoid reset conflicts)
5. PRs are re-fetched with the restored filter configuration

### Repo Stats Tab

The Repo Stats tab provides comprehensive repository-level statistics aggregated from multiple GitHub API endpoints.

#### Data Sources

Data is fetched in parallel via ThreadPoolExecutor(max_workers=7) from:
- `repos/{owner}/{repo}` — Repository metadata (size, stars, forks, watchers, created date, license)
- `repos/{owner}/{repo}/languages` — Language breakdown by bytes
- `repos/{owner}/{repo}/git/trees/HEAD?recursive=1` — Complete file listing
- `search/issues?q=repo:...+is:pr+is:open/closed/merged` — PR counts by state (3 queries)
- `repos/{owner}/{repo}/branches` — Branch count (paginated)
- `stats/contributors` — Total commits (sum of contributor totals)

#### UI Sections

| Section | Description |
|---------|-------------|
| Repository Overview | Name, description, default branch, license, age, size, stars, forks, watchers, open issues |
| Summary Stats Cards | Two rows: Code stats (commits, files, contributors, branches) and PR stats (open, opened, closed, merged) |
| Language Breakdown | Horizontal stacked color bar with legend showing language name, bytes, and percentage |
| Files by Extension | Sortable table with extension, count, percentage. Top 20 with "Show all" toggle |
| Lines of Code | On-demand shallow clone + line counting. Shows per-language breakdown of blank, comment, and code lines |

#### Caching

- Main stats: SQLite cache with 4-hour TTL, stale-while-revalidate pattern
- LOC results: SQLite cache with 24-hour TTL, synchronous on first request

### Review History

The Review History feature provides access to all past code reviews, enabling users to search, filter, and view historical review content.

#### UI Components

| Component | Location | Description |
|-----------|----------|-------------|
| History Toggle | Header | Clock icon button to open/close history panel |
| History Panel | Slide-out | Full review history browser with search and filters |
| Review Viewer Modal | Overlay | Full markdown content display for selected review |
| Score Badge | PR Card | Color-coded badge showing review score (if reviewed) |
| Follow-up Button | PR Card | Quick action to create follow-up review for previously reviewed PRs |

#### History Panel Features

- **Search**: Full-text search across review content and PR titles
- **Filters**: Filter by repository, author, PR number, date range, and score range
- **PR Number Search**: Quick lookup of reviews by specific PR number
- **Sorting**: Sort by date, score, or PR number
- **Pagination**: Browse through large review histories
- **Quick View**: Click any review to open full content in modal

#### Score Badges

Score badges appear on PR cards when a review exists. Color coding indicates review quality:

| Score Range | Color | Meaning |
|-------------|-------|---------|
| 7-10 | Green | Good quality, likely ready to merge |
| 4-6 | Yellow | Moderate issues, needs attention |
| 0-3 | Red | Significant issues, requires rework |
| N/A | Gray | Review exists but no score extracted |

#### Review Viewer Modal

The modal displays full review content with:

- Markdown rendering with syntax highlighting
- PR metadata (title, author, URL, review date)
- Score display with color indicator
- Follow-up indicator for chained reviews
- Link to original review file
- **Copy Markdown Button**: Copies raw review content to clipboard for easy sharing

### PR Timelines

The PR Timelines feature provides a focused, single-PR deep-dive view showing every lifecycle event as a vertical animated timeline.

#### How It Works

1. User clicks the ⏱ (Timeline) button on any PR card or merge queue card.
2. A full-screen modal opens and fetches the PR's normalized event timeline via `GET /api/repos/:owner/:repo/prs/:n/timeline`.
3. Events are rendered as a vertical rail with color-coded dots and expandable, markdown-rendered bodies.
4. Filter chips toggle groups of event types on/off (Commits, Reviews, Comments, State).
5. Closed/merged PRs are served from indefinite SQLite cache; open PRs use a 5-minute TTL with stale-while-revalidate and manual refresh.

#### Event Types

| Event | Dot color | Source |
|-------|-----------|--------|
| opened | indigo | Synthesized from PR `createdAt` |
| committed | emerald | `committed` |
| commented | cyan | `commented` |
| reviewed (APPROVED) | emerald | `reviewed` with state APPROVED |
| reviewed (CHANGES_REQUESTED) | red | `reviewed` with state CHANGES_REQUESTED |
| reviewed (COMMENTED) | amber | `reviewed` with state COMMENTED |
| review_requested | slate | `review_requested` |
| ready_for_review / convert_to_draft | sky | `ready_for_review` / `convert_to_draft` |
| closed | red | `closed` |
| reopened | indigo | `reopened` |
| merged | violet | `merged` |
| head_ref_force_pushed | amber | `head_ref_force_pushed` |

#### UI Components

| Component | Responsibility |
|-----------|----------------|
| `TimelineModal` | Overlay + shell, keyboard handling, scroll lock |
| `TimelineHeader` | PR title, refresh, updated indicator, close |
| `TimelineFilters` | Event-type chip toggles |
| `TimelineView` | Vertical rail, stagger-in animation, empty/error states |
| `TimelineEventRow` | Card shell, dot, expand/collapse, body dispatch |
| `eventBodies/*` | Per-type renderers (Commit, Comment, Review, StateChange, ReviewRequested, ForcePush) |

#### Interaction Model

- **Expand**: click the dot OR the card header. Any number of events can be expanded simultaneously (multi-expand).
- **Filter**: click a chip to hide/show that event group.
- **Refresh**: click the ↻ button in the header to force a fresh fetch.
- **Close**: click outside the shell, press Esc, or click ×.

#### Animations

All use Framer Motion spring physics:
- **Modal enter/exit**: fade + slide + scale spring.
- **Stagger-in**: events fade+slide from below with 40ms stagger (first 20 only).
- **Expand/collapse**: AnimatePresence height spring.
- **Refresh indicator**: opacity pulse while `refreshing === true`.

#### Dependencies

- `framer-motion@^11.0.0` — animations
- `react-markdown` + `remark-gfm` + `rehype-highlight` (existing) — comment and review body rendering

#### Live Updates

- While the modal is open AND the PR is `OPEN`, the timeline is re-fetched every 45 seconds in the background. Closed/Merged PRs do not poll (their history is immutable).
- When the modal opens, if the cached entry is older than 5 minutes and the PR is open, a forced refresh is triggered immediately (optimistic invalidation) so a PR opened hours ago doesn't show stale events on reopen.
- A `Refresh` button in the header forces an immediate refresh at any time.
- The `Updated X ago` indicator pulses when a refresh is in progress.

#### Entry Points

| Location | Button |
|----------|--------|
| PR card in the PR list | ⏱ Timeline |
| Merge queue card | ⏱ Timeline |

### Merge Queue

The Merge Queue feature allows users to organize PRs they intend to review or merge, providing a prioritized list across repositories.

#### Features

- **Cross-Repository Support**: Queue PRs from any repository
- **Persistent Storage**: Queue persisted to SQLite database (`pr_explorer.db`)
- **Drag/Reorder**: Move items up/down to prioritize
- **Quick Actions**: Add/remove PRs with single click
- **Slide-out Panel**: Non-intrusive UI that doesn't obstruct PR browsing
- **Position Tracking**: Queue order maintained via `position` column in database

#### Queue Item Data Structure

```json
{
  "id": 1,
  "number": 123,
  "title": "PR Title",
  "url": "https://github.com/owner/repo/pull/123",
  "repo": "owner/repo",
  "author": "username",
  "additions": 150,
  "deletions": 50,
  "addedAt": "2024-01-15T10:30:00Z",
  "notesCount": 0,
  "prState": "OPEN",
  "hasNewCommits": false,
  "lastReviewedSha": "abc123def456",
  "currentSha": "abc123def456",
  "hasReview": true,
  "reviewScore": 8,
  "reviewId": 42,
  "inlineCommentsPosted": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Database ID of the queue item |
| `number` | integer | PR number |
| `title` | string | PR title |
| `url` | string | GitHub PR URL |
| `repo` | string | Repository in `owner/repo` format |
| `author` | string | PR author username |
| `additions` | integer | Lines added |
| `deletions` | integer | Lines deleted |
| `addedAt` | string | ISO timestamp when added to queue |
| `notesCount` | integer | Number of notes attached to this queue item |
| `prState` | string | Current PR state (OPEN, CLOSED, MERGED) |
| `hasNewCommits` | boolean | True if new commits since last review |
| `lastReviewedSha` | string | Commit SHA of last review |
| `currentSha` | string | Current HEAD commit SHA |
| `hasReview` | boolean | True if PR has been reviewed |
| `reviewScore` | integer | Latest review score (0-10) |
| `reviewId` | integer | Database ID of latest review |
| `inlineCommentsPosted` | boolean | True if inline comments have been posted |

#### UI Components

| Component | Location | Description |
|-----------|----------|-------------|
| Queue Toggle | Header | Button with badge showing queue count |
| Queue Button | PR Card | Add/remove PR from queue |
| Queue Panel | Slide-out | Full queue management interface |
| Queue Item | Panel | Individual PR with reorder and remove controls |
| Review Button | Queue Item | Start code review for queued PR |
| Post Inline Comments | Queue Item | Post critical issues to GitHub (appears when review exists) |
| Verdict Button | Queue Item | Submit formal PR review verdict to GitHub (appears when review exists) |
| Verdict Modal | Overlay | Modal with event selector, custom text, section toggles, and submit |
| View Description | Queue Item | 📝 button that opens the same draggable description modal used by the main PR list. Lazy-fetches the PR via `GET /api/repos/.../prs?prNumber=N`. |
| Notes Toggle | Queue Item | Expand/collapse notes for the PR |
| Add Note Button | Queue Item | Add a new note to the PR |
| PR State Badge | Queue Item | Shows current PR state (open/closed/merged) |
| Review Score Badge | Queue Item | Shows review score if PR has been reviewed |
| New Commits Badge | Queue Item | Indicates new commits since last review |
| Timeline Button | Queue Item | Opens the PR Timelines modal for this PR |

### Swimlane Board (Kanban view of merge queue)

A Trello-style alternative view of the merge queue. Cards displayed inside swimlanes are the *same records* as the merge queue — opening either view shows the same PRs. Lanes express workflow state (e.g., "Reviewing", "Blocked", "Ready to merge"), are user-defined, and are color-coded.

#### How It Works

1. The user clicks the 📊 button in the header. A full-screen overlay slides in from the right (Framer Motion spring, mirroring the Timeline modal pattern).
2. The board shows all user-defined lanes horizontally. The default lane (`Unassigned`) is seeded on first run and always exists.
3. Cards can be dragged within a lane (reorder) or between lanes (workflow transition). Both go through `PUT /api/swimlanes/cards/move` with optimistic local state and revert on failure.
4. New PRs added to the merge queue automatically land in the default lane (auto-assigned by `MergeQueueDB.add_to_queue` via `SwimlanesDB.auto_assign_new_card`).
5. Removing a PR from the merge queue deletes its swimlane assignment via SQLite `ON DELETE CASCADE`.

#### Lane Properties

| Property | Description |
|----------|-------------|
| `id` | DB primary key |
| `name` | Editable label (double-click the column header to rename) |
| `color` | One of 8 palette keys: `success`, `warning`, `error`, `info`, `primary`, `accent`, `violet`, `slate`. Each maps to a Matrix UI CSS custom property |
| `position` | 1-based ordering across lanes |
| `isDefault` | Exactly one lane is the default; new merge queue items land here |
| `isProtected` | Protected lanes (the automation "Auto" lane) cannot be deleted or renamed; recolor and reorder stay allowed |

#### UI Components

| Component | Responsibility |
|-----------|----------------|
| `SwimlaneModal` | Full-screen slide-from-right overlay shell, ESC handling, scroll lock |
| `SwimlaneHeader` | Title, card count, auto/manual split, search input, badge-filter popover, auto-mode segmented filter, "Clear merged (N)" bulk-remove button, "+ Add Lane" inline form, refresh, close |
| `BadgeFilterPopover` | Funnel button next to the search input that opens a popover for badge-based card filtering (AND/OR toggle + grouped chips, see "Filtering" below) |
| `SwimlaneBoard` | `DndContext` orchestrating cross-column and within-column DnD |
| `SwimlaneColumn` | Single lane: colored header, name (inline-editable on double-click), color swatch popover, count badge, `−` delete button, droppable + sortable body |
| `LaneColorPicker` | 8-swatch grid for color selection |
| `QueueItem` (reused) | Renders the same card component used in the merge queue panel — verdict, inline comments, notes, timeline, badges, review actions all work identically. When rendered inside a swimlane column it also exposes a lane-selector dropdown (see "Lane selector dropdown" below) and a 📌 pin toggle (see "Pinned cards" below) |

#### Lane selector dropdown

In addition to drag-and-drop, each card rendered inside the swimlane board includes a small native `<select>` in its meta row listing every lane by name with the card's current lane pre-selected. Selecting a different lane calls `useSwimlaneStore.moveCard(item.id, currentLaneId, toLaneId, 0)`, which optimistically inserts the card at the top of the destination lane and persists the move via `PUT /api/swimlanes/cards/move`. The dropdown is purely additive — drag-and-drop still works — and is intended as a shortcut for boards with many lanes where dragging across the full board width is awkward. It is fed live by `useSwimlaneStore.lanes`, so newly added or renamed lanes appear immediately. The dropdown is hidden when only one lane exists, and is only rendered when `QueueItem` receives the `swimlaneContext` prop (the merge queue panel does not).

#### Clear merged shortcut

The swimlane header carries a "Clear merged (N)" button in the actions row that bulk-removes every queued PR whose `prState === 'MERGED'`. Clicking it shows a `window.confirm` with the count, then fires `removeFromQueue(number, repo)` for each merged card in parallel via `useSwimlaneStore.clearMergedCards`, pausing polling for the duration and reloading the board on completion. Failures on individual PRs are swallowed so one bad delete doesn't block the rest. The button is disabled when no merged cards are present.

#### Pinned cards

Any card in a swimlane can be pinned via the 📌 toggle button in its action row. Pinning anchors a card so it stays put regardless of board churn:

- **Anchored to the top** — pinned cards form a contiguous group at the top of their lane, above all unpinned cards. This is enforced by a single ordering invariant: everywhere a lane is read or compacted, cards are ordered `is_pinned DESC, position_in_lane ASC`, and `_compact_lane()` renumbers `position_in_lane` to `1..N` in that same order. New cards auto-assign to the bottom of the default lane (unpinned), so they can never displace a pinned card, and the 45-second background refresh never reshuffles them.
- **Survives "Clear merged"** — `clearMergedCards` and the header's merged count exclude pinned cards. A pinned merged card stays on the board; only unpinned merged cards are removed.
- **Still draggable, pin sticks** — a pinned card can be reordered among the other pinned cards or dragged to another lane (where it lands in that lane's pinned zone, still pinned), but a drag never crosses the pinned/unpinned boundary. `SwimlanesDB.move_card` clamps a pinned card's target into `[1, pinnedCount + 1]` and an unpinned card's into `[pinnedCount + 1, N + 1]` (computed in the destination lane, excluding the moving card). The same clamp (`pinZoneClamp`) is mirrored in `useSwimlaneStore.moveCard` so the optimistic UI matches the persisted result. Pin/unpin is only ever toggled by the button — dragging changes order and lane, never pin state.

A pinned card shows a 📌 corner marker and a subtle accent border/tint (`mx-queue-item--pinned`, derived from `--mx-color-accent`). The pin button and treatment only appear when `QueueItem` is rendered inside the swimlane board (the merge queue panel does not pass `swimlaneContext`).

Backend: `is_pinned` lives on `swimlane_assignments` (added via a tracked `ALTER TABLE` migration in `base.py`). `SwimlanesDB.set_pinned(queue_item_id, pinned)` flips the flag and repositions the card to the boundary (pin → bottom of pinned group; unpin → top of unpinned group). The board response and `move_card`/pin responses surface `isPinned` on each card/assignment.

#### Drag-and-drop

Built on dnd-kit (already used by the merge queue panel — no new dependencies). One `DndContext` at the board level, one `useDroppable` per column with id `lane-{id}`, one `SortableContext` per column over its card ids (numeric `merge_queue.id`). `onDragEnd` discriminates by `over.id` shape:
- numeric → dropped on a card; locate the card's lane and use its index
- string `lane-{id}` → dropped on empty column space; append to that lane

Lane deletion behavior: if the lane is empty, deletion is silent. If it has cards, a confirm dialog warns the cards will move to the default lane. The backend `SwimlanesDB.delete_lane` then re-homes orphaned cards (whose `swimlane_id` was set to NULL by `ON DELETE SET NULL`) to the new default. The last remaining lane cannot be deleted.

#### Persistence

Two SQLite tables:

```sql
swimlanes (id, name, color, position, is_default, is_protected, created_at)
swimlane_assignments (id, queue_item_id UNIQUE, swimlane_id, position_in_lane, updated_at)
```

`swimlane_assignments.queue_item_id` cascades from `merge_queue(id)`. `swimlane_assignments.swimlane_id` is `ON DELETE SET NULL`, with `delete_lane()` re-homing orphans to the default. On startup, `create_app()` invokes `ensure_default_lane()` and `reconcile_assignments()` to handle drift and bootstrap the feature on existing databases; `get_board` additionally invokes `ensure_auto_lane()` so the protected Auto lane self-heals (see the Automation feature section).

#### Filtering

The header carries three visibility filters that all drive the same "match glow + non-match dim + auto-scroll-to-first-match" visual treatment. Filters are AND'd with each other: a card is visible (highlighted) iff it passes the text search, the badge filter, and the auto-mode filter.

| Filter | Surface | Behavior |
|--------|---------|----------|
| Text search | Search input | Substring match against PR number, title, author, repo (case-insensitive); exact match on digit-only queries against the PR number |
| Badge filter | Funnel popover (`BadgeFilterPopover`) | Grouped chip selector with an OR / AND mode toggle |
| Auto mode | Segmented control (`All` / `🤖 Auto` / `Manual`) | One-click split by `autoVerdict.enabled` — armed cards, un-armed cards, or everything |

Badge filter dimensions:

| Group | Chips |
|-------|-------|
| State | Open, Closed, Merged |
| Draft | Draft |
| Review | ✓ Approved, ✗ Changes Requested, 👀 Review Required |
| CI | CI Passed, CI Failed, CI Running |
| Review Score | Has review, Score ≥ 7, Score 4–6, Score < 4 |
| Auto Verdict | 🤖 Armed, 🤖 Verdict Posted, 🤖 Needs Manual Approval |
| Other | New Commits, Reviewers Requested, Follow-up |

**Combinator semantics**

- **OR mode** — a card matches if any selected chip's predicate is true.
- **AND mode** — within a single dimension, picks are still OR'd (a card can't be both Open and Merged at the same time); across dimensions each non-empty dimension must have at least one matching chip. Example: `State ∈ {Open, Merged}` AND `CI = Failure`.

Selections live on `useSwimlaneStore` as `badgeFilters: Set<BadgeFilterKey>`, `badgeFilterMode: 'OR' | 'AND'`, and `autoModeFilter: 'all' | 'auto' | 'manual'`. The pure helper `cardPassesFilters(card, query, badges, mode, autoMode)` combines all three predicates and is consumed by `SwimlaneColumn` (to drive `searchMatch="match"|"dim"` on each `QueueItem`) and by `SwimlaneHeader` (to compute the live `N matches` count). The match-glow uses the existing `mx-queue-item--search-match` pulse animation; non-matches receive `mx-queue-item--search-dim`. "Clear all" resets all three.

The auto-mode control overlaps the `🤖 Armed` badge chip deliberately: the segmented control is the one-click path for the common "show me what's on autopilot" question, while the chip remains available for AND/OR combinations with other badge dimensions.

#### Auto/manual split

Next to the card count the header shows `🤖 N auto · M manual`, counting cards by `autoVerdict.enabled` across every lane. The counts are unfiltered — they describe the whole board, not the current filter — so the split stays a stable read on how much of the queue is armed while filters come and go.

Arming a card updates the count and the auto-mode filter immediately, not on the next poll: `AutoVerdictToggle` holds the requested state locally *and* calls `useSwimlaneStore.applyAutoVerdictLocal(prNumber, repo, autoVerdict)`, which patches the board's own copy of the card and bumps `boardEpoch` (so an in-flight poll can't undo it — the same guard the card-move path uses). The store action is a no-op when the PR isn't on the board, which is what makes the shared `QueueItem` safe to render in the merge queue panel. See "Optimistic arming" under Auto Verdicts.

#### Live Updates

While the swimlane modal is open, the board silently re-fetches `/api/swimlanes/board` every 45 seconds so card state (PR draft toggles, new commits, CI status, review decisions) stays in sync with GitHub without requiring the user to close and re-open the board. The cadence matches the timeline modal — each refresh enriches every queued PR via `gh pr view`, so a tighter interval would burn through the GitHub rate limit on large queues.

The poll is suspended whenever:
- The browser tab is hidden (no work for an unviewed UI; resumes immediately on `visibilitychange`)
- The user is mid-drag (a refetch would yank cards out from under the cursor)
- A mutation is in flight (`moveCard`, `reorderLanesLocal`) — pollPause is reference-counted so concurrent drag + mutation both contribute and resume independently

Pause-suspension alone cannot catch a slow board fetch that *started before* a card move and *lands after* the move's pause window has already closed — applying its pre-move snapshot would visibly "snap" the card back to its original lane. To close that gap, the store carries a `boardEpoch` generation counter: every optimistic mutation (`moveCard`, `togglePin`, `reorderLanesLocal`) and every authoritative `loadBoard` increments it. A background `refreshBoard` stamps the epoch at fetch-start and discards its response if the epoch has advanced by the time it resolves (in addition to the pause-depth re-check). Since the move itself is already persisted server-side, the next clean poll renders the correct lane.

The header shows a `CacheTimestamp` indicator ("Updated X ago" / "refreshing…") sourced from `lastUpdated` and `refreshing` flags on the swimlane store. Background refreshes do not flip the modal's `loading` flag and silently swallow transient errors so a brief network blip doesn't surface a banner mid-session.

### PB↔ED Audit

The PB↔ED Audit feature audits the Engineering Design (ED) documents touched in a PR against their parent Product Brief (PB) for **parity** (does the design implement what the brief specifies — and only that?) and against each other for **cross-ED consistency** (do sibling EDs agree on shared values, enums, contracts, and cross-references?). It runs the global `/pb-ed-audit` skill via Claude CLI and runs as a background subprocess parallel to the code review system, persisting completed audits to the `audits` SQLite table.

#### How It Works

1. The user picks **PB ED Audit** — the fourth option in the same "Review ▾" picker used for code reviews. This dispatches to `POST /api/audits` (not `/api/reviews`).
2. The backend (`audit_service.start_audit_process`) spawns a `claude -p` subprocess whose prompt invokes the `/pb-ed-audit` skill, instructing it to write a markdown report **and** a structured JSON file conforming to `backend/services/audit_schema_spec.json`.
3. The skill fetches the PR-head ED/PB docs, runs the two audits (Audit A — cross-ED consistency, Audit B — PB↔ED parity), and writes both artifacts. The embedded `_AUDIT_SCHEMA_INSTRUCTIONS` prompt emphasizes that each finding's `locations[]` must carry a resolved repo-relative `file` and integer `line` so findings can be posted as inline PR comments.
4. On completion, `save_audit_to_db` reads and validates the `.json`, computes finding/blocking tallies, and inserts a row into `audits`.
5. The UI polls active audits to drive the spinner, then surfaces the result via the audit chip and viewer.

#### UI Components

| Component | Location | Description |
|-----------|----------|-------------|
| **PB ED Audit** picker option | PR card / queue item "Review ▾" menu | Starts an audit for the PR |
| `AuditChip` | Audit viewer header / audit history rows | Green when the latest audit has zero blocking findings, red when one or more findings are blocking; the label shows the blocking count (`Audit · N blocking`), with the total finding count in the tooltip |
| `AuditViewer` | Overlay modal | Renders the full audit: executive summary, the two-part report (**Audit A** cross-ED consistency and **Audit B** PB↔ED parity), per-finding detail, verified-clean list, and action map |
| Audits history tab | History panel | A dedicated tab listing past audits with repo/author/PR/search filters, alongside the existing reviews history |
| VerdictModal audit mode | Overlay | The verdict modal opens in audit mode from the `AuditViewer`, composing a PR review body from toggleable audit blocks and inline comments drawn from findings with resolvable `file`+`line` locations |

#### Audit Chip Status

| State | Color | Meaning |
|-------|-------|---------|
| Clean | Green | Latest audit has no blocking findings (`blocking_count == 0`) |
| Blocking | Red | One or more findings are blocking (`blocking_count > 0`) |

#### Inline Comments

Audit findings can be posted to the PR as inline comments via `POST /api/audits/<audit_id>/post-inline-comments`. The backend maps each finding's first location with a concrete `file` + integer `line` to an inline comment (`_findings_to_inline_comments`), then posts them through the shared `post_verdict` helper. Findings whose locations carry only a human display `ref` (no resolved `file`/`line`) are silently skipped, which is why the skill is instructed to resolve real line numbers.

### Code Review System (Claude CLI Integration)

The Code Review feature integrates with Claude CLI to perform automated code reviews. Reviews run as background subprocesses, with real-time status tracking in the UI. Completed reviews are persisted to the SQLite database for historical access.

#### How It Works

1. User clicks the **📋 Review ▾** button on a PR card or queue item
2. A small picker menu (`ReviewerPickerMenu`) appears offering three reviewer agents:
   - **Default Reviewer** — `elite-code-reviewer` (general code review)
   - **Product Brief Reviewer** — `product-brief-reviewer` (PB-000 brief review)
   - **Engineering Design Reviewer** — `ed-reviewer` (ED-000 engineering design review; applies both the SDLC-conformance and code-review lenses described in the agent's protocol)
3. Backend spawns a Claude CLI subprocess with a prompt tailored to the selected reviewer
4. UI shows spinner while review is in progress
5. All reviewer types produce output in the same dual format: a markdown file (`.md`) and a structured JSON file (`.json`) following the schema in `backend/services/review_schema.py`
6. Review metadata and `content_json` are saved to SQLite database; markdown is generated on the fly from `content_json` when needed
7. UI updates to show completed/failed status with score badge
8. Failed reviews display error details in a modal

The reviewer choice is plumbed through the `reviewer_type` field on `POST /api/reviews` (`"default"`, `"pb"`, or `"ed"`). When `"pb"` is selected, the prompt invokes the `product-brief-reviewer` agent and asks it to identify and review the PB-NNN brief file(s) touched in the PR diff. When `"ed"` is selected, the prompt invokes the `ed-reviewer` agent and asks it to identify and review the ED-NNN engineering design file(s) under `docs/designs/` touched in the PR diff. All three reviewers must emit the same JSON schema and write to the same `.md` + `.json` paths so downstream parsing, inline-comment posting, and verdict composition are reviewer-agnostic.

Every prompt also carries `_FOREGROUND_INSTRUCTIONS`, requiring the wrapper CLI to dispatch the reviewer agent in the foreground and to confirm both files exist before ending its turn. This is load-bearing, not advisory: in `claude -p` a text-only turn ends the run, so a wrapper that backgrounds the reviewer and then narrates progress exits 0 while its agent is killed mid-review, leaving no output. See "Attempt Outcome and Retries" for how such a run is detected and retried.

#### Review Underway PR Comment

When a review starts, GitHub PR Explorer posts a plain conversation comment to the PR announcing that a review is in progress, so anyone watching the PR knows work is underway before any results land.

- **Where**: `backend/services/review_started_service.py`, called from `begin_review()` in `review_service.py` after the Claude CLI subprocess spawns successfully and the review is registered in `active_reviews`. Because both `POST /api/reviews` and the auto follow-up watcher funnel through `begin_review()`, manual and auto-started reviews are both covered by this one hook.
- **What**: an issue comment (`POST repos/{owner}/{repo}/issues/{pr_number}/comments`) — deliberately *not* a formal PR review, which is reserved for the verdict posted by `verdict_service` once findings exist. The body names the reviewer agent and the start time, and its lead line varies for normal, follow-up, and auto-started reviews.
- **Failure handling**: the post is wrapped so that no exception escapes — a comment failure is logged and the review continues. Announcing a review must never be able to stop one.
- **Lifecycle**: the comment is posted once and left in place; it is not edited or deleted when the review completes. A PR that goes through several follow-up rounds therefore accumulates one such comment per round.
- **Config**: set `post_review_started_comment` to `false` in `config.json` to suppress the comment (default `true`).

No comment is posted when the review is rejected as a duplicate (409) or when the subprocess fails to spawn (500).

#### Split Review / Audit Triggers

Every PR card — on the **PR list**, the **Merge Queue**, and the **Swimlane board** (queue and swimlane cards both render through `QueueItem`) — shows **two independent controls side by side**, so a review and a PB↔ED audit can run on the **same** PR at the same time, each tracking its own running/failed state (the backend already executes them independently):

- **📋 Review ▾** — a pure review control (`ReviewButton` on the PR list, `QueueReviewButton` on queue/swimlane cards) that opens `ReviewerPickerMenu` with the three reviewer agents above (Default / Product Brief / Engineering Design). It dispatches to `POST /api/reviews` and carries no audit option.
- **🔎 Audit** (`AuditButton`, in `frontend/src/components/audits/`) — starts, cancels, and surfaces errors for the PB↔ED audit independently. It dispatches to `POST /api/audits` and routes to a separate audit path with its own JSON schema, DB table, history tab, and chip — see [PB↔ED Audit](#pbed-audit). The button shows `🔎 Audit` when idle, an `Auditing… Cancel` spinner while running, and `✗ Audit Error` (opening the audit error modal) when the audit failed.

`AuditButton` is shared across all three surfaces: it takes explicit `owner`/`repo`/`number`/`url` (plus optional `title`/`author`/`headRef`/`baseRef`) props, so the PR list passes them from a `PullRequest` and the queue/swimlane cards pass them from a `MergeQueueItem`. Because audit is always triggered by this dedicated button, `ReviewerPickerMenu` is purely review reviewers on every surface (no audit option).

#### Claude CLI Command

```bash
claude -p "Review PR #123 at https://github.com/owner/repo/pull/123. \
  Use the code-reviewer agent. \
  Write the review to /path/to/reviews/owner-repo-pr-123.md \
  AND write structured JSON to /path/to/reviews/owner-repo-pr-123.json" \
  --allowedTools "Bash(git*),Bash(gh*),Read,Glob,Grep,Write,Task" \
  --dangerously-skip-permissions
```

**Flags**:
- `-p`: Prompt with review instructions requesting both `.md` and `.json` output files
- `--allowedTools`: Grants read-only git/gh access + file tools
- `--dangerously-skip-permissions`: Bypass permission prompts for automated execution

#### Review States

| State | UI Indicator | Description |
|-------|--------------|-------------|
| `running` | Yellow spinner | Review in progress |
| `completed` | Green checkmark | Review finished successfully |
| `failed` | Red X mark | Review process failed |

#### Review Storage

- **Active Reviews**: In-memory dictionary (`active_reviews`) with process references
- **Database Storage**: Completed reviews saved to `reviews` table in SQLite; `content_json` is the primary storage column containing the structured JSON review
- **Markdown Generation**: Markdown content is generated on the fly from `content_json` via `json_to_markdown()` when needed (API responses, file export)
- **Review Files**: Written to `/Users/jvargas714/Documents/code-reviews/`
- **File Naming**: `{owner}-{repo}-pr-{number}.md` and `{owner}-{repo}-pr-{number}.json`

#### Score Tracking

Reviews store numerical scores extracted from structured JSON:

- **Automatic Extraction**: Score read directly from `content_json["score"]["overall"]`
- **Score Range**: 0-10 scale stored in database
- **Visual Display**: Color-coded badges on PR cards
- **Statistics**: Aggregate score data available via stats endpoint

#### Follow-up Reviews

The system supports creating follow-up reviews for previously reviewed PRs:

| Feature | Description |
|---------|-------------|
| **Context Inclusion** | Previous review content included in Claude prompt for context |
| **Parent Linking** | Follow-up reviews linked via `parent_review_id` foreign key |
| **Flag Tracking** | `is_followup` boolean distinguishes follow-ups from initial reviews |
| **Review Chain** | Multiple follow-ups can be chained for iterative review processes |

#### Follow-up Workflow

1. User clicks "Follow-up" button on a PR with existing review
2. Backend fetches most recent review content for that PR
3. Claude CLI prompt includes previous review as context
4. New review is created with `is_followup=true` and `parent_review_id` set
5. Review chain viewable in History panel

#### Error Handling

When a review fails:
- Exit code and stderr are captured
- Error details stored in review state
- Clicking the failed review button opens error modal
- Modal displays PR info, exit code, and error output
- Comprehensive logging in backend for debugging

#### Thread Safety

- `reviews_lock` (threading.Lock) protects `active_reviews` dictionary
- Process status checked via `poll()` method
- Safe concurrent access from multiple requests
- Database connections are thread-local for safety

### Inline Comments Posting

The Inline Comments feature allows users to post critical issues from code reviews directly as inline comments on GitHub PRs.

#### How It Works

1. After a review completes, the "Post Inline Comments" button appears on the PR card
2. User clicks the button to parse critical issues from the review content
3. Backend extracts file paths, line numbers, and issue descriptions
4. Comments are posted to GitHub via the `gh` CLI
5. The button disappears after comments are posted (tracked in database)

#### Critical Issues Parsing

The system extracts critical issues from review content using pattern matching:

```python
# Matches patterns like:
# - Location: path/to/file.rs:123-456
# - Problem: Description of the issue
# - Fix: Recommended solution

patterns = [
    r'Location:\s*`?([^`\n:]+):(\d+)(?:-(\d+))?`?',  # File path and line numbers
    r'Problem:\s*(.+?)(?=\n-|\n\n|\Z)',                # Issue description
    r'Fix:\s*(.+?)(?=\n-|\n\n|\Z)'                     # Recommended fix
]
```

#### UI Components

| Component | Location | Description |
|-----------|----------|-------------|
| Post Inline Comments Button | PR Card | Appears when review exists and comments not yet posted |
| Post Inline Comments Button | Merge Queue | Same functionality for queued PRs |
| Loading Spinner | Button | Shows while posting in progress |

#### Button Visibility Logic

The button appears when all conditions are met:
- PR has an existing review (`hasReview: true`)
- Inline comments have not been posted (`inlineCommentsPosted: false`)
- Review ID is available (`reviewId` is not null)

#### Cache Refresh

When a review completes, the PR review cache is automatically invalidated and refreshed to ensure the button appears immediately without requiring a page reload.

### Review Verdict

The Review Verdict feature allows users to submit a formal GitHub PR review verdict (Approve, Request Changes, or Comment) directly from the merge queue, composing the review body from custom text and/or sections extracted from a completed code review.

#### How It Works

1. After a review completes, the "Verdict" button appears on the merge queue card
2. User clicks the button to open a modal
3. User selects the review action (Approve, Request Changes, or Comment)
4. User writes optional custom text and toggles review sections to include
5. The composed body is posted as a formal PR review to GitHub via the API

#### UI Components

| Component | Location | Description |
|-----------|----------|-------------|
| Verdict Button | Merge Queue Card | Appears when PR has a completed review |
| VerdictModal | Overlay | Modal with event selector, textarea, section toggles, and submit |
| Verdict Source toggle | VerdictModal | Review / Audit selector, shown only when the PR has both a completed review and a completed audit (see [Verdict Source Toggle](#verdict-source-toggle) below) |
| Event Selector | VerdictModal | Three side-by-side buttons for Approve/Request Changes/Comment |
| Section Toggles | VerdictModal | Checkbox per review section. Clicking **Edit** opens the section in `SectionEditModal` rather than expanding inline. |
| SectionEditModal | Floating overlay | Standalone draggable/resizable modal for editing a single section's body (or per-issue Problem/Fix fields when the section is marked Inline). One section open at a time. |
| Preview Panel | Floating overlay | Draggable/resizable preview of the composed body. Header has **Edit** / **Done** / **Recompose** buttons that flip the body between rendered markdown and a freeform textarea bound to a manual override. |

#### Verdict Button Visibility

The button appears when:
- PR has an existing review (`hasReview: true`)
- Review ID is available (`reviewId` is not null)

#### Review Sections

The modal parses the completed review content to extract named sections:

| Section | Description |
|---------|-------------|
| Critical Issues | Critical bugs or security issues |
| Major Concerns | Significant design or logic concerns |
| Minor Issues | Style, naming, or minor code issues |
| Recommendations | Suggested improvements |

Each section can be individually toggled on/off and previewed before submission. Clicking **Edit** on a row opens `SectionEditModal` — a floating, draggable, resizable editor for that section's content (or per-issue Problem/Fix fields when the section is marked Inline).

#### Composed Body Format

The final review body is assembled from (joined by `\n\n---\n\n`):
1. **Inline issues summary table** (prepended automatically when one or more inline comments will be posted) — a GFM markdown table with `Severity | Issue | Location` columns, sorted critical → major → minor with stable ordering within each severity. Heading: `**Inline issues posted (N)**`. Omitted entirely when no inline comments are selected.
2. Custom text (if provided)
3. Enabled review sections (each preceded by a bold heading)

The summary table gives the GitHub review entry a quick index into the diff comments so an Approve/Request-Changes/Comment verdict is not effectively empty when all content has been posted inline.

#### Editable Preview (Manual Override)

The preview panel can switch into edit mode, allowing the user to hand-edit the assembled markdown body in one large freeform textarea instead of bouncing between the per-section editors:

| Action | Effect |
|--------|--------|
| **Edit** (preview header) | Captures the current `composeBody()` output into `manualBodyOverride` and switches the preview into a textarea bound to that override. |
| **Done** | Returns the preview to rendered-markdown view. The override is preserved and used on submit. |
| **Recompose** | Discards the override (`manualBodyOverride = null`) and rebuilds the body from custom text + enabled sections. Visible only while an override is active. |
| **manually edited** badge | Shown in the preview header whenever `manualBodyOverride !== null` so it's visible at a glance that section toggles will not modify the body until Recompose is clicked. |

When an override is active, the final submitted body uses the override verbatim. Inline comments and the inline summary table are independent of the override and continue to come from the section toggles.

#### Verdict Source Toggle

When a PR has **both** a completed review and a completed audit, the verdict modal shows a **Verdict Source** toggle (Review / Audit) so a single modal can compose its body from either source:

- **Default source** — the modal opens on the source it was launched from: the merge queue opens it on **Review**, while the `AuditViewer` opens it on **Audit**. It then discovers the *other* source's latest id via the existing `checkPRReviewed` / `checkPRAudited` endpoints. The toggle renders only when **both** ids resolve; if discovery returns nothing (or fails — discovery is best-effort), the modal stays single-source, unchanged from before.
- **Switching source** — recomposes the verdict body from the newly selected source. Source-derived selections are reset (parsed sections, enabled/inline toggles, audit blocks, structured/edited issue content, and any manual body override), while the user's chosen review action (Approve / Request Changes / Comment) and custom text are preserved.
- **Submission** — exactly one verdict is posted per submission, from the selected source. `review_id` (used for review section-count tracking) is sent **only** when the Review source is selected; audit submissions never send it. To post the other source as its own GitHub verdict, switch the toggle (or reopen the modal) and submit again.

### Auto Verdicts

Auto verdicts remove the manual click-path for the mechanical case: a PR card is **armed** with a 🤖 toggle, and when a review for that PR completes, the backend acts on it without a human click. An armed card is in one of two **modes**:

- **Verdict mode** (the default) — the review's issue counts are compared against configurable thresholds and the verdict (`REQUEST_CHANGES`, `APPROVE`, or nothing) is posted to GitHub.
- **Comment mode** — thresholds are ignored and every completed review's findings are posted as a `COMMENT` review, clean reviews included. This is the self-review path: GitHub rejects both `APPROVE` and `REQUEST_CHANGES` on your own PR (422), so comment mode is how an armed self-authored PR reliably gets its report onto GitHub — and it doubles as an audit trail that the review happened.

The comment body is composed the same way a manually posted verdict is (summary, issue sections, recommendations — no score or metadata). Every auto-generated verdict is badged in the UI so it can be audited after the fact.

#### How It Works

1. The user sets thresholds once in the **Auto Verdict Criteria** section of the Automation tab (🤖 button in the header jumps there, or "Edit global criteria…" from any card's auto popover).
2. On a queue or swimlane card, the **🤖 Auto** button arms that PR, picks the mode (verdict / comment), and picks which reviewer agent its auto review uses. Optionally, the popover's "Override for this PR…" sets per-PR criteria (see below).
3. A review completes — started from anywhere, by any surface.
4. `check_review_status` saves the review, then spawns a thread running `maybe_post_auto_verdict` (`backend/services/auto_verdict_service.py`).
5. The evaluator resolves the effective criteria (global config + the card's override, if any). In verdict mode it counts issues per severity, compares against the criteria, and posts `REQUEST_CHANGES`, `APPROVE`, `COMMENT`, or nothing. In comment mode it always posts `COMMENT`.
6. The decision is recorded in the `auto_verdicts` table and surfaces on the card as a badge plus a verdict chip on the triggering review's rev-log row.

#### Criteria

Stored as the `auto_verdict_config` key in `user_settings`. Defaults live in exactly one place — `DEFAULT_CRITERIA` in `backend/services/auto_verdict_config.py` — because both the evaluator and the API read them.

| Field | Default | Meaning |
|-------|---------|---------|
| `enabled` | `false` | Master switch. While off, armed cards are never evaluated and nothing is posted. |
| `maxCritical` | `0` | Critical issues tolerated. `0` means one critical triggers changes-requested. |
| `maxMajor` | `0` | Major issues tolerated. |
| `maxMinor` | `99` | Minor issues tolerated — effectively unlimited, so minors alone never block. |
| `allowAutoApprove` | `false` | When off, a passing review posts nothing; only changes-requested is automated. |
| `autoFollowupReview` | `false` | When on, an armed PR that gets new commits after a review automatically starts a follow-up review. Independent of `enabled` — it starts reviews but never posts to GitHub itself. |

Thresholds are **inclusive upper bounds**: `maxMajor: 1` allows one major and trips on two. Both switches default off so installing the feature cannot post anything until deliberately enabled.

#### Per-PR Criteria Overrides

The global config is the default; any queued PR can carry its own **criteria override** — a complete snapshot of the five overridable fields (`maxCritical`, `maxMajor`, `maxMinor`, `allowAutoApprove`, `autoFollowupReview`) stored as JSON in `merge_queue.auto_verdict_criteria`. The rules:

- **Whole-config, not per-field.** A PR either follows the global config or has its own full snapshot; there is no partial inheritance. Later changes to the global defaults do not affect overridden PRs.
- **The master `enabled` switch is never overridable.** `OVERRIDE_KEYS` in `auto_verdict_config.py` deliberately excludes it, `validate_override` strips it, and `apply_override` never copies it — so "the master switch is off" always means nothing posts, board-wide.
- **Merging is one pure function.** `apply_override(criteria, queue_item)` returns the effective criteria; the evaluator and the follow-up watcher both go through it. A malformed stored override is logged and ignored (global config applies).
- **History stays honest.** `auto_verdicts.criteria_json` snapshots the *effective* criteria at decision time, so an overridden decision records the override that drove it.
- The follow-up watcher (`scan_and_start_followups`) resolves `autoFollowupReview` per card, so an override can switch auto follow-ups on or off for one PR independently of the global setting.

#### Decision Table

Verdict mode:

| Condition | Event posted | Recorded outcome |
|-----------|--------------|------------------|
| Any severity over its limit | `REQUEST_CHANGES` | `posted` |
| Within all limits, `allowAutoApprove` on, PR authored by someone else | `APPROVE` | `posted` |
| Within all limits, `allowAutoApprove` on, PR self-authored | `COMMENT` | `posted` |
| Within all limits, `allowAutoApprove` off | *(nothing)* | `suppressed` |
| Review failed, content unusable, or PR not `OPEN` | *(nothing)* | `skipped` |
| `post_verdict` returned non-200 or raised | *(attempted)* | `error` |

Comment mode:

| Condition | Event posted | Recorded outcome |
|-----------|--------------|------------------|
| Review completed (any issue counts, clean included) | `COMMENT` | `posted` |
| Review failed, content unusable, or PR not `OPEN` | *(nothing)* | `skipped` |
| `post_verdict` returned non-200 or raised | *(attempted)* | `error` |

Comment mode never suppresses: thresholds and `allowAutoApprove` are irrelevant, and the reason records the issue tallies (`comment mode — review findings posted as comment (N critical, …)`). Both modes are gated by the global master `enabled` switch — while it is off, armed cards in either mode post nothing and per-PR overrides are inert.

GitHub rejects `APPROVE` on your own PR with a 422, so in verdict mode a self-authored passing PR falls back to `COMMENT` and the reason records why. A `suppressed` outcome is the "changes-requested only" mode: the card shows *passed — approve manually* so every approval stays a human action.

#### Verdict Body

The body is composed by `compose_report_body(content_json)` to match what the manual verdict modal posts by default: the summary, each severity section that has issues (with Location/Problem/Fix per issue), and recommendations, joined with horizontal rules. The report title, metadata block, positive highlights, and the 0-10 score are deliberately excluded so auto-posted verdicts are indistinguishable in format from manually posted ones. It is truncated at 60 000 characters (GitHub's cap is 65 536) with a trailing notice. No inline comments are posted, and no auto-generated header is injected into the body; the auto-generated marker lives in the UI badge instead.

Note there is no per-issue resolved/dismissed state anywhere in the system, so "remaining issues" necessarily means *the issues in the latest review*. For a follow-up review that is already the remaining set.

#### Idempotency

`auto_verdicts.review_id` is `UNIQUE`, and `AutoVerdictsDB.claim()` inserts the row in the `pending` state **before** GitHub is contacted. Whichever caller wins the claim posts; every other caller returns immediately. This is what makes a double post structurally impossible when the watcher thread and a frontend poll notice the same completion. `claim()` distinguishes a lost race from a genuine constraint failure (such as the foreign key to `reviews(id)`) by re-querying, so an FK error is never silently reported as a duplicate.

#### Completion Watcher

`check_review_status` only runs when the frontend polls `GET /api/reviews`, so with no browser tab open a finished review was previously neither persisted nor verdicted until someone reopened the app. `auto_verdict_watcher_loop` (`backend/services/auto_verdict_watcher.py`) polls `check_review_status` for every key in `active_reviews` every 10 seconds. It starts as a daemon thread from `app.py` alongside the existing startup cache-refresh threads, guarded on `WERKZEUG_RUN_MAIN` so Flask's reloader cannot double-start it in debug mode. This also fixes the pre-existing persistence gap for reviews that finish after the tab closes.

#### Auto Follow-Up Reviews

With `autoFollowupReview` on (resolved per card: the card's criteria override wins over the global flag when one is set), the loop closes completely for armed cards: review → auto verdict → author pushes fixes → follow-up review → auto verdict again. `auto_review_watcher_loop` (`backend/services/auto_review_watcher.py`) is a second daemon thread (60-second interval, same `WERKZEUG_RUN_MAIN` guard) whose `scan_and_start_followups` pass walks every `merge_queue` row with `auto_verdict_enabled` and starts a follow-up review when **all** of the following hold:

1. No review is currently running for the PR (`active_reviews` check, before any gh call).
2. The PR has at least one saved review — auto-started reviews are always follow-ups; a first review stays a human action.
3. The latest review recorded a `head_commit_sha`. An unknown baseline is skipped rather than guessed, because triggering without one could re-review a PR with no new commits.
4. One `fetch_pr_state_and_sha` call reports the PR is `OPEN` and its head SHA differs from the recorded one — the exact signal behind the "new commits" badge.
5. That head SHA has not already been attempted (in-memory `_attempted_shas` map, so a failed spawn is not retried every cycle; a restart may retry once).

The review is started through `review_service.begin_review` — the same function `POST /api/reviews` uses — with `is_followup=True` and the card's armed reviewer agent (`auto_verdict_reviewer`), so previous-review lookup, prompt composition, and `active_reviews` registration are identical to a manually started follow-up. Loop safety needs no persistent state beyond the reviews table: a finished review (completed *or* failed) records the then-current head SHA, which clears the trigger condition itself.

Auto-started reviews are marked for auditability: the watcher passes `auto_started=True` through `begin_review`, which carries it through `active_reviews` into the `reviews.auto_started` column (tracked `ALTER TABLE` migration). The flag surfaces as a `🤖 auto` chip on the review's rev-log entry, a `🤖 Auto-started` badge in the Review History panel, and an `auto_started` field on `GET /api/reviews` so an in-flight auto review is identifiable while still running.

The setting is deliberately independent of the master `enabled` switch: `enabled` gates posting verdicts to GitHub, while `autoFollowupReview` only starts local reviews and posts nothing. Once the follow-up completes, the normal auto-verdict path evaluates it (subject to `enabled` as usual).

#### Persistence

```sql
auto_verdicts (
  id, repo, pr_number, review_id UNIQUE, event, outcome,
  reason, critical_count, major_count, minor_count,
  criteria_json, head_commit_sha, error_detail, created_at
)
```

Plus four columns on `merge_queue` (added via tracked `ALTER TABLE` migrations in `base.py`), which is the single record behind both the queue panel and the swimlane board:

```sql
auto_verdict_enabled  INTEGER NOT NULL DEFAULT 0
auto_verdict_reviewer TEXT      -- 'default' | 'pb' | 'ed'
auto_verdict_mode     TEXT      -- 'verdict' | 'comment'; NULL reads as 'verdict'
auto_verdict_criteria TEXT      -- per-PR criteria override (JSON); NULL = use global
```

`criteria_json` snapshots the thresholds at decision time, so changing the criteria later does not rewrite the history of why a past verdict fired.

#### UI Components

| Component | Location | Description |
|-----------|----------|-------------|
| `AutoVerdictToggle` | Queue / swimlane card action row | `🤖 Auto` (or `💬 Auto` in comment mode) button, `--active` when armed. Opens a popover with arm/disarm, a mode radio group (verdict / comment), a reviewer-agent radio group, the effective criteria (with an `overridden` chip when a per-PR override is set), an "Override for this PR…" link, and an "Edit global criteria…" link |
| `AutoVerdictConfigModal` | Overlay | Criteria editor opened from a card's 🤖 menu: "Edit global criteria…" edits the global config; with the `perPR` prop it edits that PR's criteria override (seeded from the effective config, master toggle hidden, "Use defaults" clears it). The header path moved to the Automation tab (`AutoVerdictCriteriaSection`); modal and section render the shared `AutoVerdictCriteriaForm` |
| `AutoVerdictBadge` | Card badge row | Outcome badge with a tooltip carrying the reason, tallies, and local timestamp |
| 🤖 header button | Header | Opens the criteria panel; shows an `on` chip while the master switch is enabled |
| `RevLogBadge` | Card rev-log popover | Shows the verdict as a chip on the triggering review's row (reason in the tooltip); orphaned verdicts render as standalone `AUTO`-tagged entries whose click opens the derived-from review |

Badge variants: `🤖 auto ✗ changes requested` (error), `🤖 auto ✓ approved` (success), `🤖 auto 💬 comment` (info), `🤖 passed — approve manually` (warning), `🤖 auto verdict failed` (error), `🤖 auto skipped` (neutral).

#### Optimistic arming

Arming or disarming is reflected in the UI on click, not on the next fetch.
`AutoVerdictToggle` renders from a locally-held `pending` state layered over the
card's server value, clearing it once a refreshed card carries the same value and
rolling it back if the `PUT` fails. It also patches the swimlane board's own copy
via `useSwimlaneStore.applyAutoVerdictLocal` so the header's auto/manual counts
and auto-mode filter move in step. The trigger button deliberately does *not*
disable itself while the request is in flight — the previous behaviour left it
disabled and unchanged for the length of a full board refetch (`gh pr view` per
queued PR), which read as the toggle being broken.

An armed card's **Review** button skips the reviewer picker on its primary click and starts the armed agent directly (labelled `🤖 Review`, or `💬 Review` in comment mode); the adjacent `▾` still opens the picker to override for one run without changing the stored arming. This works identically in both modes.

Arming state (`mode`, `criteriaOverride`) rides the card payload's `autoVerdict` object (shaped by `format_auto_verdict_state` in `queue_enrichment.py`), so both the queue panel and the swimlane board see it. Comment-armed cards count as "auto" in the header's auto/manual split and the auto-mode filter, same as verdict-armed ones — the existing Auto Verdict badge chips cover both modes.

The swimlane badge filter gains an **Auto Verdict** dimension with chips *🤖 Armed*, *🤖 Verdict Posted*, and *🤖 Needs Manual Approval*, mirroring the rendered badges one-for-one as `cardMatchesBadge` requires.

---

### Review Event Log

An append-only operational record of every review the app starts, every attempt
it makes, and why any attempt failed — surfaced in the **📜 Review Logs** tab.

This is deliberately distinct from **Review History**, which browses *finished
reviews and their findings*. The event log answers a different class of
question: did a review start at all, how many attempts did it take, what killed
the ones that died, and is the retry loop actually saving runs. Before it
existed, a review that failed silently left no trace beyond the server's stdout,
which is not persisted anywhere.

#### Why a table rather than a log file

The events live in SQLite (`review_events`) rather than a JSON/JSONL file on
disk. Both were considered: a file is greppable without the app and survives
database problems, but a table reuses the existing schema init, migrations,
connection pooling, and filter/paginate helpers, so the same feature costs a
fraction of the code and needs no rotation logic. Retention is a scheduled
delete instead (see `review_log_retention_days`).

#### Run grouping

Every event carries a `run_id` — a UUID minted in `begin_review()`, stored on
the `active_reviews` entry, and stamped onto each event for that review. All
attempts of one review therefore share a `run_id`, so the UI groups a run's
attempts with a `GROUP BY` rather than inferring the grouping from timestamps.
This is what makes the per-attempt event model legible: a review that succeeded
on its third try reads as one collapsible group, not three unrelated rows.

#### Event vocabulary

Both vocabularies are closed sets. Recorders never invent a value.

| `event` | When | Key fields |
|---------|------|-----------|
| `started` | An attempt's subprocess spawned | `attempt`, `pid` |
| `completed` | Attempt produced output and the review was saved | `review_id`, `score` |
| `failed` | Attempt failed | `reason`, `exit_code`, `detail` |
| `retry_scheduled` | Backoff armed before the next attempt | `detail` (delay) |
| `gave_up` | Attempt limit reached; review recorded as failed | `attempt`, `max_attempts` |
| `cancelled` | User cancelled the review | — |
| `verdict_posted` | A verdict for this run's review reached GitHub | `review_id`, `auto_started`, `detail` |
| `verdict_not_posted` | An auto verdict was evaluated but nothing was posted | `review_id`, `reason`, `detail` |

| `reason` | Meaning |
|----------|---------|
| `no_output` | Exited 0 without writing either output file (see "Attempt Outcome and Retries") |
| `nonzero_exit` | CLI exited non-zero; `detail` carries the stderr tail |
| `spawn_failed` | The subprocess could not be started at all |
| `attempts_exhausted` | Set on the `gave_up` event |
| `cancelled` | User-initiated termination |
| `auto_suppressed` | Criteria were met but auto-approve is off, so nothing was posted |
| `auto_skipped` | The review was not eligible (PR closed, no usable content, non-completed status) |
| `post_failed` | A verdict was chosen but GitHub rejected the post |

#### Verdict events

Whether a verdict reached GitHub is a *separate axis* from how the review run
itself ended: a run can complete cleanly and still post nothing. The two
`verdict_*` events record that axis.

Both attach to the run that produced the review, resolved by
`ReviewEventsDB.get_run_id_for_review(review_id)` — the `completed` event carries
`review_id`, which is what ties a much-later verdict back to its run. **A verdict
with no such run is not recorded**: reviews written before the event log existed,
and verdicts posted with no review attached (the audit route), have no run to
group under, and the Review Logs tab is grouped by run.

`detail` leads with the GitHub review event (`APPROVE` / `REQUEST_CHANGES` /
`COMMENT`), followed by the free-text explanation after an em dash separator —
e.g. `APPROVE — 0 critical, 1 major`. `auto_started` distinguishes an auto
verdict from a hand-posted one.

#### Recording

`backend/services/review_event_log.py` exposes one named recorder per event
(`record_started`, `record_completed`, `record_failed`, `record_retry_scheduled`,
`record_gave_up`, `record_cancelled`, `record_verdict_posted`,
`record_verdict_not_posted`). Call sites pass domain values, never dicts, so the
vocabulary above is enforced in one place.

**Every recorder swallows its own exceptions.** This mirrors
`post_review_started_comment()`: observing a review must never be able to break
the review it observes. A failed write is logged at WARNING and the review
continues.

Call sites:

| Site | Event |
|------|-------|
| `begin_review()` | `started` (attempt 1) |
| `check_review_status()` | `completed`, `failed`, `gave_up` |
| `_schedule_review_retry()` | `retry_scheduled` |
| `_respawn_review()` | `started` (attempt N) |
| `DELETE /api/reviews/<owner>/<repo>/<pr>` | `cancelled` |
| `maybe_post_auto_verdict()` (its inner `record()`) | `verdict_posted`, `verdict_not_posted` |
| `POST /api/repos/<owner>/<repo>/prs/<pr>/verdict` | `verdict_posted` (manual, only when the request carries a `review_id`) |

#### UI

`components/reviewLogs/ReviewLogsView.tsx` renders a summary strip (successes,
failures by reason, and how many runs a retry rescued) above a table grouped by
`run_id`, each group collapsible to its attempt rows.

Each run row carries two independent outcome columns:

| Column | Sourced from | Shows |
|--------|--------------|-------|
| **Outcome** | The run's latest *lifecycle* event | How the review run itself ended (`completed`, `gave up`, …) |
| **Posted** | The run's latest *verdict* event | `✓ APPROVE` / `✗ suppressed by criteria` / `—` when the run never reached a posting decision |

`groupIntoRuns` holds the `verdict_*` events out of the lifecycle list when
picking a run's `last` event, so a verdict landing after the review completes
never displaces `completed` in the Outcome column. A 🤖 marker on a posted
verdict distinguishes an auto post from a hand-posted one. The view defaults to the
selected repository with an **All repos** toggle, since the tab only renders once
a repo is chosen but the log is useful across repos.

##### Day grouping

Runs are bucketed into calendar days by `groupIntoDays`, with a separator row
heading each day: the date plus that day's run count, how those runs ended, and
how many posted a verdict — answering "how many reviews ran today and what
happened to them" without expanding anything. Zero-valued counts are omitted, so
a clean day reads `7 runs · 7 completed · 5 posted`.

Three details carry the correctness of that header:

- **Bucketed by local day, not UTC.** `localDayKey` builds its key from the
  `Date`'s local getters rather than `toISOString().slice(0, 10)`, which buckets
  by UTC and would file a late-evening run under the following day for any
  viewer west of Greenwich.
- **Ordered by when a run started**, not by its latest event. That is what
  "reviews done that day" means, and it is what keeps each day's block
  contiguous — ordering by latest event would let a run started yesterday and
  retried today sit in today's slot under a yesterday header, heading the same
  date twice. Runs are re-sorted by `first.created_at` before bucketing.
- **A truncated page is disclosed.** The view requests 1000 events (the server
  max); when the log holds more, the cut lands mid-way through the oldest day
  loaded, whose counts would then describe what loaded rather than what
  happened. That day's header is marked `≥N runs · partial day`. Only the oldest
  loaded day can be affected, and only when `events.length < total`.

Counts derive from the same `last` / `verdict` fields the Outcome and Posted
columns render, so a day header can never disagree with the rows beneath it.

##### Day pagination

The table shows **one day per page**. A navigator bar between the stats strip
and the table carries ◀ / ▶ arrows, the selected day's label (`Mon, Aug 25,
2026 · 12 runs`), and a 📅 button that opens a native `<input type="date">`
picker (via `showPicker()` on a visually hidden input; `display: none` would
break the picker's anchoring in some browsers, so it is kept in the layout at
`opacity: 0`).

Selection is a `selectedDayKey` (`YYYY-MM-DD`, `null` = newest day with runs).
It snaps back to newest when the repo scope or event filter changes, since a
new scope has a different day list. `navTargets()` resolves each arrow's
target from the newest-first key list — keys compare chronologically as plain
strings — and **skips days with no runs**: ▶ is the nearest newer day with
data, ◀ the nearest older one.

The calendar can land on a day with no runs (its `min`/`max` bound only the
loaded range, not its gaps). That renders an empty state naming the date, with
the navigator still live — `navTargets` accepts a key absent from the list, so
the arrows step out of an empty day to its nearest real neighbours.

When the window is truncated, ◀ on the oldest loaded day fetches the next page
via the existing `offset` param and jumps to the first day it exposes, so older
days stay reachable instead of silently missing. Offset paging over a
newest-first list overlaps when new events arrive between fetches (everything
shifts down), so the merge dedupes by event id.

The stats strip stays global — the day header row already carries the selected
day's counts. The footer reports both scopes: runs shown for the day, and runs
loaded across total events.

`formatDayLabel` parses the day key field-by-field: `new Date('2026-08-25')`
is UTC midnight, which `toLocaleDateString` would render as the *previous* day
west of Greenwich.

##### Run hover panel

Hovering a run row shows a panel with the review's issue tally and the run's
timing:

```
0 critical · 5 major · 4 minor
completed · 1 attempt · took 14m 26s
```

A run that produced no review has no tally to show, so it reports how it ended
instead — the row you most want to inspect on hover:

```
gave up · 3 attempts · took 1m 17s
all attempts used
```

`runTooltip()` builds the string and hangs it on the row's `data-tooltip`. No
new tooltip machinery was needed: the app's global `TooltipProvider` already
portals any `data-tooltip` out of its overflow container, and
`.mx-tooltip-portal` is styled `white-space: pre-line`, so newlines render as
line breaks. Elapsed time spans the run's *lifecycle* events only — measuring to
the latest event would let a verdict posted an hour later inflate "took".

**Issue counts are tallied at query time, not stored.** `GET /api/review-logs`
collects the `review_id`s on the page, batch-loads those reviews in one query
(chunked at 500 to stay under SQLite's bound-variable ceiling), and tallies each
`content_json` through `review_schema.count_issues`. Measured at ~21ms for 223
reviews, which buys coverage of every run ever logged with no new columns, no
migration and no backfill.

Two related columns are deliberately *not* the source. `reviews.critical_found_count`
and friends are written only when inline comments are posted — populated for 2 of
the 223 reviews in the log — and they count issues *posted to GitHub*, which is a
different quantity from issues the review found.

`count_issues` lives in `review_schema` rather than `auto_verdict_service` so this
read-only path can tally a review without importing `verdict_service` and the `gh`
subprocess layer.

A review whose row is gone or whose `content_json` will not parse yields
`issue_counts: null`, rendered as "issue counts unavailable" — never as a clean
review. Every event carries the key even when nothing can be tallied, so the
client sees a consistent `null` rather than a sometimes-absent field.

**Everything displayed is in the viewer's local timezone; everything stored is
UTC.** The recorders write `datetime.now(timezone.utc).isoformat()`, so every
`created_at` carries an explicit `+00:00` and parses to the correct instant —
which is what lets the client convert to local without ambiguity. (A timestamp
written without an offset would be read as *local* by `new Date()` and land in
the wrong day for any non-UTC viewer; `review_events.created_at` has no
`DEFAULT CURRENT_TIMESTAMP` precisely so this stays true.)

Because a date header establishes the day, the **Started** and **Latest**
columns — and the timestamps on the expanded per-event rows — show local clock
time (`formatClockTime`) rather than relative time or a raw ISO string, with the
full local timestamp on hover via `title`.

The tab is repo-independent in every other respect: it reads only
`/api/review-logs`, so it works even when PR fetching is failing — which is
precisely when it is most needed.

### PR List Sync

**Purpose**: Serve the PR list tab from a locally synced SQLite table so navigation
and filtering are instant and GitHub 5xx flakiness (notably 504s on heavy
`gh pr list --json` queries) never reaches the UI.

**Motivation**: The live PR list fetch is one `gh pr list --limit 100` requesting
~25 JSON fields per PR — including `reviews` (full review history) and
`statusCheckRollup` (every CI check). On busy repos GitHub times that query out
(504) deterministically, so `run_gh_command`'s retry/backoff cannot save it. The
fix is to never need a big query on the request path: a background worker keeps a
local copy fresh using only small, 504-resistant queries, and the route serves
from SQLite.

**Full design spec**: `docs/specs/2026-08-28-pr-sync-db-design.md`.

**Storage** (`backend/database/synced_prs.py`, schema in `base.py`):

- `synced_repos` — one row per registered repo (`repo` is the full `"owner/name"`
  string, matching the DB-wide convention): `last_visited_at`, `last_synced_at`,
  `backfill_done`, `backfill_error`. A repo registers itself the first time its
  PR list is requested.
- `synced_prs` — one row per PR, PK `(repo, pr_number)`: scalar columns for cheap
  SQL narrowing (`state`, `is_draft`, `author`, created/updated/closed/merged
  timestamps), the **full PR JSON blob** (every field the live path fetches — no
  data is dropped), and `fetched_at`. `reviewStatus` / `ciStatus` /
  `currentReviewers` are never stored; they are computed at serve time by the same
  `pr_service` helpers as the live path.

**Sync worker** (`backend/services/pr_sync_worker.py`, daemon thread started from
`app.py` behind the `pr_sync.enabled` flag and the WERKZEUG reloader guard):

- **Backfill** (first visit): fetch PR *numbers only* (open, then
  `is:closed updated:>=<180-day cutoff>`), then hydrate each number with one
  `gh pr view` (full field set) in a small thread pool — open PRs first so the
  main view fills within seconds. Every request is single-PR-sized; a single PR's
  failure is logged and skipped; a failed backfill records `backfill_error` and
  retries next cycle (hydration is idempotent upserts).
- **Incremental** (each cycle, default 120s): numbers-only query for PRs
  `updated:>=` the last sync minus a 10-minute slack, re-hydrate just those
  (state transitions are picked up naturally), prune CLOSED/MERGED rows older
  than the window, stamp `last_synced_at`.
- Eligible repos: registered minus `exclude_repos`, most-recently-visited first,
  capped at `max_synced_repos`. Each repo's cycle is exception-isolated.

**Route dispatch** (`GET /api/repos/<owner>/<repo>/prs`, three-way):

1. **DB path** — repo backfilled and no GitHub-only filter active: SQL narrows by
   state, `backend/services/pr_local_filter.py` applies the remaining filters
   against the stored JSON with gh-qualifier semantics (labels ANDed, inclusive
   date bounds, `milestone=none`, exclusions, title/body substring search), local
   `created`/`updated` sort, then the shared post-filter block
   (draft/review/CI status) and `limit`.
2. **Hybrid path** — DB ready but a GitHub-only filter is active (`mentions`,
   `commenter`, `involves`, `reactions`, `interactions`, `comments`, `linked`,
   `team-review-requested`, search-in-comments, or a comments/reactions/
   interactions sort): run the normal `PRFilterBuilder` query with
   `--json number` only (tiny, reliable), then serve the matching rows from the
   DB **preserving GitHub's order**; numbers outside the sync window are hydrated
   on the spot.
3. **Live path** — repo unregistered, excluded, or backfill still running:
   today's full live query, unchanged. If a live fetch mid-backfill hits a
   transient 5xx and partial local rows exist, they are served instead of a 503.

The response gains metadata: each PR carries `fetchedAt`, and the top level adds
`"sync": {"status": "ready"|"backfilling"|"live", "lastSyncedAt": ...}`.

**Per-card refresh**: `POST /api/repos/<owner>/<repo>/prs/<n>/refresh` live-fetches
one PR with the full field set, upserts it into the store, and returns the fresh
processed row; a 404 deletes the stale row.

**Frontend**: each PR card shows a muted "⟳ <relative time>" freshness stamp
(hover for the absolute timestamp) and a 🔄 button that refreshes just that PR in
place. The list header shows "synced Xs ago" when serving from local data; while
a repo is backfilling, an info banner appears and the list polls every 5s so it
flips to local data without a manual refresh.

**Configuration** (`pr_sync` block, all defaults internal — the block is optional):
`enabled` (true; false is a clean kill switch back to live fetching),
`poll_interval_seconds` (120), `history_days` (180), `max_synced_repos` (10,
least-recently-visited repos beyond the cap fall back to the live path),
`exclude_repos` ([]).

### Automation (Full Auto Review Pipeline)

**Purpose**: A master **Automation tab** (sixth main tab, 🤖 in the header jumps to
it) consolidating all auto-mode configuration, plus a full-automation pipeline:
newly arriving PRs are detected by the PR sync worker, routed to a reviewer by
configurable file-pattern rules, placed in a permanent protected **Auto** swimlane,
and reviewed automatically — with per-rule auto-verdict/auto-comment behavior.
Nothing is hardcoded (reviewers, patterns, repos): the tool stays generic for other
repos and reviewer sets.

**Reviewer registry** (`reviewers` table, `backend/database/reviewers.py`):
each row maps a key (slug) to a display label, a Claude agent name, and optional
prompt context prepended to the review prompt. Seeded idempotently with the three
builtins previously hardcoded in `review_service.py`:
`default` → elite-code-reviewer, `pb` → product-brief-reviewer, `ed` → ed-reviewer
(the old `pb_context` strings became their `prompt_context`). Builtins cannot be
deleted or repointed to another agent; label/context stay editable. Dispatch
resolves the agent via `_resolve_reviewer()` (unknown key → warn + fall back to
`default`); `valid_reviewer_types()` replaces the old hardcoded tuple in route
validation, and every frontend picker (`ReviewerPickerMenu`, `AutoVerdictToggle`)
maps over `useAutomationStore.reviewers` instead of local constants.

**Automation config** (`user_settings['automation_config']`,
`backend/services/automation_config.py`, same pattern as `auto_verdict_config.py`):

| Key | Default | Meaning |
|-----|---------|---------|
| `scope` | `"off"` | `off` \| `authors` (only listed authors) \| `all` new PRs |
| `authors` | `[]` | GitHub logins, used when scope is `authors` |
| `repoAllowlist` | `[]` | `owner/repo` list; empty = nothing processed |
| `maxConcurrentAutoReviews` | `2` | cap on running auto-started reviews |
| `requireCiPass` | `true` | CI must be completed and passing before dispatch |
| `maxBehindBase` | `10` | max commits the PR branch may be behind its base head |
| `dispatchTimeoutHours` | `24` | give up (skip) after waiting this long for conditions |
| `ignorePatterns` | `[]` | globs stripped before classification (index files) |
| `defaultRule` | default reviewer, verdict off | applies when no rule matches |
| `rules` | `[]` | ordered `{name, patterns[], reviewerKey, autoVerdict, autoVerdictMode}` |

All defaults are off/empty: installing the feature dispatches nothing until the
operator sets a scope AND allowlists repos. `validate_config` rejects unknown
reviewer keys, bad scopes/modes, empty rule names/patterns, concurrency < 1.

**Seeding** (`scripts/seed_automation_config.py`): installs a starter ruleset
from `scripts/automation_seed.json` — the internal Scala convention (PB/ED
rules, index-file ignores, elite default) — via the validated `save_config`
path. Refuses to touch an existing config unless `--force` (which replaces the
whole blob); the shipped seed keeps `scope: off` and an empty allowlist, so
seeding never starts dispatching. Other installations copy and edit the JSON.

**Detection** (`pr_sync_worker.incremental_sync_repo`): before hydration the
worker computes `new_numbers = fetched − known rows`; after hydration
`_record_automation_candidates` filters them (scope on, repo allowlisted, state
OPEN, author in scope) and inserts `pending` rows into
`automation_dispatches`. `UNIQUE(repo, pr_number)` makes the row a restart-proof
idempotence guard: a PR is auto-dispatched at most once, ever. Backfill never
calls the hook, so enabling automation cannot sweep existing PRs — only PRs first
seen after enabling are picked up. Drafts ARE recorded at detection: the dispatch
worker's readiness gate holds them until they're marked ready (within the
timeout), so a ready-later draft still gets auto-reviewed. The hook is fully
wrapped: a failure can never break the sync cycle.

**Classification** (`backend/services/automation_service.py`, pure):
`matches(path, pattern)` = `fnmatch.fnmatchcase` against the full repo-relative
path OR the basename (note `*` crosses `/` in fnmatch). `classify_files` strips
ignore-pattern files, then attributes each remaining file to the first rule (list
order) with a matching pattern:
- every file → the same single rule → **matched** (that rule's reviewer)
- no file matches any rule (or all files ignored / empty) → **default**
- files span ≥2 rules, or mix rule + unmatched → **unidentified**

**Dispatch worker** (`backend/services/automation_dispatch_worker.py`, daemon
started unconditionally from `app.py`, 30s interval; the loop's own
`scope == 'off'` check is the live kill switch). Each cycle it evaluates up to
`EVAL_LIMIT` (20) pending rows but starts reviews only within a budget of
`maxConcurrentAutoReviews − running auto-started reviews` — evaluating more rows
than the budget means a PR stuck waiting on its conditions never starves ready
PRs queued behind it. Per row: re-check repo allowlisted (else `skipped`) → PR
metadata from `synced_prs` (fallback `fetch_full_pr`) → one `fetch_pr_queue_data`
call for live state/draft/CI (closed or merged → `skipped`) → add to merge queue
if absent and `assign_card_to_lane` into the Auto lane (before the gates, so a
waiting PR is visible on the board) → **dispatch condition gates** → `fetch_pr_files`
(REST files endpoint with `--paginate`; `gh pr view --json files` truncates at
100) → classify → for unidentified, persist and stop (no review); otherwise
`begin_review(reviewer_type=rule.reviewerKey, auto_started=True)` and, only after
a 201, arm per-PR auto-verdict with the rule's `autoVerdict`/`autoVerdictMode`
via `set_auto_verdict`. `begin_review` 409 (a review already running) →
`skipped`; other failures increment `attempts` and retry next cycle, `failed`
after 3. Follow-up reviews stay owned by the existing auto-review watcher once
the card is armed.

**Dispatch condition gates** (`_dispatch_blocker`): a review starts only when the
live PR data is readable (a `fetch_pr_queue_data` failure blocks rather than
dispatching blind), the PR is not a draft, CI is completed and passing
(`get_ci_status` == pending/failure blocks; a PR with **no checks at all**
passes, so CI-less repos are never held up; gate disabled via
`requireCiPass: false`), and the branch is at most `maxBehindBase` commits behind
its base head (via `fetch_pr_behind_by`, the `gh api …/compare/{base}...{head}`
`behind_by` count; a compare failure blocks without consuming attempts). A
blocked row stays `pending` with `detail = "waiting: <reason>"` and is
re-evaluated every cycle — CI turning green, a rebase, or marking ready triggers
the review naturally. A row still blocked `dispatchTimeoutHours` after detection
(`created_at`) is marked `skipped` with the last blocking reason for manual
handling.

**Dispatch statuses** (`automation_dispatches.status`): `pending` → `dispatched`
| `unidentified` | `skipped` | `failed`. The row also stores `outcome_json`
(classification result), `reviewer_key`, `detail`, `attempts`.

**Protected Auto lane**: `swimlanes.is_protected` column; `ensure_auto_lane()`
seeds one violet "Auto" lane (self-heals from `get_board`). `delete_lane` and
rename refuse protected lanes (recolor allowed); the frontend hides the delete
button and rename affordance and shows a `🤖 auto` tag. `assign_card_to_lane`
places a card at the bottom of a lane idempotently (used by the dispatcher so
auto cards land in Auto instead of the default lane).

**Card surface**: enriched queue items carry `automation:
{status, reviewerKey, ruleName, matchedRules, detail, updatedAt} | null`
(`format_automation_state` in `queue_enrichment.py`). `QueueItem` renders — in
the title row, outside the `hasReview` gate — `❓ Unidentified` (warning, tooltip
lists the spanned rules), `🤖 Auto` (info, tooltip names rule + reviewer),
`🤖 Auto failed` (error, tooltip carries the detail), `⏳ Auto waiting` (neutral,
tooltip carries the blocking reason while a pending row waits on the dispatch
conditions), or `🤖 Auto skipped` (neutral, tooltip carries the skip reason —
e.g. a conditions timeout). The swimlane badge filter
gains an `auto:unidentified` chip in the Auto Verdict group. Routing an
unidentified PR is manual by design: the operator uses the normal review
button/picker and AutoVerdictToggle on the card.

**Automation tab** (`frontend/src/components/automation/`): `AutomationPanel`
(draft state, one explicit Save for the config blob, dirty indicator) opens with
`ActiveConfigSummary` — a read-only ●&nbsp;ACTIVE/○&nbsp;OFF strip of the SAVED
config (scope + authors, allowlisted repos, rule→reviewer routing map, dispatch
conditions, concurrency), distinct from the unsaved draft below — followed by
the sections: `ScopeSection` (off/authors/all cards, author + repo chip lists,
concurrency), `RoutingRulesSection` (ordered rules with ↑/↓, pattern chips,
reviewer select, per-rule verdict toggle + mode, ignore patterns, pinned default
rule), `ReviewerRegistrySection` (table + inline add/edit/delete, builtins
locked), and `AutoVerdictCriteriaSection` — the global auto-verdict criteria form
relocated from the old header modal (storage and API unchanged; the shared form
lives in `AutoVerdictCriteriaForm`, still used by the per-PR override modal).
State: `useAutomationStore` (config + reviewers, loaded at app start). The header
🤖 button now navigates to the tab and shows `on` when auto verdicts are enabled
or automation scope ≠ off.

---

## API Endpoints

### Authentication

**GET** `/api/user`

Returns the currently authenticated GitHub user.

**Response**:
```json
{
  "user": {
    "login": "username",
    "name": "Full Name",
    "avatar_url": "https://avatars.githubusercontent.com/..."
  }
}
```

### Accounts

**GET** `/api/orgs`

Returns the user's personal account and organizations.

**Response**:
```json
{
  "accounts": [
    {
      "login": "username",
      "name": "Full Name",
      "avatar_url": "https://...",
      "type": "user",
      "is_personal": true
    },
    {
      "login": "org-name",
      "name": "org-name",
      "avatar_url": "https://...",
      "type": "org"
    }
  ]
}
```

### Repositories

**GET** `/api/repos`

Lists repositories for an owner.

**Query Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `owner` | string | - | Organization or user login |
| `limit` | integer | 100 | Maximum repositories to return |

**Response**:
```json
{
  "repos": [
    {
      "name": "repo-name",
      "owner": { "login": "owner" },
      "description": "Repository description",
      "isPrivate": false,
      "updatedAt": "2024-01-15T10:30:00Z"
    }
  ]
}
```

### Pull Requests

**GET** `/api/repos/<owner>/<repo>/prs`

Fetches PRs with advanced filtering.

**Query Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `state` | string | "open" | open, closed, merged, all |
| `limit` | integer | 30 | Results limit (max 100) |
| `author` | string | - | Filter by author username |
| `assignee` | string | - | Filter by assignee username |
| `labels` | string | - | Comma-separated label names |
| `base` | string | - | Base branch name |
| `head` | string | - | Head branch name |
| `draft` | string | - | "true" or "false" |
| `review` | string | - | Comma-separated: none, required, approved, changes_requested |
| `reviewedBy` | string | - | Username who reviewed |
| `reviewRequested` | string | - | Username with pending review request |
| `status` | string | - | Comma-separated CI status: pending, success, failure |
| `involves` | string | - | Username involved in any capacity |
| `mentions` | string | - | Username mentioned |
| `commenter` | string | - | Username who commented |
| `linked` | string | - | "true" or "false" for linked issues |
| `milestone` | string | - | Milestone title or "none" |
| `noAssignee` | string | - | "true" for PRs without assignee |
| `noLabel` | string | - | "true" for PRs without labels |
| `comments` | string | - | Comment count filter (e.g., ">5") |
| `createdAfter` | string | - | Date in YYYY-MM-DD format |
| `createdBefore` | string | - | Date in YYYY-MM-DD format |
| `updatedAfter` | string | - | Date in YYYY-MM-DD format |
| `updatedBefore` | string | - | Date in YYYY-MM-DD format |
| `mergedAfter` | string | - | Date in YYYY-MM-DD format |
| `mergedBefore` | string | - | Date in YYYY-MM-DD format |
| `closedAfter` | string | - | Date in YYYY-MM-DD format |
| `closedBefore` | string | - | Date in YYYY-MM-DD format |
| `search` | string | - | Text search keywords |
| `searchIn` | string | - | Comma-separated: title, body, comments |
| `reactions` | string | - | Reaction count filter (e.g., ">=10") |
| `interactions` | string | - | Interaction count filter |
| `teamReviewRequested` | string | - | Team slug for review request |
| `excludeLabels` | string | - | Comma-separated labels to exclude |
| `excludeAuthor` | string | - | Author to exclude |
| `excludeMilestone` | string | - | Milestone to exclude |
| `sortBy` | string | - | created, updated, comments, reactions, interactions |
| `sortDirection` | string | "desc" | asc or desc |

**Response**:
```json
{
  "prs": [
    {
      "number": 123,
      "title": "PR Title",
      "author": { "login": "user", "avatarUrl": "https://..." },
      "state": "OPEN",
      "isDraft": false,
      "createdAt": "2024-01-10T08:00:00Z",
      "updatedAt": "2024-01-15T10:30:00Z",
      "closedAt": null,
      "mergedAt": null,
      "url": "https://github.com/owner/repo/pull/123",
      "body": "PR description in markdown",
      "headRefName": "feature-branch",
      "baseRefName": "main",
      "labels": [{ "name": "bug", "color": "d73a4a" }],
      "assignees": [{ "login": "assignee" }],
      "reviewRequests": [],
      "reviewDecision": "APPROVED",
      "reviewStatus": "approved",
      "ciStatus": "success",
      "statusCheckRollup": [...],
      "mergeable": "MERGEABLE",
      "additions": 150,
      "deletions": 50,
      "changedFiles": 5,
      "milestone": { "title": "v1.0" }
    }
  ]
}
```

**Computed Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `reviewStatus` | string | Computed from `reviewDecision`: "approved", "changes_requested", "review_required", or "pending" |
| `ciStatus` | string | Computed from `statusCheckRollup`: "success", "failure", "pending", "neutral", or null |

**Sync metadata** (see the PR List Sync feature): each PR carries `fetchedAt`
(when its data was last pulled from GitHub), and the response includes a
top-level `sync` object:

```json
{
  "prs": [ ... ],
  "sync": { "status": "ready", "lastSyncedAt": "2026-08-28 04:10:22" }
}
```

`status` is `ready` (served from the local synced store), `backfilling` (first
sync still running; data is live or partial), or `live` (repo not synced —
excluded or over the `max_synced_repos` cap).

**POST** `/api/repos/<owner>/<repo>/prs/<pr_number>/refresh`

Live-fetches one PR with the full field set, upserts it into the synced store,
and returns the fresh processed row.

**Response**: `{"pr": { ...list-item shape, incl. fetchedAt... }}`

**Errors**: `404` when the PR no longer exists on GitHub (the stale local row is
deleted); `503` with `"transient": true` on upstream 5xx.

### Repository Metadata

**GET** `/api/repos/<owner>/<repo>/contributors`

Returns list of contributor usernames.

**Response**:
```json
{
  "contributors": ["user1", "user2", "user3"]
}
```

---

**GET** `/api/repos/<owner>/<repo>/labels`

Returns list of label names.

**Response**:
```json
{
  "labels": ["bug", "enhancement", "documentation"]
}
```

---

**GET** `/api/repos/<owner>/<repo>/branches`

Returns list of branch names.

**Response**:
```json
{
  "branches": ["main", "develop", "feature/auth"]
}
```

---

**GET** `/api/repos/<owner>/<repo>/milestones`

Returns milestones with state.

**Response**:
```json
{
  "milestones": [
    { "title": "v1.0", "state": "open", "number": 1 },
    { "title": "v0.9", "state": "closed", "number": 2 }
  ]
}
```

---

**GET** `/api/repos/<owner>/<repo>/teams`

Returns teams with repository access.

**Response**:
```json
{
  "teams": [
    { "slug": "core-team", "name": "Core Team" },
    { "slug": "reviewers", "name": "Reviewers" }
  ]
}
```

### Developer Statistics

**GET** `/api/repos/<owner>/<repo>/stats`

Returns aggregated developer statistics.

**Response**:
```json
{
  "stats": [
    {
      "login": "developer1",
      "avatar_url": "https://...",
      "commits": 245,
      "lines_added": 15000,
      "lines_deleted": 8000,
      "prs_authored": 45,
      "prs_merged": 42,
      "prs_closed": 2,
      "prs_open": 1,
      "reviews_given": 120,
      "approvals": 95,
      "changes_requested": 15,
      "comments": 10
    }
  ]
}
```

### Branch Divergence

**POST** `/api/repos/<owner>/<repo>/prs/divergence`

Batch-fetches branch ahead/behind information for open PRs using the GitHub compare API. Uses `ThreadPoolExecutor` with 5 workers for parallel fetching.

**Request Body**:
```json
{
  "prs": [
    { "number": 123, "base": "main", "head": "feature-branch" },
    { "number": 124, "base": "main", "head": "fix-bug" }
  ]
}
```

**Response**:
```json
{
  "divergence": {
    "123": { "status": "behind", "ahead_by": 2, "behind_by": 5 },
    "124": { "status": "identical", "ahead_by": 0, "behind_by": 0 }
  }
}
```

**Error Responses**:
- `400`: Missing `prs` in request body
- `500`: Failed to fetch divergence data

---

**GET** `/api/repos/<owner>/<repo>/prs/<pr_number>/timeline`

Returns a normalized chronological event timeline for a single PR. Cached in SQLite with state-aware TTL — closed/merged PRs cached indefinitely (immutable), open PRs cached 5 minutes with stale-while-revalidate.

**Query Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `refresh` | string | Set to "true" to bypass cache and force a fresh fetch |

**Response**:
```json
{
  "events": [
    { "id": "opened-...", "type": "opened", "created_at": "...", "actor": {...} },
    { "id": "committed-...", "type": "committed", "sha": "...", "short_sha": "abc1234", "message": "...", ... }
  ],
  "pr_state": "OPEN",
  "last_updated": "2026-04-16T14:02:11Z",
  "cached": false,
  "stale": false,
  "refreshing": false
}
```

**Event Types**: `opened`, `committed`, `commented`, `reviewed`, `review_requested`, `ready_for_review`, `convert_to_draft`, `closed`, `reopened`, `merged`, `head_ref_force_pushed`.

**Error Responses**:
- `404`: PR not found
- `503`: GitHub API error (falls back to stale cache if available)
- `500`: Internal server error

---

### CI/Workflow Runs

**GET** `/api/repos/<owner>/<repo>/workflow-runs`

Returns GitHub Actions workflow runs with optional filters and aggregate statistics. Cached with the default TTL.

**Query Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 50 | Maximum runs to return (capped at 100) |
| `workflow_id` | integer | - | Filter by workflow ID |
| `branch` | string | - | Filter by branch name |
| `event` | string | - | Filter by trigger event (push, pull_request, schedule) |
| `status` | string | - | Filter by run status |
| `conclusion` | string | - | Filter by run conclusion (success, failure, cancelled) |

**Response**:
```json
{
  "runs": [
    {
      "id": 12345,
      "name": "CI",
      "display_title": "Fix authentication bug",
      "status": "completed",
      "conclusion": "success",
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-15T10:35:00Z",
      "event": "push",
      "head_branch": "main",
      "run_attempt": 1,
      "run_number": 456,
      "html_url": "https://github.com/owner/repo/actions/runs/12345",
      "actor_login": "developer",
      "duration_seconds": 300
    }
  ],
  "stats": {
    "total_runs": 50,
    "pass_rate": 92.5,
    "avg_duration": 285,
    "failure_count": 3,
    "success_count": 37,
    "runs_by_workflow": {
      "CI": { "total": 30, "failures": 2 },
      "Deploy": { "total": 20, "failures": 1 }
    }
  },
  "workflows": [
    { "id": 1, "name": "CI", "state": "active", "path": ".github/workflows/ci.yml" }
  ]
}
```

---

### Code Activity

**GET** `/api/repos/<owner>/<repo>/code-activity`

Returns code activity statistics including commit frequency, code changes, and owner/community participation. Cached with a 10-minute TTL.

**Query Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `weeks` | integer | 52 | Number of weeks to analyze (1-52) |

**Response**:
```json
{
  "weekly_commits": [
    { "week": "2024-01-08", "total": 15, "days": [2, 3, 4, 1, 2, 3, 0] }
  ],
  "code_changes": [
    { "week": "2024-01-08", "additions": 500, "deletions": 200 }
  ],
  "owner_commits": [10, 12, 8],
  "community_commits": [5, 3, 7],
  "summary": {
    "total_commits": 150,
    "avg_weekly_commits": 11.5,
    "total_additions": 15000,
    "total_deletions": 8000,
    "peak_week": "2024-01-08",
    "peak_commits": 25,
    "owner_percentage": 65.3
  }
}
```

---

### Contributor Time Series

**GET** `/api/repos/<owner>/<repo>/contributor-timeseries`

Returns per-contributor weekly time series data (commits, additions, deletions). Cached in SQLite with 24-hour TTL using stale-while-revalidate pattern.

**Query Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `refresh` | string | - | Set to "true" to force a synchronous refresh |

**Response**:
```json
{
  "contributors": [
    {
      "login": "developer1",
      "avatar_url": "https://...",
      "total": 150,
      "weeks": [
        {
          "week": "2025-01-06",
          "commits": 5,
          "additions": 100,
          "deletions": 50
        }
      ]
    }
  ]
}
```

---

### PR Lifecycle Metrics

**GET** `/api/repos/<owner>/<repo>/lifecycle-metrics`

Returns PR lifecycle metrics including time-to-merge, time-to-first-review, stale PR detection, and merge time distribution. Uses `fetch_pr_review_times()` shared helper with SQLite cache (2-hour TTL).

**Response**:
```json
{
  "median_time_to_merge": 18.5,
  "avg_time_to_merge": 42.3,
  "median_time_to_first_review": 4.2,
  "avg_time_to_first_review": 8.7,
  "stale_prs": [
    { "number": 45, "title": "Old feature", "author": "developer", "age_days": 21.3 }
  ],
  "stale_count": 3,
  "distribution": {
    "<1h": 5,
    "1-4h": 12,
    "4-24h": 18,
    "1-3d": 8,
    "3-7d": 4,
    ">7d": 3
  },
  "pr_table": [
    {
      "number": 123,
      "title": "Add new feature",
      "author": "developer",
      "created_at": "2024-01-10T08:00:00Z",
      "state": "MERGED",
      "time_to_first_review_hours": 2.5,
      "time_to_merge_hours": 18.3,
      "first_reviewer": "reviewer1"
    }
  ]
}
```

---

### Review Responsiveness

**GET** `/api/repos/<owner>/<repo>/review-responsiveness`

Returns per-reviewer response time metrics, a ranked leaderboard, and bottleneck detection for unreviewed PRs. Shares the `fetch_pr_review_times()` cached data with the lifecycle endpoint.

**Response**:
```json
{
  "leaderboard": [
    {
      "reviewer": "fast-reviewer",
      "avg_response_time_hours": 2.5,
      "median_response_time_hours": 1.8,
      "total_reviews": 45,
      "approvals": 38,
      "changes_requested": 5,
      "approval_rate": 84.4
    }
  ],
  "bottlenecks": [
    { "number": 99, "title": "Waiting PR", "author": "developer", "wait_hours": 120.5 }
  ],
  "avg_team_response_hours": 8.3,
  "fastest_reviewer": "fast-reviewer",
  "prs_awaiting_review": 5
}
```

---

### Merge Queue

**GET** `/api/merge-queue`

Returns the current merge queue.

**Response**:
```json
{
  "queue": [
    {
      "id": 1,
      "number": 123,
      "title": "Add new feature",
      "url": "https://github.com/owner/repo/pull/123",
      "repo": "owner/repo",
      "author": "developer",
      "additions": 150,
      "deletions": 50,
      "addedAt": "2024-01-15T10:30:00Z",
      "notesCount": 2,
      "prState": "OPEN",
      "hasNewCommits": false,
      "lastReviewedSha": "abc123",
      "currentSha": "abc123",
      "hasReview": true,
      "reviewScore": 8,
      "reviewId": 42,
      "inlineCommentsPosted": false
    }
  ]
}
```

---

**POST** `/api/merge-queue`

Adds a PR to the merge queue.

**Request Body**:
```json
{
  "number": 123,
  "title": "Add new feature",
  "url": "https://github.com/owner/repo/pull/123",
  "repo": "owner/repo",
  "author": "developer",
  "additions": 150,
  "deletions": 50
}
```

**Response**:
```json
{
  "message": "Added to queue",
  "queue": [...]
}
```

---

**DELETE** `/api/merge-queue`

Removes a PR from the merge queue.

**Query Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `pr_number` | integer | PR number to remove |
| `repo` | string | Repository in `owner/repo` format |

**Response**:
```json
{
  "message": "Removed from queue",
  "queue": [...]
}
```

---

**PUT** `/api/merge-queue/reorder`

Reorders items in the merge queue.

**Request Body**:
```json
{
  "from_index": 0,
  "to_index": 2
}
```

**Response**:
```json
{
  "message": "Queue reordered",
  "queue": [...]
}
```

---

### Auto Verdicts

**GET** `/api/auto-verdict/config`

Returns the global auto-verdict criteria, stored values merged over `DEFAULT_CRITERIA`.

**Response**:
```json
{
  "config": {
    "enabled": false,
    "maxCritical": 0,
    "maxMajor": 0,
    "maxMinor": 99,
    "allowAutoApprove": false,
    "autoFollowupReview": false
  }
}
```

**PUT** `/api/auto-verdict/config`

Validates and saves the criteria. Thresholds must be integers ≥ 0; a negative or
non-numeric value returns 400. Unrecognized keys are ignored, and omitted keys fall
back to their defaults. Also accepts POST. The payload may be sent either wrapped in
`config` or as a bare object.

**Request Body**:
```json
{
  "config": {
    "enabled": true,
    "maxCritical": 0,
    "maxMajor": 1,
    "maxMinor": 99,
    "allowAutoApprove": false,
    "autoFollowupReview": false
  }
}
```

**Response**:
```json
{
  "config": { "...": "the stored value" },
  "message": "Auto-verdict config saved"
}
```

**PUT** `/api/merge-queue/<pr_number>/auto-verdict`

Arms or disarms auto verdicts for a queued PR.

**Query Parameters**:
- `repo` (required): Repository in `owner/repo` format

**Request Body**:
```json
{
  "enabled": true,
  "reviewerType": "default",
  "mode": "verdict"
}
```

`reviewerType` is one of `default`, `pb`, `ed` (defaults to `default`); anything else
returns 400. `mode` is `verdict` or `comment` (defaults to `verdict`); anything else
returns 400. A PR that is not in the merge queue returns 404.

**Response**:
```json
{
  "autoVerdict": { "enabled": true, "reviewerType": "default", "mode": "verdict" },
  "message": "Auto verdict updated"
}
```

**PUT** `/api/merge-queue/<pr_number>/auto-verdict/criteria`

Sets or clears a queued PR's criteria override (see [Auto Verdicts — Per-PR
Criteria Overrides](#per-pr-criteria-overrides)).

**Query Parameters**:
- `repo` (required): Repository in `owner/repo` format

**Request Body** — a full override snapshot, or `null` to clear:
```json
{
  "criteria": {
    "maxCritical": 3,
    "maxMajor": 1,
    "maxMinor": 99,
    "allowAutoApprove": true,
    "autoFollowupReview": false
  }
}
```

The override is validated like the global config (integer thresholds ≥ 0, else 400)
but never contains `enabled` — the master switch is not per-PR and an `enabled` key
in the payload is dropped. A PR that is not in the merge queue returns 404.

**Response**:
```json
{
  "criteriaOverride": { "...": "the stored override, or null when cleared" },
  "message": "Auto verdict criteria updated"
}
```

---

### Automation

**GET** `/api/reviewers`

Lists the reviewer registry (builtins first).

**Response**:
```json
{
  "reviewers": [
    {"key": "default", "label": "Default Reviewer", "agentName": "elite-code-reviewer",
     "promptContext": null, "isBuiltin": true}
  ]
}
```

**POST** `/api/reviewers` — body `{"key", "label", "agentName", "promptContext"?}`.
Key must match `^[a-z0-9_-]{1,32}$` and be unique. Returns `201 {"reviewer": {...}}`;
400 on validation errors.

**PATCH** `/api/reviewers/<key>` — body `{"label"?, "agentName"?, "promptContext"?}`.
Key is immutable; builtins refuse `agentName` changes. Returns `{"reviewer": {...}}`.

**DELETE** `/api/reviewers/<key>` — 400 for builtins. A deleted key still referenced
by a card or rule falls back to `default` at dispatch time with a logged warning
(saving a config that references an unknown key is rejected).

**GET** `/api/automation/config`

Returns `{"config": {...}}` — stored `automation_config` merged over the defaults
(see the Automation feature section for the shape).

**PUT** `/api/automation/config` — body `{"config": {...}}` (or the bare object).
Validates and persists; 400 with a message on bad scope/mode/rule/reviewer key.

---

### Queue Notes

**GET** `/api/merge-queue/<pr_number>/notes`

Gets all notes for a queue item.

**Query Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `repo` | string | Repository in `owner/repo` format |

**Response**:
```json
{
  "notes": [
    {
      "id": 1,
      "content": "Need to verify database migrations before merge",
      "createdAt": "2024-01-15T10:30:00Z"
    }
  ]
}
```

---

**POST** `/api/merge-queue/<pr_number>/notes`

Adds a note to a queue item.

**Request Body**:
```json
{
  "repo": "owner/repo",
  "content": "Remember to update the changelog"
}
```

**Response**:
```json
{
  "message": "Note added",
  "note": {
    "id": 5,
    "content": "Remember to update the changelog",
    "createdAt": "2024-01-15T14:00:00Z"
  }
}
```

---

**DELETE** `/api/merge-queue/notes/<note_id>`

Deletes a note from a queue item.

**Response**:
```json
{
  "message": "Note deleted"
}
```

---

### Swimlane Board

**GET** `/api/swimlanes/board`

Returns the full swimlane board: lanes plus enriched cards grouped by lane id. Cards use the same enrichment as `/api/merge-queue` so the frontend can reuse the `QueueItem` component.

**Response**:
```json
{
  "lanes": [
    { "id": 1, "name": "Unassigned", "color": "info", "position": 1, "isDefault": true, "createdAt": "..." }
  ],
  "cardsByLane": {
    "1": [ /* MergeQueueItem-shaped objects (see /api/merge-queue), each also carrying `isPinned: boolean` */ ]
  }
}
```

---

**POST** `/api/swimlanes`

Create a lane.

**Request Body**:
```json
{ "name": "Reviewing", "color": "warning" }
```

`color` must be one of: `success`, `warning`, `error`, `info`, `primary`, `accent`, `violet`, `slate`.

**Response** (201):
```json
{ "lane": { "id": 5, "name": "Reviewing", "color": "warning", "position": 2, "isDefault": false, "createdAt": "..." } }
```

---

**PATCH** `/api/swimlanes/<lane_id>`

Rename and/or recolor a lane. Body may contain `name` and/or `color`.

---

**DELETE** `/api/swimlanes/<lane_id>`

Delete a lane. Orphaned cards are re-homed to the (potentially new) default lane and the response includes the current default. Refuses to delete the last remaining lane.

**Response**:
```json
{ "message": "Lane deleted", "defaultLane": { "id": 1, "name": "Unassigned", "color": "info", "position": 1, "isDefault": true, "createdAt": "..." } }
```

---

**PUT** `/api/swimlanes/reorder`

Reorder lanes by ID.

**Request Body**:
```json
{ "order": [3, 1, 2] }
```

---

**PUT** `/api/swimlanes/<lane_id>/default`

Mark the given lane as the default. New merge queue items land here.

---

**PUT** `/api/swimlanes/cards/move`

Move a card to a target lane and 1-based position. Compacts the source and destination lanes atomically.

**Request Body**:
```json
{ "queueItemId": 42, "toLaneId": 3, "toPosition": 1 }
```

**Response**:
```json
{ "assignment": { "queueItemId": 42, "swimlaneId": 3, "positionInLane": 1, "isPinned": false } }
```

---

**PUT** `/api/swimlanes/cards/<queue_item_id>/pin`

Pin or unpin a card within its lane. Pinning moves it to the bottom of the lane's pinned group; unpinning moves it to the top of the unpinned group.

**Request Body**:
```json
{ "pinned": true }
```

**Response**:
```json
{ "assignment": { "queueItemId": 42, "swimlaneId": 3, "positionInLane": 1, "isPinned": true } }
```

---

### Code Reviews

**GET** `/api/reviews`

Returns all active and recent reviews with their current statuses.

**Response**:
```json
{
  "reviews": [
    {
      "key": "owner/repo/123",
      "owner": "owner",
      "repo": "repo",
      "pr_number": 123,
      "status": "running",
      "started_at": "2024-01-15T10:30:00Z",
      "completed_at": null,
      "pr_url": "https://github.com/owner/repo/pull/123",
      "review_file": "/path/to/reviews/owner-repo-pr-123.md",
      "exit_code": null,
      "error_output": ""
    }
  ]
}
```

---

**POST** `/api/reviews`

Starts a new code review for a PR.

**Request Body**:
```json
{
  "number": 123,
  "url": "https://github.com/owner/repo/pull/123",
  "owner": "owner",
  "repo": "repo",
  "reviewer_type": "default"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `number` | integer | Yes | PR number |
| `url` | string | Yes | GitHub PR URL |
| `owner` | string | Yes | Repository owner |
| `repo` | string | Yes | Repository name |
| `reviewer_type` | string | No | `"default"` (elite-code-reviewer, default), `"pb"` (product-brief-reviewer), or `"ed"` (ed-reviewer) |
| `is_followup` | boolean | No | If true, includes previous review content as context |
| `previous_review_id` | integer | No | Specific review to use as the follow-up parent |
| `title` | string | No | PR title (used for display in the active reviews list) |
| `author` | string | No | PR author login |

**Response** (201 Created):
```json
{
  "message": "Review started",
  "key": "owner/repo/123",
  "status": "running",
  "review_file": "/path/to/reviews/owner-repo-pr-123.md"
}
```

**Error Responses**:
- `400`: Missing required fields
- `409`: Review already in progress for this PR
- `500`: Failed to start review (e.g., Claude CLI not found)

---

**DELETE** `/api/reviews/<owner>/<repo>/<pr_number>`

Cancels a running review.

**Response**:
```json
{
  "message": "Review cancelled",
  "key": "owner/repo/123"
}
```

---

**GET** `/api/reviews/<owner>/<repo>/<pr_number>/status`

Gets the status of a specific review.

**Response**:
```json
{
  "key": "owner/repo/123",
  "status": "completed",
  "started_at": "2024-01-15T10:30:00Z",
  "completed_at": "2024-01-15T10:35:00Z",
  "pr_url": "https://github.com/owner/repo/pull/123",
  "review_file": "/path/to/reviews/owner-repo-pr-123.md",
  "exit_code": 0,
  "error_output": ""
}
```

---

**POST** `/api/reviews/<review_id>/post-inline-comments`

Posts critical issues from a review as inline comments on the GitHub PR.

**Response** (Success):
```json
{
  "message": "Posted inline comments",
  "issues_posted": 3,
  "issues_found": 3
}
```

**Response** (No Issues Found):
```json
{
  "message": "No critical issues found to post",
  "issues_posted": 0,
  "issues_found": 0
}
```

**Error Responses**:
- `404`: Review not found
- `400`: Review has no content or missing PR information
- `500`: Failed to post comments to GitHub

---

**POST** `/api/repos/<owner>/<repo>/prs/<pr_number>/verdict`

Posts a formal PR review verdict (Approve, Request Changes, or Comment) to GitHub.

**Request Body**:
```json
{
  "event": "APPROVE",
  "body": "Looks good! All critical issues addressed."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `event` | string | Yes | One of: `APPROVE`, `REQUEST_CHANGES`, `COMMENT` |
| `body` | string | Yes | Review body text (cannot be empty) |

**Response** (Success):
```json
{
  "message": "Review verdict posted: APPROVE",
  "event": "APPROVE",
  "pr_number": 123
}
```

**Error Responses**:
- `400`: Missing event, invalid event type, or empty body
- `500`: Failed to fetch PR head SHA or failed to post to GitHub

---

### Audits

PB↔ED audit endpoints mirror the code-review endpoints. Active-audit routes drive the spinner; history routes serve persisted audits from the `audits` table.

**GET** `/api/audits`

Returns active/recent audits with refreshed statuses (polled to drive the spinner).

**Response**:
```json
{
  "audits": [
    {
      "key": "owner/repo/123",
      "owner": "owner",
      "repo": "repo",
      "pr_number": 123,
      "status": "running",
      "started_at": "2026-06-05T10:30:00Z",
      "completed_at": "",
      "pr_url": "https://github.com/owner/repo/pull/123",
      "audit_file": "/path/to/reviews/owner-repo-pr-123-audit.md",
      "exit_code": null,
      "error_output": ""
    }
  ]
}
```

---

**POST** `/api/audits`

Starts a PB↔ED audit for a PR.

**Request Body**:
```json
{
  "number": 123,
  "url": "https://github.com/owner/repo/pull/123",
  "owner": "owner",
  "repo": "repo",
  "title": "PR title",
  "author": "developer",
  "head_ref": "feature-branch",
  "base_ref": "main"
}
```

`number`, `url`, `owner`, and `repo` are required; the rest are optional display/metadata fields.

**Response** (201 Created):
```json
{
  "message": "Audit started",
  "key": "owner/repo/123",
  "status": "running",
  "audit_file": "/path/to/reviews/owner-repo-pr-123-audit.md"
}
```

**Error Responses**:
- `400`: Missing required field
- `409`: Audit already in progress for this PR
- `500`: Failed to start audit

---

**DELETE** `/api/audits/<owner>/<repo>/<pr_number>`

Cancels a running audit.

**Response**:
```json
{ "message": "Audit cancelled", "key": "owner/repo/123" }
```

---

**GET** `/api/audits/<owner>/<repo>/<pr_number>/status`

Gets the status of a specific audit (same shape as a single entry in `GET /api/audits`).

---

**POST** `/api/audits/<audit_id>/post-inline-comments`

Posts audit findings that have a resolvable `file` + integer `line` location as inline PR comments via the shared `post_verdict` helper. Findings without a mappable location are skipped.

**Response** (Success):
```json
{ "message": "...", "issues_posted": 3 }
```

**Response** (No mappable locations):
```json
{ "message": "No findings with mappable file+line locations", "issues_posted": 0, "issues_found": 0 }
```

**Error Responses**:
- `404`: Audit not found
- `409`: Inline comments already posted for this audit
- `400`: Audit has no parseable content / invalid repo format

---

**GET** `/api/audit-history`

Returns a list of past audits with optional filtering.

**Query Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `repo` | string | Filter by repository (owner/repo format) |
| `author` | string | Filter by PR author |
| `pr_number` | integer | Filter by PR number |
| `search` | string | Full-text search across audit content |
| `limit` | integer | Maximum results (default 50) |
| `offset` | integer | Pagination offset |

**Response**:
```json
{
  "audits": [
    {
      "id": 1,
      "pr_number": 123,
      "repo": "owner/repo",
      "pr_title": "Add new feature",
      "pr_author": "developer",
      "pr_url": "https://github.com/owner/repo/pull/123",
      "audit_timestamp": "2026-06-05T10:30:00Z",
      "status": "completed",
      "finding_count": 7,
      "blocking_count": 1,
      "inline_comments_posted": false
    }
  ],
  "total": 12
}
```

---

**GET** `/api/audit-history/<audit_id>`

Returns a single audit with full content in both structured JSON (`content_json`) and generated markdown (`content`, produced on the fly via `audit_json_to_markdown()`), plus `head_ref`, `base_ref`, and `audit_file_path`.

**Error Responses**:
- `404`: Audit not found

---

**GET** `/api/audit-history/check/<owner>/<repo>/<pr_number>`

Checks whether a PR has been audited (drives the audit chip).

**Response**:
```json
{ "audited": true, "audit_count": 2, "latest_audit": { "id": 5, "blocking_count": 0 } }
```

---

### Review History

**GET** `/api/review-history`

Returns a list of past reviews with optional filtering.

**Query Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `repo` | string | Filter by repository (owner/repo format) |
| `author` | string | Filter by PR author |
| `start_date` | string | Filter reviews after this date (YYYY-MM-DD) |
| `end_date` | string | Filter reviews before this date (YYYY-MM-DD) |
| `min_score` | integer | Minimum review score (0-10) |
| `max_score` | integer | Maximum review score (0-10) |
| `search` | string | Full-text search in content and title |
| `limit` | integer | Maximum results to return (default: 50) |
| `offset` | integer | Pagination offset |

**Response**:
```json
{
  "reviews": [
    {
      "id": 1,
      "pr_number": 123,
      "repo": "owner/repo",
      "pr_title": "Add new feature",
      "pr_author": "developer",
      "pr_url": "https://github.com/owner/repo/pull/123",
      "review_timestamp": "2024-01-15T10:30:00Z",
      "status": "completed",
      "score": 8,
      "is_followup": false,
      "parent_review_id": null
    }
  ],
  "total": 45
}
```

---

**GET** `/api/review-history/<id>`

Returns a single review with full content in both structured JSON and generated markdown formats.

**Response**:
```json
{
  "id": 1,
  "pr_number": 123,
  "repo": "owner/repo",
  "pr_title": "Add new feature",
  "pr_author": "developer",
  "pr_url": "https://github.com/owner/repo/pull/123",
  "review_timestamp": "2024-01-15T10:30:00Z",
  "status": "completed",
  "review_file_path": "/path/to/reviews/owner-repo-pr-123.md",
  "score": 8,
  "content_json": {
    "schema_version": "1.0.0",
    "metadata": { "pr_number": 123, "repository": "owner/repo", "author": "developer" },
    "summary": "Overall review summary...",
    "score": { "overall": 8, "breakdown": [] },
    "sections": [
      { "type": "critical", "display_name": "Critical Issues", "issues": [] },
      { "type": "major", "display_name": "Major Concerns", "issues": [] },
      { "type": "minor", "display_name": "Minor Issues", "issues": [] }
    ],
    "recommendations": []
  },
  "content": "# Code Review for PR #123\n\n## Summary\n...",
  "is_followup": false,
  "parent_review_id": null
}
```

**Note**: `content_json` is the primary structured data stored in the database. `content` is a markdown string generated on the fly from `content_json` via `json_to_markdown()` for display and backward compatibility.

---

**GET** `/api/review-history/pr/<owner>/<repo>/<pr_number>`

Returns all reviews for a specific PR.

**Response**:
```json
{
  "reviews": [
    {
      "id": 1,
      "review_timestamp": "2024-01-15T10:30:00Z",
      "score": 6,
      "is_followup": false,
      "parent_review_id": null
    },
    {
      "id": 5,
      "review_timestamp": "2024-01-18T14:00:00Z",
      "score": 8,
      "is_followup": true,
      "parent_review_id": 1
    }
  ]
}
```

---

**GET** `/api/review-history/stats`

Returns aggregate review statistics.

**Response**:
```json
{
  "total_reviews": 245,
  "average_score": 7.2,
  "reviews_by_repo": {
    "owner/repo1": 120,
    "owner/repo2": 85,
    "owner/repo3": 40
  },
  "reviews_by_month": {
    "2024-01": 45,
    "2024-02": 68
  },
  "score_distribution": {
    "0-3": 15,
    "4-6": 78,
    "7-10": 152
  },
  "followup_count": 32
}
```

---

**GET** `/api/review-history/check/<owner>/<repo>/<pr_number>`

Checks if a PR has been reviewed.

**Response**:
```json
{
  "reviewed": true,
  "review_count": 2,
  "latest_review": {
    "id": 5,
    "review_timestamp": "2024-01-18T14:00:00Z",
    "score": 8,
    "is_followup": true
  }
}
```

---

### Review Logs

**GET** `/api/review-logs`

Returns review lifecycle events, newest first. Powers the Review Logs tab.

**Query Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `repo` | string | Filter to one `owner/name` repository |
| `pr_number` | integer | Filter to one PR |
| `event` | string | Filter by event type (`started`, `failed`, `verdict_posted`, …) |
| `reason` | string | Filter by failure reason (`no_output`, `auto_suppressed`, …) |
| `since` | string | ISO8601 lower bound on `created_at` |
| `limit` | integer | Page size (default 200) |
| `offset` | integer | Page offset (default 0) |

**Response**:
```json
{
  "events": [
    {
      "id": 412,
      "created_at": "2026-08-18T21:42:30Z",
      "run_id": "7c1f...",
      "event": "completed",
      "repo": "scala-computing/scala",
      "pr_number": 3179,
      "reviewer_agent": "default",
      "is_followup": true,
      "auto_started": true,
      "attempt": 2,
      "max_attempts": 3,
      "exit_code": 0,
      "reason": null,
      "detail": null,
      "review_id": 969,
      "score": 8.0,
      "pid": 196753,
      "issue_counts": { "critical": 0, "major": 5, "minor": 4 }
    }
  ],
  "total": 1
}
```

`issue_counts` is tallied at query time from the review's `content_json`. It is
`null` when the event names no review, or when that review is missing or
unparseable — which the client renders as "unavailable", never as a clean
review. The key is always present.

**GET** `/api/review-logs/stats`

Returns aggregate counts for the summary strip.

**Query Parameters**: `repo`, `since` (both optional).

**Response**:
```json
{
  "stats": {
    "runs": 42,
    "completed": 38,
    "failed": 4,
    "rescued_by_retry": 6,
    "by_reason": {
      "no_output": 5,
      "nonzero_exit": 3
    }
  }
}
```

`rescued_by_retry` counts runs that completed on an attempt after their first —
the direct measure of whether the retry loop is earning its keep.

---

### Repo Stats

**GET** `/api/repos/<owner>/<repo>/repo-stats`

Returns aggregated repository statistics. Cached with 4-hour TTL using stale-while-revalidate.

**Query Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `refresh` | string | Set to "true" for synchronous refresh |

**Response**: Contains `overview`, `code`, `prs`, `languages`, `files_by_extension` objects plus cache metadata (`last_updated`, `cached`, `stale`, `refreshing`).

---

**POST** `/api/repos/<owner>/<repo>/repo-stats/loc`

Triggers a shallow clone and counts non-whitespace lines per language. Cached with 24-hour TTL.

**Response**: Contains `loc` (array of per-language stats) and `totals` objects plus `last_updated` and `cached` fields. Returns 202 if calculation is already in progress.

---

### Cache Management

**POST** `/api/clear-cache`

Clears the in-memory cache.

**Response**:
```json
{
  "message": "Cache cleared"
}
```

---

## Configuration

**File**: `/Users/jvargas714/Documents/dev/gh-pr-explorer/config.json`

Runtime-editable configuration lives in the DB-backed `user_settings` table
instead of this file: `auto_verdict_config` (Auto Verdicts feature) and
`automation_config` (Automation feature) are both edited from the Automation tab
and validated server-side; see those feature sections for their shapes.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `port` | integer | 5714 | HTTP server port (Flask API) |
| `host` | string | "localhost" | HTTP server bind address |
| `frontend_port` | integer | 3050 | Vite dev server port |
| `debug` | boolean | false | Flask debug mode |
| `default_per_page` | integer | 30 | Default PR results limit |
| `cache_ttl_seconds` | integer | 300 | Cache time-to-live in seconds (5 minutes) |
| `workflow_cache_ttl_minutes` | integer | 60 | Workflow cache TTL in minutes (stale-while-revalidate) |
| `workflow_cache_max_runs` | integer | 1000 | Maximum unfiltered workflow runs to cache per repo |
| `review_sample_limit` | integer | 250 | Maximum PRs to sample for review statistics and lifecycle metrics |
| `review_section_names` | object | `{"critical": "Critical Issues", "major": "Major Concerns", "minor": "Minor Issues"}` | Custom display names for review sections |
| `reviews_dir` | string | `~/code-reviews` | Directory where Claude code reviews (`.md`/`.json`) are written. Supports `~` and `$VAR` expansion so it stays machine-agnostic. Falls back to `~/code-reviews` if omitted. |
| `post_review_started_comment` | boolean | true | Post a "review underway" comment to the PR when a code review starts. Set to `false` to suppress the comment entirely. |
| `review_max_attempts` | integer | 3 | Total review attempts (including the first) before a review is recorded as failed. Clamped to 1–5; `1` disables retries. |
| `review_retry_delay_seconds` | number | 30 | Backoff before each retry attempt. Gives a transient API or GitHub outage time to clear. |
| `review_log_retention_days` | integer | 90 | How long review lifecycle events are kept. Purged once on startup; `0` disables purging. |
| `past_reviews_dir` | string | `<reviews_dir>/past-reviews` | Legacy reviews directory used only by the one-time `migrate_data.py` import. Supports `~`/`$VAR` expansion. |
| `pr_sync` | object | see below | PR List Sync worker settings. Optional block; every key has an internal default. `enabled` (bool, true) — master switch; `false` reverts the PR list to live fetching. `poll_interval_seconds` (int, 120) — worker cycle interval. `history_days` (int, 180) — how far back closed/merged PRs are synced and kept. `max_synced_repos` (int, 10) — most-recently-visited repos kept in sync; the rest fall back to the live path. `exclude_repos` (list, `[]`) — `"owner/name"` strings never synced. |

### Example Configuration

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
  "reviews_dir": "~/code-reviews",
  "review_max_attempts": 3,
  "review_retry_delay_seconds": 30,
  "review_log_retention_days": 90,
  "post_review_started_comment": true,
  "review_section_names": {
    "critical": "Critical Issues",
    "major": "Major Concerns",
    "minor": "Minor Issues"
  }
}
```

---

## Technical Details

### GitHub CLI Integration

The application uses the GitHub CLI (`gh`) for all GitHub API interactions. This approach provides:

**Advantages**:
- No need to manage OAuth tokens or API keys
- Automatic authentication via `gh auth login`
- Rate limiting handled by gh CLI
- Support for GitHub Enterprise

**Implementation**:

```python
def run_gh_command(args, check=True):
    """Run a gh CLI command and return the output."""
    try:
        result = subprocess.run(
            ["gh"] + args,
            capture_output=True,
            text=True,
            check=check,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"gh command failed: {e.stderr}")
    except FileNotFoundError:
        raise RuntimeError("gh CLI not found. Please install GitHub CLI.")
```

**Common Commands Used**:

| Command | Purpose |
|---------|---------|
| `gh api user` | Get authenticated user |
| `gh api user/orgs` | List user's organizations |
| `gh repo list` | List repositories |
| `gh pr list` | List pull requests with filters |
| `gh api repos/.../contributors` | Get contributors |
| `gh api repos/.../labels` | Get labels |
| `gh api repos/.../branches` | Get branches |
| `gh api repos/.../milestones` | Get milestones |
| `gh api repos/.../teams` | Get teams |
| `gh api repos/.../stats/contributors` | Get commit statistics |
| `gh api repos/.../stats/code_frequency` | Get weekly code additions/deletions |
| `gh api repos/.../stats/commit_activity` | Get weekly commit activity |
| `gh api repos/.../stats/participation` | Get owner vs. community participation |
| `gh api repos/.../compare/{base}...{head}` | Get branch comparison (ahead/behind) |
| `gh api repos/.../actions/workflows` | List repository workflows |
| `gh api repos/.../actions/runs` | List workflow runs with filters |
| `gh api repos/.../pulls/.../reviews` | Get PR reviews |

### Caching Mechanism

The application implements a simple TTL-based in-memory cache:

```python
cache = {}  # Global cache dictionary

def cached(ttl_seconds=None):
    """Decorator for caching function results."""
    if ttl_seconds is None:
        ttl_seconds = config.get("cache_ttl_seconds", 300)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            qs = request.query_string.decode() if request else ''
            cache_key = f"{func.__name__}:{args}:{sorted(kwargs.items())}:{qs}"
            now = time.time()

            if cache_key in cache:
                result, timestamp = cache[cache_key]
                if now - timestamp < ttl_seconds:
                    return result

            result = func(*args, **kwargs)
            cache[cache_key] = (result, now)
            return result

        return wrapper

    return decorator
```

**Characteristics**:
- **Scope**: Per-process, in-memory
- **TTL**: Configurable, default 5 minutes
- **Key Generation**: Function name + arguments + keyword arguments + request query string
- **Invalidation**: Manual via `/api/clear-cache` endpoint or process restart

### Cache Timestamps

All cached endpoints include metadata fields so the frontend can show data freshness:

| Field | Type | Description |
|-------|------|-------------|
| `last_updated` | string (ISO 8601) | UTC timestamp of when the cached data was last fetched, with "Z" suffix |
| `cached` | boolean | Whether the response was served from cache |
| `stale` | boolean | Whether the cached data has exceeded its TTL |
| `refreshing` | boolean | Whether a background refresh is currently in progress |

**Endpoints with cache metadata**: `/stats`, `/lifecycle-metrics`, `/review-responsiveness`, `/code-activity`, `/contributor-timeseries`, `/workflow-runs`

The frontend displays a subtle "Updated X ago" indicator on each cached view using the `CacheTimestamp` component. When data is stale and a background refresh is in progress, the indicator shows "Updated X ago · refreshing..."

### Workflow Cache (SQLite + Stale-While-Revalidate)

The CI/Workflows endpoint uses a dedicated SQLite cache for persistent, filter-independent caching of workflow runs.

**Strategy**: Cache 1000 unfiltered runs per repo in SQLite. Apply filters in Python on every request. Background refresh on a configurable interval (default 1 hour) keeps data fresh.

**How It Works**:
1. On first request for a repo, fetch up to 1000 unfiltered runs via parallel API calls (10 pages max, batched through `ThreadPoolExecutor(max_workers=5)`), save to SQLite
2. On subsequent requests, serve from SQLite cache (~5-10ms) with Python-side filtering
3. When cache is stale, return stale data immediately and trigger background refresh
4. Changing filters does not trigger a re-fetch — all filtering happens on the cached data
5. On server startup, a daemon thread checks for stale cached repos and refreshes them

**Parallel Fetching**: Pages are fetched in 3 batches (pages 1-3, 4-8, 9-10) to minimize wall-clock time. Each batch uses up to 5 parallel workers. Fetching stops early if any page returns < 100 runs.

**Pre-seeding**: The `seed_workflow_cache.py` script can pre-populate the cache before launching the app:
```bash
python seed_workflow_cache.py owner/repo1 owner/repo2    # seed specific repos
python seed_workflow_cache.py --refresh                   # re-seed all cached repos
```

**Performance Impact**:

| Scenario | Before | After |
|----------|--------|-------|
| Cold fetch | 4-5 sequential calls (~4-8s) | 12 calls in parallel batches (~3-5s) |
| Same filters (cached) | In-memory hit (~0ms) | SQLite hit + filter (~5-10ms) |
| Different filters (cached) | Full re-fetch (~4-8s) | SQLite hit + filter (~5-10ms) |
| After process restart | Full re-fetch per combo | SQLite hit (~5-10ms) |

### Error Handling

The application implements error handling at multiple levels:

**Backend**:

1. **gh CLI Errors**: Caught and converted to RuntimeError with stderr message
2. **Missing gh CLI**: Specific FileNotFoundError handling with helpful message
3. **JSON Parse Errors**: Returns empty array/object on invalid JSON
4. **API Errors**: Returns 500 status with error message in response body

**Frontend**:

1. **Network Errors**: Caught in fetch calls, displayed in error state
2. **API Errors**: Error messages displayed with retry button
3. **Empty States**: Handled gracefully with informative messages

**GitHub Stats API Handling**:

GitHub stats endpoints (`stats/contributors`, `stats/code_frequency`, `stats/commit_activity`, `stats/participation`) may return HTTP 202 while computing statistics. The application implements a reusable helper with retry logic:

```python
def fetch_github_stats_api(owner, repo, endpoint, jq_query=None, max_retries=3, retry_delay=2):
    """Fetch data from GitHub's stats API with 202-retry logic."""
    for attempt in range(max_retries):
        result = subprocess.run(
            ["gh", "api", f"repos/{owner}/{repo}/{endpoint}", "-i"],
            capture_output=True, text=True, check=False,
        )
        if "HTTP/2.0 202" in result.stdout or "202 Accepted" in result.stdout:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            else:
                return []
        # ... fetch with optional jq query and parse
    return []
```

This helper is used by:
- `fetch_contributor_stats()` for developer statistics
- `get_code_activity()` for commit frequency, code churn, and participation data

### Parallel API Fetching

The application uses `concurrent.futures.ThreadPoolExecutor` for parallel API calls in performance-critical paths:

| Usage | Max Workers | Description |
|-------|-------------|-------------|
| Branch divergence | 5 | Batch compare API calls for all open PRs |
| PR review times | 5 | Fetch reviews for each PR in lifecycle/responsiveness endpoints |

```python
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=5) as executor:
    futures = [executor.submit(fetch_one, pr) for pr in pr_list]
    for future in futures:
        number, result = future.result()
```

### GraphQL Node Limits

GitHub's GraphQL API has a limit of 500,000 nodes per request. To prevent errors:

1. PR results are capped at 100 (hard limit in code)
2. Heavy nested fields (commits, comments, reviews) are excluded from the PR query
3. Developer stats fetch reviews separately per PR

### Logging

The application uses Python's built-in logging module for operational visibility:

```python
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)
```

**Logged Events**:

| Event | Level | Description |
|-------|-------|-------------|
| Review request received | INFO | When a new review is requested |
| Review process started | INFO | Includes PID and PR details |
| Review completed | INFO | Successful review completion |
| Review failed | ERROR | Includes exit code and error output |
| Exited 0 without output | ERROR | Clean exit that wrote no review file; counted as a failed attempt |
| Review attempt failed | WARNING | Includes attempt number, limit, and retry delay |
| Retry attempt started | INFO | Includes attempt number and new PID |
| Gave up after N attempts | ERROR | Attempt limit reached; review recorded as failed |
| Review cancelled | INFO | When user cancels a review |
| Process termination | WARNING | If process required kill signal |

### Subprocess Management (Code Reviews)

Code reviews run as detached subprocesses managed by the Flask backend:

```python
process = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)
```

**Characteristics**:
- **Non-blocking**: `Popen` returns immediately
- **Output capture**: stdout/stderr piped for error reporting
- **Status polling**: `process.poll()` checks completion without blocking
- **Graceful termination**: `terminate()` then `kill()` if needed
- **Thread safety**: Access protected by `reviews_lock`

**Lifecycle**:
1. Request received → process spawned
2. Process reference stored in `active_reviews`
3. Frontend polls `/api/reviews` every 5 seconds
4. On poll, backend calls `poll()` on each process
5. When `poll()` returns exit code, the attempt is judged (see below) and the status updated
6. stderr captured for failed reviews
7. Process removed on cancellation or after viewing error

#### Attempt Outcome and Retries

An exit code of 0 is **not** sufficient to call a review successful. The Claude
CLI can exit cleanly having written neither output file — most often because the
wrapper delegated the review to a background agent and then ended its turn,
which kills the agent mid-review. Recording that as `completed` stores a
0-score error stub that is indistinguishable in the UI from a genuine failing
review, and (for follow-ups) feeds an empty "previous review" into the next
round's prompt.

`check_review_status()` therefore classifies each attempt as successful only
when **both** conditions hold:

- the process exited 0, and
- `review_produced_output()` finds either the `.md` or the `.json` file on disk

A failed attempt is retried up to `review_max_attempts` times in total, with a
`review_retry_delay_seconds` backoff between attempts:

| State | Meaning |
|-------|---------|
| `attempt` | 1-based index of the attempt currently running |
| `retry_at` | `time.monotonic()` deadline; non-`None` means a retry is armed |
| `spawn` | The verbatim `start_review_process()` kwargs, so a retry reproduces the same run (including `is_followup` and the previous review content) |

Design notes:

- **The reported status stays `running` across retries.** The frontend's
  `ActiveReview.status` is a closed union of `running | completed | failed`, and
  `ReviewPollingManager` stops polling once nothing is `running`; a distinct
  `retrying` status would stall the UI. Retries are an internal detail — the
  review is genuinely still in progress. The attempt number is surfaced as the
  `attempt` field on `GET /api/reviews` for visibility.
- **The backoff never sleeps under the lock.** A retry arms a `retry_at`
  deadline; the next poll (the auto-verdict watcher ticks every 10s) spawns the
  next attempt. Sleeping inside `check_review_status()` would stall every other
  review's poll and hold `reviews_lock` for the duration.
- **Retries do not re-announce the review.** `post_review_started_comment()` is
  called once from `begin_review()`, not per attempt, so a retried review does
  not spam the PR conversation.
- **A spawn failure is terminal.** If `start_review_process()` cannot start the
  CLI at all (missing binary), the review is recorded as failed immediately
  rather than burning the remaining attempts on an unfixable error.
- Each attempt writes to a freshly timestamped file for follow-ups, so a
  partial file from a dead attempt is never mistaken for the retry's output.

#### Follow-up Parent Selection

A review that exhausts every attempt is still persisted — with the `{"error":
true}` content stub, which carries no findings. That stub must never become a
follow-up's parent: `json_to_markdown()` renders it as an empty review body with
a bare **Score: 0/10**, so the follow-up prompt asks the reviewer to track
resolution against an empty issue list.

`begin_review()` therefore resolves the parent through `_is_error_stub()` and
`_find_usable_previous_review()` rather than taking whatever review is newest:

| Situation | Parent chosen |
|-----------|---------------|
| Newest review has findings | That review (unchanged) |
| Newest review is a stub | The most recent earlier review with findings |
| Every review within `PREVIOUS_REVIEW_SEARCH_LIMIT` is a stub | None — falls back to a normal review |
| `previous_review_id` names a review with findings | That review (unchanged) |
| `previous_review_id` names a stub | Falls through to the search above |

**Walking back rather than starting fresh** is the deliberate choice. Falling
back to a normal review would discard findings the PR still has open, and spend
a full review run that cannot do resolution tracking. The earlier findings remain
the right thing to track against — a failed attempt says nothing about the code.

Content that is present but not valid JSON is *not* treated as a stub. It is
passed through verbatim, matching `start_review_process()`, which falls back to
the raw string when `json_to_markdown()` cannot parse it.

Note that `get_latest_review_for_pr()` is deliberately left unfiltered. Its other
callers — the auto follow-up watcher's new-commit check and the divergence badge
endpoints — want the newest review whatever its content, because a stub still
records a valid `head_commit_sha`.

### Review JSON Schema

Reviews are stored as structured JSON in the `content_json` column. The schema is versioned to support future evolution.

#### Schema Version: 1.0.0

```json
{
  "schema_version": "1.0.0",
  "metadata": {
    "pr_number": 123,
    "repository": "owner/repo",
    "pr_title": "Add new feature",
    "author": "developer",
    "pr_url": "https://github.com/owner/repo/pull/123",
    "review_date": "2024-01-15",
    "review_type": "initial",
    "branch": { "head": "feature-branch", "base": "main" },
    "files_changed": 5,
    "additions": 150,
    "deletions": 50
  },
  "summary": "Brief overall assessment of the PR.",
  "score": {
    "overall": 8,
    "breakdown": [
      { "category": "Correctness", "score": 9, "comment": "All logic paths handled" },
      { "category": "Design", "score": 7, "comment": "Minor coupling concerns" }
    ],
    "summary": "Well-structured PR with minor design concerns."
  },
  "sections": [
    {
      "type": "critical",
      "display_name": "Critical Issues",
      "issues": [
        {
          "title": "Race condition in check_and_hold",
          "location": { "file": "src/service.rs", "start_line": 123, "end_line": 145 },
          "problem": "Concurrent access without lock.",
          "fix": "Wrap in mutex guard."
        }
      ]
    },
    { "type": "major", "display_name": "Major Concerns", "issues": [] },
    { "type": "minor", "display_name": "Minor Issues", "issues": [] }
  ],
  "highlights": [
    "Good test coverage for the new endpoint.",
    "Clean separation of concerns in the service layer."
  ],
  "recommendations": [
    { "priority": "must_fix", "text": "Fix the race condition before merge." },
    { "priority": "medium", "text": "Consider extracting the validation logic into a shared helper." }
  ]
}
```

#### Key Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema_version` | string | Yes | Semver version of the schema (currently `"1.0.0"`) |
| `metadata` | object | Yes | PR identification and review context |
| `metadata.repository` | string | Yes | Repository in `owner/repo` format |
| `summary` | string | Yes | Brief overall assessment |
| `score.overall` | integer | Yes | Overall score (0-10) |
| `score.breakdown` | array | No | Optional array of `{category, score, comment}` |
| `sections` | array | Yes | Array of `{type, display_name, issues}` objects |
| `highlights` | array | No | Positive aspects of the PR |
| `recommendations` | array | No | Array of `{priority, text}` objects |

#### Validation and Conversion

The `review_schema.py` service module provides:

- **`validate_review_json(data)`**: Validates a review object against the schema, returning errors if any required fields are missing or malformed
- **`json_to_markdown(data)`**: Converts structured JSON to human-readable markdown for display and file export
- **`markdown_to_json(text)`**: Best-effort conversion of legacy markdown reviews into the structured JSON format
- **`get_section_display_names()`**: Returns the configured display names for each section key (customizable via `review_section_names` in config)
- **`SCHEMA_VERSION`**: Current schema version constant (`"1.0.0"`)

The formal JSON Schema specification is available at `backend/services/review_schema_spec.json` for use by external tools and agents.

### Audit JSON Schema

PB↔ED audits are stored as structured JSON in the `audits.content_json` column, distinct from the review schema. The formal specification lives at `backend/services/audit_schema_spec.json`; `backend/services/audit_schema.py` provides `validate_audit_json()`, `audit_json_to_markdown()`, `compute_audit_tallies()`, and `AUDIT_SCHEMA_VERSION`. The same shape is documented for the skill in `_AUDIT_SCHEMA_INSTRUCTIONS` (`backend/services/audit_service.py`) and in the `/pb-ed-audit` skill's JSON-output section.

#### Schema Version: 1.0.0

```json
{
  "schema_version": "1.0.0",
  "format": "audit",
  "audit_type": "pb_ed",
  "metadata": {
    "pr_number": 123,
    "repository": "owner/repo",
    "pr_url": "https://github.com/owner/repo/pull/123",
    "pr_title": "Add bulk export",
    "head_ref": "feature-branch",
    "base_ref": "main",
    "parent_pb": { "id": "PB-017", "title": "Export", "status": "approved" },
    "eds": [{ "id": "ED-010", "title": "Bulk export design" }],
    "auditor": "pb-ed-audit",
    "date": "2026-06-05",
    "scope": "PB↔ED parity + cross-ED consistency"
  },
  "executive_summary": "Action-bucketed summary markdown.",
  "audits": [
    {
      "key": "A",
      "name": "Cross-ED consistency",
      "verdict": "Coherent, one inconsistency.",
      "tally": { "CONTRADICTION": 0, "INCONSISTENCY": 1, "INFO": 2 },
      "findings": []
    },
    {
      "key": "B",
      "name": "PB↔ED parity",
      "verdict": "One scope violation to decide.",
      "tally": { "SCOPE-VIOLATION": 1, "UN-ANCHORED": 1 },
      "findings": [
        {
          "id": "PE-1",
          "severity": "SCOPE-VIOLATION",
          "blocking": true,
          "rule_id": "ED.SCOPE.PB_DEFERRED_IMPLEMENTED",
          "rule_authority": "SPEC-AUTH-0012",
          "lens": "SDLC",
          "summary": "ED-010 implements the P2-deferred bulk-export endpoint.",
          "locations": [
            {
              "file": "docs/designs/ED-010-export.md",
              "line": 389,
              "ref": "ED-010 §10:389",
              "quote": "Expose POST /exports/bulk returning a job id."
            }
          ],
          "detail": "PB-017 lists bulk export under P2 (deferred).",
          "recommendation": "Amend PB-017 to P1, or descope from ED-010."
        }
      ]
    }
  ],
  "verified_clean": "What passed / was correctly scoped (markdown).",
  "supplementary_notes": "Auditor-spotted items outside the two audits (markdown).",
  "action_map": [
    { "priority": "Decide", "finding_ids": ["PE-1"], "nature": "In/out scope decision" }
  ]
}
```

#### Key Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema_version` | string | Yes | `"1.0.0"` |
| `format` | string | Yes | `"audit"` (distinguishes from review JSON) |
| `audit_type` | string | Yes | `"pb_ed"` |
| `metadata` | object | Yes | PR identification + `parent_pb`, `eds`, auditor, date, scope. `pr_number` and `repository` required |
| `audits` | array | Yes | One entry per audit run (`{key, name, verdict, tally, findings}`); Audit A omitted for single-ED PRs |
| `executive_summary` | string | No | Action-bucketed summary markdown |
| `verified_clean` | string | No | What passed / was correctly scoped |
| `supplementary_notes` | string | No | Auditor-spotted items outside the two audits |
| `action_map` | array | No | `{priority, finding_ids, nature}` rows |

Each **finding** requires `id`, `severity` (uppercase token: `CONTRADICTION`, `SCOPE-VIOLATION`, `INCONSISTENCY`, `UN-ANCHORED`, `UNDER-COVERAGE`, `INFO`), and `summary`. Optional fields include `blocking`, `rule_id`, `rule_authority`, `concept`, `lens`, `detail`, `recommendation`, and `locations`. Each `locations[]` entry carries `file` (repo-relative path), `line` (integer or null), `ref` (human display reference), and `quote`. The resolved `file` + integer `line` are what enable a finding to be posted as an inline PR comment.

---

## Future Considerations

### Potential Improvements

#### Performance

1. ~~**Persistent Caching**: Implement Redis or SQLite caching for cross-process/restart persistence~~ **Implemented**: SQLite database now provides persistent storage for reviews and merge queue
2. **Pagination**: Add infinite scroll or pagination for large result sets
3. **Incremental Loading**: Load PR details on-demand rather than in bulk
4. **WebSocket Updates**: Real-time updates for PR status changes

#### Features

1. **PR Comparison**: Side-by-side comparison of multiple PRs
2. **Saved Filters**: Save and name filter presets
3. **Export Functionality**: Export PR lists and stats to CSV/JSON
4. **Notification Integration**: Browser notifications for PR updates
5. **Multi-Repository View**: View PRs across multiple repositories simultaneously
6. ~~**Custom Dashboards**: User-configurable dashboard widgets~~ **Implemented**: Analytics tab with 5 sub-tabs (Stats, Lifecycle, Activity, Reviews, Contributors) and CI/Workflows tab
7. **PR Templates**: Quick filter templates (e.g., "My Open PRs", "Needs My Review")
8. ~~**CI/Workflow Visibility**: View workflow run history and pass/fail rates~~ **Implemented**: CI/Workflows tab with filters, stats cards, and runs table
9. ~~**PR Lifecycle Metrics**: Time-to-merge and review responsiveness tracking~~ **Implemented**: Lifecycle and Reviews sub-tabs in Analytics
10. ~~**Branch Staleness Detection**: Show how far behind base branch a PR is~~ **Implemented**: Branch divergence badges on PR cards

#### User Experience

1. **Keyboard Shortcuts**: Navigation and actions via keyboard
2. **PR Preview**: Hover preview of PR details
3. **Bulk Actions**: Select and act on multiple PRs
4. ~~**History**: Track recently viewed PRs and repositories~~ **Implemented**: Review History panel provides full review history access

#### Technical

1. ~~**TypeScript**: Add type safety to frontend code~~ **Implemented**: Frontend rewritten in React + TypeScript
2. **Testing**: Add unit and integration tests
3. **Docker Support**: Containerized deployment option
4. **Authentication Options**: Support for multiple authentication methods
5. **Rate Limit Handling**: Better handling and display of GitHub rate limits
6. **Offline Support**: Service worker for offline access to cached data

### Known Limitations

1. **Single User**: Designed for single-user local use
2. ~~**No Persistence**: Cache and active reviews lost on restart~~ **Resolved**: Review history and merge queue now persist to SQLite database
3. **Rate Limits**: Subject to GitHub API rate limits via gh CLI
4. **Large Repositories**: Stats fetching may be slow for repos with many PRs
5. **Teams Endpoint**: May fail for personal repositories (non-fatal)
6. **Review Stats Sampling**: Reviews fetched for a configurable number of PRs (default 250, set via `review_sample_limit` in config.json)
7. **Claude CLI Required**: Code review feature requires Claude CLI installed and authenticated
8. **One Review Per PR**: Cannot run multiple concurrent reviews for the same PR
9. **Active Review Volatility**: In-progress reviews lost if server restarts mid-review (completed reviews are persisted)
10. **Fixed Review Output Path**: Reviews always written to hardcoded directory
11. **Score Extraction Heuristic**: Score parsing relies on regex patterns; unusual formats may not be detected
12. **Migration One-Time**: Data migration from legacy JSON/markdown runs once; subsequent manual additions to old format not auto-imported
13. **Stats API Availability**: GitHub stats endpoints return 202 while computing; data may be unavailable for first request on cold repositories
14. **Lifecycle PR Limit**: Lifecycle and review responsiveness metrics analyze the most recent PRs (default 250, configurable via `review_sample_limit`)
15. **Divergence API Calls**: Branch divergence fetches one compare API call per open PR, which may be slow for repositories with many open PRs
16. **Code Activity Max Range**: Code activity is limited to 52 weeks maximum (GitHub API limitation)
17. **Mixed Chart Rendering**: Activity bar charts use CSS-only rendering (no click handlers, zoom, or drill-down); Contributor time series charts use recharts with interactive tooltips and legend toggling

---

## Appendix

### Dependencies

**Backend**:
- Python 3.x
- Flask
- GitHub CLI (`gh`) - required for GitHub API access
- Claude CLI (`claude`) - optional, required for code review feature

**Frontend**:
- React 18 + TypeScript
- Vite (build tool)
- Zustand (state management)
- Recharts (interactive line charts)
- Framer Motion (timeline modal animations)
- Node.js 18+

### File Structure

```
gh-pr-explorer/
├── app.py                          # Thin launcher: create_app() + app.run()
├── database.py                     # Thin re-export layer for backward compat with scripts
├── migrate_data.py                 # Data migration script for legacy JSON/markdown files
├── seed_workflow_cache.py          # Pre-seeds workflow cache for faster first load
├── scripts/
│   └── review_converter.py         # Bidirectional CLI converter: JSON <-> markdown
├── pr_explorer.db                  # SQLite database file (auto-created)
├── config.json                     # Application configuration
├── requirements.txt                # Python dependencies
├── CLAUDE.md                       # Development instructions
├── docs/
│   └── DESIGN.md                   # This document
│
├── backend/                        # Flask backend package
│   ├── __init__.py                 # create_app() factory, startup_refresh_workflow_caches()
│   ├── config.py                   # AppConfig loading, PROJECT_ROOT, REVIEWS_DIR, DB_PATH
│   ├── extensions.py               # Shared singletons: logger, cache, active_reviews, locks
│   │
│   ├── database/                   # SQLite database layer
│   │   ├── __init__.py             # Singleton factory functions (get_reviews_db, etc.)
│   │   ├── base.py                 # Database base class (connection, schema, migrations)
│   │   ├── reviews.py              # ReviewsDB
│   │   ├── merge_queue.py          # MergeQueueDB
│   │   ├── settings.py             # SettingsDB
│   │   ├── dev_stats.py            # DeveloperStatsDB
│   │   └── cache_stores.py         # LifecycleCacheDB, WorkflowCacheDB, ContributorTSCacheDB, CodeActivityCacheDB, TimelineCacheDB
│   │
│   ├── services/                   # Business logic layer
│   │   ├── github_service.py       # gh CLI wrapper: run_command, parse_json, fetch_stats_api
│   │   ├── pr_service.py           # PR post-processing: review_status, ci_status
│   │   ├── stats_service.py        # Dev stats aggregation from 3 sources
│   │   ├── review_service.py       # Claude CLI subprocess management
│   │   ├── inline_comments_service.py  # Critical issue parsing + posting to GitHub
│   │   ├── lifecycle_service.py    # PR review times fetch (ThreadPoolExecutor)
│   │   ├── workflow_service.py     # Parallel batch workflow data fetching
│   │   ├── activity_service.py     # Code activity data from 3 stats APIs
│   │   ├── contributor_service.py  # Contributor time series transform
│   │   ├── timeline_service.py     # PR timeline: normalize + fetch + cache-aware get
│   │   ├── review_schema.py        # Review JSON schema, validation, JSON<->markdown conversion
│   │   ├── review_schema_spec.json # Formal JSON Schema file for external tools/agents
│   │   └── repo_stats_service.py       # Parallel repo stats fetching + LOC analysis
│   │
│   ├── filters/                    # Request parameter processing
│   │   └── pr_filter_builder.py    # PRFilterParams dataclass + PRFilterBuilder -> gh CLI args
│   │
│   ├── cache/                      # Caching infrastructure
│   │   └── memory_cache.py         # In-memory TTL cache decorator (@cached)
│   │
│   ├── visualizers/                # Data transformation for charts/tables
│   │   ├── activity_visualizer.py  # Slice 52-week data by timeframe, compute summary stats
│   │   ├── workflow_visualizer.py  # Apply filters to cached runs, compute aggregate stats
│   │   ├── lifecycle_visualizer.py # Merge time distribution, stale PR detection, pr_table
│   │   └── responsiveness_visualizer.py  # Reviewer leaderboard, bottleneck detection
│   │
│   └── routes/                     # Flask Blueprints (12 blueprints)
│       ├── __init__.py             # register_blueprints(app)
│       ├── static_routes.py        # / and /assets/<path>
│       ├── auth_routes.py          # /api/user, /api/orgs
│       ├── repo_routes.py          # /api/repos, contributors, labels, branches, milestones, teams
│       ├── pr_routes.py            # /api/repos/.../prs, prs/divergence
│       ├── analytics_routes.py     # /api/repos/.../stats, lifecycle, responsiveness, activity, contributors
│       ├── workflow_routes.py      # /api/repos/.../workflow-runs
│       ├── queue_routes.py         # /api/merge-queue CRUD + reorder + notes
│       ├── review_routes.py        # /api/reviews CRUD + status + inline-comments + check-new-commits
│       ├── history_routes.py       # /api/review-history list, detail, PR reviews, stats, check
│       ├── settings_routes.py      # /api/settings CRUD
│       ├── automation_routes.py    # /api/reviewers CRUD + /api/automation/config
│       ├── cache_routes.py         # /api/clear-cache
│       └── repo_stats_routes.py        # /api/repos/.../repo-stats, repo-stats/loc
│   │
│   └── tests/                      # Pytest suite
│       ├── __init__.py
│       ├── conftest.py             # Adds project root to sys.path
│       ├── test_timeline_cache_db.py
│       ├── test_timeline_service.py
│       └── fixtures/
│           └── timeline_raw.json
│
├── frontend/                       # React + TypeScript frontend
│   ├── src/
│   │   ├── api/                    # Type-safe API modules
│   │   │   └── timeline.ts         # fetchTimeline()
│   │   ├── components/             # React components by feature
│   │   │   ├── /repo-stats       # RepoStatsView
│   │   │   └── timeline/           # PR Timelines modal
│   │   │       ├── TimelineModal.tsx
│   │   │       ├── TimelineHeader.tsx
│   │   │       ├── TimelineFilters.tsx
│   │   │       ├── TimelineView.tsx
│   │   │       ├── TimelineEventRow.tsx
│   │   │       └── eventBodies/
│   │   │           ├── CommitBody.tsx
│   │   │           ├── CommentBody.tsx
│   │   │           ├── ReviewBody.tsx
│   │   │           ├── StateChangeBody.tsx
│   │   │           ├── ReviewRequestedBody.tsx
│   │   │           └── ForcePushBody.tsx
│   │   ├── stores/                 # Zustand state management
│   │   │   └── useTimelineStore.ts # Timeline modal state + timelineKey helper
│   │   ├── styles/                 # CSS styles
│   │   │   └── timeline.css        # Timeline modal styles
│   │   ├── types/                  # TypeScript types
│   │   ├── App.tsx                 # Root component
│   │   └── main.tsx                # Entry point
│   ├── dist/                       # Production build output (generated)
│   ├── vite.config.ts              # Vite configuration
│   ├── tsconfig.json               # TypeScript config
│   └── package.json                # Frontend dependencies

External Dependencies:
├── /Users/jvargas714/Documents/code-reviews/              # Code review output directory
└── /Users/jvargas714/Documents/code-reviews/past-reviews/ # Historical reviews (migrated)
```

**Note**: The `MQ/` folder with `merge_queue.json` has been deprecated. Merge queue data is now stored in the SQLite database. The legacy `static/` and `templates/` directories have been removed as part of the migration to React + TypeScript. The root `database.py` is a thin re-export layer for backward compatibility with `migrate_data.py` and `seed_workflow_cache.py`.

### Running the Application

#### Development Mode (two terminals)

```bash
# Terminal 1: Start the Flask API backend
pip install -r requirements.txt
gh auth login
python app.py
# API runs on http://127.0.0.1:5714

# Terminal 2: Start the Vite dev server
cd frontend
npm install
npm run dev
# Frontend runs on http://localhost:3050 (proxies API to :5714)
```

#### Production Mode

```bash
# Build the frontend
cd frontend
npm install
npm run build

# Start the Flask backend (serves built frontend from frontend/dist/)
cd ..
python app.py
# Access at http://127.0.0.1:5714
```

**Note**: Ensure `gh` CLI is authenticated via `gh auth login`. For the code review feature, Claude CLI must also be installed and authenticated.

### Using the Code Review Feature

1. Select a repository and load PRs
2. Click the review button (clipboard icon) on any PR card
3. The button shows a spinner while the review runs
4. Check `/Users/jvargas714/Documents/code-reviews/` for review output
5. If review fails, click the red X button to see error details
