"""Repo stats routes: repository overview, language breakdown, LOC calculation."""

import threading

from flask import Blueprint, jsonify, request

from backend.extensions import (
    logger,
    repo_stats_refresh_in_progress, repo_stats_refresh_lock,
    loc_in_progress, loc_lock,
)
from backend.database import get_repo_stats_cache_db, get_repo_loc_cache_db
from backend.services.repo_stats_service import fetch_repo_stats, calculate_loc
from backend.routes import error_response

repo_stats_bp = Blueprint("repo_stats", __name__)


def _normalize_timestamp(ts):
    """Normalize SQLite CURRENT_TIMESTAMP ('YYYY-MM-DD HH:MM:SS') to ISO 8601 with Z suffix."""
    if ts is None:
        return None
    s = str(ts)
    if "T" not in s:
        s = s.replace(" ", "T")
    if not s.endswith("Z"):
        s += "Z"
    return s


# --- Repo Stats ---

def _background_refresh_repo_stats(owner, repo, repo_key):
    """Background task to refresh repo stats for a repository."""
    try:
        logger.info(f"Background repo stats refresh started for {repo_key}")
        repo_stats_cache_db = get_repo_stats_cache_db()
        data = fetch_repo_stats(owner, repo)
        if data:
            repo_stats_cache_db.save_cache(repo_key, data)
            logger.info(f"Background repo stats refresh completed for {repo_key}")
        else:
            logger.warning(f"Background repo stats refresh got empty data for {repo_key}, keeping existing cache")
    except Exception as e:
        logger.error(f"Background repo stats refresh failed for {repo_key}: {e}")
    finally:
        with repo_stats_refresh_lock:
            repo_stats_refresh_in_progress.discard(repo_key)


@repo_stats_bp.route("/api/repos/<owner>/<repo>/repo-stats")
def get_repo_stats(owner, repo):
    """Get repository statistics with stale-while-revalidate caching."""
    repo_key = f"{owner}/{repo}"
    force_refresh = request.args.get("refresh", "").lower() == "true"
    repo_stats_cache_db = get_repo_stats_cache_db()

    try:
        if force_refresh:
            logger.info(f"Force refresh repo stats for {repo_key}")
            data = fetch_repo_stats(owner, repo)
            if data:
                repo_stats_cache_db.save_cache(repo_key, data)
            fresh_cached = repo_stats_cache_db.get_cached(repo_key)
            return jsonify({
                **(data or {}),
                "last_updated": _normalize_timestamp(fresh_cached["updated_at"]) if fresh_cached else None,
                "cached": False,
                "stale": False,
                "refreshing": False,
            })

        cached = repo_stats_cache_db.get_cached(repo_key)
        is_stale = repo_stats_cache_db.is_stale(repo_key)

        if cached:
            refreshing = False
            if is_stale:
                with repo_stats_refresh_lock:
                    if repo_key not in repo_stats_refresh_in_progress:
                        repo_stats_refresh_in_progress.add(repo_key)
                        thread = threading.Thread(
                            target=_background_refresh_repo_stats,
                            args=(owner, repo, repo_key),
                            daemon=True,
                        )
                        thread.start()
                        refreshing = True
                    else:
                        refreshing = True
            return jsonify({
                **cached["data"],
                "last_updated": _normalize_timestamp(cached["updated_at"]),
                "cached": True,
                "stale": is_stale,
                "refreshing": refreshing,
            })

        # No cache: synchronous fetch
        data = fetch_repo_stats(owner, repo)
        if data:
            repo_stats_cache_db.save_cache(repo_key, data)
        fresh_cached = repo_stats_cache_db.get_cached(repo_key)
        return jsonify({
            **(data or {}),
            "last_updated": _normalize_timestamp(fresh_cached["updated_at"]) if fresh_cached else None,
            "cached": False,
            "stale": False,
            "refreshing": False,
        })

    except Exception as e:
        return error_response("Internal server error", 500, f"Failed to fetch repo stats for {repo_key}: {e}")


# --- LOC Cache ---

@repo_stats_bp.route("/api/repos/<owner>/<repo>/repo-stats/loc", methods=["GET"])
def get_cached_loc(owner, repo):
    """Return cached LOC data if available, otherwise 404."""
    repo_key = f"{owner}/{repo}"
    repo_loc_cache_db = get_repo_loc_cache_db()
    cached = repo_loc_cache_db.get_cached(repo_key)
    if not cached:
        return jsonify({"message": "No cached LOC data"}), 404
    return jsonify({
        **cached["data"],
        "last_updated": _normalize_timestamp(cached["updated_at"]),
        "cached": True,
    })


# --- LOC Calculation ---

@repo_stats_bp.route("/api/repos/<owner>/<repo>/repo-stats/loc", methods=["POST"])
def get_repo_loc(owner, repo):
    """Calculate lines of code for a repository (expensive: clones the repo)."""
    repo_key = f"{owner}/{repo}"
    repo_loc_cache_db = get_repo_loc_cache_db()

    try:
        # Check if LOC calculation already in progress
        with loc_lock:
            if repo_key in loc_in_progress:
                return jsonify({"message": "LOC calculation already in progress", "in_progress": True}), 202
            loc_in_progress.add(repo_key)

        try:
            logger.info(f"Starting LOC calculation for {repo_key}")
            data = calculate_loc(owner, repo)
            repo_loc_cache_db.save_cache(repo_key, data)
            fresh_cached = repo_loc_cache_db.get_cached(repo_key)
            logger.info(f"LOC calculation completed for {repo_key}")
            return jsonify({
                **data,
                "last_updated": _normalize_timestamp(fresh_cached["updated_at"]) if fresh_cached else None,
                "cached": False,
            })
        finally:
            with loc_lock:
                loc_in_progress.discard(repo_key)

    except Exception as e:
        return error_response("Internal server error", 500, f"Failed to calculate LOC for {repo_key}: {e}")
