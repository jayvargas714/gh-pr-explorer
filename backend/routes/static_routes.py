"""Serve React frontend static files."""

from pathlib import Path

from flask import Blueprint, send_from_directory

static_bp = Blueprint("static", __name__)

DIST_DIR = Path(__file__).parent.parent.parent / "frontend" / "dist"


@static_bp.route("/")
def index():
    """Serve the React frontend."""
    return send_from_directory(DIST_DIR, "index.html")


@static_bp.route("/assets/<path:filename>")
def serve_frontend_assets(filename):
    """Serve static assets from the React build."""
    return send_from_directory(DIST_DIR / "assets", filename)
