"""Repository metadata routes: repos, contributors, labels, branches, milestones, teams."""

from flask import Blueprint, jsonify, request

from backend.services.github_service import run_gh_command, parse_json_output

repo_bp = Blueprint("repo", __name__)


@repo_bp.route("/api/repos")
def get_repos():
    """List repositories for an organization or user."""
    try:
        limit = request.args.get("limit", 100, type=int)
        owner = request.args.get("owner")

        args = ["repo", "list"]
        if owner:
            args.append(owner)
        args.extend([
            "--json", "name,owner,description,isPrivate,updatedAt",
            "--limit", str(limit),
        ])

        output = run_gh_command(args)
        repos = parse_json_output(output)
        return jsonify({"repos": repos})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@repo_bp.route("/api/repos/<owner>/<repo>/contributors")
def get_contributors(owner, repo):
    """Get contributors for a repository."""
    try:
        output = run_gh_command([
            "api",
            f"repos/{owner}/{repo}/contributors",
            "--jq", ".[].login",
        ])
        contributors = [c.strip() for c in output.split("\n") if c.strip()]
        return jsonify({"contributors": contributors})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@repo_bp.route("/api/repos/<owner>/<repo>/labels")
def get_labels(owner, repo):
    """Get labels for a repository."""
    try:
        output = run_gh_command([
            "api",
            f"repos/{owner}/{repo}/labels",
            "--jq", ".[].name",
        ])
        labels = [l.strip() for l in output.split("\n") if l.strip()]
        return jsonify({"labels": labels})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@repo_bp.route("/api/repos/<owner>/<repo>/branches")
def get_branches(owner, repo):
    """Get branches for a repository."""
    try:
        output = run_gh_command([
            "api",
            f"repos/{owner}/{repo}/branches",
            "--jq", ".[].name",
            "--paginate",
        ])
        branches = [b.strip() for b in output.split("\n") if b.strip()]
        return jsonify({"branches": branches})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@repo_bp.route("/api/repos/<owner>/<repo>/milestones")
def get_milestones(owner, repo):
    """Get milestones for a repository."""
    try:
        output = run_gh_command([
            "api",
            f"repos/{owner}/{repo}/milestones",
            "--jq", "[.[] | {title: .title, state: .state, number: .number}]",
        ])
        milestones = parse_json_output(output)
        return jsonify({"milestones": milestones})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@repo_bp.route("/api/repos/<owner>/<repo>/teams")
def get_teams(owner, repo):
    """Get teams with access to a repository."""
    try:
        output = run_gh_command([
            "api",
            f"repos/{owner}/{repo}/teams",
            "--jq", "[.[] | {slug: .slug, name: .name}]",
        ])
        teams = parse_json_output(output)
        return jsonify({"teams": teams})
    except RuntimeError as e:
        return jsonify({"teams": []})
