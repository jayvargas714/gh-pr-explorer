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

    return jsonify({"dispatches": [_dispatch_payload(row) for row in rows]})


def _dispatch_payload(row):
    return {
        "repo": row["repo"],
        "prNumber": row["pr_number"],
        "status": row["status"],
        "detail": row["detail"],
        "reviewerKey": row["reviewer_key"],
        "attempts": row["attempts"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


@automation_bp.route("/api/automation/dispatches/<owner>/<repo>/<int:pr_number>/enroll",
                     methods=["POST"])
def enroll_automation_dispatch(owner, repo, pr_number):
    """Manually add a PR to the automation pipeline (or revive a skipped/failed row).

    A row that is already pending is a no-op; dispatched/unidentified rows are
    refused — a PR is auto-dispatched at most once.
    """
    repo_full = f"{owner}/{repo}"
    dispatches = get_automation_dispatches_db()
    row = dispatches.get_by_pr(repo_full, pr_number)

    if row and row["status"] == "pending":
        return jsonify({"dispatch": _dispatch_payload(row), "message": "Already in the pipeline"})
    if row and row["status"] in ("dispatched", "unidentified"):
        return jsonify({"error": f"PR was already {row['status']} — a PR is auto-dispatched at most once"}), 409

    cap = automation_config.get_config().get("maxPipelineSize", 1000)
    if dispatches.count_pending() >= cap:
        return jsonify({"error": f"Pipeline is at maxPipelineSize ({cap})"}), 409

    if row is None:
        dispatches.record_candidate(repo_full, pr_number)
        status = 201
    else:  # skipped or failed
        dispatches.requeue(row["id"], detail="manually re-enrolled")
        status = 200
    fresh = dispatches.get_by_pr(repo_full, pr_number)
    logger_msg = "enrolled" if status == 201 else "re-enrolled"
    return jsonify({"dispatch": _dispatch_payload(fresh),
                    "message": f"PR {logger_msg} in the automation pipeline"}), status


@automation_bp.route("/api/automation/dispatches/<owner>/<repo>/<int:pr_number>/optout",
                     methods=["POST"])
def optout_automation_dispatch(owner, repo, pr_number):
    """Remove a waiting PR from the pipeline (manual mode).

    Only pending rows can opt out; the backfill script never revives a
    "manual opt-out" row, so the choice sticks until explicitly re-enrolled.
    """
    repo_full = f"{owner}/{repo}"
    dispatches = get_automation_dispatches_db()
    row = dispatches.get_by_pr(repo_full, pr_number)
    if row is None:
        return jsonify({"error": "PR is not in the pipeline"}), 404
    if row["status"] != "pending":
        return jsonify({"error": f"PR is {row['status']}, not waiting — nothing to remove"}), 409

    dispatches.set_status(row["id"], "skipped", detail="manual opt-out")
    fresh = dispatches.get_by_pr(repo_full, pr_number)
    return jsonify({"dispatch": _dispatch_payload(fresh),
                    "message": "PR removed from the automation pipeline"})


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
