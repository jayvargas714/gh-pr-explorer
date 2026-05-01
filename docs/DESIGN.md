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
| `MergeQueueDB` | Manages merge queue persistence and ordering |
| `SwimlanesDB` | Manages swimlane definitions and per-card lane assignments for the Kanban view of the merge queue |
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
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_review_id) REFERENCES reviews(id)
);

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
    UNIQUE(pr_number, repo)
);

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
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_swimlanes_position ON swimlanes(position);

-- Swimlane assignments table: Which lane each merge queue card sits in
CREATE TABLE IF NOT EXISTS swimlane_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_item_id INTEGER NOT NULL UNIQUE,
    swimlane_id INTEGER,
    position_in_lane INTEGER NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (queue_item_id) REFERENCES merge_queue(id) ON DELETE CASCADE,
    FOREIGN KEY (swimlane_id) REFERENCES swimlanes(id) ON DELETE SET NULL
);
CREATE INDEX idx_swl_assign_lane ON swimlane_assignments(swimlane_id);
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

The application uses a 4-tab layout as the primary navigation:

| Tab | View Key | Description |
|-----|----------|-------------|
| Pull Requests | `prs` | PR list with filters, pagination, and action buttons |
| Analytics | `analytics` | 5 sub-tabs for developer and repository analytics |
| CI/Workflows | `workflows` | Workflow run history with filters and aggregate stats |
| Repo Stats | `repo-stats` | Repository-level statistics, language breakdown, LOC analysis |

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

#### Other PR Card Badges

| Badge | Description |
|-------|-------------|
| Draft | Orange badge for draft PRs |
| Review Score | Color-coded score from Claude code review (0-10) |
| New Commits | Indicates commits added since last review |
| Posted | Shows inline comments have been posted to GitHub |
| Branch Divergence | Shows how many commits behind the base branch (open PRs only) |

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

#### UI Components

| Component | Responsibility |
|-----------|----------------|
| `SwimlaneModal` | Full-screen slide-from-right overlay shell, ESC handling, scroll lock |
| `SwimlaneHeader` | Title, card count, "+ Add Lane" inline form, refresh, close |
| `SwimlaneBoard` | `DndContext` orchestrating cross-column and within-column DnD |
| `SwimlaneColumn` | Single lane: colored header, name (inline-editable on double-click), color swatch popover, count badge, `−` delete button, droppable + sortable body |
| `LaneColorPicker` | 8-swatch grid for color selection |
| `QueueItem` (reused) | Renders the same card component used in the merge queue panel — verdict, inline comments, notes, timeline, badges, review actions all work identically |

#### Drag-and-drop

Built on dnd-kit (already used by the merge queue panel — no new dependencies). One `DndContext` at the board level, one `useDroppable` per column with id `lane-{id}`, one `SortableContext` per column over its card ids (numeric `merge_queue.id`). `onDragEnd` discriminates by `over.id` shape:
- numeric → dropped on a card; locate the card's lane and use its index
- string `lane-{id}` → dropped on empty column space; append to that lane

Lane deletion behavior: if the lane is empty, deletion is silent. If it has cards, a confirm dialog warns the cards will move to the default lane. The backend `SwimlanesDB.delete_lane` then re-homes orphaned cards (whose `swimlane_id` was set to NULL by `ON DELETE SET NULL`) to the new default. The last remaining lane cannot be deleted.

#### Persistence

Two SQLite tables:

```sql
swimlanes (id, name, color, position, is_default, created_at)
swimlane_assignments (id, queue_item_id UNIQUE, swimlane_id, position_in_lane, updated_at)
```

`swimlane_assignments.queue_item_id` cascades from `merge_queue(id)`. `swimlane_assignments.swimlane_id` is `ON DELETE SET NULL`, with `delete_lane()` re-homing orphans to the default. On startup, `create_app()` invokes `ensure_default_lane()` and `reconcile_assignments()` to handle drift and bootstrap the feature on existing databases.

#### Live Updates

While the swimlane modal is open, the board silently re-fetches `/api/swimlanes/board` every 45 seconds so card state (PR draft toggles, new commits, CI status, review decisions) stays in sync with GitHub without requiring the user to close and re-open the board. The cadence matches the timeline modal — each refresh enriches every queued PR via `gh pr view`, so a tighter interval would burn through the GitHub rate limit on large queues.

The poll is suspended whenever:
- The browser tab is hidden (no work for an unviewed UI; resumes immediately on `visibilitychange`)
- The user is mid-drag (a refetch would yank cards out from under the cursor)
- A mutation is in flight (`moveCard`, `reorderLanesLocal`) — pollPause is reference-counted so concurrent drag + mutation both contribute and resume independently

The header shows a `CacheTimestamp` indicator ("Updated X ago" / "refreshing…") sourced from `lastUpdated` and `refreshing` flags on the swimlane store. Background refreshes do not flip the modal's `loading` flag and silently swallow transient errors so a brief network blip doesn't surface a banner mid-session.

### Code Review System (Claude CLI Integration)

The Code Review feature integrates with Claude CLI to perform automated code reviews. Reviews run as background subprocesses, with real-time status tracking in the UI. Completed reviews are persisted to the SQLite database for historical access.

#### How It Works

1. User clicks "Review" button on a PR card or queue item
2. Backend spawns a Claude CLI subprocess with the review prompt
3. UI shows spinner while review is in progress
4. Claude CLI uses the `code-reviewer` agent to analyze the PR
5. Review output is written to both a markdown file (`.md`) and a structured JSON file (`.json`)
6. Review metadata and `content_json` are saved to SQLite database; markdown is generated on the fly from `content_json` when needed
7. UI updates to show completed/failed status with score badge
8. Failed reviews display error details in a modal

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
| Event Selector | VerdictModal | Three side-by-side buttons for Approve/Request Changes/Comment |
| Section Toggles | VerdictModal | Checkboxes with collapsible preview for each review section |

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

Each section can be individually toggled on/off and previewed before submission.

#### Composed Body Format

The final review body is assembled from (joined by `\n\n---\n\n`):
1. **Inline issues summary table** (prepended automatically when one or more inline comments will be posted) — a GFM markdown table with `Severity | Issue | Location` columns, sorted critical → major → minor with stable ordering within each severity. Heading: `**Inline issues posted (N)**`. Omitted entirely when no inline comments are selected.
2. Custom text (if provided)
3. Enabled review sections (each preceded by a bold heading)

The summary table gives the GitHub review entry a quick index into the diff comments so an Approve/Request-Changes/Comment verdict is not effectively empty when all content has been posted inline.

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
    "1": [ /* MergeQueueItem-shaped objects (see /api/merge-queue) */ ]
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
{ "assignment": { "queueItemId": 42, "swimlaneId": 3, "positionInLane": 1 } }
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
  "repo": "repo"
}
```

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
5. When `poll()` returns exit code, status updated
6. stderr captured for failed reviews
7. Process removed on cancellation or after viewing error

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
