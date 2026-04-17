# PR Timelines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a full-screen modal that surfaces every GitHub event for a single PR in a modern, animated vertical timeline. Launchable from PR cards and merge queue cards.

**Architecture:** Backend: new SQLite-cached endpoint `GET /api/repos/:owner/:repo/prs/:pr_number/timeline` wrapping `gh api repos/.../issues/:n/timeline --paginate`, with state-aware TTL (infinite for closed/merged, 5-min for open) + stale-while-revalidate. Frontend: Zustand-backed modal rendering a Framer-Motion-animated vertical timeline with multi-expand markdown event bodies, filter chips, refresh button, and 45-second polling while the modal is open for OPEN PRs.

**Tech Stack:** Flask + SQLite + `gh` CLI (backend). React 18 + TypeScript + Zustand + Framer Motion + react-markdown (frontend, all existing except Framer Motion).

**Spec:** `docs/specs/2026-04-16-pr-timeline-design.md`

**Worktree:** `.worktrees/pr-timeline/` on branch `feature/pr-timeline`.

**Commit policy (per project CLAUDE.md):** Do NOT auto-commit. Each commit step stages files + proposes a message, then halts for the user to approve. No "co-authored-by" in messages.

**Agent delegation hints:** Frontend TypeScript tasks (Phase 2+) may be delegated to the `typescript-pro` agent. UI/styling polish tasks may consult the `ui-ux-pro-max` skill. These are optional — the tasks are self-contained either way.

---

## Phase 1 — Backend foundation

### Task 1.1: Add pytest dependency and test directory

**Files:**
- Modify: `requirements.txt`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`

- [ ] **Step 1: Add pytest to requirements.txt**

Append to `requirements.txt`:
```
pytest>=8.0.0
```

- [ ] **Step 2: Create empty test package marker**

Create `backend/tests/__init__.py`:
```python
```

- [ ] **Step 3: Create pytest conftest for test-path sys.path handling**

Create `backend/tests/conftest.py`:
```python
"""Pytest config — adds project root to sys.path so 'backend.' imports work."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
```

- [ ] **Step 4: Install pytest into the venv**

Run: `pip install pytest`
Expected: install succeeds.

- [ ] **Step 5: Verify pytest discovery works**

Run: `pytest backend/tests/ -v`
Expected: `no tests ran in 0.XXs` (no tests yet — just verifying pytest can discover the package).

- [ ] **Step 6: Stage and propose commit**

Run:
```bash
git add requirements.txt backend/tests/__init__.py backend/tests/conftest.py
git status
```
Propose message: `Add pytest dev dependency and empty backend/tests package`
Halt for user approval before committing.

---

### Task 1.2: Add `pr_timeline_cache` schema

**Files:**
- Modify: `backend/database/base.py` (add CREATE TABLE inside `_init_db`)

- [ ] **Step 1: Add schema block to `_init_db`**

Edit `backend/database/base.py`. Locate the section near the other cache tables (after the `repo_loc_cache` table creation, around line 235). Add:

```python
            # Create pr_timeline_cache table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pr_timeline_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo TEXT NOT NULL,
                    pr_number INTEGER NOT NULL,
                    pr_state TEXT NOT NULL,
                    data TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(repo, pr_number)
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_pr_timeline_cache_key
                ON pr_timeline_cache(repo, pr_number)
            """)
```

- [ ] **Step 2: Delete dev DB and verify it recreates with the new table**

Run:
```bash
rm -f pr_explorer.db
python -c "from backend.database import get_database; get_database()"
sqlite3 pr_explorer.db ".schema pr_timeline_cache"
```
Expected: the `CREATE TABLE pr_timeline_cache ...` block is printed.

- [ ] **Step 3: Stage and propose commit**

Run:
```bash
git add backend/database/base.py
git status
```
Propose message: `Add pr_timeline_cache schema for PR timeline caching`
Halt for user approval.

---

### Task 1.3: Create `TimelineCacheDB` class

**Files:**
- Modify: `backend/database/cache_stores.py` (append new class)
- Modify: `backend/database/__init__.py` (add import + singleton factory)
- Create: `backend/tests/test_timeline_cache_db.py`

- [ ] **Step 1: Write the failing test for TimelineCacheDB**

Create `backend/tests/test_timeline_cache_db.py`:
```python
"""Tests for TimelineCacheDB."""
import tempfile
from pathlib import Path

import pytest

from backend.database.base import Database
from backend.database.cache_stores import TimelineCacheDB


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as tmp:
        yield Database(db_path=Path(tmp) / "test.db")


def test_get_cached_returns_none_when_empty(db):
    cache = TimelineCacheDB(db)
    assert cache.get_cached("owner/repo", 1) is None


def test_save_and_get_cached(db):
    cache = TimelineCacheDB(db)
    events = [{"id": "e1", "type": "opened"}]
    cache.save_cache("owner/repo", 42, "OPEN", events)
    row = cache.get_cached("owner/repo", 42)
    assert row is not None
    assert row["data"] == events
    assert row["pr_state"] == "OPEN"
    assert row["updated_at"]


def test_save_upserts_on_conflict(db):
    cache = TimelineCacheDB(db)
    cache.save_cache("owner/repo", 42, "OPEN", [{"id": "a"}])
    cache.save_cache("owner/repo", 42, "MERGED", [{"id": "b"}])
    row = cache.get_cached("owner/repo", 42)
    assert row["pr_state"] == "MERGED"
    assert row["data"] == [{"id": "b"}]


def test_is_stale_missing_row(db):
    cache = TimelineCacheDB(db)
    assert cache.is_stale("owner/repo", 1, ttl_minutes=5) is True


def test_is_stale_none_ttl_means_never_stale(db):
    cache = TimelineCacheDB(db)
    cache.save_cache("owner/repo", 42, "MERGED", [])
    assert cache.is_stale("owner/repo", 42, ttl_minutes=None) is False


def test_is_stale_fresh_row(db):
    cache = TimelineCacheDB(db)
    cache.save_cache("owner/repo", 42, "OPEN", [])
    assert cache.is_stale("owner/repo", 42, ttl_minutes=5) is False


def test_clear_removes_all(db):
    cache = TimelineCacheDB(db)
    cache.save_cache("owner/repo", 1, "OPEN", [])
    cache.save_cache("owner/repo", 2, "OPEN", [])
    cache.clear()
    assert cache.get_cached("owner/repo", 1) is None
    assert cache.get_cached("owner/repo", 2) is None
```

- [ ] **Step 2: Run test — verify it fails**

Run: `pytest backend/tests/test_timeline_cache_db.py -v`
Expected: FAIL with `ImportError: cannot import name 'TimelineCacheDB'`

- [ ] **Step 3: Add `TimelineCacheDB` class to `cache_stores.py`**

Append to `backend/database/cache_stores.py`:

```python
class TimelineCacheDB:
    """Cache for per-PR timeline events in SQLite.

    Key: (repo, pr_number). Closed/Merged PRs are immutable, so callers pass
    ttl_minutes=None to treat them as never stale.
    """

    def __init__(self, db):
        self.db = db

    def get_cached(self, repo: str, pr_number: int) -> Optional[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT data, pr_state, updated_at FROM pr_timeline_cache "
                "WHERE repo = ? AND pr_number = ?",
                (repo, pr_number)
            )
            row = cursor.fetchone()
            if row:
                try:
                    return {
                        "data": json.loads(row["data"]),
                        "pr_state": row["pr_state"],
                        "updated_at": row["updated_at"],
                    }
                except json.JSONDecodeError:
                    logger.warning(
                        f"Corrupt timeline cache for {repo}#{pr_number}, treating as miss"
                    )
                    return None
            return None

    def save_cache(self, repo: str, pr_number: int, pr_state: str, data: Any) -> None:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO pr_timeline_cache (repo, pr_number, pr_state, data, updated_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(repo, pr_number) DO UPDATE SET
                   pr_state = excluded.pr_state,
                   data = excluded.data,
                   updated_at = CURRENT_TIMESTAMP""",
                (repo, pr_number, pr_state, json.dumps(data))
            )

    def is_stale(self, repo: str, pr_number: int, ttl_minutes: Optional[int]) -> bool:
        """Return True when there is no cache entry, or when the entry is older
        than ttl_minutes. A ttl_minutes of None means "never stale" (used for
        closed/merged PRs)."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT updated_at FROM pr_timeline_cache WHERE repo = ? AND pr_number = ?",
                (repo, pr_number)
            )
            row = cursor.fetchone()
            if not row:
                return True
            if ttl_minutes is None:
                return False
            updated = datetime.strptime(row["updated_at"], "%Y-%m-%d %H:%M:%S")
            age_minutes = (datetime.now() - updated).total_seconds() / 60
            return age_minutes > ttl_minutes

    def clear(self) -> None:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM pr_timeline_cache")
```

- [ ] **Step 4: Run test — verify it passes**

Run: `pytest backend/tests/test_timeline_cache_db.py -v`
Expected: 7 passed.

- [ ] **Step 5: Register singleton factory**

Edit `backend/database/__init__.py`:

Add `TimelineCacheDB` to the existing multi-import from `cache_stores`:
```python
from backend.database.cache_stores import (
    LifecycleCacheDB,
    WorkflowCacheDB,
    ContributorTimeSeriesCacheDB,
    CodeActivityCacheDB,
    RepoStatsCacheDB,
    RepoLOCCacheDB,
    TimelineCacheDB,
)
```

Add a new singleton variable after `_repo_loc_cache_db`:
```python
_timeline_cache_db: Optional[TimelineCacheDB] = None
```

Add factory function after `get_repo_loc_cache_db`:
```python
def get_timeline_cache_db() -> TimelineCacheDB:
    global _timeline_cache_db
    if _timeline_cache_db is None:
        db = get_database()
        with _db_lock:
            if _timeline_cache_db is None:
                _timeline_cache_db = TimelineCacheDB(db)
    return _timeline_cache_db
```

Add `"TimelineCacheDB"` and `"get_timeline_cache_db"` to `__all__`.

- [ ] **Step 6: Verify singleton factory import works**

Run: `python -c "from backend.database import get_timeline_cache_db; print(get_timeline_cache_db().__class__.__name__)"`
Expected: `TimelineCacheDB`

- [ ] **Step 7: Stage and propose commit**

Run:
```bash
git add backend/database/cache_stores.py backend/database/__init__.py backend/tests/test_timeline_cache_db.py
git status
```
Propose message: `Add TimelineCacheDB with state-aware TTL`
Halt for user approval.

---

### Task 1.4: Create `timeline_service` with event normalization

**Files:**
- Create: `backend/services/timeline_service.py`
- Create: `backend/tests/test_timeline_service.py`
- Create: `backend/tests/fixtures/timeline_raw.json` (sample GitHub response)

- [ ] **Step 1: Create raw fixture**

Create `backend/tests/fixtures/timeline_raw.json`:
```json
[
  {
    "event": "committed",
    "sha": "abc1234567890abcdef1234567890abcdef1234",
    "message": "Add caching layer\n\nDetails...",
    "author": {"name": "J Vargas", "email": "j@example.com", "date": "2026-04-10T14:30:00Z"},
    "url": "https://api.github.com/repos/owner/repo/git/commits/abc1234567890abcdef1234567890abcdef1234"
  },
  {
    "event": "reviewed",
    "id": 999,
    "user": {"login": "alice", "avatar_url": "https://example.com/a.png"},
    "state": "changes_requested",
    "body": "Please fix the race condition.",
    "html_url": "https://github.com/owner/repo/pull/847#pullrequestreview-999",
    "submitted_at": "2026-04-11T15:45:00Z"
  },
  {
    "event": "commented",
    "id": 1000,
    "user": {"login": "bob", "avatar_url": "https://example.com/b.png"},
    "body": "Looks good to me.",
    "html_url": "https://github.com/owner/repo/pull/847#issuecomment-1000",
    "created_at": "2026-04-11T16:00:00Z"
  },
  {
    "event": "review_requested",
    "id": 1001,
    "actor": {"login": "jvargas", "avatar_url": "https://example.com/j.png"},
    "requested_reviewer": {"login": "charlie", "avatar_url": "https://example.com/c.png"},
    "created_at": "2026-04-11T16:05:00Z"
  },
  {
    "event": "ready_for_review",
    "id": 1002,
    "actor": {"login": "jvargas", "avatar_url": "https://example.com/j.png"},
    "created_at": "2026-04-11T17:00:00Z"
  },
  {
    "event": "convert_to_draft",
    "id": 1003,
    "actor": {"login": "jvargas", "avatar_url": "https://example.com/j.png"},
    "created_at": "2026-04-11T17:30:00Z"
  },
  {
    "event": "head_ref_force_pushed",
    "id": 1004,
    "actor": {"login": "jvargas", "avatar_url": "https://example.com/j.png"},
    "created_at": "2026-04-11T18:00:00Z"
  },
  {
    "event": "closed",
    "id": 1005,
    "actor": {"login": "bob", "avatar_url": "https://example.com/b.png"},
    "created_at": "2026-04-12T09:00:00Z"
  },
  {
    "event": "reopened",
    "id": 1006,
    "actor": {"login": "jvargas", "avatar_url": "https://example.com/j.png"},
    "created_at": "2026-04-12T09:30:00Z"
  },
  {
    "event": "merged",
    "id": 1007,
    "actor": {"login": "jvargas", "avatar_url": "https://example.com/j.png"},
    "commit_id": "merged1234567890abcdef1234567890abcdef12",
    "created_at": "2026-04-12T10:20:00Z"
  }
]
```

- [ ] **Step 2: Write failing test for normalization**

Create `backend/tests/test_timeline_service.py`:
```python
"""Tests for timeline_service event normalization."""
import json
from pathlib import Path

import pytest

from backend.services.timeline_service import normalize_timeline_events


FIXTURE = Path(__file__).parent / "fixtures" / "timeline_raw.json"


@pytest.fixture
def raw_events():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def pr_info():
    return {
        "created_at": "2026-04-10T14:00:00Z",
        "user": {"login": "jvargas", "avatar_url": "https://example.com/j.png"},
    }


def test_prepends_synthesized_opened_event(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    assert events[0]["type"] == "opened"
    assert events[0]["created_at"] == "2026-04-10T14:00:00Z"
    assert events[0]["actor"]["login"] == "jvargas"


def test_sorts_ascending_by_created_at(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    timestamps = [e["created_at"] for e in events]
    assert timestamps == sorted(timestamps)


def test_committed_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    commit = next(e for e in events if e["type"] == "committed")
    assert commit["sha"] == "abc1234567890abcdef1234567890abcdef1234"
    assert commit["short_sha"] == "abc1234"
    assert commit["message"] == "Add caching layer\n\nDetails..."
    assert commit["actor"]["login"] == "J Vargas"
    assert commit["created_at"] == "2026-04-10T14:30:00Z"


def test_reviewed_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    review = next(e for e in events if e["type"] == "reviewed")
    assert review["state"] == "CHANGES_REQUESTED"
    assert review["body"] == "Please fix the race condition."
    assert review["actor"]["login"] == "alice"
    assert review["html_url"].endswith("pullrequestreview-999")


def test_commented_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    comment = next(e for e in events if e["type"] == "commented")
    assert comment["body"] == "Looks good to me."
    assert comment["actor"]["login"] == "bob"
    assert comment["html_url"].endswith("issuecomment-1000")


def test_review_requested_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    rr = next(e for e in events if e["type"] == "review_requested")
    assert rr["requested_reviewer"]["login"] == "charlie"
    assert rr["actor"]["login"] == "jvargas"


def test_ready_for_review_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    rfr = next(e for e in events if e["type"] == "ready_for_review")
    assert rfr["actor"]["login"] == "jvargas"


def test_convert_to_draft_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    ctd = next(e for e in events if e["type"] == "convert_to_draft")
    assert ctd["actor"]["login"] == "jvargas"


def test_closed_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    closed = next(e for e in events if e["type"] == "closed")
    assert closed["actor"]["login"] == "bob"


def test_reopened_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    reopened = next(e for e in events if e["type"] == "reopened")
    assert reopened["actor"]["login"] == "jvargas"


def test_merged_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    merged = next(e for e in events if e["type"] == "merged")
    assert merged["sha"] == "merged1234567890abcdef1234567890abcdef12"
    assert merged["actor"]["login"] == "jvargas"


def test_force_pushed_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    fp = next(e for e in events if e["type"] == "head_ref_force_pushed")
    assert fp["actor"]["login"] == "jvargas"


def test_all_events_have_required_fields(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    for e in events:
        assert "id" in e and e["id"]
        assert "type" in e
        assert "created_at" in e
```

- [ ] **Step 3: Run test — verify it fails**

Run: `pytest backend/tests/test_timeline_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.services.timeline_service'`

- [ ] **Step 4: Implement normalize_timeline_events**

Create `backend/services/timeline_service.py`:
```python
"""PR timeline service: fetch, normalize, and cache GitHub issue timeline events."""

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.services.github_service import (
    run_gh_command,
    parse_json_output,
    fetch_pr_state,
)

logger = logging.getLogger(__name__)

# Events we surface to the UI. Anything else from GitHub is dropped.
_SUPPORTED_EVENT_TYPES = {
    "committed",
    "commented",
    "reviewed",
    "review_requested",
    "ready_for_review",
    "convert_to_draft",
    "closed",
    "reopened",
    "merged",
    "head_ref_force_pushed",
}

_OPEN_TTL_MINUTES = 5

# Tracks which (repo, pr_number) keys have an in-flight background refresh.
_refresh_lock = threading.Lock()
_refreshing: set = set()


def _actor_from(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """Extract a normalized actor dict from a GitHub user object."""
    if not raw:
        return None
    return {
        "login": raw.get("login") or raw.get("name") or "",
        "avatar_url": raw.get("avatar_url", ""),
    }


def _stable_id(event_type: str, created_at: str, actor_login: str, idx: int) -> str:
    return f"{event_type}-{created_at}-{actor_login}-{idx}"


def _normalize_committed(raw: Dict[str, Any], idx: int) -> Optional[Dict[str, Any]]:
    author = raw.get("author") or {}
    sha = raw.get("sha") or ""
    created_at = author.get("date") or ""
    actor = _actor_from({"login": author.get("name", ""), "avatar_url": ""})
    return {
        "id": _stable_id("committed", created_at, actor["login"] if actor else "", idx),
        "type": "committed",
        "created_at": created_at,
        "actor": actor,
        "sha": sha,
        "short_sha": sha[:7],
        "message": raw.get("message", ""),
    }


def _normalize_reviewed(raw: Dict[str, Any], idx: int) -> Optional[Dict[str, Any]]:
    actor = _actor_from(raw.get("user"))
    created_at = raw.get("submitted_at") or raw.get("created_at") or ""
    state = (raw.get("state") or "").upper()
    return {
        "id": _stable_id("reviewed", created_at, actor["login"] if actor else "", idx),
        "type": "reviewed",
        "created_at": created_at,
        "actor": actor,
        "state": state,
        "body": raw.get("body") or "",
        "html_url": raw.get("html_url", ""),
    }


def _normalize_commented(raw: Dict[str, Any], idx: int) -> Optional[Dict[str, Any]]:
    actor = _actor_from(raw.get("user") or raw.get("actor"))
    created_at = raw.get("created_at") or ""
    return {
        "id": _stable_id("commented", created_at, actor["login"] if actor else "", idx),
        "type": "commented",
        "created_at": created_at,
        "actor": actor,
        "body": raw.get("body") or "",
        "html_url": raw.get("html_url", ""),
    }


def _normalize_review_requested(raw: Dict[str, Any], idx: int) -> Optional[Dict[str, Any]]:
    actor = _actor_from(raw.get("actor"))
    created_at = raw.get("created_at") or ""
    reviewer = _actor_from(raw.get("requested_reviewer"))
    return {
        "id": _stable_id("review_requested", created_at, actor["login"] if actor else "", idx),
        "type": "review_requested",
        "created_at": created_at,
        "actor": actor,
        "requested_reviewer": reviewer,
    }


def _normalize_merged(raw: Dict[str, Any], idx: int) -> Optional[Dict[str, Any]]:
    actor = _actor_from(raw.get("actor"))
    created_at = raw.get("created_at") or ""
    return {
        "id": _stable_id("merged", created_at, actor["login"] if actor else "", idx),
        "type": "merged",
        "created_at": created_at,
        "actor": actor,
        "sha": raw.get("commit_id") or "",
    }


def _normalize_force_pushed(raw: Dict[str, Any], idx: int) -> Optional[Dict[str, Any]]:
    actor = _actor_from(raw.get("actor"))
    created_at = raw.get("created_at") or ""
    return {
        "id": _stable_id("head_ref_force_pushed", created_at, actor["login"] if actor else "", idx),
        "type": "head_ref_force_pushed",
        "created_at": created_at,
        "actor": actor,
        "before": raw.get("before_commit_oid") or "",
        "after": raw.get("after_commit_oid") or "",
    }


def _normalize_simple_state_change(raw: Dict[str, Any], event_type: str, idx: int) -> Optional[Dict[str, Any]]:
    """Shared shape for ready_for_review, convert_to_draft, closed, reopened."""
    actor = _actor_from(raw.get("actor"))
    created_at = raw.get("created_at") or ""
    return {
        "id": _stable_id(event_type, created_at, actor["login"] if actor else "", idx),
        "type": event_type,
        "created_at": created_at,
        "actor": actor,
    }


_NORMALIZERS = {
    "committed": _normalize_committed,
    "reviewed": _normalize_reviewed,
    "commented": _normalize_commented,
    "review_requested": _normalize_review_requested,
    "merged": _normalize_merged,
    "head_ref_force_pushed": _normalize_force_pushed,
}


def normalize_timeline_events(
    raw_events: List[Dict[str, Any]],
    pr_info: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Normalize raw GitHub timeline events into unified TimelineEvent dicts.

    pr_info must contain:
        - created_at: ISO 8601 PR creation timestamp
        - user: {login, avatar_url} of PR author

    Returns a list of events sorted ascending by created_at, with an 'opened'
    event synthesized from pr_info prepended.
    """
    result: List[Dict[str, Any]] = []

    for idx, raw in enumerate(raw_events or []):
        event_type = raw.get("event")
        if event_type not in _SUPPORTED_EVENT_TYPES:
            continue
        if event_type in _NORMALIZERS:
            normalized = _NORMALIZERS[event_type](raw, idx)
        else:
            normalized = _normalize_simple_state_change(raw, event_type, idx)
        if normalized and normalized.get("created_at"):
            result.append(normalized)

    # Synthesize the 'opened' event from pr_info.
    opened_actor = _actor_from(pr_info.get("user"))
    opened_created_at = pr_info.get("created_at") or ""
    if opened_created_at:
        result.append({
            "id": _stable_id("opened", opened_created_at, opened_actor["login"] if opened_actor else "", -1),
            "type": "opened",
            "created_at": opened_created_at,
            "actor": opened_actor,
        })

    result.sort(key=lambda e: e["created_at"])
    return result
```

- [ ] **Step 5: Run test — verify it passes**

Run: `pytest backend/tests/test_timeline_service.py -v`
Expected: 13 passed.

- [ ] **Step 6: Stage and propose commit**

Run:
```bash
git add backend/services/timeline_service.py backend/tests/test_timeline_service.py backend/tests/fixtures/timeline_raw.json
git status
```
Propose message: `Add timeline_service event normalization`
Halt for user approval.

---

### Task 1.5: Add fetch and cache orchestration to `timeline_service`

**Files:**
- Modify: `backend/services/timeline_service.py` (append `fetch_pr_timeline_from_api`, `get_timeline`, background refresh helper)

- [ ] **Step 1: Append API fetch function**

Add to `backend/services/timeline_service.py`:

```python
def fetch_pr_timeline_from_api(owner: str, repo: str, pr_number: int) -> List[Dict[str, Any]]:
    """Fetch and normalize the full issue timeline for a PR.

    Also fetches PR metadata (createdAt, user) to synthesize the 'opened' event.
    """
    try:
        raw_output = run_gh_command([
            "api",
            f"repos/{owner}/{repo}/issues/{pr_number}/timeline",
            "--paginate",
        ])
    except RuntimeError as e:
        logger.warning(f"Failed to fetch timeline for {owner}/{repo}#{pr_number}: {e}")
        raise

    raw_events = parse_json_output(raw_output) or []

    # Fetch minimal PR metadata for the synthesized opened event.
    try:
        pr_output = run_gh_command([
            "api",
            f"repos/{owner}/{repo}/pulls/{pr_number}",
            "--jq",
            '{created_at: .created_at, user: {login: .user.login, avatar_url: .user.avatar_url}}',
        ])
        pr_info = parse_json_output(pr_output) or {}
    except RuntimeError as e:
        logger.warning(f"Failed to fetch PR info for {owner}/{repo}#{pr_number}: {e}")
        pr_info = {}

    return normalize_timeline_events(raw_events, pr_info)
```

- [ ] **Step 2: Append cache orchestration function**

Add to `backend/services/timeline_service.py`:

```python
def _now_iso_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ttl_for_state(pr_state: Optional[str]) -> Optional[int]:
    """Return the TTL (in minutes) for a given PR state.

    Closed/Merged PRs are immutable — ttl of None means 'never stale'.
    Open PRs use 5-minute TTL.
    """
    if pr_state in ("CLOSED", "MERGED"):
        return None
    return _OPEN_TTL_MINUTES


def _background_refresh(owner: str, repo: str, pr_number: int, cache_db) -> None:
    """Worker function: refetch from the API and update the cache."""
    key = (repo, pr_number)
    try:
        current_state = fetch_pr_state(owner, repo, pr_number) or "OPEN"
        events = fetch_pr_timeline_from_api(owner, repo, pr_number)
        cache_db.save_cache(f"{owner}/{repo}", pr_number, current_state, events)
        logger.info(f"Background timeline refresh complete for {owner}/{repo}#{pr_number}")
    except Exception as e:
        logger.warning(
            f"Background timeline refresh failed for {owner}/{repo}#{pr_number}: {e}"
        )
    finally:
        with _refresh_lock:
            _refreshing.discard(key)


def get_timeline(
    owner: str,
    repo: str,
    pr_number: int,
    cache_db,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Cache-aware entry point for the timeline endpoint.

    Returns a dict matching the response schema:
        {
            "events": [...],
            "pr_state": "OPEN" | "CLOSED" | "MERGED",
            "last_updated": "...Z",
            "cached": bool,
            "stale": bool,
            "refreshing": bool,
        }
    """
    repo_key = f"{owner}/{repo}"
    key = (repo, pr_number)
    cached = cache_db.get_cached(repo_key, pr_number)

    if cached and not force_refresh:
        ttl = _ttl_for_state(cached["pr_state"])
        is_stale = cache_db.is_stale(repo_key, pr_number, ttl)

        if not is_stale:
            return {
                "events": cached["data"],
                "pr_state": cached["pr_state"],
                "last_updated": cached["updated_at"],
                "cached": True,
                "stale": False,
                "refreshing": False,
            }

        # Stale: return immediately, trigger background refresh.
        with _refresh_lock:
            already_refreshing = key in _refreshing
            if not already_refreshing:
                _refreshing.add(key)
        if not already_refreshing:
            t = threading.Thread(
                target=_background_refresh,
                args=(owner, repo, pr_number, cache_db),
                daemon=True,
            )
            t.start()

        return {
            "events": cached["data"],
            "pr_state": cached["pr_state"],
            "last_updated": cached["updated_at"],
            "cached": True,
            "stale": True,
            "refreshing": True,
        }

    # Cache miss or force refresh: fetch synchronously.
    current_state = fetch_pr_state(owner, repo, pr_number) or "OPEN"
    events = fetch_pr_timeline_from_api(owner, repo, pr_number)
    cache_db.save_cache(repo_key, pr_number, current_state, events)

    return {
        "events": events,
        "pr_state": current_state,
        "last_updated": _now_iso_z(),
        "cached": False,
        "stale": False,
        "refreshing": False,
    }
```

- [ ] **Step 3: Verify import and basic structure**

Run: `python -c "from backend.services.timeline_service import get_timeline, fetch_pr_timeline_from_api; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Stage and propose commit**

Run:
```bash
git add backend/services/timeline_service.py
git status
```
Propose message: `Add cache-aware get_timeline with stale-while-revalidate`
Halt for user approval.

---

### Task 1.6: Add `/timeline` route and wire clear-cache

**Files:**
- Modify: `backend/routes/pr_routes.py` (add route)
- Modify: `backend/routes/cache_routes.py` (wire in clear)

- [ ] **Step 1: Add the route**

Edit `backend/routes/pr_routes.py`. Add at the top with the other service imports:
```python
from backend.database import get_timeline_cache_db
from backend.services.timeline_service import get_timeline
```

Append a new route at the end of the file:
```python
@pr_bp.route("/api/repos/<owner>/<repo>/prs/<int:pr_number>/timeline")
def get_pr_timeline(owner, repo, pr_number):
    """Return the normalized event timeline for a single PR."""
    try:
        force = request.args.get("refresh") == "true"
        cache_db = get_timeline_cache_db()
        result = get_timeline(owner, repo, pr_number, cache_db, force_refresh=force)
        return jsonify(result)
    except RuntimeError as e:
        msg = str(e)
        if "Not Found" in msg or "404" in msg:
            return jsonify({"error": "PR not found"}), 404
        logger.error(f"Timeline fetch failed for {owner}/{repo}#{pr_number}: {msg}")
        return jsonify({"error": msg}), 503
    except Exception as e:
        logger.exception(f"Unexpected timeline error for {owner}/{repo}#{pr_number}")
        return jsonify({"error": str(e)}), 500
```

- [ ] **Step 2: Wire clear-cache to also clear timeline**

Read `backend/routes/cache_routes.py` to find the existing clear-cache handler. Add `get_timeline_cache_db` to the imports:
```python
from backend.database import (
    # existing imports...
    get_timeline_cache_db,
)
```

Inside the clear-cache handler, add a call to `get_timeline_cache_db().clear()` alongside the other `.clear()` calls.

- [ ] **Step 3: Manual smoke test**

Start the server: `python app.py`
In another terminal, hit the endpoint against a real PR you have access to (replace placeholders):
```bash
curl -sS 'http://127.0.0.1:5714/api/repos/OWNER/REPO/prs/PR_NUMBER/timeline' | python -m json.tool | head -60
```
Expected: JSON response with `events`, `pr_state`, `last_updated`, `cached: false` (first call), plus at least one event.

Then re-run the same curl immediately.
Expected: same JSON but with `cached: true`.

- [ ] **Step 4: Stage and propose commit**

Run:
```bash
git add backend/routes/pr_routes.py backend/routes/cache_routes.py
git status
```
Propose message: `Add GET /prs/:n/timeline route and clear-cache integration`
Halt for user approval.

---

### Task 1.7: Update `docs/DESIGN.md` for Phase 1

**Files:**
- Modify: `docs/DESIGN.md`

- [ ] **Step 1: Add new cache class entry**

In the "Database Classes" table inside `docs/DESIGN.md`, add a row:
```
| `TimelineCacheDB` | Caches per-PR timeline events with state-aware TTL (no TTL for closed/merged, 5-min for open) |
```

- [ ] **Step 2: Add new SQL schema block**

In the "Database Schema" code block, add the `pr_timeline_cache` table CREATE statement to match what's in `base.py`.

- [ ] **Step 3: Add TimelineCacheDB methods table**

Add a new "#### TimelineCacheDB Methods" subsection, mirroring the other cache DB subsections:

```markdown
#### TimelineCacheDB Methods

| Method | Description |
|--------|-------------|
| `get_cached()` | Returns cached timeline data (events + pr_state) for a (repo, pr_number) key |
| `save_cache()` | Upserts timeline data and pr_state |
| `is_stale()` | Checks staleness; ttl_minutes=None means "never stale" (closed/merged) |
| `clear()` | Removes all timeline cache entries |
```

- [ ] **Step 4: Add new service entry**

Add a row in the "Services" table:
```
| `timeline_service.py` | `fetch_pr_timeline_from_api()`, `normalize_timeline_events()`, `get_timeline()` |
```

- [ ] **Step 5: Add new blueprint route entry**

Under the `pr_bp` row in the "Blueprint | Routes" table, append: `, /api/repos/.../prs/:n/timeline`

- [ ] **Step 6: Add new API endpoint section**

Add under the "Pull Requests" API section a new subsection:

```markdown
---

**GET** `/api/repos/<owner>/<repo>/prs/<pr_number>/timeline`

Returns a normalized chronological event timeline for a single PR. Cached
in SQLite with state-aware TTL — closed/merged PRs cached indefinitely
(immutable), open PRs cached 5 minutes with stale-while-revalidate.

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
\```

**Event Types**: `opened`, `committed`, `commented`, `reviewed`,
`review_requested`, `ready_for_review`, `convert_to_draft`, `closed`,
`reopened`, `merged`, `head_ref_force_pushed`.

**Error Responses**:
- `404`: PR not found
- `503`: GitHub API error (falls back to stale cache if available)
- `500`: Internal server error
```

(Note: in the actual file, the inner triple-backtick `\``` should be written as real triple-backticks.)

- [ ] **Step 7: Stage and propose commit**

Run:
```bash
git add docs/DESIGN.md
git status
```
Propose message: `Document TimelineCacheDB, timeline_service, and /timeline endpoint`
Halt for user approval.

---

### Task 1.8: Phase 1 end-to-end verification

- [ ] **Step 1: Run full backend test suite**

Run: `pytest backend/tests/ -v`
Expected: all tests pass.

- [ ] **Step 2: Confirm Phase 1 smoke test still passes**

Restart `python app.py` and re-run the curl from Task 1.6 Step 3.
Expected: unchanged response shape.

- [ ] **Step 3: Push feature branch (optional — user discretion)**

Halt and ask user whether to push the branch to the remote now or wait until more phases are done.

---

## Phase 2 — Frontend modal & rendering

> All frontend TypeScript tasks in this phase may be delegated to the `typescript-pro` agent for implementation. Styling polish tasks may reference the `ui-ux-pro-max` skill. The task specifications below are self-contained either way.

### Task 2.1: Install Framer Motion

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json` (auto)

- [ ] **Step 1: Install framer-motion**

Run:
```bash
cd frontend && npm install framer-motion@^11.0.0
```
Expected: install succeeds with no peer dep warnings about React.

- [ ] **Step 2: Verify build still works**

Run: `cd frontend && npm run build`
Expected: build completes with no errors.

- [ ] **Step 3: Stage and propose commit**

Run:
```bash
git add frontend/package.json frontend/package-lock.json
git status
```
Propose message: `Add framer-motion for PR timeline animations`
Halt for user approval.

---

### Task 2.2: Add TimelineEvent types

**Files:**
- Modify: `frontend/src/api/types.ts` (add new exports at the bottom)

- [ ] **Step 1: Append types**

Append to `frontend/src/api/types.ts`:

```typescript
// ============================================================================
// PR Timeline types
// ============================================================================

export type TimelineEventType =
  | 'opened'
  | 'committed'
  | 'commented'
  | 'reviewed'
  | 'review_requested'
  | 'ready_for_review'
  | 'convert_to_draft'
  | 'closed'
  | 'reopened'
  | 'merged'
  | 'head_ref_force_pushed'

export interface TimelineActor {
  login: string
  avatar_url: string
}

export interface TimelineEventBase {
  id: string
  type: TimelineEventType
  created_at: string
  actor: TimelineActor | null
}

export interface OpenedEvent extends TimelineEventBase { type: 'opened' }
export interface CommittedEvent extends TimelineEventBase {
  type: 'committed'
  sha: string
  short_sha: string
  message: string
}
export interface CommentedEvent extends TimelineEventBase {
  type: 'commented'
  body: string
  html_url: string
}
export interface ReviewedEvent extends TimelineEventBase {
  type: 'reviewed'
  state: 'APPROVED' | 'CHANGES_REQUESTED' | 'COMMENTED'
  body: string
  html_url: string
}
export interface ReviewRequestedEvent extends TimelineEventBase {
  type: 'review_requested'
  requested_reviewer: TimelineActor | null
}
export interface ReadyForReviewEvent extends TimelineEventBase { type: 'ready_for_review' }
export interface ConvertToDraftEvent extends TimelineEventBase { type: 'convert_to_draft' }
export interface ClosedEvent extends TimelineEventBase { type: 'closed' }
export interface ReopenedEvent extends TimelineEventBase { type: 'reopened' }
export interface MergedEvent extends TimelineEventBase { type: 'merged', sha: string }
export interface ForcePushedEvent extends TimelineEventBase {
  type: 'head_ref_force_pushed'
  before: string
  after: string
}

export type TimelineEvent =
  | OpenedEvent
  | CommittedEvent
  | CommentedEvent
  | ReviewedEvent
  | ReviewRequestedEvent
  | ReadyForReviewEvent
  | ConvertToDraftEvent
  | ClosedEvent
  | ReopenedEvent
  | MergedEvent
  | ForcePushedEvent

export interface TimelineResponse {
  events: TimelineEvent[]
  pr_state: 'OPEN' | 'CLOSED' | 'MERGED'
  last_updated: string
  cached: boolean
  stale: boolean
  refreshing: boolean
}
```

- [ ] **Step 2: Verify typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Stage and propose commit**

Run:
```bash
git add frontend/src/api/types.ts
git status
```
Propose message: `Add TimelineEvent type union`
Halt for user approval.

---

### Task 2.3: Create the timeline API module

**Files:**
- Create: `frontend/src/api/timeline.ts`

- [ ] **Step 1: Locate the existing `apiFetch` pattern**

Read `frontend/src/api/client.ts` to confirm the shared fetch helper function name and signature. Use whatever the existing API modules use (most likely a `apiFetch` or raw `fetch` wrapped with error handling).

- [ ] **Step 2: Create timeline.ts mirroring an existing API module**

Read `frontend/src/api/repos.ts` as the shape reference. Create `frontend/src/api/timeline.ts`:

```typescript
import type { TimelineResponse } from './types'

interface FetchTimelineOptions {
  refresh?: boolean
}

export async function fetchTimeline(
  owner: string,
  repo: string,
  prNumber: number,
  opts: FetchTimelineOptions = {}
): Promise<TimelineResponse> {
  const params = new URLSearchParams()
  if (opts.refresh) params.set('refresh', 'true')
  const qs = params.toString() ? `?${params.toString()}` : ''
  const url = `/api/repos/${owner}/${repo}/prs/${prNumber}/timeline${qs}`
  const res = await fetch(url)
  if (!res.ok) {
    let message = `HTTP ${res.status}`
    try {
      const body = await res.json()
      message = body.error || message
    } catch {}
    throw new Error(message)
  }
  return res.json()
}
```

If `frontend/src/api/client.ts` exports a typed helper like `apiFetch<T>(path)`, use that instead — match the repo's existing convention.

- [ ] **Step 3: Verify typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Stage and propose commit**

Run:
```bash
git add frontend/src/api/timeline.ts
git status
```
Propose message: `Add timeline API fetcher`
Halt for user approval.

---

### Task 2.4: Create `useTimelineStore` (no polling yet)

**Files:**
- Create: `frontend/src/stores/useTimelineStore.ts`

- [ ] **Step 1: Review existing store conventions**

Read one of: `frontend/src/stores/useReviewStore.ts` or `frontend/src/stores/useQueueStore.ts` to see the project's Zustand style (imports, middleware, naming).

- [ ] **Step 2: Create the store**

Create `frontend/src/stores/useTimelineStore.ts`:

```typescript
import { create } from 'zustand'
import type { TimelineEvent, TimelineEventType, TimelineResponse } from '../api/types'
import { fetchTimeline } from '../api/timeline'

interface TimelineEntry {
  events: TimelineEvent[]
  prState: 'OPEN' | 'CLOSED' | 'MERGED'
  lastUpdated: string
  loading: boolean
  refreshing: boolean
  error: string | null
  expandedIds: Set<string>
  hiddenTypes: Set<TimelineEventType>
}

interface ModalTarget {
  owner: string
  repo: string
  prNumber: number
  title: string
  url: string
}

interface TimelineState {
  timelines: Record<string, TimelineEntry>
  openFor: ModalTarget | null

  open(target: ModalTarget): void
  close(): void
  load(owner: string, repo: string, prNumber: number, opts?: { force?: boolean }): Promise<void>
  toggleExpanded(key: string, eventId: string): void
  toggleType(key: string, type: TimelineEventType): void
  resetFilters(key: string): void
}

function keyFor(owner: string, repo: string, prNumber: number): string {
  return `${owner}/${repo}/${prNumber}`
}

function emptyEntry(): TimelineEntry {
  return {
    events: [],
    prState: 'OPEN',
    lastUpdated: '',
    loading: false,
    refreshing: false,
    error: null,
    expandedIds: new Set(),
    hiddenTypes: new Set(),
  }
}

export const useTimelineStore = create<TimelineState>((set, get) => ({
  timelines: {},
  openFor: null,

  open(target) {
    const key = keyFor(target.owner, target.repo, target.prNumber)
    set((state) => ({
      openFor: target,
      timelines: state.timelines[key]
        ? state.timelines
        : { ...state.timelines, [key]: emptyEntry() },
    }))
    get().load(target.owner, target.repo, target.prNumber)
  },

  close() {
    set({ openFor: null })
  },

  async load(owner, repo, prNumber, opts = {}) {
    const key = keyFor(owner, repo, prNumber)
    const existing = get().timelines[key]
    const hasData = existing && existing.events.length > 0

    set((state) => ({
      timelines: {
        ...state.timelines,
        [key]: {
          ...(state.timelines[key] ?? emptyEntry()),
          loading: !hasData,
          refreshing: hasData,
          error: null,
        },
      },
    }))

    try {
      const resp: TimelineResponse = await fetchTimeline(owner, repo, prNumber, { refresh: opts.force })
      set((state) => ({
        timelines: {
          ...state.timelines,
          [key]: {
            ...(state.timelines[key] ?? emptyEntry()),
            events: resp.events,
            prState: resp.pr_state,
            lastUpdated: resp.last_updated,
            loading: false,
            refreshing: resp.refreshing,
            error: null,
          },
        },
      }))
    } catch (err) {
      set((state) => ({
        timelines: {
          ...state.timelines,
          [key]: {
            ...(state.timelines[key] ?? emptyEntry()),
            loading: false,
            refreshing: false,
            error: err instanceof Error ? err.message : String(err),
          },
        },
      }))
    }
  },

  toggleExpanded(key, eventId) {
    set((state) => {
      const entry = state.timelines[key]
      if (!entry) return state
      const expandedIds = new Set(entry.expandedIds)
      if (expandedIds.has(eventId)) expandedIds.delete(eventId)
      else expandedIds.add(eventId)
      return { timelines: { ...state.timelines, [key]: { ...entry, expandedIds } } }
    })
  },

  toggleType(key, type) {
    set((state) => {
      const entry = state.timelines[key]
      if (!entry) return state
      const hiddenTypes = new Set(entry.hiddenTypes)
      if (hiddenTypes.has(type)) hiddenTypes.delete(type)
      else hiddenTypes.add(type)
      return { timelines: { ...state.timelines, [key]: { ...entry, hiddenTypes } } }
    })
  },

  resetFilters(key) {
    set((state) => {
      const entry = state.timelines[key]
      if (!entry) return state
      return { timelines: { ...state.timelines, [key]: { ...entry, hiddenTypes: new Set() } } }
    })
  },
}))

export function timelineKey(owner: string, repo: string, prNumber: number): string {
  return keyFor(owner, repo, prNumber)
}
```

- [ ] **Step 3: Verify typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Stage and propose commit**

Run:
```bash
git add frontend/src/stores/useTimelineStore.ts
git status
```
Propose message: `Add useTimelineStore for modal + timeline state`
Halt for user approval.

---

### Task 2.5: Create `timeline.css` styles

**Files:**
- Create: `frontend/src/styles/timeline.css`
- Modify: `frontend/src/main.tsx` (or the main stylesheet barrel) to import the new file

- [ ] **Step 1: Find the CSS import point**

Read `frontend/src/main.tsx`. Locate existing CSS imports (e.g., `import './styles/main.css'`). Note the pattern.

- [ ] **Step 2: Create the stylesheet**

Create `frontend/src/styles/timeline.css`:

```css
/* ============================================================================
   PR Timeline
   ============================================================================ */

/* Modal overlay and shell */
.tl-modal__overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 2.5vh 2.5vw;
}

.tl-modal__shell {
  background: var(--mx-surface, #151515);
  border: 1px solid var(--mx-border, #2a2a2a);
  border-radius: 16px;
  width: 95vw;
  height: 95vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
}

.tl-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 24px;
  border-bottom: 1px solid var(--mx-border, #2a2a2a);
  gap: 16px;
}

.tl-modal__title {
  font-size: 16px;
  font-weight: 600;
  color: var(--mx-text, #e5e7eb);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.tl-modal__title:hover { text-decoration: underline; }

.tl-modal__actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.tl-modal__body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 28px 32px;
  scroll-behavior: smooth;
}

/* Filter chips */
.tl-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 24px;
  border-bottom: 1px solid var(--mx-border, #2a2a2a);
  background: var(--mx-surface-2, #1a1a1a);
}

.tl-chip {
  border: 1px solid var(--mx-border, #2a2a2a);
  background: var(--mx-surface-2, #1a1a1a);
  color: var(--mx-text-muted, #888);
  font-size: 12px;
  padding: 6px 12px;
  border-radius: 999px;
  cursor: pointer;
  transition: background-color 120ms ease, color 120ms ease, border-color 120ms ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.tl-chip:hover { border-color: var(--mx-accent, #6366f1); color: var(--mx-text, #e5e7eb); }

.tl-chip--active {
  background: rgba(99, 102, 241, 0.15);
  border-color: var(--mx-accent, #6366f1);
  color: var(--mx-accent-fg, #a5b4fc);
}

.tl-chip__dot {
  width: 8px; height: 8px; border-radius: 50%;
}

/* Vertical rail */
.tl-rail {
  position: relative;
  padding-left: 44px;
}

.tl-rail::before {
  content: '';
  position: absolute;
  left: 18px;
  top: 4px;
  bottom: 4px;
  width: 2px;
  background: linear-gradient(180deg,
    var(--mx-accent, #6366f1) 0%,
    var(--mx-border, #2a2a2a) 70%,
    transparent 100%);
  border-radius: 2px;
}

/* Event row + dot */
.tl-event {
  position: relative;
  margin-bottom: 14px;
}

.tl-event__dot {
  position: absolute;
  left: -34px;
  top: 14px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--tl-dot-color, var(--mx-accent, #6366f1));
  box-shadow: 0 0 0 4px var(--tl-dot-glow, rgba(99, 102, 241, 0.2));
  cursor: pointer;
  transition: transform 160ms ease;
}

.tl-event__dot:hover { transform: scale(1.15); }

.tl-event__card {
  background: var(--mx-surface-2, #1a1a1a);
  border: 1px solid var(--mx-border, #2a2a2a);
  border-radius: 10px;
  padding: 12px 14px;
  transition: border-color 160ms ease;
}

.tl-event__card--expanded { border-color: var(--tl-dot-color, var(--mx-accent, #6366f1)); }

.tl-event__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  cursor: pointer;
  background: transparent;
  border: none;
  width: 100%;
  text-align: left;
  color: inherit;
  padding: 0;
  font: inherit;
}

.tl-event__who {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--mx-text, #e5e7eb);
  min-width: 0;
}

.tl-event__avatar { width: 20px; height: 20px; border-radius: 50%; flex-shrink: 0; }

.tl-event__when {
  font-size: 11px;
  color: var(--mx-text-muted, #888);
  white-space: nowrap;
  flex-shrink: 0;
}

.tl-event__body {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--mx-border, #2a2a2a);
  font-size: 13px;
  color: var(--mx-text-secondary, #bbb);
  line-height: 1.55;
  overflow: hidden;
}

.tl-event__body pre,
.tl-event__body code {
  background: var(--mx-code-bg, #0f0f0f);
  border-radius: 4px;
  font-size: 12px;
}

.tl-event__body pre {
  padding: 10px 12px;
  overflow-x: auto;
}

.tl-event__body code { padding: 1px 6px; }
.tl-event__body pre code { padding: 0; }

/* Skeleton loading */
.tl-skeleton {
  background: linear-gradient(90deg,
    var(--mx-surface-2, #1a1a1a) 0%,
    var(--mx-surface-3, #222) 50%,
    var(--mx-surface-2, #1a1a1a) 100%);
  background-size: 200% 100%;
  animation: tl-shimmer 1.4s infinite;
  border-radius: 8px;
  height: 48px;
  margin-bottom: 14px;
}

@keyframes tl-shimmer {
  from { background-position: 200% 0; }
  to { background-position: -200% 0; }
}

/* Empty / error states */
.tl-empty, .tl-error {
  padding: 48px 24px;
  text-align: center;
  color: var(--mx-text-muted, #888);
}

.tl-error { color: var(--mx-color-danger, #ef4444); }

/* Refresh / updated indicator */
.tl-updated {
  font-size: 11px;
  color: var(--mx-text-muted, #888);
  padding: 4px 10px;
  background: var(--mx-surface-2, #1a1a1a);
  border: 1px solid var(--mx-border, #2a2a2a);
  border-radius: 999px;
}

.tl-updated--refreshing { animation: tl-pulse 1.2s ease-in-out infinite; }

@keyframes tl-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}

@media (max-width: 768px) {
  .tl-modal__overlay { padding: 0; }
  .tl-modal__shell { width: 100vw; height: 100vh; border-radius: 0; }
  .tl-modal__body { padding: 16px; }
  .tl-rail { padding-left: 32px; }
  .tl-event__dot { left: -24px; }
}
```

- [ ] **Step 3: Import the stylesheet in `main.tsx`**

Add near the other CSS imports in `frontend/src/main.tsx`:
```typescript
import './styles/timeline.css'
```

- [ ] **Step 4: Verify the Vite dev server still starts**

Run: `cd frontend && npm run dev` (in a separate terminal)
Expected: server starts on :3050, no CSS parse errors. Stop the server after verifying.

- [ ] **Step 5: Stage and propose commit**

Run:
```bash
git add frontend/src/styles/timeline.css frontend/src/main.tsx
git status
```
Propose message: `Add PR timeline stylesheet with Matrix UI tokens`
Halt for user approval.

---

### Task 2.6: Event body components

**Files:**
- Create: `frontend/src/components/timeline/eventBodies/CommitBody.tsx`
- Create: `frontend/src/components/timeline/eventBodies/CommentBody.tsx`
- Create: `frontend/src/components/timeline/eventBodies/ReviewBody.tsx`
- Create: `frontend/src/components/timeline/eventBodies/StateChangeBody.tsx`
- Create: `frontend/src/components/timeline/eventBodies/ReviewRequestedBody.tsx`
- Create: `frontend/src/components/timeline/eventBodies/ForcePushBody.tsx`

- [ ] **Step 1: Create CommitBody**

Create `frontend/src/components/timeline/eventBodies/CommitBody.tsx`:

```tsx
import type { CommittedEvent } from '../../../api/types'

interface Props { event: CommittedEvent }

export function CommitBody({ event }: Props) {
  return (
    <div>
      <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{event.message}</pre>
      <div style={{ marginTop: 8 }}>
        <code>{event.short_sha}</code>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Create CommentBody (markdown)**

Create `frontend/src/components/timeline/eventBodies/CommentBody.tsx`:

```tsx
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import type { CommentedEvent } from '../../../api/types'

interface Props { event: CommentedEvent }

export function CommentBody({ event }: Props) {
  if (!event.body) return <em>(no content)</em>
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
      {event.body}
    </ReactMarkdown>
  )
}
```

- [ ] **Step 3: Create ReviewBody**

Create `frontend/src/components/timeline/eventBodies/ReviewBody.tsx`:

```tsx
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import type { ReviewedEvent } from '../../../api/types'

interface Props { event: ReviewedEvent }

const STATE_LABEL: Record<ReviewedEvent['state'], string> = {
  APPROVED: 'Approved',
  CHANGES_REQUESTED: 'Changes requested',
  COMMENTED: 'Commented',
}

export function ReviewBody({ event }: Props) {
  return (
    <div>
      <div style={{ marginBottom: 10, fontWeight: 500 }}>
        {STATE_LABEL[event.state] ?? event.state}
      </div>
      {event.body
        ? <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
            {event.body}
          </ReactMarkdown>
        : <em style={{ color: 'var(--mx-text-muted, #888)' }}>(no body)</em>}
    </div>
  )
}
```

- [ ] **Step 4: Create StateChangeBody**

Create `frontend/src/components/timeline/eventBodies/StateChangeBody.tsx`:

```tsx
import type {
  ClosedEvent,
  ReopenedEvent,
  MergedEvent,
  ReadyForReviewEvent,
  ConvertToDraftEvent,
  OpenedEvent,
} from '../../../api/types'

type AnyStateEvent =
  | OpenedEvent | ClosedEvent | ReopenedEvent | MergedEvent
  | ReadyForReviewEvent | ConvertToDraftEvent

interface Props { event: AnyStateEvent }

const LABEL: Record<AnyStateEvent['type'], string> = {
  opened: 'Opened this pull request',
  closed: 'Closed this pull request',
  reopened: 'Reopened this pull request',
  merged: 'Merged',
  ready_for_review: 'Marked ready for review',
  convert_to_draft: 'Converted back to draft',
}

export function StateChangeBody({ event }: Props) {
  return <div>{LABEL[event.type]}</div>
}
```

- [ ] **Step 5: Create ReviewRequestedBody**

Create `frontend/src/components/timeline/eventBodies/ReviewRequestedBody.tsx`:

```tsx
import type { ReviewRequestedEvent } from '../../../api/types'

interface Props { event: ReviewRequestedEvent }

export function ReviewRequestedBody({ event }: Props) {
  const reviewer = event.requested_reviewer
  if (!reviewer) return <div>Review requested</div>
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <img src={reviewer.avatar_url} alt={reviewer.login} width={20} height={20}
           style={{ borderRadius: '50%' }} />
      <span>Requested review from <strong>{reviewer.login}</strong></span>
    </div>
  )
}
```

- [ ] **Step 6: Create ForcePushBody**

Create `frontend/src/components/timeline/eventBodies/ForcePushBody.tsx`:

```tsx
import type { ForcePushedEvent } from '../../../api/types'

interface Props { event: ForcePushedEvent }

export function ForcePushBody({ event }: Props) {
  return (
    <div>
      Force-pushed{' '}
      <code>{event.before ? event.before.slice(0, 7) : '—'}</code>
      {' → '}
      <code>{event.after ? event.after.slice(0, 7) : '—'}</code>
    </div>
  )
}
```

- [ ] **Step 7: Verify typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 8: Stage and propose commit**

Run:
```bash
git add frontend/src/components/timeline/eventBodies
git status
```
Propose message: `Add per-event-type body components`
Halt for user approval.

---

### Task 2.7: `TimelineEventRow` component

**Files:**
- Create: `frontend/src/components/timeline/TimelineEventRow.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/timeline/TimelineEventRow.tsx`:

```tsx
import { motion, AnimatePresence } from 'framer-motion'
import type { TimelineEvent, TimelineEventType } from '../../api/types'
import { CommitBody } from './eventBodies/CommitBody'
import { CommentBody } from './eventBodies/CommentBody'
import { ReviewBody } from './eventBodies/ReviewBody'
import { StateChangeBody } from './eventBodies/StateChangeBody'
import { ReviewRequestedBody } from './eventBodies/ReviewRequestedBody'
import { ForcePushBody } from './eventBodies/ForcePushBody'

interface Props {
  event: TimelineEvent
  expanded: boolean
  onToggle: () => void
}

interface StyleVars extends React.CSSProperties {
  ['--tl-dot-color']?: string
  ['--tl-dot-glow']?: string
}

const DOT_COLOR: Record<TimelineEventType, string> = {
  opened: '#6366f1',
  committed: '#10b981',
  commented: '#f59e0b',
  reviewed: '#f59e0b', // overridden by state below
  review_requested: '#94a3b8',
  ready_for_review: '#0ea5e9',
  convert_to_draft: '#0ea5e9',
  closed: '#ef4444',
  reopened: '#6366f1',
  merged: '#8b5cf6',
  head_ref_force_pushed: '#f59e0b',
}

function dotColorFor(event: TimelineEvent): string {
  if (event.type === 'reviewed') {
    if (event.state === 'APPROVED') return '#10b981'
    if (event.state === 'CHANGES_REQUESTED') return '#ef4444'
    return '#f59e0b'
  }
  return DOT_COLOR[event.type]
}

function glowFor(hex: string): string {
  // hex -> rgba with 0.2 alpha
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, 0.22)`
}

function formatWhen(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}

function renderHeader(event: TimelineEvent): string {
  const who = event.actor?.login || 'unknown'
  switch (event.type) {
    case 'opened': return `${who} opened this pull request`
    case 'committed': return `${who} committed`
    case 'commented': return `${who} commented`
    case 'reviewed': {
      if (event.state === 'APPROVED') return `${who} approved`
      if (event.state === 'CHANGES_REQUESTED') return `${who} requested changes`
      return `${who} reviewed`
    }
    case 'review_requested':
      return `${who} requested a review`
    case 'ready_for_review': return `${who} marked ready for review`
    case 'convert_to_draft': return `${who} converted to draft`
    case 'closed': return `${who} closed this pull request`
    case 'reopened': return `${who} reopened this pull request`
    case 'merged': return `${who} merged this pull request`
    case 'head_ref_force_pushed': return `${who} force-pushed`
  }
}

function renderBody(event: TimelineEvent) {
  switch (event.type) {
    case 'committed': return <CommitBody event={event} />
    case 'commented': return <CommentBody event={event} />
    case 'reviewed': return <ReviewBody event={event} />
    case 'review_requested': return <ReviewRequestedBody event={event} />
    case 'head_ref_force_pushed': return <ForcePushBody event={event} />
    case 'opened':
    case 'closed':
    case 'reopened':
    case 'merged':
    case 'ready_for_review':
    case 'convert_to_draft':
      return <StateChangeBody event={event} />
  }
}

export function TimelineEventRow({ event, expanded, onToggle }: Props) {
  const color = dotColorFor(event)
  const styleVars: StyleVars = {
    '--tl-dot-color': color,
    '--tl-dot-glow': glowFor(color),
  }

  return (
    <div className="tl-event" style={styleVars}>
      <span
        className="tl-event__dot"
        onClick={onToggle}
        role="button"
        aria-label={expanded ? 'Collapse event' : 'Expand event'}
      />
      <motion.div
        layout
        className={`tl-event__card${expanded ? ' tl-event__card--expanded' : ''}`}
      >
        <button
          type="button"
          className="tl-event__header"
          onClick={onToggle}
          aria-expanded={expanded}
        >
          <span className="tl-event__who">
            {event.actor?.avatar_url && (
              <img className="tl-event__avatar" src={event.actor.avatar_url} alt="" />
            )}
            <span>{renderHeader(event)}</span>
          </span>
          <span className="tl-event__when">{formatWhen(event.created_at)}</span>
        </button>
        <AnimatePresence initial={false}>
          {expanded && (
            <motion.div
              className="tl-event__body"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ type: 'spring', damping: 26, stiffness: 300 }}
            >
              {renderBody(event)}
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  )
}
```

- [ ] **Step 2: Verify typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Stage and propose commit**

Run:
```bash
git add frontend/src/components/timeline/TimelineEventRow.tsx
git status
```
Propose message: `Add TimelineEventRow with color-coded dot and animated body`
Halt for user approval.

---

### Task 2.8: `TimelineView` component

**Files:**
- Create: `frontend/src/components/timeline/TimelineView.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/timeline/TimelineView.tsx`:

```tsx
import { motion } from 'framer-motion'
import type { TimelineEvent } from '../../api/types'
import { useTimelineStore, timelineKey } from '../../stores/useTimelineStore'
import { TimelineEventRow } from './TimelineEventRow'

interface Props {
  owner: string
  repo: string
  prNumber: number
}

export function TimelineView({ owner, repo, prNumber }: Props) {
  const key = timelineKey(owner, repo, prNumber)
  const entry = useTimelineStore((s) => s.timelines[key])
  const toggleExpanded = useTimelineStore((s) => s.toggleExpanded)
  const resetFilters = useTimelineStore((s) => s.resetFilters)

  if (!entry) return null

  if (entry.loading) {
    return (
      <div>
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="tl-skeleton" />
        ))}
      </div>
    )
  }

  if (entry.error) {
    return (
      <div className="tl-error">
        Failed to load timeline: {entry.error}
      </div>
    )
  }

  const visibleEvents: TimelineEvent[] = entry.events.filter(
    (e) => !entry.hiddenTypes.has(e.type)
  )

  if (visibleEvents.length === 0) {
    return (
      <div className="tl-empty">
        {entry.events.length === 0
          ? 'No events yet.'
          : (
            <>
              No events match the selected filters.{' '}
              <button type="button" onClick={() => resetFilters(key)}
                      style={{ background: 'none', border: 'none', color: 'var(--mx-accent, #6366f1)',
                               cursor: 'pointer', textDecoration: 'underline' }}>
                Reset filters
              </button>
            </>
          )}
      </div>
    )
  }

  return (
    <div className="tl-rail">
      {visibleEvents.map((event, i) => (
        <motion.div
          key={event.id}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            type: 'spring',
            damping: 28,
            stiffness: 320,
            delay: i < 20 ? i * 0.04 : 0,
          }}
        >
          <TimelineEventRow
            event={event}
            expanded={entry.expandedIds.has(event.id)}
            onToggle={() => toggleExpanded(key, event.id)}
          />
        </motion.div>
      ))}
    </div>
  )
}
```

- [ ] **Step 2: Verify typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Stage and propose commit**

Run:
```bash
git add frontend/src/components/timeline/TimelineView.tsx
git status
```
Propose message: `Add TimelineView with stagger-in animation and empty states`
Halt for user approval.

---

### Task 2.9: `TimelineFilters` component

**Files:**
- Create: `frontend/src/components/timeline/TimelineFilters.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/timeline/TimelineFilters.tsx`:

```tsx
import type { TimelineEventType } from '../../api/types'
import { useTimelineStore, timelineKey } from '../../stores/useTimelineStore'

interface Props {
  owner: string
  repo: string
  prNumber: number
}

const FILTER_GROUPS: Array<{ label: string; types: TimelineEventType[]; color: string }> = [
  { label: 'Commits', types: ['committed', 'head_ref_force_pushed'], color: '#10b981' },
  { label: 'Reviews', types: ['reviewed', 'review_requested'], color: '#f59e0b' },
  { label: 'Comments', types: ['commented'], color: '#f59e0b' },
  { label: 'State', types: ['opened', 'closed', 'reopened', 'merged', 'ready_for_review', 'convert_to_draft'], color: '#8b5cf6' },
]

export function TimelineFilters({ owner, repo, prNumber }: Props) {
  const key = timelineKey(owner, repo, prNumber)
  const entry = useTimelineStore((s) => s.timelines[key])
  const toggleType = useTimelineStore((s) => s.toggleType)

  if (!entry) return null

  return (
    <div className="tl-filters" role="group" aria-label="Filter timeline events">
      {FILTER_GROUPS.map((group) => {
        const allHidden = group.types.every((t) => entry.hiddenTypes.has(t))
        const isActive = !allHidden
        return (
          <button
            key={group.label}
            type="button"
            role="switch"
            aria-checked={isActive}
            className={`tl-chip${isActive ? ' tl-chip--active' : ''}`}
            onClick={() => group.types.forEach((t) => toggleType(key, t))}
          >
            <span className="tl-chip__dot" style={{ background: group.color }} />
            {group.label}
          </button>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 2: Verify typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Stage and propose commit**

Run:
```bash
git add frontend/src/components/timeline/TimelineFilters.tsx
git status
```
Propose message: `Add TimelineFilters chip bar`
Halt for user approval.

---

### Task 2.10: `TimelineHeader` component

**Files:**
- Create: `frontend/src/components/timeline/TimelineHeader.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/timeline/TimelineHeader.tsx`:

```tsx
import { useTimelineStore, timelineKey } from '../../stores/useTimelineStore'

interface Props {
  owner: string
  repo: string
  prNumber: number
  title: string
  url: string
}

function formatAgo(iso: string): string {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (!Number.isFinite(t)) return ''
  const diff = Math.max(0, (Date.now() - t) / 1000)
  if (diff < 60) return `${Math.floor(diff)}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

export function TimelineHeader({ owner, repo, prNumber, title, url }: Props) {
  const key = timelineKey(owner, repo, prNumber)
  const entry = useTimelineStore((s) => s.timelines[key])
  const load = useTimelineStore((s) => s.load)
  const close = useTimelineStore((s) => s.close)

  return (
    <div className="tl-modal__header">
      <a className="tl-modal__title" href={url} target="_blank" rel="noopener noreferrer">
        #{prNumber} {title}
      </a>
      <div className="tl-modal__actions">
        {entry?.lastUpdated && (
          <span className={`tl-updated${entry.refreshing ? ' tl-updated--refreshing' : ''}`}>
            Updated {formatAgo(entry.lastUpdated)}{entry.refreshing ? ' · refreshing…' : ''}
          </span>
        )}
        <button
          type="button"
          onClick={() => load(owner, repo, prNumber, { force: true })}
          aria-label="Refresh timeline"
          style={{ background: 'transparent', border: '1px solid var(--mx-border, #2a2a2a)',
                   color: 'var(--mx-text, #e5e7eb)', borderRadius: 8, padding: '6px 10px',
                   cursor: 'pointer' }}
        >
          ↻ Refresh
        </button>
        <button
          type="button"
          onClick={close}
          aria-label="Close timeline"
          style={{ background: 'transparent', border: 'none', color: 'var(--mx-text, #e5e7eb)',
                   fontSize: 20, cursor: 'pointer', padding: '0 8px' }}
        >
          ×
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Stage and propose commit**

Run:
```bash
git add frontend/src/components/timeline/TimelineHeader.tsx
git status
```
Propose message: `Add TimelineHeader with refresh and updated indicator`
Halt for user approval.

---

### Task 2.11: `TimelineModal` shell

**Files:**
- Create: `frontend/src/components/timeline/TimelineModal.tsx`

- [ ] **Step 1: Create the modal**

Create `frontend/src/components/timeline/TimelineModal.tsx`:

```tsx
import { useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useTimelineStore } from '../../stores/useTimelineStore'
import { TimelineHeader } from './TimelineHeader'
import { TimelineFilters } from './TimelineFilters'
import { TimelineView } from './TimelineView'

export function TimelineModal() {
  const openFor = useTimelineStore((s) => s.openFor)
  const close = useTimelineStore((s) => s.close)

  useEffect(() => {
    if (!openFor) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKey)
    const originalOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = originalOverflow
    }
  }, [openFor, close])

  return (
    <AnimatePresence>
      {openFor && (
        <motion.div
          className="tl-modal__overlay"
          onClick={close}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          role="dialog"
          aria-modal="true"
          aria-label={`Timeline for PR #${openFor.prNumber}`}
        >
          <motion.div
            className="tl-modal__shell"
            onClick={(e) => e.stopPropagation()}
            initial={{ opacity: 0, y: 20, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.98 }}
            transition={{ type: 'spring', damping: 28, stiffness: 320 }}
          >
            <TimelineHeader
              owner={openFor.owner}
              repo={openFor.repo}
              prNumber={openFor.prNumber}
              title={openFor.title}
              url={openFor.url}
            />
            <TimelineFilters
              owner={openFor.owner}
              repo={openFor.repo}
              prNumber={openFor.prNumber}
            />
            <div className="tl-modal__body">
              <TimelineView
                owner={openFor.owner}
                repo={openFor.repo}
                prNumber={openFor.prNumber}
              />
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
```

- [ ] **Step 2: Verify typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Stage and propose commit**

Run:
```bash
git add frontend/src/components/timeline/TimelineModal.tsx
git status
```
Propose message: `Add TimelineModal with focus-trap-style escape handling`
Halt for user approval.

---

### Task 2.12: Mount modal in App and add Timeline button to PRCard

**Files:**
- Modify: `frontend/src/App.tsx` (mount modal)
- Modify: `frontend/src/components/prs/PRCard.tsx` (add button)

- [ ] **Step 1: Mount modal at app root**

Edit `frontend/src/App.tsx`. Add import near the top with the other component imports:
```typescript
import { TimelineModal } from './components/timeline/TimelineModal'
```

Locate the root return JSX. Render `<TimelineModal />` as a sibling to the main app layout (typically just before the closing tag of the outermost `<div>` or fragment). For example:

```tsx
  return (
    <>
      {/* existing app content */}
      <TimelineModal />
    </>
  )
```

- [ ] **Step 2: Add Timeline button to PRCard**

Edit `frontend/src/components/prs/PRCard.tsx`. Add import:
```typescript
import { useTimelineStore } from '../../stores/useTimelineStore'
```

Inside the component body, add near the other store hooks:
```typescript
  const openTimeline = useTimelineStore((state) => state.open)
```

Then, inside the `<div className="mx-pr-card__actions">` block, add a new button alongside the existing ones (place it right after the Review button):

```tsx
        <Button
          variant="ghost"
          size="sm"
          onClick={() => openTimeline({
            owner: selectedRepo!.owner.login,
            repo: selectedRepo!.name,
            prNumber: pr.number,
            title: pr.title,
            url: pr.url,
          })}
          data-tooltip="View timeline"
        >
          ⏱
        </Button>
```

The `selectedRepo!` assertion is safe because the PR card only renders when a repo is selected, matching the existing `repoFullName` construction pattern.

- [ ] **Step 3: Verify typecheck and build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: no errors, build succeeds.

- [ ] **Step 4: Manual verify**

Start both servers:
- Terminal 1: `python app.py`
- Terminal 2: `cd frontend && npm run dev`

Open http://localhost:3050, select an account + repo, load PRs, click the ⏱ button on any card.

Verify:
- Modal opens with overlay + shell animation
- PR title and link render in header
- Filter chips appear
- Timeline loads events and stagger-animates in
- Clicking a dot or the header row expands the event body
- Markdown renders in commented / reviewed events
- Commit messages render with SHA
- Filter chips hide/show event types
- Esc closes the modal
- Click outside shell closes the modal
- Refresh button re-fetches

- [ ] **Step 5: Stage and propose commit**

Run:
```bash
git add frontend/src/App.tsx frontend/src/components/prs/PRCard.tsx
git status
```
Propose message: `Mount TimelineModal and add Timeline button to PR cards`
Halt for user approval.

---

### Task 2.13: Update `docs/DESIGN.md` for Phase 2

**Files:**
- Modify: `docs/DESIGN.md`

- [ ] **Step 1: Add "PR Timelines" feature section**

Under the "Features" section (after e.g. "Review History"), add:

```markdown
### PR Timelines

The PR Timelines feature provides a focused, single-PR deep-dive view showing
every lifecycle event as a vertical animated timeline.

#### How It Works

1. User clicks the ⏱ (Timeline) button on any PR card or merge queue card.
2. A full-screen modal opens and fetches the PR's normalized event timeline.
3. Events are rendered as a vertical rail with color-coded dots and
   expandable, markdown-rendered bodies.
4. Filter chips toggle groups of event types on/off.
5. Closed/merged PRs are served from indefinite SQLite cache; open PRs use
   a 5-minute TTL with stale-while-revalidate and manual refresh.

#### Event Types

| Event | Dot color | Source |
|-------|-----------|--------|
| opened | indigo | Synthesized from PR createdAt |
| committed | emerald | `committed` |
| commented | amber | `commented` |
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
```

- [ ] **Step 2: Stage and propose commit**

Run:
```bash
git add docs/DESIGN.md
git status
```
Propose message: `Document PR Timelines feature and components`
Halt for user approval.

---

## Phase 3 — Live updates & merge queue integration

### Task 3.1: Add polling lifecycle to the store

**Files:**
- Modify: `frontend/src/stores/useTimelineStore.ts`

- [ ] **Step 1: Extend store state**

Edit `frontend/src/stores/useTimelineStore.ts`. Inside the `TimelineEntry` interface, add:
```typescript
  pollTimer: number | null
```

Update `emptyEntry()` to include:
```typescript
    pollTimer: null,
```

Inside the `TimelineState` interface, add new methods:
```typescript
  startPolling(key: string): void
  stopPolling(key: string): void
```

- [ ] **Step 2: Implement polling methods**

Add these methods inside the `create<TimelineState>` factory, after `resetFilters`:

```typescript
  startPolling(key) {
    const entry = get().timelines[key]
    if (!entry) return
    if (entry.pollTimer !== null) return
    if (entry.prState !== 'OPEN') return
    const [owner, repo, prStr] = key.split('/')
    const prNumber = parseInt(prStr, 10)
    const timer = window.setInterval(() => {
      const current = get().timelines[key]
      if (!current || current.prState !== 'OPEN') return
      get().load(owner, repo, prNumber, { force: true })
    }, 45_000)
    set((state) => ({
      timelines: {
        ...state.timelines,
        [key]: { ...state.timelines[key], pollTimer: timer },
      },
    }))
  },

  stopPolling(key) {
    const entry = get().timelines[key]
    if (!entry || entry.pollTimer === null) return
    window.clearInterval(entry.pollTimer)
    set((state) => ({
      timelines: {
        ...state.timelines,
        [key]: { ...state.timelines[key], pollTimer: null },
      },
    }))
  },
```

Note: `key.split('/')` works because our `keyFor` produces `owner/repo/prNumber`. Repos never contain `/` inside `owner` or `repo` separately because each segment is path-safe in GitHub URLs.

- [ ] **Step 3: Add optimistic invalidation to open()**

Replace the existing `open` method body with:
```typescript
  open(target) {
    const key = keyFor(target.owner, target.repo, target.prNumber)
    const existing = get().timelines[key]
    let shouldForce = false
    if (existing && existing.lastUpdated && existing.prState === 'OPEN') {
      const age = Date.now() - new Date(existing.lastUpdated).getTime()
      if (age > 5 * 60_000) shouldForce = true
    }
    set((state) => ({
      openFor: target,
      timelines: state.timelines[key]
        ? state.timelines
        : { ...state.timelines, [key]: emptyEntry() },
    }))
    get().load(target.owner, target.repo, target.prNumber, { force: shouldForce })
  },
```

- [ ] **Step 4: Verify typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Stage and propose commit**

Run:
```bash
git add frontend/src/stores/useTimelineStore.ts
git status
```
Propose message: `Add polling lifecycle and optimistic invalidation to timeline store`
Halt for user approval.

---

### Task 3.2: Wire polling into TimelineModal lifecycle

**Files:**
- Modify: `frontend/src/components/timeline/TimelineModal.tsx`

- [ ] **Step 1: Add polling start/stop in effect**

Edit the existing `useEffect` block in `TimelineModal.tsx`. Replace it with:

```tsx
  const startPolling = useTimelineStore((s) => s.startPolling)
  const stopPolling = useTimelineStore((s) => s.stopPolling)

  useEffect(() => {
    if (!openFor) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    const key = `${openFor.owner}/${openFor.repo}/${openFor.prNumber}`

    window.addEventListener('keydown', onKey)
    const originalOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    // Start polling once the initial load has a known prState.
    // We kick it off via a micro-delay so load() has a chance to populate prState first.
    const pollStarter = window.setTimeout(() => startPolling(key), 200)

    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = originalOverflow
      window.clearTimeout(pollStarter)
      stopPolling(key)
    }
  }, [openFor, close, startPolling, stopPolling])
```

Note: the import for `useTimelineStore` is already present because the component already uses `close`.

- [ ] **Step 2: Verify typecheck and manual behavior**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

Start dev servers and open the modal on an OPEN PR. Leave it open for ~50 seconds. Then on GitHub (in a browser), post a comment on that PR. Return to the modal — within 45 s the new comment should appear without user interaction.

Close the modal. Reopen. Check the devtools Network tab to confirm polling stops when the modal is closed and starts when it's open.

- [ ] **Step 3: Stage and propose commit**

Run:
```bash
git add frontend/src/components/timeline/TimelineModal.tsx
git status
```
Propose message: `Start and stop timeline polling with modal lifecycle`
Halt for user approval.

---

### Task 3.3: Add Timeline button to QueueItem

**Files:**
- Modify: `frontend/src/components/queue/QueueItem.tsx`

- [ ] **Step 1: Read QueueItem to locate actions region**

Read `frontend/src/components/queue/QueueItem.tsx` and locate the actions / buttons region (mirrors `PRCard.tsx`).

- [ ] **Step 2: Add store hook and button**

Add the import at the top:
```typescript
import { useTimelineStore } from '../../stores/useTimelineStore'
```

Inside the component body, destructure the open method:
```typescript
  const openTimeline = useTimelineStore((state) => state.open)
```

In the actions region, add a Timeline button that derives `owner` and `repo` from the queue item's `repo` field (which is in `owner/repo` format):

```tsx
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            const [owner, repo] = item.repo.split('/')
            openTimeline({
              owner,
              repo,
              prNumber: item.number,
              title: item.title,
              url: item.url,
            })
          }}
          data-tooltip="View timeline"
        >
          ⏱
        </Button>
```

Match the prop name (`item` vs. another identifier) used by the surrounding code.

- [ ] **Step 3: Verify typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Manual verify**

In the dev servers, open the merge queue panel, click ⏱ on a queued item. Confirm the timeline modal opens with that PR's data. Confirm that the PR card modal and queue item modal share the same store entry (opening from either doesn't re-fetch if already cached).

- [ ] **Step 5: Stage and propose commit**

Run:
```bash
git add frontend/src/components/queue/QueueItem.tsx
git status
```
Propose message: `Add Timeline button to merge queue items`
Halt for user approval.

---

### Task 3.4: Update `docs/DESIGN.md` for Phase 3

**Files:**
- Modify: `docs/DESIGN.md`

- [ ] **Step 1: Extend the PR Timelines feature section**

At the end of the "PR Timelines" feature section added in Phase 2, append:

```markdown
#### Live Updates

- While the modal is open AND the PR is `OPEN`, the timeline is re-fetched
  every 45 seconds in the background. Closed/Merged PRs do not poll
  (their history is immutable).
- When the modal opens, if the cached entry is older than 5 minutes and the
  PR is open, a forced refresh is triggered immediately (optimistic
  invalidation) so a PR you opened hours ago doesn't show stale events
  on reopen.
- A `Refresh` button in the header forces an immediate refresh at any time.
- The `Updated X ago` indicator pulses when a refresh is in progress.

#### Entry Points

| Location | Button |
|----------|--------|
| PR card in the PR list | ⏱ Timeline |
| Merge queue card | ⏱ Timeline |
```

- [ ] **Step 2: Add to "Entry Points" in Merge Queue UI Components table**

In the Merge Queue "UI Components" table within `docs/DESIGN.md`, add a new row:
```
| Timeline Button | Queue Item | Opens the PR Timelines modal for this PR |
```

- [ ] **Step 3: Stage and propose commit**

Run:
```bash
git add docs/DESIGN.md
git status
```
Propose message: `Document PR Timeline live updates and merge queue integration`
Halt for user approval.

---

### Task 3.5: Phase 3 verification and branch wrap-up

- [ ] **Step 1: Run full backend test suite**

Run: `pytest backend/tests/ -v`
Expected: all tests pass.

- [ ] **Step 2: Frontend typecheck + build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: no errors, build succeeds.

- [ ] **Step 3: End-to-end smoke test**

With both dev servers running, verify each of these in a browser:
- Open modal from a PR card for an OPEN PR. Leave open, post a comment on GitHub, see it appear within 45s.
- Open modal from the merge queue for the same PR. Same cached data, no extra fetch.
- Open modal for a MERGED PR. No polling requests in devtools Network.
- Close modal. No further polling requests.
- Reopen modal on open PR after > 5 min. Observe optimistic forced refresh.
- Refresh button forces an immediate re-fetch regardless of age.
- Dark and light mode both render the timeline correctly.
- Filter chips hide/show event groups.
- All event types render with appropriate colors.

- [ ] **Step 4: Invoke superpowers:finishing-a-development-branch**

Follow the skill's guidance to merge the feature branch (via PR or fast-forward as preferred) and clean up the worktree.

---

## Summary of files

**Created:**
- `backend/tests/__init__.py`
- `backend/tests/conftest.py`
- `backend/tests/test_timeline_cache_db.py`
- `backend/tests/test_timeline_service.py`
- `backend/tests/fixtures/timeline_raw.json`
- `backend/services/timeline_service.py`
- `frontend/src/api/timeline.ts`
- `frontend/src/stores/useTimelineStore.ts`
- `frontend/src/styles/timeline.css`
- `frontend/src/components/timeline/TimelineModal.tsx`
- `frontend/src/components/timeline/TimelineHeader.tsx`
- `frontend/src/components/timeline/TimelineFilters.tsx`
- `frontend/src/components/timeline/TimelineView.tsx`
- `frontend/src/components/timeline/TimelineEventRow.tsx`
- `frontend/src/components/timeline/eventBodies/CommitBody.tsx`
- `frontend/src/components/timeline/eventBodies/CommentBody.tsx`
- `frontend/src/components/timeline/eventBodies/ReviewBody.tsx`
- `frontend/src/components/timeline/eventBodies/StateChangeBody.tsx`
- `frontend/src/components/timeline/eventBodies/ReviewRequestedBody.tsx`
- `frontend/src/components/timeline/eventBodies/ForcePushBody.tsx`

**Modified:**
- `requirements.txt`
- `backend/database/base.py`
- `backend/database/cache_stores.py`
- `backend/database/__init__.py`
- `backend/routes/pr_routes.py`
- `backend/routes/cache_routes.py`
- `frontend/package.json`
- `frontend/src/api/types.ts`
- `frontend/src/main.tsx`
- `frontend/src/App.tsx`
- `frontend/src/components/prs/PRCard.tsx`
- `frontend/src/components/queue/QueueItem.tsx`
- `docs/DESIGN.md`
