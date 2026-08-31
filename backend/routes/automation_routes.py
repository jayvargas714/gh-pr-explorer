"""Automation routes: reviewer registry CRUD + automation config + pipeline view."""

from flask import Blueprint, jsonify, request

from backend.database import get_automation_dispatches_db, get_reviewers_db
from backend.database.automation_dispatches import VALID_STATUSES
from backend.routes import error_response
from backend.services import automation_config

automation_bp = Blueprint("automation", __name__)


@automation_bp.route("/api/automation/dispatches", methods=["GET"])
def list_automation_dispatches():
    """The pipeline view: dispatch rows, most recently updated first.

    Query params: status (comma-separated subset of the dispatch statuses,
    default all) and limit (default 200).
    """
    status_param = (request.args.get("status") or "").strip()
    statuses = [s.strip() for s in status_param.split(",") if s.strip()] or None
    if statuses:
        unknown = [s for s in statuses if s not in VALID_STATUSES]
        if unknown:
            return jsonify({"error": f"Unknown status: {', '.join(unknown)}"}), 400
    limit = request.args.get("limit", default=200, type=int)

    try:
        rows = get_automation_dispatches_db().list_dispatches(statuses=statuses, limit=limit)
    except Exception as e:
        return error_response("Internal server error", 500, f"Error listing automation dispatches: {e}")

    return jsonify({"dispatches": [
        {
            "repo": row["repo"],
            "prNumber": row["pr_number"],
            "status": row["status"],
            "detail": row["detail"],
            "reviewerKey": row["reviewer_key"],
            "attempts": row["attempts"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
        for row in rows
    ]})


@automation_bp.route("/api/automation/config", methods=["GET"])
def get_automation_config():
    try:
        return jsonify({"config": automation_config.get_config()})
    except Exception as e:
        return error_response("Internal server error", 500, f"Error reading automation config: {e}")


@automation_bp.route("/api/automation/config", methods=["PUT"])
def save_automation_config():
    try:
        data = request.get_json() or {}
        payload = data.get("config", data)
        valid_keys = [r["key"] for r in get_reviewers_db().list_reviewers()]
        config = automation_config.save_config(payload, valid_keys)
        return jsonify({"config": config, "message": "Automation config saved"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return error_response("Internal server error", 500, f"Error saving automation config: {e}")


def _format_reviewer(row):
    return {
        "key": row["key"],
        "label": row["label"],
        "agentName": row["agent_name"],
        "promptContext": row["prompt_context"],
        "isBuiltin": row["is_builtin"],
    }


@automation_bp.route("/api/reviewers", methods=["GET"])
def list_reviewers():
    try:
        reviewers = get_reviewers_db().list_reviewers()
        return jsonify({"reviewers": [_format_reviewer(r) for r in reviewers]})
    except Exception as e:
        return error_response("Internal server error", 500, f"Error listing reviewers: {e}")


@automation_bp.route("/api/reviewers", methods=["POST"])
def create_reviewer():
    try:
        data = request.get_json() or {}
        if "key" not in data:
            return jsonify({"error": "Missing required field: key"}), 400
        row = get_reviewers_db().create(
            data.get("key"),
            data.get("label") or "",
            data.get("agentName") or "",
            prompt_context=data.get("promptContext"),
        )
        return jsonify({"reviewer": _format_reviewer(row)}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return error_response("Internal server error", 500, f"Error creating reviewer: {e}")


@automation_bp.route("/api/reviewers/<key>", methods=["PATCH"])
def update_reviewer(key):
    try:
        data = request.get_json() or {}
        row = get_reviewers_db().update(
            key,
            label=data.get("label"),
            agent_name=data.get("agentName"),
            prompt_context=data.get("promptContext"),
        )
        return jsonify({"reviewer": _format_reviewer(row)})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return error_response("Internal server error", 500, f"Error updating reviewer: {e}")


@automation_bp.route("/api/reviewers/<key>", methods=["DELETE"])
def delete_reviewer(key):
    try:
        get_reviewers_db().delete(key)
        return jsonify({"message": "Reviewer deleted"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return error_response("Internal server error", 500, f"Error deleting reviewer: {e}")
