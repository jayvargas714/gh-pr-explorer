"""Merge queue routes: CRUD, reorder, notes."""

from flask import Blueprint, jsonify, request

from backend.extensions import logger
from backend.database import get_queue_db
from backend.services.auto_verdict_config import validate_override
from backend.services.github_service import fetch_pr_state_and_sha
from backend.services.queue_enrichment import enrich_queue_items
from backend.services.review_service import VALID_REVIEWER_TYPES
from backend.routes import error_response

VALID_AUTO_VERDICT_MODES = ("verdict", "comment")

queue_bp = Blueprint("queue", __name__)


@queue_bp.route("/api/merge-queue", methods=["GET"])
def get_merge_queue():
    """Get all items in the merge queue with fresh PR states and review info."""
    try:
        queue_db = get_queue_db()
        queue_items = queue_db.get_queue()
        return jsonify({"queue": enrich_queue_items(queue_items)})
    except Exception as e:
        return error_response("Internal server error", 500, f"Error getting merge queue: {e}")


@queue_bp.route("/api/merge-queue", methods=["POST"])
def add_to_merge_queue():
    """Add a PR to the merge queue."""
    try:
        queue_db = get_queue_db()
        pr_data = request.get_json()
        if not pr_data:
            return jsonify({"error": "No data provided"}), 400

        required_fields = ["number", "title", "url", "author", "repo"]
        for field in required_fields:
            if field not in pr_data:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        repo_parts = pr_data["repo"].split("/")
        pr_state = None
        if len(repo_parts) == 2:
            pr_state, _ = fetch_pr_state_and_sha(repo_parts[0], repo_parts[1], pr_data["number"])

        item = queue_db.add_to_queue(
            pr_number=pr_data["number"],
            repo=pr_data["repo"],
            pr_title=pr_data["title"],
            pr_author=pr_data["author"],
            pr_url=pr_data["url"],
            additions=pr_data.get("additions", 0),
            deletions=pr_data.get("deletions", 0),
            pr_state=pr_state
        )

        queue_item = {
            "id": item["id"],
            "number": item["pr_number"],
            "title": item["pr_title"],
            "url": item["pr_url"],
            "author": item["pr_author"],
            "additions": item["additions"],
            "deletions": item["deletions"],
            "repo": item["repo"],
            "addedAt": item["added_at"],
            "notesCount": 0,
            "prState": pr_state
        }

        return jsonify({"message": "PR added to queue", "item": queue_item}), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        return error_response("Internal server error", 500, f"Error adding to merge queue: {e}")


@queue_bp.route("/api/merge-queue/<int:pr_number>", methods=["DELETE"])
def remove_from_merge_queue(pr_number):
    """Remove a PR from the merge queue."""
    try:
        queue_db = get_queue_db()
        repo = request.args.get("repo")
        removed = queue_db.remove_from_queue(pr_number, repo)

        if not removed:
            return jsonify({"error": "PR not found in queue"}), 404

        return jsonify({"message": "PR removed from queue"})

    except Exception as e:
        return error_response("Internal server error", 500, f"Error removing from merge queue: {e}")


@queue_bp.route("/api/merge-queue/<int:pr_number>/auto-verdict", methods=["PUT"])
def set_queue_auto_verdict(pr_number):
    """Arm or disarm auto verdicts for a queued PR."""
    try:
        repo = request.args.get("repo")
        if not repo:
            return jsonify({"error": "Missing 'repo' query parameter"}), 400

        data = request.get_json()
        if data is None or "enabled" not in data:
            return jsonify({"error": "Missing 'enabled' in request body"}), 400

        reviewer_type = data.get("reviewerType") or "default"
        if reviewer_type not in VALID_REVIEWER_TYPES:
            return jsonify({"error": f"Invalid reviewerType: {reviewer_type}"}), 400

        mode = data.get("mode") or "verdict"
        if mode not in VALID_AUTO_VERDICT_MODES:
            return jsonify({"error": f"Invalid mode: {mode}"}), 400

        enabled = bool(data["enabled"])
        row = get_queue_db().set_auto_verdict(pr_number, repo, enabled, reviewer_type, mode=mode)
        if row is None:
            return jsonify({"error": "PR not found in queue"}), 404

        logger.info(f"Auto verdict {'armed' if enabled else 'disarmed'} for {repo}#{pr_number} "
                    f"(reviewer={reviewer_type}, mode={mode})")
        return jsonify({
            "autoVerdict": {"enabled": enabled, "reviewerType": reviewer_type, "mode": mode},
            "message": "Auto verdict updated",
        })

    except Exception as e:
        return error_response("Internal server error", 500,
                              f"Error updating auto verdict for PR #{pr_number}: {e}")


@queue_bp.route("/api/merge-queue/<int:pr_number>/auto-verdict/criteria", methods=["PUT"])
def set_queue_auto_verdict_criteria(pr_number):
    """Set or clear a queued PR's auto-verdict criteria override."""
    try:
        repo = request.args.get("repo")
        if not repo:
            return jsonify({"error": "Missing 'repo' query parameter"}), 400

        data = request.get_json()
        if data is None or "criteria" not in data:
            return jsonify({"error": "Missing 'criteria' in request body"}), 400

        criteria = data["criteria"]
        if criteria is not None:
            try:
                criteria = validate_override(criteria)
            except ValueError as e:
                return jsonify({"error": str(e)}), 400

        row = get_queue_db().set_auto_verdict_criteria(pr_number, repo, criteria)
        if row is None:
            return jsonify({"error": "PR not found in queue"}), 404

        logger.info(f"Auto verdict criteria override {'set' if criteria else 'cleared'} "
                    f"for {repo}#{pr_number}")
        return jsonify({
            "criteriaOverride": criteria,
            "message": "Auto verdict criteria updated",
        })

    except Exception as e:
        return error_response("Internal server error", 500,
                              f"Error updating auto verdict criteria for PR #{pr_number}: {e}")


@queue_bp.route("/api/merge-queue/reorder", methods=["POST"])
def reorder_merge_queue():
    """Reorder items in the merge queue."""
    try:
        queue_db = get_queue_db()
        order_data = request.get_json()
        if not order_data or "order" not in order_data:
            return jsonify({"error": "No order provided"}), 400

        order = order_data["order"]
        queue_items = queue_db.reorder_queue(order)

        new_queue = []
        for item in queue_items:
            new_queue.append({
                "number": item["pr_number"],
                "title": item["pr_title"],
                "url": item["pr_url"],
                "author": item["pr_author"],
                "additions": item["additions"],
                "deletions": item["deletions"],
                "repo": item["repo"],
                "addedAt": item["added_at"]
            })

        return jsonify({"message": "Queue reordered", "queue": new_queue})

    except Exception as e:
        return error_response("Internal server error", 500, f"Error reordering merge queue: {e}")


# --- Queue Notes ---

@queue_bp.route("/api/merge-queue/<int:pr_number>/notes", methods=["GET"])
def get_queue_notes(pr_number):
    """Get all notes for a queue item."""
    try:
        queue_db = get_queue_db()
        repo = request.args.get("repo")
        if not repo:
            return jsonify({"error": "repo parameter required"}), 400

        queue_item_id = queue_db.get_queue_item_id(pr_number, repo)
        if not queue_item_id:
            return jsonify({"error": "PR not found in queue"}), 404

        notes = queue_db.get_notes(queue_item_id)

        formatted_notes = []
        for note in notes:
            # Append Z to mark SQLite CURRENT_TIMESTAMP as UTC
            created_at = note["created_at"]
            if created_at and not created_at.endswith("Z"):
                created_at += "Z"
            formatted_notes.append({
                "id": note["id"],
                "content": note["content"],
                "createdAt": created_at
            })

        return jsonify({"notes": formatted_notes})

    except Exception as e:
        return error_response("Internal server error", 500, f"Error getting queue notes: {e}")


@queue_bp.route("/api/merge-queue/<int:pr_number>/notes", methods=["POST"])
def add_queue_note(pr_number):
    """Add a note to a queue item."""
    try:
        queue_db = get_queue_db()
        repo = request.args.get("repo")
        if not repo:
            return jsonify({"error": "repo parameter required"}), 400

        data = request.get_json()
        if not data or "content" not in data:
            return jsonify({"error": "content is required"}), 400

        content = data["content"].strip()
        if not content:
            return jsonify({"error": "content cannot be empty"}), 400

        queue_item_id = queue_db.get_queue_item_id(pr_number, repo)
        if not queue_item_id:
            return jsonify({"error": "PR not found in queue"}), 404

        note = queue_db.add_note(queue_item_id, content)

        created_at = note["created_at"]
        if created_at and not created_at.endswith("Z"):
            created_at += "Z"

        return jsonify({
            "message": "Note added",
            "note": {
                "id": note["id"],
                "content": note["content"],
                "createdAt": created_at
            }
        }), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return error_response("Internal server error", 500, f"Error adding queue note: {e}")


@queue_bp.route("/api/merge-queue/notes/<int:note_id>", methods=["DELETE"])
def delete_queue_note(note_id):
    """Delete a note from a queue item."""
    try:
        queue_db = get_queue_db()
        deleted = queue_db.delete_note(note_id)
        if not deleted:
            return jsonify({"error": "Note not found"}), 404

        return jsonify({"message": "Note deleted"})

    except Exception as e:
        return error_response("Internal server error", 500, f"Error deleting queue note: {e}")
