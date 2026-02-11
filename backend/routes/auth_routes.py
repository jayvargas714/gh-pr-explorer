"""Authentication routes: /api/user, /api/orgs."""

import json

from flask import Blueprint, jsonify

from backend.services.github_service import run_gh_command, parse_json_output

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/user")
def get_user():
    """Get the current authenticated user."""
    try:
        output = run_gh_command([
            "api", "user",
            "--jq", "{login: .login, name: .name, avatar_url: .avatar_url}"
        ])
        user = parse_json_output(output) if output else {}
        return jsonify({"user": user})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@auth_bp.route("/api/orgs")
def get_orgs():
    """List organizations the user belongs to, plus their personal account."""
    try:
        user_output = run_gh_command([
            "api", "user",
            "--jq", '{login: .login, name: .name, avatar_url: .avatar_url, type: "user"}'
        ])
        user = json.loads(user_output) if user_output else None

        orgs_output = run_gh_command([
            "api", "user/orgs",
            "--jq", '[.[] | {login: .login, name: .login, avatar_url: .avatar_url, type: "org"}]'
        ])
        orgs = parse_json_output(orgs_output)

        accounts = []
        if user:
            user["is_personal"] = True
            accounts.append(user)
        accounts.extend(orgs)

        return jsonify({"accounts": accounts})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
