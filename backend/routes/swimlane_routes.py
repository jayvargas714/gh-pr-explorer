"""Swimlane board routes: lane CRUD, reorder, default-lane setting, card move."""

from flask import Blueprint, jsonify, request

from backend.database import get_queue_db, get_swimlanes_db
from backend.services.queue_enrichment import enrich_queue_items
from backend.routes import error_response

swimlane_bp = Blueprint("swimlanes", __name__)


def _format_lane(lane):
    return {
        "id": lane["id"],
        "name": lane["name"],
        "color": lane["color"],
        "position": lane["position"],
        "isDefault": bool(lane["is_default"]),
        "createdAt": lane.get("created_at"),
    }


@swimlane_bp.route("/api/swimlanes/board", methods=["GET"])
def get_board():
    """Return the full swimlane board: lanes + cards-by-lane (enriched)."""
    try:
        swimlanes_db = get_swimlanes_db()
        queue_db = get_queue_db()

        # Heal any drift before serving the board.
        swimlanes_db.ensure_default_lane()
        swimlanes_db.reconcile_assignments()

        lanes = swimlanes_db.list_lanes()
        assignments = swimlanes_db.get_assignments()
        queue_rows = queue_db.get_queue()

        enriched = enrich_queue_items(queue_rows)
        enriched_by_id = {c["id"]: c for c in enriched}

        cards_by_lane: dict[int, list[dict]] = {lane["id"]: [] for lane in lanes}

        # assignments are already ordered by lane,position; preserve that order
        for assignment in assignments:
            lane_id = assignment["swimlane_id"]
            queue_item_id = assignment["queue_item_id"]
            card = enriched_by_id.get(queue_item_id)
            if not card or lane_id is None:
                continue
            if lane_id in cards_by_lane:
                cards_by_lane[lane_id].append(card)

        return jsonify({
            "lanes": [_format_lane(l) for l in lanes],
            "cardsByLane": {str(k): v for k, v in cards_by_lane.items()},
        })
    except Exception as e:
        return error_response("Internal server error", 500, f"Error fetching swimlane board: {e}")


@swimlane_bp.route("/api/swimlanes", methods=["POST"])
def create_lane():
    """Create a new swimlane."""
    try:
        data = request.get_json() or {}
        name = data.get("name")
        color = data.get("color")
        if not name:
            return jsonify({"error": "name is required"}), 400
        if not color:
            return jsonify({"error": "color is required"}), 400
        lane = get_swimlanes_db().create_lane(name=name, color=color)
        return jsonify({"lane": _format_lane(lane)}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return error_response("Internal server error", 500, f"Error creating lane: {e}")


@swimlane_bp.route("/api/swimlanes/<int:lane_id>", methods=["PATCH"])
def update_lane(lane_id):
    """Rename or recolor a swimlane."""
    try:
        data = request.get_json() or {}
        lane = get_swimlanes_db().update_lane(
            lane_id, name=data.get("name"), color=data.get("color")
        )
        return jsonify({"lane": _format_lane(lane)})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return error_response("Internal server error", 500, f"Error updating lane: {e}")


@swimlane_bp.route("/api/swimlanes/<int:lane_id>", methods=["DELETE"])
def delete_lane(lane_id):
    """Delete a swimlane; orphaned cards are re-homed to the (new) default lane."""
    try:
        default_lane = get_swimlanes_db().delete_lane(lane_id)
        return jsonify({"message": "Lane deleted", "defaultLane": _format_lane(default_lane)})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return error_response("Internal server error", 500, f"Error deleting lane: {e}")


@swimlane_bp.route("/api/swimlanes/reorder", methods=["PUT"])
def reorder_lanes():
    """Reorder lanes by ID."""
    try:
        data = request.get_json() or {}
        order = data.get("order")
        if not isinstance(order, list) or not all(isinstance(i, int) for i in order):
            return jsonify({"error": "order must be a list of integer lane ids"}), 400
        lanes = get_swimlanes_db().reorder_lanes(order)
        return jsonify({"lanes": [_format_lane(l) for l in lanes]})
    except Exception as e:
        return error_response("Internal server error", 500, f"Error reordering lanes: {e}")


@swimlane_bp.route("/api/swimlanes/<int:lane_id>/default", methods=["PUT"])
def set_default(lane_id):
    """Mark a lane as the default (where new merge-queue cards land)."""
    try:
        lane = get_swimlanes_db().set_default_lane(lane_id)
        return jsonify({"lane": _format_lane(lane)})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return error_response("Internal server error", 500, f"Error setting default lane: {e}")


@swimlane_bp.route("/api/swimlanes/cards/move", methods=["PUT"])
def move_card():
    """Move a card to (toLaneId, toPosition).

    Body: {queueItemId: int, toLaneId: int, toPosition: int}  (1-based toPosition)
    """
    try:
        data = request.get_json() or {}
        queue_item_id = data.get("queueItemId")
        to_lane_id = data.get("toLaneId")
        to_position = data.get("toPosition")

        for field in ("queueItemId", "toLaneId", "toPosition"):
            if data.get(field) is None:
                return jsonify({"error": f"{field} is required"}), 400

        assignment = get_swimlanes_db().move_card(
            queue_item_id=int(queue_item_id),
            to_lane_id=int(to_lane_id),
            to_position=int(to_position),
        )
        return jsonify({
            "assignment": {
                "queueItemId": assignment["queue_item_id"],
                "swimlaneId": assignment["swimlane_id"],
                "positionInLane": assignment["position_in_lane"],
            }
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return error_response("Internal server error", 500, f"Error moving card: {e}")
