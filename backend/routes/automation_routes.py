"""Automation routes: reviewer registry CRUD + automation config + pipeline view."""

from flask import Blueprint, jsonify, request

from backend.database import (
    get_automation_dispatches_db,
    get_auto_verdicts_db,
    get_queue_db,
    get_reviewers_db,
    get_reviews_db,
    get_synced_prs_db,
)
from backend.database.automation_dispatches import VALID_STATUSES
from backend.extensions import logger
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

    rows = _hide_closed_prs(rows)
    payloads = [_dispatch_payload(row) for row in rows]
    _attach_review_states(payloads)
    return jsonify({"dispatches": payloads})


def _hide_closed_prs(rows):
    """Drop rows whose PR is merged/closed (per the synced-PR store): the
    ledger keeps them — dispatch-at-most-once — but the pipeline view only
    shows PRs that still exist to act on. PRs the store doesn't know stay
    visible; on any failure the unfiltered rows are shown."""
    try:
        store = get_synced_prs_db()
        by_repo = {}
        for r in rows:
            by_repo.setdefault(r["repo"], []).append(r["pr_number"])
        gone = set()
        for repo, numbers in by_repo.items():
            for num, state in store.get_states_by_numbers(repo, numbers).items():
                if (state or "").upper() in ("MERGED", "CLOSED"):
                    gone.add((repo, num))
        return [r for r in rows if (r["repo"], r["pr_number"]) not in gone]
    except Exception as e:
        logger.warning(f"Could not filter closed PRs from the pipeline view: {e}")
        return rows


def _attach_review_states(payloads):
    """Stamp each pipeline row with its live review picture — a review running
    right now (in-memory registry, same source as the Running-now strip), the
    newest recorded review with its posted verdict, and whether the card is
    armed for auto verdicts. A row with none of those carries None. Never
    fails the listing."""
    try:
        from backend.extensions import active_reviews, reviews_lock
        from backend.services.review_service import check_review_status

        reviews_db = get_reviews_db()

        # Reap finished subprocesses the same way GET /api/reviews does, so a
        # review that just exited doesn't linger as "running" here.
        running = set()
        with reviews_lock:
            keys = list(active_reviews.keys())
        for key in keys:
            check_review_status(key, active_reviews, reviews_lock, reviews_db)
            with reviews_lock:
                review = active_reviews.get(key)
            if review and review.get("status") == "running":
                parts = key.split("/")
                if len(parts) >= 3:
                    running.add((f"{parts[0]}/{parts[1]}", int(parts[2])))

        pairs = [(p["repo"], p["prNumber"]) for p in payloads]
        latest = reviews_db.get_latest_for_prs(pairs)
        verdicts = get_auto_verdicts_db().get_latest_for_review_ids(
            [rev["id"] for rev in latest.values()]
        )
        queue_rows = {
            (q["repo"], q["pr_number"]): q for q in get_queue_db().get_queue()
        }

        for p in payloads:
            pair = (p["repo"], p["prNumber"])
            rev = latest.get(pair)
            q = queue_rows.get(pair)
            armed = bool(q and q.get("auto_verdict_enabled"))
            is_running = pair in running
            if rev is None and not armed and not is_running:
                p["reviewState"] = None
                continue
            verdict = verdicts.get(rev["id"]) if rev else None
            p["reviewState"] = {
                "running": is_running,
                "lastReviewId": rev["id"] if rev else None,
                "lastReviewStatus": rev["status"] if rev else None,
                "lastReviewAt": rev["review_timestamp"] if rev else None,
                "isFollowup": bool(rev["is_followup"]) if rev else False,
                "score": rev["score"] if rev else None,
                "verdictEvent": verdict["event"] if verdict else None,
                "verdictOutcome": verdict["outcome"] if verdict else None,
                "armed": armed,
                "autoVerdictMode": (q or {}).get("auto_verdict_mode"),
            }
    except Exception as e:
        logger.warning(f"Could not attach review states to the pipeline view: {e}")
        for p in payloads:
            p.setdefault("reviewState", None)
    return payloads


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
