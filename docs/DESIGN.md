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
- **Zero Authentication Setup**: Leverages existing GitHub CLI (`gh`) authentication
- **Lightweight Deployment**: Single-file Flask backend with CDN-loaded frontend dependencies

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
|   (Vue.js 3 SPA)  |     |   (app.py)        |     |   (gh)            |
|                   |     |                   |     |                   |
+-------------------+     +-------------------+     +-------------------+
        |                         |                         |
        |                         |                         |
        v                         v                         v
+-------------------+     +-------------------+     +-------------------+
|                   |     |                   |     |                   |
|   static/         |     |   In-Memory       |     |   GitHub API      |
|   - js/app.js     |     |   - Cache (TTL)   |     |   (via gh CLI)    |
|   - css/styles.css|     |   - Active Reviews|     |                   |
|                   |     |                   |     |                   |
+-------------------+     +-------------------+     +-------------------+
        |                         |
        |                         v
        |                 +-------------------+     +-------------------+
        |                 |                   |     |                   |
        |                 |   SQLite Database |     |   Claude CLI      |
        |                 |   (database.py)   |<----|   (code reviews)  |
        |                 |   - reviews       |     |                   |
        |                 |   - merge_queue   |     |                   |
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
2. Vue.js Frontend (app.js)
   - Updates reactive state
   - Constructs API request with filters
         |
         v
3. Flask Backend (app.py)
   - Receives HTTP request
   - Checks in-memory cache
   - If cache miss: builds gh CLI command
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
6. Vue.js Frontend
   - Updates reactive state
   - Renders UI components
```

### Backend Components (Flask)

**File**: `/Users/jvargas714/Documents/dev/gh-pr-explorer/app.py`

| Component | Description |
|-----------|-------------|
| `app` | Flask application instance |
| `config` | Configuration loaded from `config.json` |
| `cache` | In-memory dictionary for caching API responses |
| `active_reviews` | In-memory dictionary tracking running code review processes |
| `reviews_lock` | Threading lock for thread-safe review state access |
| `logger` | Python logging instance for application logging |
| `cached()` | Decorator function implementing TTL-based caching |
| `run_gh_command()` | Executes GitHub CLI commands via subprocess |
| `parse_json_output()` | Parses JSON output from gh CLI |
| `get_review_status()` | Maps GitHub review decision to human-readable status |

**Helper Functions**:

| Function | Purpose |
|----------|---------|
| `fetch_contributor_stats()` | Retrieves commit statistics with retry logic for 202 responses |
| `fetch_pr_stats()` | Aggregates PR counts by author |
| `fetch_review_stats()` | Collects review activity across PRs |
| `_check_review_status()` | Checks and updates status of a review subprocess |
| `_start_review_process()` | Spawns Claude CLI subprocess for code review |

### Database Module

**File**: `/Users/jvargas714/Documents/dev/gh-pr-explorer/database.py`

The database module provides SQLite-based persistence for reviews and merge queue data, replacing the previous JSON file storage.

#### Database Classes

| Class | Description |
|-------|-------------|
| `Database` | Base class managing SQLite connection and schema initialization |
| `ReviewsDB` | Handles review storage, retrieval, and search operations |
| `MergeQueueDB` | Manages merge queue persistence and ordering |

#### Database Schema

```sql
-- Reviews table: Stores code review history and content
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
    content TEXT,
    is_followup BOOLEAN DEFAULT FALSE,
    parent_review_id INTEGER,
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

-- Migrations table: Tracks executed database migrations
CREATE TABLE migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    executed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### ReviewsDB Methods

| Method | Description |
|--------|-------------|
| `add_review()` | Creates a new review record with optional follow-up linking |
| `get_review()` | Retrieves a single review by ID |
| `get_reviews_for_pr()` | Gets all reviews for a specific PR |
| `search_reviews()` | Searches reviews with filters (repo, author, date range) |
| `get_stats()` | Returns aggregate review statistics |
| `check_pr_reviewed()` | Checks if a PR has existing reviews |
| `extract_score()` | Extracts numerical score from review content using regex |

#### MergeQueueDB Methods

| Method | Description |
|--------|-------------|
| `get_queue()` | Returns all queued items ordered by position |
| `add_to_queue()` | Adds a PR to the queue at the end |
| `remove_from_queue()` | Removes a PR from the queue |
| `reorder_queue()` | Moves an item from one position to another |
| `is_in_queue()` | Checks if a PR is already in the queue |

#### Score Extraction

The database module extracts review scores from markdown content using regex patterns:

```python
# Matches patterns like "Score: 8/10", "Overall Score: 7", "Rating: 9/10"
score_pattern = r'(?:score|rating|overall\s*score)[:\s]*(\d+)(?:\s*/\s*10)?'
```

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

### Frontend Components (Vue.js 3)

**File**: `/Users/jvargas714/Documents/dev/gh-pr-explorer/static/js/app.js`

The frontend uses Vue.js 3 Composition API with the following reactive state structure:

#### State Management

```javascript
// Theme
darkMode: ref(true)

// Account/Organization Selection
accounts: ref([])
selectedAccount: ref(null)

// Repository Selection
repos: ref([])
selectedRepo: ref(null)
repoSearch: ref('')

// Filter State
filters: reactive({
    state: 'open',
    author: '',
    assignee: '',
    labels: [],
    // ... 40+ filter properties
})

// Pull Requests
prs: ref([])
loading: ref(false)
error: ref(null)

// Developer Statistics
developerStats: ref([])
statsLoading: ref(false)
statsSortBy: ref('commits')

// Merge Queue
mergeQueue: ref([])
showQueuePanel: ref(false)

// Code Reviews
activeReviews: ref({})  // key: "owner/repo/pr_number"
reviewPollingInterval: ref(null)
reviewErrorModal: reactive({
    show: false,
    prNumber: null,
    prTitle: '',
    errorOutput: '',
    exitCode: null
})
```

#### Computed Properties

| Property | Description |
|----------|-------------|
| `activeFiltersCount` | Count of non-default filter values |
| `sortedDeveloperStats` | Developer stats sorted by selected column |
| `filteredRepos` | Repository list filtered by search term |

#### Key Methods

| Method | Description |
|--------|-------------|
| `fetchAccounts()` | Loads user's personal account and organizations |
| `fetchRepos()` | Loads repositories for selected account |
| `fetchPRs()` | Fetches PRs with current filter configuration |
| `fetchDeveloperStats()` | Loads aggregated developer statistics |
| `fetchRepoMetadata()` | Parallel fetch of contributors, labels, branches, milestones, teams |
| `resetFilters()` | Resets all filters to default values |

**Merge Queue Methods**:

| Method | Description |
|--------|-------------|
| `fetchMergeQueue()` | Loads merge queue from backend |
| `addToQueue(pr)` | Adds a PR to the merge queue |
| `removeFromQueue(prNumber, repo)` | Removes a PR from the queue |
| `moveQueueItem(index, direction)` | Reorders items in the queue |
| `isInQueue(prNumber)` | Checks if a PR is already queued |

**Code Review Methods**:

| Method | Description |
|--------|-------------|
| `fetchReviews()` | Fetches all active/completed reviews from backend |
| `startReview(pr)` | Initiates a Claude CLI code review for a PR |
| `cancelReview(pr)` | Cancels a running review process |
| `getReviewStatus(prNumber)` | Gets current status of a review |
| `handleReviewClick(pr)` | Click handler for review button (start/cancel/show error) |
| `showReviewError(pr)` | Opens modal displaying review error details |

### UI Template

**File**: `/Users/jvargas714/Documents/dev/gh-pr-explorer/templates/index.html`

The template is a Jinja2 file containing the Vue.js single-file component structure:

| Section | Description |
|---------|-------------|
| Header | Logo, title, merge queue toggle, theme toggle button |
| Account Selector | Buttons for personal account and organizations |
| Repository Selector | Searchable dropdown with repo list |
| Filter Panel | Tabbed interface with 5 filter categories |
| PR List / Stats View | Toggle between PR cards and developer stats table |
| PR Card Actions | Queue button, review button, description button per PR |
| Description Modal | Markdown-rendered PR description popup |
| Review Error Modal | Error details when a code review fails |
| Queue Panel | Slide-out panel for managing merge queue |
| Welcome Section | Onboarding message for unauthenticated users |

### Styling

**File**: `/Users/jvargas714/Documents/dev/gh-pr-explorer/static/css/styles.css`

The CSS uses a modern design system with:

- **CSS Custom Properties**: Comprehensive variable system for theming
- **Dark/Light Mode**: Full theme support via `.dark-mode` class
- **Responsive Design**: Mobile-first with breakpoint at 768px
- **Component Styles**: Modular styling for cards, buttons, tables, modals

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

### Developer Stats Tab

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

- **Sortable Columns**: Click any column header to sort ascending/descending
- **Sticky Developer Column**: First column stays visible while scrolling horizontally
- **Formatted Numbers**: Large numbers displayed with K/M suffixes
- **Color-coded Values**: Merge rate and stat types use semantic colors
- **Avatar Display**: Developer avatars shown inline

### Dark/Light Theme Support

- Theme preference persisted to localStorage
- Toggle button in header
- Full CSS variable system for seamless switching
- Respects system preference on first load

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
- **Filters**: Filter by repository, author, date range, and score range
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
  "number": 123,
  "title": "PR Title",
  "url": "https://github.com/owner/repo/pull/123",
  "repo": "owner/repo",
  "author": "username",
  "additions": 150,
  "deletions": 50,
  "position": 1,
  "added_at": "2024-01-15T10:30:00Z"
}
```

#### UI Components

| Component | Location | Description |
|-----------|----------|-------------|
| Queue Toggle | Header | Button with badge showing queue count |
| Queue Button | PR Card | Add/remove PR from queue |
| Queue Panel | Slide-out | Full queue management interface |
| Queue Item | Panel | Individual PR with reorder and remove controls |

### Code Review System (Claude CLI Integration)

The Code Review feature integrates with Claude CLI to perform automated code reviews. Reviews run as background subprocesses, with real-time status tracking in the UI. Completed reviews are persisted to the SQLite database for historical access.

#### How It Works

1. User clicks "Review" button on a PR card or queue item
2. Backend spawns a Claude CLI subprocess with the review prompt
3. UI shows spinner while review is in progress
4. Claude CLI uses the `code-reviewer` agent to analyze the PR
5. Review output is written to a markdown file
6. Review metadata and content are saved to SQLite database
7. UI updates to show completed/failed status with score badge
8. Failed reviews display error details in a modal

#### Claude CLI Command

```bash
claude -p "Review PR #123 at https://github.com/owner/repo/pull/123. \
  Use the code-reviewer agent. \
  Write the review to /path/to/reviews/owner-repo-pr-123.md" \
  --allowedTools "Bash(git*),Bash(gh*),Read,Glob,Grep,Write,Task" \
  --dangerously-skip-permissions
```

**Flags**:
- `-p`: Prompt with review instructions
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
- **Database Storage**: Completed reviews saved to `reviews` table in SQLite
- **Review Files**: Written to `/Users/jvargas714/Documents/code-reviews/`
- **File Naming**: `{owner}-{repo}-pr-{number}.md`

#### Score Tracking

Reviews are analyzed to extract numerical scores:

- **Automatic Extraction**: Regex parses content for score patterns (e.g., "Score: 8/10")
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
      "mergeable": "MERGEABLE",
      "additions": 150,
      "deletions": 50,
      "changedFiles": 5,
      "milestone": { "title": "v1.0" }
    }
  ]
}
```

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

### Merge Queue

**GET** `/api/merge-queue`

Returns the current merge queue.

**Response**:
```json
{
  "queue": [
    {
      "number": 123,
      "title": "Add new feature",
      "url": "https://github.com/owner/repo/pull/123",
      "repo": "owner/repo",
      "author": "developer",
      "additions": 150,
      "deletions": 50
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

Returns a single review with full content.

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
  "content": "# Code Review for PR #123\n\n## Summary\n...",
  "is_followup": false,
  "parent_review_id": null
}
```

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
| `port` | integer | 5050 | HTTP server port |
| `host` | string | "127.0.0.1" | HTTP server bind address |
| `debug` | boolean | false | Flask debug mode |
| `default_per_page` | integer | 30 | Default PR results limit |
| `cache_ttl_seconds` | integer | 300 | Cache time-to-live in seconds (5 minutes) |

### Example Configuration

```json
{
  "port": 5050,
  "host": "127.0.0.1",
  "debug": false,
  "default_per_page": 30,
  "cache_ttl_seconds": 300
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
            cache_key = f"{func.__name__}:{args}:{sorted(kwargs.items())}"
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
- **Key Generation**: Function name + arguments + keyword arguments
- **Invalidation**: Manual via `/api/clear-cache` endpoint or process restart

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

The `/stats/contributors` endpoint may return 202 when computing statistics. The application implements retry logic:

```python
def fetch_contributor_stats(owner, repo):
    max_retries = 3
    retry_delay = 2  # seconds

    for attempt in range(max_retries):
        # Check for 202 response
        if "HTTP/2.0 202" in result.stdout:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
        # ... process response
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
6. **Custom Dashboards**: User-configurable dashboard widgets
7. **PR Templates**: Quick filter templates (e.g., "My Open PRs", "Needs My Review")

#### User Experience

1. **Keyboard Shortcuts**: Navigation and actions via keyboard
2. **PR Preview**: Hover preview of PR details
3. **Bulk Actions**: Select and act on multiple PRs
4. ~~**History**: Track recently viewed PRs and repositories~~ **Implemented**: Review History panel provides full review history access

#### Technical

1. **TypeScript**: Add type safety to frontend code
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
6. **Review Stats Sampling**: Reviews fetched for first 100 PRs only
7. **Claude CLI Required**: Code review feature requires Claude CLI installed and authenticated
8. **One Review Per PR**: Cannot run multiple concurrent reviews for the same PR
9. **Active Review Volatility**: In-progress reviews lost if server restarts mid-review (completed reviews are persisted)
10. **Fixed Review Output Path**: Reviews always written to hardcoded directory
11. **Score Extraction Heuristic**: Score parsing relies on regex patterns; unusual formats may not be detected
12. **Migration One-Time**: Data migration from legacy JSON/markdown runs once; subsequent manual additions to old format not auto-imported

---

## Appendix

### Dependencies

**Backend**:
- Python 3.x
- Flask
- GitHub CLI (`gh`) - required for GitHub API access
- Claude CLI (`claude`) - optional, required for code review feature

**Frontend (CDN)**:
- Vue.js 3 (production build)
- marked.js 12.0.0 (Markdown rendering)

### File Structure

```
gh-pr-explorer/
├── app.py                 # Flask backend (main application)
├── database.py            # SQLite database module (Reviews, MergeQueue, Migrations)
├── migrate_data.py        # Data migration script for legacy JSON/markdown files
├── pr_explorer.db         # SQLite database file (auto-created)
├── config.json            # Application configuration
├── requirements.txt       # Python dependencies
├── CLAUDE.md              # Development instructions
├── docs/
│   └── DESIGN.md          # This document
├── static/
│   ├── css/
│   │   └── styles.css     # Application styles
│   └── js/
│       └── app.js         # Vue.js application
└── templates/
    └── index.html         # Jinja2/Vue.js template

External Dependencies:
├── /Users/jvargas714/Documents/code-reviews/              # Code review output directory
└── /Users/jvargas714/Documents/code-reviews/past-reviews/ # Historical reviews (migrated)
```

**Note**: The `MQ/` folder with `merge_queue.json` has been deprecated. Merge queue data is now stored in the SQLite database.

### Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Ensure gh CLI is authenticated
gh auth login

# (Optional) For code review feature, ensure Claude CLI is available
# See: https://claude.ai/claude-code

# Start the server
python app.py

# Access the application
open http://127.0.0.1:5050
```

### Using the Code Review Feature

1. Select a repository and load PRs
2. Click the review button (clipboard icon) on any PR card
3. The button shows a spinner while the review runs
4. Check `/Users/jvargas714/Documents/code-reviews/` for review output
5. If review fails, click the red X button to see error details
