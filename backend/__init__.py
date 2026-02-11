"""GitHub PR Explorer - Backend Package.

Provides the Flask application factory and all backend modules.
"""

import threading

from flask import Flask

from backend.config import get_config, PROJECT_ROOT, REVIEWS_DIR
from backend.extensions import logger
from backend.database import get_workflow_cache_db
from backend.routes import register_blueprints


def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__)
    register_blueprints(app)
    return app


def startup_refresh_workflow_caches():
    """Background task: refresh any stale workflow caches on startup."""
    from backend.extensions import workflow_refresh_in_progress, workflow_refresh_lock
    from backend.services.workflow_service import fetch_workflow_data

    config = get_config()
    ttl_minutes = config.get("workflow_cache_ttl_minutes", 60)
    workflow_cache_db = get_workflow_cache_db()

    try:
        repos = workflow_cache_db.get_all_repos()
        for repo_key in repos:
            if workflow_cache_db.is_stale(repo_key, ttl_minutes):
                parts = repo_key.split("/", 1)
                if len(parts) == 2:
                    owner, repo = parts
                    with workflow_refresh_lock:
                        if repo_key not in workflow_refresh_in_progress:
                            workflow_refresh_in_progress.add(repo_key)
                    try:
                        logger.info(f"Startup: refreshing stale workflow cache for {repo_key}")
                        data = fetch_workflow_data(owner, repo)
                        workflow_cache_db.save_cache(repo_key, data)
                        logger.info(f"Startup: refreshed {repo_key} with {len(data['runs'])} runs")
                    except Exception as e:
                        logger.error(f"Startup: failed to refresh {repo_key}: {e}")
                    finally:
                        with workflow_refresh_lock:
                            workflow_refresh_in_progress.discard(repo_key)
    except Exception as e:
        logger.error(f"Startup workflow cache refresh failed: {e}")
