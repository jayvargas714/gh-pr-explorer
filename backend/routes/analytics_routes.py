"""Analytics routes: stats, lifecycle, responsiveness, code-activity, contributor-timeseries."""

import threading

from flask import Blueprint, jsonify, request

from backend.config import get_config
from backend.extensions import (
    logger,
    activity_refresh_in_progress, activity_refresh_lock,
    contributor_ts_refresh_in_progress, contributor_ts_refresh_lock,
    lifecycle_refresh_in_progress, lifecycle_refresh_lock,
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
from backend.services.lifecycle_service import fetch_pr_review_times, fetch_review_times_from_api
from backend.services.activity_service import fetch_code_activity_data
from backend.services.contributor_service import fetch_contributor_timeseries
from backend.visualizers.lifecycle_visualizer import compute_lifecycle_metrics
from backend.visualizers.responsiveness_visualizer import compute_responsiveness_metrics
from backend.visualizers.activity_visualizer import slice_and_summarize
from backend.routes import error_response

analytics_bp = Blueprint("analytics", __name__)


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
                "last_updated": _normalize_timestamp(last_updated.isoformat()) if last_updated else None,
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
                "last_updated": _normalize_timestamp(last_updated.isoformat()) if last_updated else None,
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
            "last_updated": _normalize_timestamp(last_updated.isoformat()) if last_updated else None,
            "cached": False,
            "refreshing": False
        })

    except RuntimeError as e:
        return error_response("Internal server error", 500, f"Failed to fetch developer stats for {full_repo}: {e}")


# --- Lifecycle / Review Responsiveness (shared cache) ---

def _background_refresh_lifecycle(owner, repo, repo_key):
    """Background task to refresh lifecycle/review-responsiveness cache."""
    try:
        logger.info(f"Background lifecycle refresh started for {repo_key}")
        lifecycle_cache_db = get_lifecycle_cache_db()
        data = fetch_review_times_from_api(owner, repo)
        if data:
            lifecycle_cache_db.save_cache(repo_key, data)
            logger.info(f"Background lifecycle refresh completed for {repo_key}: {len(data)} PRs")
    except Exception as e:
        logger.error(f"Background lifecycle refresh failed for {repo_key}: {e}")
    finally:
        with lifecycle_refresh_lock:
            lifecycle_refresh_in_progress.discard(repo_key)


def _get_lifecycle_data(owner, repo):
    """Shared helper: return (prs, cache_meta) with stale-while-revalidate."""
    repo_key = f"{owner}/{repo}"
    lifecycle_cache_db = get_lifecycle_cache_db()
    is_stale = lifecycle_cache_db.is_stale(repo_key)
    cached = lifecycle_cache_db.get_cached(repo_key)
    refreshing = False

    prs = fetch_pr_review_times(owner, repo, lifecycle_cache_db)

    if is_stale and prs:
        with lifecycle_refresh_lock:
            if repo_key not in lifecycle_refresh_in_progress:
                lifecycle_refresh_in_progress.add(repo_key)
                thread = threading.Thread(
                    target=_background_refresh_lifecycle,
                    args=(owner, repo, repo_key),
                    daemon=True
                )
                thread.start()
                refreshing = True
            else:
                refreshing = True

    cache_meta = {
        "last_updated": _normalize_timestamp(cached["updated_at"]) if cached else None,
        "cached": cached is not None,
        "stale": is_stale if cached else False,
        "refreshing": refreshing,
    }

    return prs, cache_meta


@analytics_bp.route("/api/repos/<owner>/<repo>/lifecycle-metrics")
def get_lifecycle_metrics(owner, repo):
    """Get PR lifecycle metrics."""
    try:
        prs, cache_meta = _get_lifecycle_data(owner, repo)
        metrics = compute_lifecycle_metrics(prs)
        metrics.update(cache_meta)
        return jsonify(metrics)
    except Exception as e:
        return error_response("Internal server error", 500, f"Failed to fetch lifecycle metrics: {e}")


@analytics_bp.route("/api/repos/<owner>/<repo>/review-responsiveness")
def get_review_responsiveness(owner, repo):
    """Get per-reviewer responsiveness metrics and bottleneck detection."""
    try:
        prs, cache_meta = _get_lifecycle_data(owner, repo)
        metrics = compute_responsiveness_metrics(prs)
        metrics.update(cache_meta)
        return jsonify(metrics)
    except Exception as e:
        return error_response("Internal server error", 500, f"Failed to fetch review responsiveness: {e}")


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
            fresh_cached = code_activity_cache_db.get_cached(repo_key)
            result = slice_and_summarize(data, weeks)
            result["last_updated"] = _normalize_timestamp(fresh_cached["updated_at"]) if fresh_cached else None
            result["cached"] = False
            result["stale"] = False
            result["refreshing"] = False
            return jsonify(result)

        cached = code_activity_cache_db.get_cached(repo_key)
        is_stale = code_activity_cache_db.is_stale(repo_key)

        if cached:
            refreshing = False
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
                        refreshing = True
                    else:
                        refreshing = True
            result = slice_and_summarize(cached["data"], weeks)
            result["last_updated"] = _normalize_timestamp(cached["updated_at"])
            result["cached"] = True
            result["stale"] = is_stale
            result["refreshing"] = refreshing
            return jsonify(result)

        # No cache: synchronous fetch
        data = fetch_code_activity_data(owner, repo)
        if data:
            code_activity_cache_db.save_cache(repo_key, data)
        else:
            data = {"weekly_commits": [], "code_changes": [], "owner_commits": [], "community_commits": []}
        fresh_cached = code_activity_cache_db.get_cached(repo_key)
        result = slice_and_summarize(data, weeks)
        result["last_updated"] = _normalize_timestamp(fresh_cached["updated_at"]) if fresh_cached else None
        result["cached"] = False
        result["stale"] = False
        result["refreshing"] = False
        return jsonify(result)

    except Exception as e:
        return error_response("Internal server error", 500, f"Failed to fetch code activity: {e}")


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
            fresh_cached = contributor_ts_cache_db.get_cached(repo_key)
            return jsonify({
                "contributors": data,
                "last_updated": _normalize_timestamp(fresh_cached["updated_at"]) if fresh_cached else None,
                "cached": False,
                "stale": False,
                "refreshing": False,
            })

        cached = contributor_ts_cache_db.get_cached(repo_key)
        is_stale = contributor_ts_cache_db.is_stale(repo_key)

        if cached:
            refreshing = False
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
                        refreshing = True
                    else:
                        refreshing = True
            return jsonify({
                "contributors": cached["data"],
                "last_updated": _normalize_timestamp(cached["updated_at"]),
                "cached": True,
                "stale": is_stale,
                "refreshing": refreshing,
            })

        # No cache: synchronous fetch
        data = fetch_contributor_timeseries(owner, repo)
        if data:
            contributor_ts_cache_db.save_cache(repo_key, data)
        fresh_cached = contributor_ts_cache_db.get_cached(repo_key)
        return jsonify({
            "contributors": data,
            "last_updated": _normalize_timestamp(fresh_cached["updated_at"]) if fresh_cached else None,
            "cached": False,
            "stale": False,
            "refreshing": False,
        })

    except Exception as e:
        return error_response("Internal server error", 500, f"Failed to fetch contributor timeseries for {repo_key}: {e}")
