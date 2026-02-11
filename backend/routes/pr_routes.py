"""PR routes: list PRs with filters, batch divergence."""

from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, jsonify, request

from backend.config import get_config
from backend.extensions import logger
from backend.filters.pr_filter_builder import PRFilterParams, PRFilterBuilder
from backend.services.github_service import run_gh_command, parse_json_output
from backend.services.pr_service import get_review_status, get_ci_status

pr_bp = Blueprint("pr", __name__)


@pr_bp.route("/api/repos/<owner>/<repo>/prs")
def get_prs(owner, repo):
    """Get PRs with advanced filtering support."""
    try:
        config = get_config()
        params = PRFilterParams.from_request_args(request.args, default_per_page=config.get("default_per_page", 30))
        builder = PRFilterBuilder(owner, repo, params)
        args = builder.build()

        output = run_gh_command(args)
        prs = parse_json_output(output)

        # Post-filter by draft status (gh search qualifier draft: is unreliable)
        if params.draft == "true":
            prs = [pr for pr in prs if pr.get("isDraft", False)]
        elif params.draft == "false":
            prs = [pr for pr in prs if not pr.get("isDraft", False)]

        # Post-process: add review status and CI status summaries
        for pr in prs:
            pr["reviewStatus"] = get_review_status(pr.get("reviewDecision"))
            pr["ciStatus"] = get_ci_status(pr.get("statusCheckRollup"))

        return jsonify({"prs": prs})

    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@pr_bp.route("/api/repos/<owner>/<repo>/prs/divergence", methods=["POST"])
def get_pr_divergence(owner, repo):
    """Batch fetch branch divergence (ahead/behind) for open PRs."""
    try:
        data = request.get_json()
        if not data or "prs" not in data:
            return jsonify({"error": "Missing 'prs' in request body"}), 400

        pr_list = data["prs"]

        def fetch_one(pr_info):
            number = pr_info["number"]
            base = pr_info["base"]
            head = pr_info["head"]
            try:
                output = run_gh_command([
                    "api", f"repos/{owner}/{repo}/compare/{base}...{head}",
                    "--jq", '{"status": .status, "ahead_by": .ahead_by, "behind_by": .behind_by}'
                ])
                result = parse_json_output(output)
                if result:
                    return (number, result)
            except RuntimeError:
                pass
            return (number, None)

        divergence = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(fetch_one, pr) for pr in pr_list]
            for future in futures:
                number, result = future.result()
                if result:
                    divergence[str(number)] = result

        return jsonify({"divergence": divergence})

    except Exception as e:
        logger.error(f"Failed to fetch divergence: {e}")
        return jsonify({"error": str(e)}), 500
