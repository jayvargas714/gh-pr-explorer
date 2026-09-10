"""Database module for GitHub PR Explorer.

Thin re-export layer - all implementations live in backend/database/.
This file exists for backward compatibility with scripts (migrate_data.py, seed_workflow_cache.py).
"""

# Re-export everything from backend.database
from backend.database import (  # noqa: F401
    Database,
    ReviewsDB,
    MergeQueueDB,
    get_workflow_cache_db,
)

# Re-export DB_PATH for backward compat
from backend.config import DB_PATH  # noqa: F401
