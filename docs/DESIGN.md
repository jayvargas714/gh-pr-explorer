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

11 Flask Blueprints organized by domain. Each route handler is thin (parse request → call service → convert → jsonify).

| Blueprint | Routes |
|-----------|--------|
| `static_bp` | `/`, `/assets/<path>` |
| `auth_bp` | `/api/user`, `/api/orgs` |
| `repo_bp` | `/api/repos`, contributors, labels, branches, milestones, teams |
| `pr_bp` | `/api/repos/.../prs`, `/api/repos/.../prs/divergence` |
| `analytics_bp` | `/api/repos/.../stats`, lifecycle-metrics, review-responsiveness, code-activity, contributor-timeseries |
| `workflow_bp` | `/api/repos/.../workflow-runs` |
| `queue_bp` | `/api/merge-queue` CRUD, reorder, notes |
| `review_bp` | `/api/reviews` CRUD, status, inline-comments, check-new-commits |
| `history_bp` | `/api/review-history` list, detail, PR reviews, stats, check |
| `settings_bp` | `/api/settings` CRUD |
| `cache_bp` | `/api/clear-cache` |

### Database Module

**Package**: `/Users/jvargas714/Documents/dev/gh-pr-explorer/backend/database/`

The database module provides SQLite-based persistence for reviews and merge queue data, replacing the previous JSON file storage. A thin re-export layer at `database.py` (root) provides backward compatibility for scripts.

#### Database Classes

| Class | Description |
|-------|-------------|
| `Database` | Base class managing SQLite connection and schema initialization |
| `ReviewsDB` | Handles review storage, retrieval, and search operations |
| `MergeQueueDB` | Manages merge queue persistence and ordering |
| `DevStatsDB` | Caches developer statistics with 4-hour TTL for improved performance |
| `LifecycleCacheDB` | Caches PR lifecycle and review timing data with 2-hour TTL |
| `WorkflowCacheDB` | Caches workflow runs data with configurable TTL (default 1 hour) for stale-while-revalidate serving |
| `ContributorTimeSeriesCacheDB` | Caches per-contributor weekly time series data with 24-hour TTL for stale-while-revalidate serving |
| `CodeActivityCacheDB` | Caches full 52-week code activity data with 24-hour TTL for stale-while-revalidate serving |

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
| Review Workflows | `engine` | Composable review pipeline runs with human gates |

#### Analytics Sub-tabs

| Sub-tab | Tab Key | Description |
|---------|---------|-------------|
| Stats | `stats` | Developer contribution statistics table |
| Lifecycle | `lifecycle` | PR lifecycle metrics, merge time distribution, stale PR detection |
| Activity | `activity` | Code activity charts: commits, code changes, top 5 contributors |
| Reviews | `responsiveness` | Per-reviewer response times, leaderboard, bottleneck detection |
| Contributors | `contributors` | Interactive per-contributor time series charts (commits, additions, deletions) |

### Workflow Engine (Review Workflows Tab)

The Review Workflows tab provides a UI for composable code review pipelines implementing the legacy adversarial review system. Built on a generic workflow engine with typed step executors, fan-out/fan-in parallelism, human gates, and expert domain selection.

#### Backend Packages

**Agents** (`backend/agents/`):

| Module | Description |
|--------|-------------|
| `base.py` | `AgentBackend` ABC with `start_review`, `check_status`, `get_output`, `cancel`, `cleanup` lifecycle methods; `AgentHandle`, `AgentStatus`, `ReviewArtifact` |
| `claude_cli.py` | `ClaudeCLIAgent` — wraps subprocess calls to `claude` CLI with live output streaming. `cancel()` terminates subprocess and calls `cleanup()` to close pipes and remove `_processes` entries |
| `openai_api.py` | `OpenAIAgent` — OpenAI chat completions via `httpx` |
| `cursor_cli.py` | `CursorCLIAgent` — wraps `agent` CLI with stream-json live output. `cancel()` terminates subprocess and calls `cleanup()` |
| `pid_tracker.py` | Persists active agent subprocess PIDs to `active_agent_pids` table. `register_pid()` on start, `unregister_pid()` on cleanup, `kill_all_tracked()` on server boot to SIGTERM orphaned processes |
| `registry.py` | `get_agent(name)`, `list_agents()`, agent type registry |

**Workflows** (`backend/workflows/`):

| Module | Description |
|--------|-------------|
| `step_types.py` | `StepType` enum, `@register_step` decorator, `STEP_REGISTRY` |
| `executor.py` | `StepExecutor` ABC, `StepResult` dataclass |
| `runtime.py` | `WorkflowRuntime` — level-based parallel execution, fan-out, gate pausing. `_is_cancelled()` checks between levels for cooperative cancellation. `resume_after_gate()` and `retry_from_step()` pre-populate `step_outputs` from DB for correct upstream data routing. `_merge_outputs()` concatenates list-valued keys in `_MERGEABLE_LIST_KEYS` (reviews, findings, followup_results). Module-level `merge_outputs()` alias used by route handlers for consistent output reconstruction |
| `cancellation.py` | Cooperative cancellation registry: `cancel()` signals instance cancellation and terminates registered agents; `is_cancelled()` checked by all polling loops and between runtime levels; `clear()` called by all lifecycle endpoints (run/resume/retry) in `finally` blocks; `register_agent()`/`unregister_agent()` for tracking live agents. `AGENT_POLL_TIMEOUT` (30min) prevents infinite hangs |
| `seed.py` | Built-in templates (Quick/Team/Self/Deep/Follow-Up Review), agents, 10 expert domains, code owners. Uses `WorkflowDB.upsert_code_owner()` abstraction |

**Step Executors** (`backend/workflows/executors/`):

| Module | Step Type | Description |
|--------|-----------|-------------|
| `pr_select.py` | `pr_select` | Fetches PRs via `gh` CLI |
| `prioritize.py` | `prioritize` | P0-P3 scoring, code owner boost, repo-scoped skip list. Preflight check auto-skips PRs the authenticated user has already reviewed on GitHub (parallel API checks via ThreadPoolExecutor) and persists them to skip list |
| `expert_select.py` | `expert_select` | DB-backed domain matching with file/keyword triggers, relevance thresholds, expert count caps |
| `prompt_generate.py` | `prompt_generate` | Structured prompt builder: header, context commands, GitHub API dedup, persona, checklist, anti-patterns, cross-cutting concerns, depth expectations, cross-file analysis, diff ingestion strategy, severity guide, output format. Per-expert fan-out for self/deep review. Severity guide enforces concrete production failure scenarios for blocking/critical findings and caps total findings on large PRs (50+ files) |
| `agent_review.py` | `agent_review` | Dispatches prompt to `AgentBackend`, Review B isolation, live output streaming, domain propagation |
| `synthesis.py` | `synthesis` | Source attribution (A/B/BOTH), synthesis log, NEEDS_DISCUSSION verdict, two-tier synthesis for self/deep review. Multi-path finding preservation: when multiple A-findings match the same B-finding, all are retained as `additional_failure_modes` to prevent synthesis loss. Single-agent critical findings produce NEEDS_DISCUSSION (not CHANGES_REQUESTED); only both-agents-agree critical findings trigger CHANGES_REQUESTED. AI verification prompt includes severity calibration and multi-path preservation instructions |
| `related_issue_scan.py` | `related_issue_scan` | Two-phase analysis: (1) **Deduplication** — compares all findings against each other using codebase context to identify duplicates (same file, overlapping lines, same defect), merging them and removing the less-detailed duplicate; (2) **Related Issue Scan** — scans codebase for structurally similar patterns. Multi-strategy search: keyword grep, structural pattern grep, file role matching. Distinguishes textual vs structural matches to identify false positives (standard patterns) and wider issues (same bug in other files). Applies dedup to synthesis before passing downstream. Outputs `duplicates`, `scanned_findings`, `likely_false_positives`, `confirmed_findings`, `wider_issues` |
| `fp_severity_check.py` | `fp_severity_check` | Expert verification per finding with three checks: correctness (trace execution path, check upstream guards, **base-branch verification for "missing X" claims**), intentionality (codebase-wide pattern analysis using related scan results), impact (concrete production failure scenario required). Base-branch verification mandates checking whether claimed-missing elements exist on the base branch before confirming. Outputs calibrated synthesis with false positives removed and severity adjustments. Preserves `_original_severity` for audit trail. Verified findings include `base_branch_verified` and `base_branch_note` fields |
| `freshness_check.py` | `freshness_check` | SUPERSEDED detection (force-push/rebase), per-finding staleness tagging, justification summaries |
| `human_gate.py` | `human_gate` | Enriched gate payload: synthesis log, questions, checklists, per-domain synthesis, holistic review, related scan, FP check, staleness |
| `publish.py` | `publish` | Rich GitHub comments with blocking findings (file:line, evidence, fix), questions, staleness notes, silent-pass test warnings, auto-creates follow-up entries. Multi-PR iteration via `per_pr` list. Publication dedup: fetches existing reviews/comments and filters already-raised findings before posting. Holistic enrichment: overlays holistic blocking/non-blocking/cross-cutting/silent-pass findings and verdict onto synthesis when available. Multi-path finding expansion: `additional_failure_modes` emitted as separate numbered line items. Fallback for `pr_number` from `prs` list when two-tier synthesis omits top-level PR number. Owner/repo fallback from `full_repo`. Returns `StepResult(success=False)` on GitHub post failure |
| `holistic_review.py` | `holistic_review` | Tier 2 analysis: cross-domain interactions, severity calibration, silent-pass test detection, domain verdict summary, tone enforcement. Minor-to-blocking promotion removed (severity inflation fix). Communication standards enforce professional, goal-oriented language. Silent-pass findings emitted as `silent_pass_findings` in output |
| `followup_check.py` | `followup_check` | Checks PR state, new commits, author responses; classifies follow-up status |
| `followup_action.py` | `followup_action` | Posts follow-up comments using templates (RESOLVED, PARTIALLY_RESOLVED, AUTHOR_DISAGREES, NO_RESPONSE) |

**Database** (`backend/database/workflows.py`): CRUD for templates, instances, steps, artifacts, agents, expert domains, follow-ups, code owners. `base.py` configures SQLite with WAL journal mode and 5s busy_timeout for safe concurrent access from parallel step execution.

**Routes** (`backend/routes/workflow_engine_routes.py`): Template CRUD, instance lifecycle, gate actions (with per-instance mutex for idempotency), instance cancellation (signals running agents via cancellation registry), agent list, expert domain CRUD, follow-up listing. Resume/retry paths use `merge_outputs()` for correct list-valued key concatenation. Per-instance locks (`_get_instance_lock`) prevent duplicate concurrent retry/resume threads. `_set_terminal_status()` prevents background threads from overwriting `cancelled` DB status.

#### Database Tables

```sql
-- Workflow templates (Quick Review, Team Review, Self-Review, Deep Review, Follow-Up Review)
CREATE TABLE workflow_templates (id, name UNIQUE, description, template_json, is_builtin, created_at, updated_at);

-- Workflow run instances
CREATE TABLE workflow_instances (id, template_id FK, repo, status, config_json, created_at, updated_at);

-- Per-step state within an instance
CREATE TABLE instance_steps (id, instance_id FK, step_id, step_type, step_config_json, status, agent_id, inputs_json, outputs_json, started_at, completed_at, error_message);

-- Artifacts produced by steps (reviews, synthesis, comments)
CREATE TABLE instance_artifacts (id, instance_id FK, step_id, pr_number, artifact_type, file_path, content_json, created_at);

-- Registered AI agents
CREATE TABLE agents (id, name UNIQUE, type, model, config_json, is_active, created_at, updated_at);

-- Code owner registry for priority scoring
CREATE TABLE code_owner_registry (id, github_handle UNIQUE, display_name, priority_boost, is_reviewer, created_at, updated_at);

-- PR skip list (repo-scoped)
CREATE TABLE skip_list (id, pr_number, repo, reason, skipped_at, instance_id, UNIQUE(pr_number, repo));

-- Expert domain catalog (10 built-in domains from legacy adversarial spec)
CREATE TABLE expert_domains (id, domain_id UNIQUE, display_name, persona, scope, triggers_json, checklist_json, anti_patterns_json, is_builtin, is_active, created_at);

-- Follow-up tracking for published reviews (ON DELETE CASCADE from workflow_instances)
CREATE TABLE review_followups (id, instance_id, pr_number, repo, source_run_id FK CASCADE, verdict, published_at, review_sha, status DEFAULT 'NO_RESPONSE', last_checked, notes, created_at);
-- Indexes: instance_id, repo+status, source_run_id

-- Per-finding status within a follow-up (ON DELETE CASCADE from review_followups)
CREATE TABLE followup_findings (id, followup_id FK CASCADE, finding_id, original_text, severity, status DEFAULT 'OPEN', author_response, resolution_notes, updated_at);
-- Index: followup_id
```

#### Expert Domain Catalog

10 built-in expert domains seeded from the legacy adversarial review specification:

| Domain | Trigger Patterns | Trigger Keywords |
|--------|-----------------|-----------------|
| rust-api | `routes/*.rs`, `server/*.rs` | `axum::`, `StatusCode`, `handler`, `into_response`, `IntoResponse` |
| database | `models/*.rs`, `migrations/`, `migrations_archive/`, `db/*.rs`, `seeds/*.sql`, `*.sql` | `sqlx::`, `BEGIN`, `COMMIT`, `transaction`, `.execute(`, `pg_dump`, `pg_restore`, `psql`, `backup`, `sync-db`, `connection_limit`, `CONNECTION LIMIT` |
| s3-cloud | — | `s3_client`, `multipart`, `presign`, `upload_id`, `complete_multipart`, `abort_multipart`, `copy_object` |
| concurrency | — | `claim_`, `status.*transition`, `Mutex`, `RwLock`, `atomic`, `race`, `CancellationToken`, `OCC`, `competing` |
| security | `auth[_/]`, `security[_/]`, `middleware/` | `validate_`, `sanitize`, `traversal`, `../`, `role`, `permission`, `auth`, `RBAC`, `secret`, `credential`, `CORS`, `cors`, `rate_limit` |
| testing | `tests/`, `#[test]`, `#[tokio::test]` | `assert`, `mock`, `fixture` |
| infra-ci | `Dockerfile`, `.github/`, `Makefile`, `justfile`, `terraform/`, `*.tf`, `docker-compose` | `pipeline`, `deploy`, `workflow`, `runner`, `build_image`, `CI/CD`, `github_actions`, `release` |
| go-backend | `*.go`, `go.mod` | `goroutine`, `chan`, `sync.`, `http.Handler` |
| cpp-simulator | `*.cc`, `*.cpp`, `*.h` | `ns3::`, `Simulator::`, `congestion`, `cwnd` |
| python-tooling | `*.py`, `requirements.txt`, `pyproject.toml`, `setup.py` | `pip` |

Each domain includes: full persona text, review scope, 5-7 checklist items, 3-4 anti-patterns.

#### Expert Selection Scoring Algorithm

The `_compute_domain_relevance()` scorer uses multi-signal NLP-style matching with:

- **Language exclusion**: Hard-excludes language-specific domains when PR files use a different language (e.g., cpp-simulator excluded from Rust-only PRs, shell-script domains excluded from pure-Rust/Go PRs). Recognized languages: Rust, Python, Go, C++, Java, Kotlin, Scala, JavaScript, TypeScript, Ruby, PHP, Bash/Shell
- **Language match bonus**: 1.4x multiplier when domain's language matches file languages
- **Identity keywords**: Extracted from domain name + scope, matched against files, file signals, and diff
- **Trigger keywords**: Domain-specific high-signal terms (e.g., `CORS`, `sqlx::`) scored independently, not diluted by identity keyword count
- **Title matching**: PR title keywords weighted 8x for identity, 12x for trigger matches
- **File signal detection**: Language/framework signals from extensions (`_EXT_TO_LANG`), directory names (`_DIR_SIGNALS`), and Python-specific basenames (`pyproject.toml`, `poetry.lock`, etc.)
- **Minimum relevance threshold**: 15.0 (domains scoring below are excluded)
- **Expert count cap**: Based on total lines changed (≤300→2, ≤800→3, ≤2000→4, >2000→5)

#### Frontend Components

| Component | File | Description |
|-----------|------|-------------|
| `WorkflowEngineView` | `components/engine/WorkflowEngineView.tsx` | Container routing between list, config, detail, gate, domains, and follow-ups views |
| `WorkflowRunList` | `components/engine/WorkflowRunList.tsx` | Table of instances with status filter bar, "+ New Run", "Expert Domains", "Follow-Ups" actions |
| `RunConfigPanel` | `components/engine/RunConfigPanel.tsx` | Template card picker with mode badges, agent assignment, PR selection, pipeline preview |
| `WorkflowRunDetail` | `components/engine/WorkflowRunDetail.tsx` | Two-panel layout: vertical step timeline (left) + content viewer (right) |
| `StepContentViewer` | `components/engine/StepContentViewer.tsx` | Renders step output by type with collapsible prompt sections, expert domain detail, follow-up views, live agent output |
| `GateView` | `components/engine/GateView.tsx` | Full-page gate: overview, comparison, synthesis log, questions, domains (per-domain synthesis), publish preview, freshness with staleness indicators |
| `ReviewComparison` | `components/engine/ReviewComparison.tsx` | Side-by-side Agent A vs Agent B review columns with synthesis classification |
| `PublishPreview` | `components/engine/PublishPreview.tsx` | Rendered markdown preview of the GitHub comment to be posted |
| `FindingCard` | `components/engine/FindingCard.tsx` | Individual finding: severity badge, file location, problem, fix, source (A/B/BOTH), classification |
| `ExpertDomainManager` | `components/engine/ExpertDomainManager.tsx` | Expandable domain list with persona, checklist, anti-patterns, triggers; create/disable/delete custom domains |
| `FollowUpTracker` | `components/engine/FollowUpTracker.tsx` | Follow-up list with status badges, per-finding resolution table, expandable detail view |

State management via `useWorkflowEngineStore` (Zustand). API client at `api/workflow-engine.ts`.

#### Built-in Templates

| Template | Steps | Description |
|----------|-------|-------------|
| Quick Review | PR Select → Prompt Gen → Agent Review | Single-agent, single-pass review |
| Team Review | PR Select → Prioritize → Prompt Gen → Agent A + Agent B → Synthesis → Related Scan → FP Check → Freshness → Human Gate → Publish | Dual-agent adversarial review with FP filtering |
| Self-Review | PR Select → Expert Select → Prompt Gen → Agent A + Agent B → Synthesis → Related Scan → FP Check → Holistic → Freshness → Human Gate | Multi-expert deep-dive with FP filtering (local only) |
| Deep Review | PR Select → Expert Select → Prompt Gen → Agent A + Agent B → Synthesis → Related Scan → FP Check → Holistic → Freshness → Human Gate → Publish | Multi-expert deep-dive with FP filtering and publication |

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

The final review body is assembled from:
1. Custom text (if provided)
2. Enabled review sections (each preceded by a `---` separator and bold heading)

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

### Workflow Engine

**GET** `/api/templates` — List all workflow templates.

**GET** `/api/templates/<id>` — Get a single template with parsed `template` object.

**POST** `/api/templates` — Create a template. Body: `{name, description?, template}`.

**PUT** `/api/templates/<id>` — Update a non-builtin template.

**POST** `/api/templates/<id>/clone` — Clone a template. Body: `{name?}`.

**POST** `/api/templates/<id>/validate` — Validate template structure. Returns `{valid, errors[]}`.

**DELETE** `/api/templates/<id>` — Delete a non-builtin template.

**POST** `/api/workflows/run` — Start a workflow run. Body: `{template_id, repo, config?}`. Returns `{id, status}`.

**GET** `/api/workflows/instances` — List instances. Query: `?repo=owner/repo`.

**GET** `/api/workflows/instances/<id>` — Get instance with steps and artifacts.

**POST** `/api/workflows/instances/<id>/gate` — Gate action. Body: `{action: "approve"|"reject", ...data}`.

**DELETE** `/api/workflows/instances/<id>` — Cancel a running instance.

**GET** `/api/agents` — List registered AI agents.

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
9. **Active Review Volatility**: In-progress reviews lost if server restarts mid-review (completed reviews are persisted). On restart, orphaned agent subprocesses are automatically killed via `pid_tracker.kill_all_tracked()` and their workflow steps marked as failed with a retry prompt
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
│   │   ├── cache_stores.py         # LifecycleCacheDB, WorkflowCacheDB, ContributorTSCacheDB, CodeActivityCacheDB
│   │   └── workflows.py            # WorkflowDB — CRUD for templates, instances, steps, artifacts, agents
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
│   │   ├── review_schema.py        # Review JSON schema, validation, JSON<->markdown conversion
│   │   └── review_schema_spec.json # Formal JSON Schema file for external tools/agents
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
│   ├── agents/                     # Pluggable AI agent backends
│   │   ├── base.py                 # AgentBackend ABC, AgentHandle, AgentStatus, ReviewArtifact
│   │   ├── claude_cli.py           # ClaudeCLIAgent — wraps subprocess calls to `claude`
│   │   ├── openai_api.py           # OpenAIAgent — OpenAI chat completions via httpx
│   │   └── registry.py             # get_agent(name), list_agents(), agent type registry
│   │
│   ├── workflows/                  # Generic workflow engine
│   │   ├── step_types.py           # StepType enum, @register_step, STEP_REGISTRY
│   │   ├── executor.py             # StepExecutor ABC, StepResult dataclass
│   │   ├── runtime.py              # WorkflowRuntime — topo-sort, fan-out, gate pausing
│   │   ├── seed.py                 # Built-in templates + agents seeded on startup
│   │   └── executors/              # Step executor implementations (10 executors)
│   │       ├── __init__.py
│   │       ├── pr_select.py
│   │       ├── prioritize.py
│   │       ├── prompt_generate.py
│   │       ├── agent_review.py
│   │       ├── synthesis.py
│   │       ├── related_issue_scan.py
│   │       ├── fp_severity_check.py
│   │       ├── freshness_check.py
│   │       ├── human_gate.py
│   │       └── publish.py
│   │
│   └── routes/                     # Flask Blueprints (12 blueprints)
│       ├── __init__.py             # register_blueprints(app)
│       ├── static_routes.py        # / and /assets/<path>
│       ├── auth_routes.py          # /api/user, /api/orgs
│       ├── repo_routes.py          # /api/repos, contributors, labels, branches, milestones, teams
│       ├── pr_routes.py            # /api/repos/.../prs, prs/divergence
│       ├── analytics_routes.py     # /api/repos/.../stats, lifecycle, responsiveness, activity, contributors
│       ├── workflow_routes.py      # /api/repos/.../workflow-runs
│       ├── workflow_engine_routes.py  # /api/templates, /api/workflows/*, /api/agents
│       ├── queue_routes.py         # /api/merge-queue CRUD + reorder + notes
│       ├── review_routes.py        # /api/reviews CRUD + status + inline-comments + check-new-commits
│       ├── history_routes.py       # /api/review-history list, detail, PR reviews, stats, check
│       ├── settings_routes.py      # /api/settings CRUD
│       └── cache_routes.py         # /api/clear-cache
│
├── frontend/                       # React + TypeScript frontend
│   ├── src/
│   │   ├── api/                    # Type-safe API modules (incl. workflow-engine.ts)
│   │   ├── components/             # React components by feature (incl. engine/)
│   │   ├── stores/                 # Zustand state management (incl. useWorkflowEngineStore)
│   │   ├── styles/                 # CSS styles (incl. workflow-engine.css)
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
