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
|   - js/app.js     |     |   Cache           |     |   (via gh CLI)    |
|   - css/styles.css|     |   (TTL-based)     |     |                   |
|                   |     |                   |     |                   |
+-------------------+     +-------------------+     +-------------------+
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

### UI Template

**File**: `/Users/jvargas714/Documents/dev/gh-pr-explorer/templates/index.html`

The template is a Jinja2 file containing the Vue.js single-file component structure:

| Section | Description |
|---------|-------------|
| Header | Logo, title, theme toggle button |
| Account Selector | Buttons for personal account and organizations |
| Repository Selector | Searchable dropdown with repo list |
| Filter Panel | Tabbed interface with 5 filter categories |
| PR List / Stats View | Toggle between PR cards and developer stats table |
| Description Modal | Markdown-rendered PR description popup |
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

---

## Future Considerations

### Potential Improvements

#### Performance

1. **Persistent Caching**: Implement Redis or SQLite caching for cross-process/restart persistence
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
4. **History**: Track recently viewed PRs and repositories

#### Technical

1. **TypeScript**: Add type safety to frontend code
2. **Testing**: Add unit and integration tests
3. **Docker Support**: Containerized deployment option
4. **Authentication Options**: Support for multiple authentication methods
5. **Rate Limit Handling**: Better handling and display of GitHub rate limits
6. **Offline Support**: Service worker for offline access to cached data

### Known Limitations

1. **Single User**: Designed for single-user local use
2. **No Persistence**: Cache lost on restart
3. **Rate Limits**: Subject to GitHub API rate limits via gh CLI
4. **Large Repositories**: Stats fetching may be slow for repos with many PRs
5. **Teams Endpoint**: May fail for personal repositories (non-fatal)
6. **Review Stats Sampling**: Reviews fetched for first 100 PRs only

---

## Appendix

### Dependencies

**Backend**:
- Python 3.x
- Flask
- GitHub CLI (`gh`)

**Frontend (CDN)**:
- Vue.js 3 (production build)
- marked.js 12.0.0 (Markdown rendering)

### File Structure

```
gh-pr-explorer/
├── app.py                 # Flask backend (single file)
├── config.json            # Application configuration
├── requirements.txt       # Python dependencies
├── CLAUDE.md             # Development instructions
├── docs/
│   └── DESIGN.md         # This document
├── static/
│   ├── css/
│   │   └── styles.css    # Application styles
│   └── js/
│       └── app.js        # Vue.js application
└── templates/
    └── index.html        # Jinja2/Vue.js template
```

### Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Ensure gh CLI is authenticated
gh auth login

# Start the server
python app.py

# Access the application
open http://127.0.0.1:5050
```
