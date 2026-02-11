"""Workflow/CI routes: workflow runs with filters and aggregate stats."""

import threading

from flask import Blueprint, jsonify, request

from backend.config import get_config
from backend.extensions import (
    logger,
    workflow_refresh_in_progress, workflow_refresh_lock,
)
from backend.database import get_workflow_cache_db
from backend.services.workflow_service import fetch_workflow_data
from backend.visualizers.workflow_visualizer import filter_and_compute_stats

workflow_bp = Blueprint("workflow", __name__)


def _background_refresh_workflows(owner, repo, repo_key):
    """Background task to refresh workflow cache for a repository."""
    try:
        logger.info(f"Background workflow refresh started for {repo_key}")
        workflow_cache_db = get_workflow_cache_db()
        data = fetch_workflow_data(owner, repo)
        workflow_cache_db.save_cache(repo_key, data)
        logger.info(f"Background workflow refresh completed for {repo_key}: {len(data['runs'])} runs cached")
    except Exception as e:
        logger.error(f"Background workflow refresh failed for {repo_key}: {e}")
    finally:
        with workflow_refresh_lock:
            workflow_refresh_in_progress.discard(repo_key)


@workflow_bp.route("/api/repos/<owner>/<repo>/workflow-runs")
def get_workflow_runs(owner, repo):
    """Get workflow runs with optional filters and aggregate stats."""
    repo_key = f"{owner}/{repo}"
    config = get_config()
    ttl_minutes = config.get("workflow_cache_ttl_minutes", 60)
    force_refresh = request.args.get("refresh", "").lower() == "true"
    workflow_cache_db = get_workflow_cache_db()

    filters = {
        "workflow_id": request.args.get("workflow_id"),
        "branch": request.args.get("branch"),
        "event": request.args.get("event"),
        "conclusion": request.args.get("conclusion"),
        "status": request.args.get("status"),
    }

    try:
        if force_refresh:
            logger.info(f"Force refresh requested for {repo_key}")
            data = fetch_workflow_data(owner, repo)
            workflow_cache_db.save_cache(repo_key, data)
            result = filter_and_compute_stats(data, filters)
            return jsonify(result)

        cached = workflow_cache_db.get_cached(repo_key)
        is_stale = workflow_cache_db.is_stale(repo_key, ttl_minutes)

        if cached:
            if is_stale:
                with workflow_refresh_lock:
                    if repo_key not in workflow_refresh_in_progress:
                        workflow_refresh_in_progress.add(repo_key)
                        thread = threading.Thread(
                            target=_background_refresh_workflows,
                            args=(owner, repo, repo_key),
                            daemon=True
                        )
                        thread.start()

            result = filter_and_compute_stats(cached["data"], filters)
            return jsonify(result)

        # No cache: synchronous fetch
        data = fetch_workflow_data(owner, repo)
        workflow_cache_db.save_cache(repo_key, data)
        result = filter_and_compute_stats(data, filters)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Failed to get workflow runs for {repo_key}: {e}")
        return jsonify({"error": str(e)}), 500
