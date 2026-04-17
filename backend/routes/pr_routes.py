"""PR routes: list PRs with filters, batch divergence."""

from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, jsonify, request

from backend.config import get_config
from backend.extensions import logger
from backend.filters.pr_filter_builder import PRFilterParams, PRFilterBuilder
from backend.routes import error_response
from backend.database import get_timeline_cache_db
from backend.services.github_service import run_gh_command, parse_json_output
from backend.services.pr_service import get_review_status, get_ci_status, get_current_reviewers
from backend.services.timeline_service import get_timeline

pr_bp = Blueprint("pr", __name__)

# Map computed reviewStatus back to uppercase reviewDecision for frontend badges
_STATUS_TO_DECISION = {
    "changes_requested": "CHANGES_REQUESTED",
    "approved": "APPROVED",
    "review_required": "REVIEW_REQUIRED",
}

PR_JSON_FIELDS = (
    "number,title,author,state,isDraft,createdAt,updatedAt,closedAt,"
    "mergedAt,url,body,headRefName,baseRefName,labels,assignees,"
    "reviewRequests,reviewDecision,reviews,"
    "mergeable,additions,deletions,changedFiles,"
    "milestone,statusCheckRollup"
)


def _get_pr_by_number(owner, repo, pr_number):
    """Fetch a single PR by number using gh pr view."""
    try:
        output = run_gh_command([
            "pr", "view", str(pr_number),
            "-R", f"{owner}/{repo}",
            "--json", PR_JSON_FIELDS
        ])
        pr = parse_json_output(output)
        if not pr:
            return jsonify({"prs": []})

        # parse_json_output returns a list for list commands, dict for view
        if isinstance(pr, list):
            pr = pr[0] if pr else None
        if not pr:
            return jsonify({"prs": []})

        reviews = pr.get("reviews")
        pr["reviewStatus"] = get_review_status(pr.get("reviewDecision"), reviews)
        pr["reviewDecision"] = _STATUS_TO_DECISION.get(pr["reviewStatus"], pr.get("reviewDecision"))
        pr["ciStatus"] = get_ci_status(pr.get("statusCheckRollup"))
        pr["currentReviewers"] = get_current_reviewers(reviews)
        return jsonify({"prs": [pr]})
    except RuntimeError:
        return jsonify({"prs": []})


@pr_bp.route("/api/repos/<owner>/<repo>/prs")
def get_prs(owner, repo):
    """Get PRs with advanced filtering support."""
    try:
        # Direct PR number lookup — bypasses all other filters
        pr_number = request.args.get("prNumber")
        if pr_number:
            return _get_pr_by_number(owner, repo, pr_number)

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
        # Compute reviewStatus from full reviews history, then sync reviewDecision
        # so badges and filters use the same source of truth.
        for pr in prs:
            reviews = pr.get("reviews")
            pr["reviewStatus"] = get_review_status(pr.get("reviewDecision"), reviews)
            pr["reviewDecision"] = _STATUS_TO_DECISION.get(pr["reviewStatus"], pr.get("reviewDecision"))
            pr["ciStatus"] = get_ci_status(pr.get("statusCheckRollup"))
            pr["currentReviewers"] = get_current_reviewers(reviews)

        # Post-filter by review status using our computed reviewStatus
        # GitHub's review: qualifier can be inconsistent when re-reviews are requested,
        # so we verify against our reviews-based computation for consistency.
        if params.review:
            review_values = {r.strip() for r in params.review.split(",") if r.strip()}
            review_status_map = {
                "none": "pending",
                "required": "review_required",
                "approved": "approved",
                "changes_requested": "changes_requested",
            }
            allowed = {review_status_map.get(v, v) for v in review_values}
            prs = [pr for pr in prs if pr.get("reviewStatus") in allowed]

        # Post-filter by CI status (gh search doesn't support status: qualifier for CI checks)
        if params.status:
            selected_statuses = {s.strip() for s in params.status.split(",") if s.strip()}
            prs = [pr for pr in prs if pr.get("ciStatus") in selected_statuses]

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
        return error_response("Internal server error", 500, f"Failed to fetch divergence: {e}")


@pr_bp.route("/api/repos/<owner>/<repo>/prs/<int:pr_number>/timeline")
def get_pr_timeline(owner, repo, pr_number):
    """Return the normalized event timeline for a single PR."""
    try:
        force = request.args.get("refresh") == "true"
        cache_db = get_timeline_cache_db()
        result = get_timeline(owner, repo, pr_number, cache_db, force_refresh=force)
        return jsonify(result)
    except RuntimeError as e:
        msg = str(e)
        if "Not Found" in msg or "404" in msg:
            return jsonify({"error": "PR not found"}), 404
        logger.error(f"Timeline fetch failed for {owner}/{repo}#{pr_number}: {msg}")
        return jsonify({"error": msg}), 503
    except Exception as e:
        logger.exception(f"Unexpected timeline error for {owner}/{repo}#{pr_number}")
        return jsonify({"error": str(e)}), 500
