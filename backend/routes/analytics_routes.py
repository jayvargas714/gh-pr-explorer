"""Analytics routes: stats, lifecycle, responsiveness, code-activity, contributor-timeseries."""

import threading

from flask import Blueprint, jsonify, request

from backend.config import get_config
from backend.extensions import (
    logger,
    activity_refresh_in_progress, activity_refresh_lock,
    contributor_ts_refresh_in_progress, contributor_ts_refresh_lock,
    stats_refresh_in_progress, stats_refresh_lock,
)
from backend.database import (
    get_reviews_db, get_dev_stats_db,
    get_lifecycle_cache_db, get_code_activity_cache_db,
    get_contributor_ts_cache_db,
)
from backend.services.stats_service import (
    fetch_and_compute_stats, add_avg_pr_scores,
    stats_to_cache_format, cached_stats_to_api_format,
)
from backend.services.lifecycle_service import fetch_pr_review_times
from backend.services.activity_service import fetch_code_activity_data
from backend.services.contributor_service import fetch_contributor_timeseries
from backend.visualizers.lifecycle_visualizer import compute_lifecycle_metrics
from backend.visualizers.responsiveness_visualizer import compute_responsiveness_metrics
from backend.visualizers.activity_visualizer import slice_and_summarize

analytics_bp = Blueprint("analytics", __name__)


# --- Developer Stats ---

def _background_refresh_stats(owner, repo, full_repo):
    """Background task to refresh stats for a repository."""
    try:
        logger.info(f"Background refresh started for {full_repo}")
        dev_stats_db = get_dev_stats_db()
        stats_list = fetch_and_compute_stats(owner, repo)
        if stats_list:
            cache_data = stats_to_cache_format(stats_list)
            dev_stats_db.save_stats(full_repo, cache_data)
            logger.info(f"Background refresh completed for {full_repo}")
        else:
            logger.warning(f"Background refresh got empty stats for {full_repo}, keeping existing cache")
    except Exception as e:
        logger.error(f"Background refresh failed for {full_repo}: {e}")
    finally:
        with stats_refresh_lock:
            stats_refresh_in_progress.discard(full_repo)


@analytics_bp.route("/api/repos/<owner>/<repo>/stats")
def get_developer_stats(owner, repo):
    """Get aggregated developer statistics for a repository."""
    full_repo = f"{owner}/{repo}"
    force_refresh = request.args.get("refresh", "").lower() == "true"
    reviews_db = get_reviews_db()
    dev_stats_db = get_dev_stats_db()

    try:
        is_stale = dev_stats_db.is_stale(full_repo)
        last_updated = dev_stats_db.get_last_updated(full_repo)
        cached_stats = dev_stats_db.get_stats(full_repo)

        with stats_refresh_lock:
            refreshing = full_repo in stats_refresh_in_progress

        if force_refresh:
            stats_list = fetch_and_compute_stats(owner, repo)
            if stats_list:
                cache_data = stats_to_cache_format(stats_list)
                dev_stats_db.save_stats(full_repo, cache_data)
                last_updated = dev_stats_db.get_last_updated(full_repo)
            stats_with_scores = add_avg_pr_scores(stats_list, full_repo, reviews_db)
            return jsonify({
                "stats": stats_with_scores,
                "last_updated": last_updated.isoformat() if last_updated else None,
                "cached": False,
                "refreshing": False
            })

        if cached_stats:
            if is_stale and not refreshing:
                with stats_refresh_lock:
                    if full_repo not in stats_refresh_in_progress:
                        stats_refresh_in_progress.add(full_repo)
                        thread = threading.Thread(
                            target=_background_refresh_stats,
                            args=(owner, repo, full_repo),
                            daemon=True
                        )
                        thread.start()
                        refreshing = True

            transformed_stats = cached_stats_to_api_format(cached_stats)
            stats_with_scores = add_avg_pr_scores(transformed_stats, full_repo, reviews_db)
            return jsonify({
                "stats": stats_with_scores,
                "last_updated": last_updated.isoformat() if last_updated else None,
                "cached": True,
                "stale": is_stale,
                "refreshing": refreshing
            })

        # No cached data: fetch synchronously
        stats_list = fetch_and_compute_stats(owner, repo)
        if stats_list:
            cache_data = stats_to_cache_format(stats_list)
            dev_stats_db.save_stats(full_repo, cache_data)
            last_updated = dev_stats_db.get_last_updated(full_repo)
        stats_with_scores = add_avg_pr_scores(stats_list, full_repo, reviews_db)

        return jsonify({
            "stats": stats_with_scores,
            "last_updated": last_updated.isoformat() if last_updated else None,
            "cached": False,
            "refreshing": False
        })

    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


# --- Lifecycle Metrics ---

@analytics_bp.route("/api/repos/<owner>/<repo>/lifecycle-metrics")
def get_lifecycle_metrics(owner, repo):
    """Get PR lifecycle metrics."""
    try:
        lifecycle_cache_db = get_lifecycle_cache_db()
        prs = fetch_pr_review_times(owner, repo, lifecycle_cache_db)
        metrics = compute_lifecycle_metrics(prs)
        return jsonify(metrics)
    except Exception as e:
        logger.error(f"Failed to fetch lifecycle metrics: {e}")
        return jsonify({"error": str(e)}), 500


# --- Review Responsiveness ---

@analytics_bp.route("/api/repos/<owner>/<repo>/review-responsiveness")
def get_review_responsiveness(owner, repo):
    """Get per-reviewer responsiveness metrics and bottleneck detection."""
    try:
        lifecycle_cache_db = get_lifecycle_cache_db()
        prs = fetch_pr_review_times(owner, repo, lifecycle_cache_db)
        metrics = compute_responsiveness_metrics(prs)
        return jsonify(metrics)
    except Exception as e:
        logger.error(f"Failed to fetch review responsiveness: {e}")
        return jsonify({"error": str(e)}), 500


# --- Code Activity ---

def _background_refresh_code_activity(owner, repo, repo_key):
    """Background task to refresh code activity cache."""
    try:
        logger.info(f"Background code activity refresh started for {repo_key}")
        code_activity_cache_db = get_code_activity_cache_db()
        data = fetch_code_activity_data(owner, repo)
        if data:
            code_activity_cache_db.save_cache(repo_key, data)
            logger.info(f"Background code activity refresh completed for {repo_key}")
    except Exception as e:
        logger.error(f"Background code activity refresh failed for {repo_key}: {e}")
    finally:
        with activity_refresh_lock:
            activity_refresh_in_progress.discard(repo_key)


@analytics_bp.route("/api/repos/<owner>/<repo>/code-activity")
def get_code_activity(owner, repo):
    """Get code activity stats with stale-while-revalidate caching."""
    try:
        weeks = int(request.args.get("weeks", 52))
        weeks = min(max(weeks, 1), 52)
        repo_key = f"{owner}/{repo}"
        force_refresh = request.args.get("refresh", "").lower() == "true"
        code_activity_cache_db = get_code_activity_cache_db()

        if force_refresh:
            logger.info(f"Force refresh code activity for {repo_key}")
            data = fetch_code_activity_data(owner, repo)
            if data:
                code_activity_cache_db.save_cache(repo_key, data)
            else:
                data = {"weekly_commits": [], "code_changes": [], "owner_commits": [], "community_commits": []}
            return jsonify(slice_and_summarize(data, weeks))

        cached = code_activity_cache_db.get_cached(repo_key)
        is_stale = code_activity_cache_db.is_stale(repo_key)

        if cached:
            if is_stale:
                with activity_refresh_lock:
                    if repo_key not in activity_refresh_in_progress:
                        activity_refresh_in_progress.add(repo_key)
                        thread = threading.Thread(
                            target=_background_refresh_code_activity,
                            args=(owner, repo, repo_key),
                            daemon=True
                        )
                        thread.start()
            return jsonify(slice_and_summarize(cached["data"], weeks))

        # No cache: synchronous fetch
        data = fetch_code_activity_data(owner, repo)
        if data:
            code_activity_cache_db.save_cache(repo_key, data)
        else:
            data = {"weekly_commits": [], "code_changes": [], "owner_commits": [], "community_commits": []}
        return jsonify(slice_and_summarize(data, weeks))

    except Exception as e:
        logger.error(f"Failed to fetch code activity: {e}")
        return jsonify({"error": str(e)}), 500


# --- Contributor Time Series ---

def _background_refresh_contributor_ts(owner, repo, repo_key):
    """Background task to refresh contributor time series cache."""
    try:
        logger.info(f"Background contributor TS refresh started for {repo_key}")
        contributor_ts_cache_db = get_contributor_ts_cache_db()
        data = fetch_contributor_timeseries(owner, repo)
        if data:
            contributor_ts_cache_db.save_cache(repo_key, data)
            logger.info(f"Background contributor TS refresh completed for {repo_key}: {len(data)} contributors")
    except Exception as e:
        logger.error(f"Background contributor TS refresh failed for {repo_key}: {e}")
    finally:
        with contributor_ts_refresh_lock:
            contributor_ts_refresh_in_progress.discard(repo_key)


@analytics_bp.route("/api/repos/<owner>/<repo>/contributor-timeseries")
def get_contributor_timeseries(owner, repo):
    """Get per-contributor weekly time series data."""
    repo_key = f"{owner}/{repo}"
    force_refresh = request.args.get("refresh", "").lower() == "true"
    contributor_ts_cache_db = get_contributor_ts_cache_db()

    try:
        if force_refresh:
            logger.info(f"Force refresh contributor TS for {repo_key}")
            data = fetch_contributor_timeseries(owner, repo)
            if data:
                contributor_ts_cache_db.save_cache(repo_key, data)
            return jsonify({"contributors": data})

        cached = contributor_ts_cache_db.get_cached(repo_key)
        is_stale = contributor_ts_cache_db.is_stale(repo_key)

        if cached:
            if is_stale:
                with contributor_ts_refresh_lock:
                    if repo_key not in contributor_ts_refresh_in_progress:
                        contributor_ts_refresh_in_progress.add(repo_key)
                        thread = threading.Thread(
                            target=_background_refresh_contributor_ts,
                            args=(owner, repo, repo_key),
                            daemon=True
                        )
                        thread.start()
            return jsonify({"contributors": cached["data"]})

        # No cache: synchronous fetch
        data = fetch_contributor_timeseries(owner, repo)
        if data:
            contributor_ts_cache_db.save_cache(repo_key, data)
        return jsonify({"contributors": data})

    except Exception as e:
        logger.error(f"Failed to fetch contributor timeseries for {repo_key}: {e}")
        return jsonify({"error": str(e)}), 500
