"""PR routes: list PRs with filters, batch divergence."""

from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, jsonify, request

from backend.config import get_config, get_pr_sync_config
from backend.extensions import logger
from backend.filters.pr_filter_builder import PRFilterParams, PRFilterBuilder
from backend.routes import error_response
from backend.database import get_automation_dispatches_db, get_timeline_cache_db, get_synced_prs_db
from backend.services.github_service import (
    run_gh_command, parse_json_output, TransientGitHubError,
    PR_LIST_JSON_FIELDS as PR_JSON_FIELDS, fetch_full_pr,
)
from backend.services.pr_local_filter import (
    filter_prs_locally, needs_github_search, sort_prs_locally, states_for,
)
from backend.services.pr_service import get_review_status, get_ci_status, get_current_reviewers
from backend.services.timeline_service import get_timeline

pr_bp = Blueprint("pr", __name__)

# Map computed reviewStatus back to uppercase reviewDecision for frontend badges
_STATUS_TO_DECISION = {
    "changes_requested": "CHANGES_REQUESTED",
    "approved": "APPROVED",
    "review_required": "REVIEW_REQUIRED",
}

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
        _attach_automation([pr], f"{owner}/{repo}")
        return jsonify({"prs": [pr]})
    except RuntimeError:
        return jsonify({"prs": []})


def _attach_automation(prs, repo_full):
    """Stamp each PR with its automation pipeline row (or None), the same
    `automation` shape queue cards carry, so the pipeline badge renders on the
    main PR list too. Never fails the list."""
    try:
        from backend.services.queue_enrichment import format_automation_state

        dispatches = get_automation_dispatches_db()
        pairs = [(repo_full, pr["number"]) for pr in prs if pr.get("number")]
        rows = {}
        # Chunked: each pair costs two SQL variables and SQLite caps them.
        for i in range(0, len(pairs), 400):
            rows.update(dispatches.get_for_prs(pairs[i:i + 400]))
        for pr in prs:
            pr["automation"] = format_automation_state(rows.get((repo_full, pr.get("number"))))
    except Exception as e:
        logger.warning(f"Could not attach automation state for {repo_full}: {e}")
        for pr in prs:
            pr.setdefault("automation", None)
    return prs


def _postprocess_and_filter(prs, params, repo_full=None):
    """Compute serve-time statuses and apply draft/review/CI post-filters.

    Shared by the DB, hybrid, and live paths so all three return identical
    shapes. When repo_full is given, rows also get their automation pipeline
    state attached.
    """
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

    if repo_full:
        _attach_automation(prs, repo_full)
    return prs


def _sync_meta(status, repo_row=None):
    return {"status": status, "lastSyncedAt": (repo_row or {}).get("last_synced_at")}


@pr_bp.route("/api/repos/<owner>/<repo>/prs")
def get_prs(owner, repo):
    """Get PRs with advanced filtering support.

    Three-way dispatch (see docs/specs/2026-08-28-pr-sync-db-design.md):
    DB path when the repo's sync backfill is done, hybrid (numbers-only gh
    search joined against DB rows) when a GitHub-only filter is active, and
    the live gh query otherwise.
    """
    try:
        # Direct PR number lookup — bypasses all other filters
        pr_number = request.args.get("prNumber")
        if pr_number:
            return _get_pr_by_number(owner, repo, pr_number)

        config = get_config()
        params = PRFilterParams.from_request_args(request.args, default_per_page=config.get("default_per_page", 30))
        builder = PRFilterBuilder(owner, repo, params)

        sync_cfg = get_pr_sync_config()
        repo_full = f"{owner}/{repo}"
        store = get_synced_prs_db()
        sync_eligible = sync_cfg["enabled"] and repo_full not in sync_cfg["exclude_repos"]

        repo_row = None
        if sync_eligible:
            store.register_repo(repo_full)
            repo_row = store.get_repo(repo_full)

        if repo_row and repo_row["backfill_done"]:
            if needs_github_search(params):
                # Hybrid: GitHub decides which PRs and in what order; the DB
                # supplies the rich rows.
                numbers = [r["number"] for r in parse_json_output(run_gh_command(builder.build(json_fields="number")))]
                by_number = store.get_prs_by_numbers(repo_full, numbers)
                prs = []
                for n in numbers:
                    if n in by_number:
                        prs.append(by_number[n])
                    else:
                        # Outside the sync window (e.g. very old closed PR) — hydrate on the spot.
                        try:
                            pr = fetch_full_pr(owner, repo, n)
                            store.upsert_pr(repo_full, pr)
                            pr["fetchedAt"] = None
                            prs.append(pr)
                        except RuntimeError:
                            logger.warning(f"Hybrid fetch: could not hydrate {repo_full}#{n}")
            else:
                prs = store.get_prs(repo_full, states=states_for(params))
                prs = sort_prs_locally(filter_prs_locally(prs, params), params)
            prs = _postprocess_and_filter(prs, params, repo_full)[: params.limit]
            return jsonify({"prs": prs, "sync": _sync_meta("ready", repo_row)})

        # Live path: unsynced repo, or backfill still running.
        live_status = "backfilling" if repo_row else "live"
        try:
            prs = parse_json_output(run_gh_command(builder.build()))
            prs = _postprocess_and_filter(prs, params, repo_full)
            return jsonify({"prs": prs, "sync": _sync_meta(live_status, repo_row)})
        except TransientGitHubError:
            # Mid-backfill upstream flake: partial local data beats an error page.
            if repo_row and store.count_prs(repo_full):
                prs = store.get_prs(repo_full, states=states_for(params))
                prs = sort_prs_locally(filter_prs_locally(prs, params), params)
                prs = _postprocess_and_filter(prs, params, repo_full)[: params.limit]
                return jsonify({"prs": prs, "sync": _sync_meta("backfilling", repo_row)})
            raise

    except TransientGitHubError as e:
        logger.warning(f"GitHub upstream error fetching PRs for {owner}/{repo}: {e}")
        return jsonify({
            "error": "GitHub is having a moment (upstream 5xx). Try again in a few seconds.",
            "transient": True,
        }), 503
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@pr_bp.route("/api/repos/<owner>/<repo>/prs/<int:pr_number>/refresh", methods=["POST"])
def refresh_pr(owner, repo, pr_number):
    """Live-fetch one PR, upsert it into the synced store, return the fresh row."""
    repo_full = f"{owner}/{repo}"
    store = get_synced_prs_db()
    try:
        pr = fetch_full_pr(owner, repo, pr_number)
    except TransientGitHubError as e:
        logger.warning(f"Refresh: upstream error for {repo_full}#{pr_number}: {e}")
        return jsonify({
            "error": "GitHub is having a moment (upstream 5xx). Try again in a few seconds.",
            "transient": True,
        }), 503
    except RuntimeError as e:
        if "Not Found" in str(e) or "404" in str(e):
            store.delete_pr(repo_full, pr_number)
            return jsonify({"error": "PR not found"}), 404
        return jsonify({"error": str(e)}), 500

    store.upsert_pr(repo_full, pr)
    row = store.get_prs_by_numbers(repo_full, [pr_number]).get(pr_number, pr)
    processed = _postprocess_and_filter([row], PRFilterParams(), repo_full)
    return jsonify({"pr": processed[0] if processed else row})


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
