"""Database package - re-exports all DB classes and factory functions."""

import threading
from typing import Optional

from backend.database.base import Database
from backend.database.reviews import ReviewsDB
from backend.database.merge_queue import MergeQueueDB
from backend.database.settings import SettingsDB
from backend.database.dev_stats import DeveloperStatsDB
from backend.database.cache_stores import (
    LifecycleCacheDB,
    WorkflowCacheDB,
    ContributorTimeSeriesCacheDB,
    CodeActivityCacheDB,
)

# Thread-safe singleton instances
_db_lock = threading.Lock()

_db_instance: Optional[Database] = None
_reviews_db: Optional[ReviewsDB] = None
_queue_db: Optional[MergeQueueDB] = None
_settings_db: Optional[SettingsDB] = None
_dev_stats_db: Optional[DeveloperStatsDB] = None
_lifecycle_cache_db: Optional[LifecycleCacheDB] = None
_workflow_cache_db: Optional[WorkflowCacheDB] = None
_contributor_ts_cache_db: Optional[ContributorTimeSeriesCacheDB] = None
_code_activity_cache_db: Optional[CodeActivityCacheDB] = None


def get_database() -> Database:
    global _db_instance
    if _db_instance is None:
        with _db_lock:
            if _db_instance is None:
                _db_instance = Database()
    return _db_instance


def get_reviews_db() -> ReviewsDB:
    global _reviews_db
    if _reviews_db is None:
        db = get_database()
        with _db_lock:
            if _reviews_db is None:
                _reviews_db = ReviewsDB(db)
    return _reviews_db


def get_queue_db() -> MergeQueueDB:
    global _queue_db
    if _queue_db is None:
        db = get_database()
        with _db_lock:
            if _queue_db is None:
                _queue_db = MergeQueueDB(db)
    return _queue_db


def get_settings_db() -> SettingsDB:
    global _settings_db
    if _settings_db is None:
        db = get_database()
        with _db_lock:
            if _settings_db is None:
                _settings_db = SettingsDB(db)
    return _settings_db


def get_dev_stats_db() -> DeveloperStatsDB:
    global _dev_stats_db
    if _dev_stats_db is None:
        db = get_database()
        with _db_lock:
            if _dev_stats_db is None:
                _dev_stats_db = DeveloperStatsDB(db)
    return _dev_stats_db


def get_lifecycle_cache_db() -> LifecycleCacheDB:
    global _lifecycle_cache_db
    if _lifecycle_cache_db is None:
        db = get_database()
        with _db_lock:
            if _lifecycle_cache_db is None:
                _lifecycle_cache_db = LifecycleCacheDB(db)
    return _lifecycle_cache_db


def get_workflow_cache_db() -> WorkflowCacheDB:
    global _workflow_cache_db
    if _workflow_cache_db is None:
        db = get_database()
        with _db_lock:
            if _workflow_cache_db is None:
                _workflow_cache_db = WorkflowCacheDB(db)
    return _workflow_cache_db


def get_contributor_ts_cache_db() -> ContributorTimeSeriesCacheDB:
    global _contributor_ts_cache_db
    if _contributor_ts_cache_db is None:
        db = get_database()
        with _db_lock:
            if _contributor_ts_cache_db is None:
                _contributor_ts_cache_db = ContributorTimeSeriesCacheDB(db)
    return _contributor_ts_cache_db


def get_code_activity_cache_db() -> CodeActivityCacheDB:
    global _code_activity_cache_db
    if _code_activity_cache_db is None:
        db = get_database()
        with _db_lock:
            if _code_activity_cache_db is None:
                _code_activity_cache_db = CodeActivityCacheDB(db)
    return _code_activity_cache_db


__all__ = [
    "Database", "ReviewsDB", "MergeQueueDB", "SettingsDB",
    "DeveloperStatsDB", "LifecycleCacheDB", "WorkflowCacheDB",
    "ContributorTimeSeriesCacheDB", "CodeActivityCacheDB",
    "get_database", "get_reviews_db", "get_queue_db", "get_settings_db",
    "get_dev_stats_db", "get_lifecycle_cache_db", "get_workflow_cache_db",
    "get_contributor_ts_cache_db", "get_code_activity_cache_db",
]
