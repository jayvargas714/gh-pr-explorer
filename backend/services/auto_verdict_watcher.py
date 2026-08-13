"""Background watcher that notices review completions without a browser attached.

check_review_status() is normally driven by the frontend polling GET /api/reviews.
With no tab open a finished review is neither persisted nor auto-verdicted until
someone reopens the app. This watcher polls the same function on a timer so armed
PRs get their verdict as soon as the review process exits.
"""

import logging
import time

logger = logging.getLogger(__name__)

WATCH_INTERVAL_SECONDS = 10


def auto_verdict_watcher_loop(interval=WATCH_INTERVAL_SECONDS):
    """Poll every active review for completion until the process exits."""
    from backend.database import get_reviews_db
    from backend.extensions import active_reviews, reviews_lock
    from backend.services.review_service import check_review_status

    logger.info(f"Auto-verdict watcher started (interval={interval}s)")
    while True:
        try:
            with reviews_lock:
                keys = list(active_reviews.keys())
            if keys:
                reviews_db = get_reviews_db()
                for key in keys:
                    try:
                        check_review_status(key, active_reviews, reviews_lock, reviews_db)
                    except Exception as e:
                        logger.error(f"Watcher: failed to check review {key}: {e}")
        except Exception as e:
            logger.error(f"Auto-verdict watcher iteration failed: {e}")
        time.sleep(interval)
