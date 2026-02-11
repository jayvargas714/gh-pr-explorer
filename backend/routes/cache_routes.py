"""Cache management routes."""

from flask import Blueprint, jsonify

from backend.extensions import logger, cache
from backend.database import get_workflow_cache_db, get_contributor_ts_cache_db, get_code_activity_cache_db

cache_bp = Blueprint("cache", __name__)


@cache_bp.route("/api/clear-cache", methods=["POST"])
def clear_cache():
    """Clear the in-memory cache and SQLite caches."""
    cache.clear()
    get_workflow_cache_db().clear()
    get_contributor_ts_cache_db().clear()
    get_code_activity_cache_db().clear()
    return jsonify({"message": "Cache cleared"})
