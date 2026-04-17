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
