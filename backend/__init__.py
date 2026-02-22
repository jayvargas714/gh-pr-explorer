"""GitHub PR Explorer - Backend Package.

Provides the Flask application factory and all backend modules.
"""

import threading

from flask import Flask

from backend.config import get_config, PROJECT_ROOT
from backend.extensions import logger
from backend.database import get_workflow_cache_db, get_dev_stats_db
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


def startup_refresh_stats_caches():
    """Background task: refresh any stale developer stats caches on startup."""
    from backend.extensions import stats_refresh_in_progress, stats_refresh_lock
    from backend.services.stats_service import fetch_and_compute_stats, stats_to_cache_format

    dev_stats_db = get_dev_stats_db()

    try:
        repos = dev_stats_db.get_all_repos()
        for repo_key in repos:
            if dev_stats_db.is_stale(repo_key):
                parts = repo_key.split("/", 1)
                if len(parts) == 2:
                    owner, repo = parts
                    with stats_refresh_lock:
                        if repo_key not in stats_refresh_in_progress:
                            stats_refresh_in_progress.add(repo_key)
                    try:
                        logger.info(f"Startup: refreshing stale stats cache for {repo_key}")
                        stats_list = fetch_and_compute_stats(owner, repo)
                        if stats_list:
                            cache_data = stats_to_cache_format(stats_list)
                            dev_stats_db.save_stats(repo_key, cache_data)
                            logger.info(f"Startup: refreshed stats for {repo_key} with {len(stats_list)} developers")
                        else:
                            logger.warning(f"Startup: empty stats for {repo_key}, keeping existing cache")
                    except Exception as e:
                        logger.error(f"Startup: failed to refresh stats for {repo_key}: {e}")
                    finally:
                        with stats_refresh_lock:
                            stats_refresh_in_progress.discard(repo_key)
    except Exception as e:
        logger.error(f"Startup stats cache refresh failed: {e}")
