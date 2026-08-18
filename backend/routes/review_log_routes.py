"""Review log routes: list and summarize review lifecycle events."""

from flask import Blueprint, jsonify, request

from backend.database import get_review_events_db
from backend.database.review_events import VALID_EVENTS, VALID_REASONS
from backend.routes import error_response

review_log_bp = Blueprint("review_log", __name__)

# Ceiling on page size so a hand-edited URL cannot ask for the whole table.
MAX_LIMIT = 1000
DEFAULT_LIMIT = 200


@review_log_bp.route("/api/review-logs", methods=["GET"])
def get_review_logs():
    """List review lifecycle events, newest first."""
    try:
        event = request.args.get("event")
        if event and event not in VALID_EVENTS:
            return jsonify({"error": f"Unknown event '{event}'"}), 400

        reason = request.args.get("reason")
        if reason and reason not in VALID_REASONS:
            return jsonify({"error": f"Unknown reason '{reason}'"}), 400

        limit = request.args.get("limit", DEFAULT_LIMIT, type=int) or DEFAULT_LIMIT
        limit = max(1, min(limit, MAX_LIMIT))
        offset = max(0, request.args.get("offset", 0, type=int) or 0)

        events, total = get_review_events_db().list_events(
            repo=request.args.get("repo"),
            pr_number=request.args.get("pr_number", type=int),
            event=event,
            reason=reason,
            since=request.args.get("since"),
            limit=limit,
            offset=offset,
        )

        return jsonify({"events": events, "total": total})
    except Exception as e:
        return error_response("Internal server error", 500, f"Error listing review logs: {e}")


@review_log_bp.route("/api/review-logs/stats", methods=["GET"])
def get_review_log_stats():
    """Aggregate counts for the Review Logs summary strip."""
    try:
        stats = get_review_events_db().get_stats(
            repo=request.args.get("repo"),
            since=request.args.get("since"),
        )
        return jsonify({"stats": stats})
    except Exception as e:
        return error_response("Internal server error", 500, f"Error computing review log stats: {e}")
