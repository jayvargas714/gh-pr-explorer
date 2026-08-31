"""Database package - re-exports all DB classes and factory functions."""

import threading
from typing import Optional

from backend.database.base import Database
from backend.database.reviews import ReviewsDB
from backend.database.review_events import ReviewEventsDB
from backend.database.audits import AuditsDB
from backend.database.auto_verdicts import AutoVerdictsDB
from backend.database.merge_queue import MergeQueueDB
from backend.database.swimlanes import SwimlanesDB
from backend.database.settings import SettingsDB
from backend.database.reviewers import ReviewersDB
from backend.database.automation_dispatches import AutomationDispatchesDB
from backend.database.synced_prs import SyncedPRsDB
from backend.database.dev_stats import DeveloperStatsDB
from backend.database.cache_stores import (
    LifecycleCacheDB,
    WorkflowCacheDB,
    ContributorTimeSeriesCacheDB,
    CodeActivityCacheDB,
    RepoStatsCacheDB,
    RepoLOCCacheDB,
    TimelineCacheDB,
)

# Thread-safe singleton instances
_db_lock = threading.Lock()

_db_instance: Optional[Database] = None
_reviews_db: Optional[ReviewsDB] = None
_review_events_db: Optional[ReviewEventsDB] = None
_audits_db: Optional[AuditsDB] = None
_auto_verdicts_db: Optional[AutoVerdictsDB] = None
_queue_db: Optional[MergeQueueDB] = None
_swimlanes_db: Optional[SwimlanesDB] = None
_settings_db: Optional[SettingsDB] = None
_dev_stats_db: Optional[DeveloperStatsDB] = None
_lifecycle_cache_db: Optional[LifecycleCacheDB] = None
_workflow_cache_db: Optional[WorkflowCacheDB] = None
_contributor_ts_cache_db: Optional[ContributorTimeSeriesCacheDB] = None
_code_activity_cache_db: Optional[CodeActivityCacheDB] = None
_repo_stats_cache_db: Optional[RepoStatsCacheDB] = None
_repo_loc_cache_db: Optional[RepoLOCCacheDB] = None
_timeline_cache_db: Optional[TimelineCacheDB] = None
_synced_prs_db: Optional[SyncedPRsDB] = None
_reviewers_db: Optional[ReviewersDB] = None
_automation_dispatches_db: Optional[AutomationDispatchesDB] = None


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


def get_review_events_db() -> ReviewEventsDB:
    global _review_events_db
    if _review_events_db is None:
        db = get_database()
        with _db_lock:
            if _review_events_db is None:
                _review_events_db = ReviewEventsDB(db)
    return _review_events_db


def get_audits_db() -> AuditsDB:
    global _audits_db
    if _audits_db is None:
        db = get_database()
        with _db_lock:
            if _audits_db is None:
                _audits_db = AuditsDB(db)
    return _audits_db


def get_auto_verdicts_db() -> AutoVerdictsDB:
    global _auto_verdicts_db
    if _auto_verdicts_db is None:
        db = get_database()
        with _db_lock:
            if _auto_verdicts_db is None:
                _auto_verdicts_db = AutoVerdictsDB(db)
    return _auto_verdicts_db


def get_queue_db() -> MergeQueueDB:
    global _queue_db
    if _queue_db is None:
        db = get_database()
        with _db_lock:
            if _queue_db is None:
                _queue_db = MergeQueueDB(db)
    return _queue_db


def get_swimlanes_db() -> SwimlanesDB:
    global _swimlanes_db
    if _swimlanes_db is None:
        db = get_database()
        with _db_lock:
            if _swimlanes_db is None:
                _swimlanes_db = SwimlanesDB(db)
    return _swimlanes_db


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


def get_repo_stats_cache_db() -> RepoStatsCacheDB:
    global _repo_stats_cache_db
    if _repo_stats_cache_db is None:
        db = get_database()
        with _db_lock:
            if _repo_stats_cache_db is None:
                _repo_stats_cache_db = RepoStatsCacheDB(db)
    return _repo_stats_cache_db


def get_repo_loc_cache_db() -> RepoLOCCacheDB:
    global _repo_loc_cache_db
    if _repo_loc_cache_db is None:
        db = get_database()
        with _db_lock:
            if _repo_loc_cache_db is None:
                _repo_loc_cache_db = RepoLOCCacheDB(db)
    return _repo_loc_cache_db


def get_timeline_cache_db() -> TimelineCacheDB:
    global _timeline_cache_db
    if _timeline_cache_db is None:
        db = get_database()
        with _db_lock:
            if _timeline_cache_db is None:
                _timeline_cache_db = TimelineCacheDB(db)
    return _timeline_cache_db


def get_synced_prs_db() -> SyncedPRsDB:
    global _synced_prs_db
    if _synced_prs_db is None:
        db = get_database()
        with _db_lock:
            if _synced_prs_db is None:
                _synced_prs_db = SyncedPRsDB(db)
    return _synced_prs_db


def get_reviewers_db() -> ReviewersDB:
    global _reviewers_db
    if _reviewers_db is None:
        db = get_database()
        with _db_lock:
            if _reviewers_db is None:
                _reviewers_db = ReviewersDB(db)
    return _reviewers_db


def get_automation_dispatches_db() -> AutomationDispatchesDB:
    global _automation_dispatches_db
    if _automation_dispatches_db is None:
        db = get_database()
        with _db_lock:
            if _automation_dispatches_db is None:
                _automation_dispatches_db = AutomationDispatchesDB(db)
    return _automation_dispatches_db


__all__ = [
    "Database", "ReviewsDB", "ReviewEventsDB", "AuditsDB", "AutoVerdictsDB", "MergeQueueDB", "SwimlanesDB", "SettingsDB",
    "SyncedPRsDB", "get_synced_prs_db",
    "ReviewersDB", "get_reviewers_db",
    "AutomationDispatchesDB", "get_automation_dispatches_db",
    "DeveloperStatsDB", "LifecycleCacheDB", "WorkflowCacheDB",
    "ContributorTimeSeriesCacheDB", "CodeActivityCacheDB",
    "RepoStatsCacheDB", "RepoLOCCacheDB", "TimelineCacheDB",
    "get_database", "get_reviews_db", "get_review_events_db",
    "get_audits_db", "get_auto_verdicts_db",
    "get_queue_db", "get_swimlanes_db",
    "get_settings_db", "get_dev_stats_db", "get_lifecycle_cache_db",
    "get_workflow_cache_db", "get_contributor_ts_cache_db",
    "get_code_activity_cache_db", "get_repo_stats_cache_db",
    "get_repo_loc_cache_db", "get_timeline_cache_db",
]
