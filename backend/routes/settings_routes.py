"""Settings routes: CRUD for user settings, plus the auto-verdict criteria."""

from flask import Blueprint, jsonify, request

from backend.extensions import logger
from backend.database import get_settings_db
from backend.routes import error_response
from backend.services.auto_verdict_config import get_criteria, save_criteria

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/api/settings", methods=["GET"])
def get_all_settings():
    """Get all user settings."""
    try:
        settings_db = get_settings_db()
        settings = settings_db.get_all_settings()
        return jsonify({"settings": settings})
    except Exception as e:
        return error_response("Internal server error", 500, f"Error getting settings: {e}")


@settings_bp.route("/api/auto-verdict/config", methods=["GET"])
def get_auto_verdict_config():
    """Get the auto-verdict criteria (stored values merged over the defaults)."""
    try:
        return jsonify({"config": get_criteria()})
    except Exception as e:
        return error_response("Internal server error", 500, f"Error getting auto-verdict config: {e}")


@settings_bp.route("/api/auto-verdict/config", methods=["PUT", "POST"])
def set_auto_verdict_config():
    """Update the auto-verdict criteria."""
    try:
        data = request.get_json()
        if data is None:
            return jsonify({"error": "Missing request body"}), 400
        try:
            config = save_criteria(data.get("config", data))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"config": config, "message": "Auto-verdict config saved"})
    except Exception as e:
        return error_response("Internal server error", 500, f"Error saving auto-verdict config: {e}")


@settings_bp.route("/api/settings/<key>", methods=["GET"])
def get_setting(key):
    """Get a specific setting by key."""
    try:
        settings_db = get_settings_db()
        value = settings_db.get_setting(key)
        if value is None:
            return jsonify({"error": "Setting not found"}), 404
        return jsonify({"key": key, "value": value})
    except Exception as e:
        return error_response("Internal server error", 500, f"Error getting setting {key}: {e}")


@settings_bp.route("/api/settings/<key>", methods=["PUT", "POST"])
def set_setting(key):
    """Set a setting value."""
    try:
        settings_db = get_settings_db()
        data = request.get_json()
        if data is None or "value" not in data:
            return jsonify({"error": "Missing 'value' in request body"}), 400

        settings_db.set_setting(key, data["value"])
        return jsonify({"key": key, "value": data["value"], "message": "Setting saved"})
    except Exception as e:
        return error_response("Internal server error", 500, f"Error setting {key}: {e}")


@settings_bp.route("/api/settings/<key>", methods=["DELETE"])
def delete_setting(key):
    """Delete a setting."""
    try:
        settings_db = get_settings_db()
        deleted = settings_db.delete_setting(key)
        if not deleted:
            return jsonify({"error": "Setting not found"}), 404
        return jsonify({"message": "Setting deleted"})
    except Exception as e:
        return error_response("Internal server error", 500, f"Error deleting setting {key}: {e}")
