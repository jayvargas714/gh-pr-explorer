"""Database module for GitHub PR Explorer.

Thin re-export layer - all implementations live in backend/database/.
This file exists for backward compatibility with scripts (migrate_data.py, seed_workflow_cache.py).
"""

# Re-export everything from backend.database
from backend.database import (  # noqa: F401
    Database,
    ReviewsDB,
    MergeQueueDB,
    SettingsDB,
    DeveloperStatsDB,
    LifecycleCacheDB,
    WorkflowCacheDB,
    ContributorTimeSeriesCacheDB,
    CodeActivityCacheDB,
    get_database,
    get_reviews_db,
    get_queue_db,
    get_settings_db,
    get_dev_stats_db,
    get_lifecycle_cache_db,
    get_workflow_cache_db,
    get_contributor_ts_cache_db,
    get_code_activity_cache_db,
)

# Re-export DB_PATH for backward compat
from backend.config import DB_PATH  # noqa: F401
