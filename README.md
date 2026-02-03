# GitHub PR Explorer

A powerful web application for browsing, filtering, analyzing, and managing GitHub Pull Requests. Built with Flask and Vue.js 3, it leverages the GitHub CLI for seamless authentication and provides advanced features for code review management, merge queue tracking, and developer analytics.

> **Note:** This project is actively under development. Features may change, and contributions are welcome!

---

## Features

### Pull Request Browsing & Filtering

Browse PRs with an extensive filtering system organized into intuitive tabs:

**Basic Filters**
- State (Open, Closed, Merged, All)
- Draft status
- Author and Assignee selection
- Base and Head branch filtering
- Labels (multi-select with AND logic)
- Milestone filtering
- Linked issue status

**Review Filters**
- Review status (No reviews, Required, Approved, Changes requested)
- Reviewed by specific contributor
- Review requested from
- CI status (Pending, Success, Failure)

**People Filters**
- Involves (author, assignee, mentions, or commenter)
- Mentions
- Commenter

**Date Filters**
- Created, Updated, Merged, and Closed date ranges

**Advanced Filters**
- Full-text search across title, body, and comments
- Comment count with comparison operators
- Reactions and interactions count
- Team review requests
- Exclusion filters (labels, author, milestone)
- Custom sort options

### PR Display

Each PR card displays:
- PR number and title with direct GitHub link
- State badge (Open/Closed/Merged) with color coding
- Draft indicator
- Author with avatar
- Branch information (source → target)
- Time since last update
- Diff stats (+additions, -deletions, files changed)
- Label badges with colors
- Review status indicator
- Review score badge (0-10)
- New commits indicator

### Code Review Management

Integrated code review workflow:
- Start reviews directly from PR cards
- Reviews saved as markdown files
- Automatic review score extraction
- Follow-up review support when new commits are detected
- Review chain tracking (parent-child relationships)
- Post critical issues as inline GitHub PR comments
- Complete review history archive

### Merge Queue

Professional merge queue management:
- Add/remove PRs from queue
- Reorder queue items
- Track PR state (synced with GitHub)
- Attach markdown notes to queue items
- Persistent storage across sessions

### Developer Statistics

Comprehensive contributor analytics:
- Total commits, PRs authored, merged, and closed
- Merge rate percentage with color coding
- Reviews given, approvals, and changes requested
- Lines added/deleted
- Average review score
- Sortable columns
- 4-hour cache with background refresh

### Review History

Browse and search past reviews:
- Filter by repository, author, or search text
- View full review content with markdown rendering
- Track review scores and PR states
- Follow-up and inline comments indicators

### Persistent Settings

All preferences automatically saved and restored:
- Filter selections
- Selected account and repository
- Theme preference

### Dark Mode

Full dark mode support with:
- CSS variable-based theming
- Toggle in header
- Preference persisted to localStorage

---

## Screenshots

*Coming soon*

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Flask (Python 3) |
| Frontend | Vue.js 3 (Composition API) |
| Database | SQLite |
| Styling | CSS with custom properties |
| Auth | GitHub CLI (`gh`) |
| Markdown | Marked.js |

---

## Prerequisites

- **Python 3.x** with pip
- **GitHub CLI** installed and authenticated

```bash
# Install GitHub CLI (macOS)
brew install gh

# Authenticate
gh auth login
```

---

## Installation

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/gh-pr-explorer.git
cd gh-pr-explorer
```

2. **Install Python dependencies**
```bash
pip install -r requirements.txt
```

3. **Run the application**
```bash
python app.py
```

4. **Open in browser**
```
http://127.0.0.1:5050
```

---

## Configuration

Edit `config.json` to customize:

```json
{
  "port": 5050,
  "host": "127.0.0.1",
  "debug": false,
  "default_per_page": 30,
  "cache_ttl_seconds": 300
}
```

| Option | Description | Default |
|--------|-------------|---------|
| `port` | Server port | 5050 |
| `host` | Listen address | 127.0.0.1 |
| `debug` | Flask debug mode | false |
| `default_per_page` | Default results per page | 30 |
| `cache_ttl_seconds` | In-memory cache TTL | 300 |

---

## API Endpoints

### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/user` | GET | Get authenticated user info |
| `/api/orgs` | GET | List user accounts and organizations |
| `/api/repos` | GET | List repositories for an owner |
| `/api/repos/<owner>/<repo>/prs` | GET | Get PRs with extensive filtering |
| `/api/repos/<owner>/<repo>/contributors` | GET | List repository contributors |
| `/api/repos/<owner>/<repo>/labels` | GET | List repository labels |
| `/api/repos/<owner>/<repo>/branches` | GET | List repository branches |
| `/api/repos/<owner>/<repo>/milestones` | GET | List repository milestones |
| `/api/repos/<owner>/<repo>/teams` | GET | List teams with repository access |
| `/api/repos/<owner>/<repo>/stats` | GET | Get developer statistics |

### Merge Queue

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/merge-queue` | GET | Get queue items |
| `/api/merge-queue` | POST | Add PR to queue |
| `/api/merge-queue/<pr_number>` | DELETE | Remove from queue |
| `/api/merge-queue/reorder` | POST | Reorder queue items |
| `/api/merge-queue/<pr_number>/notes` | GET/POST | Get or add notes |

### Code Reviews

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/reviews` | GET | Get active reviews |
| `/api/reviews` | POST | Start a review |
| `/api/reviews/<owner>/<repo>/<pr_number>/status` | GET | Check review status |
| `/api/review-history` | GET | List past reviews |
| `/api/review-history/<review_id>` | GET | Get review details |

### Settings

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/settings` | GET | Get all settings |
| `/api/settings/<key>` | GET/PUT/DELETE | Manage individual settings |

### Cache

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/clear-cache` | POST | Clear in-memory cache |

---

## Database Schema

The application uses SQLite with the following tables:

- **reviews** - Code review history with scores, content, and metadata
- **merge_queue** - PR merge queue with positions and state tracking
- **queue_notes** - Notes attached to queue items
- **user_settings** - Persistent user preferences (filters, theme, etc.)
- **developer_stats** - Cached contributor statistics
- **stats_metadata** - Cache metadata for background refresh
- **migrations** - Database migration tracking

---

## Architecture

```
gh-pr-explorer/
├── app.py              # Flask application with all routes
├── config.json         # Application configuration
├── requirements.txt    # Python dependencies
├── pr_explorer.db      # SQLite database (created on first run)
├── templates/
│   └── index.html      # Vue.js single-file component
└── static/
    ├── css/
    │   └── styles.css  # CSS with theming support
    └── js/
        └── app.js      # Vue.js application logic
```

### Data Flow

1. Frontend makes API calls to Flask backend
2. Backend translates requests into `gh` CLI commands
3. GitHub CLI handles authentication and fetches data
4. Backend parses JSON output and returns to frontend
5. Complex data (reviews, queue, stats) stored in SQLite

---

## Development Status

This project is under active development. Current focus areas:

- [ ] Additional filtering capabilities
- [ ] Bulk PR operations
- [ ] Export functionality
- [ ] Enhanced review templates
- [ ] Performance optimizations
- [ ] Mobile responsiveness improvements
- [ ] Test coverage

---

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

This project is open source. See LICENSE file for details.

---

## Acknowledgments

- Built with [Flask](https://flask.palletsprojects.com/)
- Frontend powered by [Vue.js 3](https://vuejs.org/)
- Data fetched via [GitHub CLI](https://cli.github.com/)
- Markdown rendering by [Marked.js](https://marked.js.org/)
