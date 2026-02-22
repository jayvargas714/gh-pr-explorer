"""Shared singletons: DB instances, logger, in-memory cache dict.

All global state used across modules lives here to avoid circular imports.
"""

import logging
import threading

from cachetools import TTLCache

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("gh_pr_explorer")

# Bounded in-memory cache with TTL eviction (max 256 entries, 5-minute default TTL)
cache = TTLCache(maxsize=256, ttl=300)

# In-memory tracking of active review processes
# key: "owner/repo/pr_number", value: {"process": Popen, "status": str, ...}
active_reviews = {}
reviews_lock = threading.Lock()

# Background refresh tracking sets + locks for stale-while-revalidate caches
workflow_refresh_in_progress = set()
workflow_refresh_lock = threading.Lock()

contributor_ts_refresh_in_progress = set()
contributor_ts_refresh_lock = threading.Lock()

activity_refresh_in_progress = set()
activity_refresh_lock = threading.Lock()

stats_refresh_in_progress = set()
stats_refresh_lock = threading.Lock()

lifecycle_refresh_in_progress = set()
lifecycle_refresh_lock = threading.Lock()
