"""Code review routes: start, cancel, status, list active, post inline comments, check new commits."""

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from backend.extensions import logger, active_reviews, reviews_lock
from backend.database import get_reviews_db
from backend.services.github_service import fetch_pr_head_sha
from backend.services.review_service import save_review_to_db, check_review_status, begin_review, cancel_active_review, valid_reviewer_types
from backend.services.review_event_log import record_verdict_posted
from backend.services.inline_comments_service import post_inline_comments, preview_section_issues
from backend.services.verdict_service import post_verdict
from backend.routes import error_response

review_bp = Blueprint("review", __name__)


@review_bp.route("/api/reviews", methods=["GET"])
def get_reviews():
    """Get all active/recent reviews with updated statuses."""
    reviews_db = get_reviews_db()
    reviews_list = []

    with reviews_lock:
        keys = list(active_reviews.keys())

    for key in keys:
        check_review_status(key, active_reviews, reviews_lock, reviews_db)
        with reviews_lock:
            review = active_reviews.get(key)
            if review is None:
                continue
            parts = key.split("/")
            reviews_list.append({
                "key": key,
                "owner": parts[0] if len(parts) >= 1 else "",
                "repo": parts[1] if len(parts) >= 2 else "",
                "pr_number": int(parts[2]) if len(parts) >= 3 else 0,
                "status": review["status"],
                "started_at": review.get("started_at", ""),
                "completed_at": review.get("completed_at", ""),
                "pr_url": review.get("pr_url", ""),
                "review_file": review.get("review_file", ""),
                "exit_code": review.get("exit_code"),
                "error_output": review.get("error_output", ""),
                "is_followup": review.get("is_followup", False),
                "auto_started": review.get("auto_started", False),
                "attempt": review.get("attempt", 1)
            })

    return jsonify({"reviews": reviews_list})


@review_bp.route("/api/reviews", methods=["POST"])
def start_review():
    """Start a new code review for a PR."""
    try:
        reviews_db = get_reviews_db()
        data = request.get_json()
        if not data:
            logger.warning("Review request received with no data")
            return jsonify({"error": "No data provided"}), 400

        required_fields = ["number", "url", "owner", "repo"]
        for field in required_fields:
            if field not in data:
                logger.warning(f"Review request missing required field: {field}")
                return jsonify({"error": f"Missing required field: {field}"}), 400

        pr_number = data["number"]
        pr_url = data["url"]
        owner = data["owner"]
        repo = data["repo"]
        key = f"{owner}/{repo}/{pr_number}"

        is_followup = data.get("is_followup", False)
        previous_review_id = data.get("previous_review_id")
        pr_title = data.get("title")
        pr_author = data.get("author")
        reviewer_type = data.get("reviewer_type", "default")
        if reviewer_type not in valid_reviewer_types():
            return jsonify({"error": f"Invalid reviewer_type: {reviewer_type}"}), 400

        logger.info(f"Received {'follow-up ' if is_followup else ''}review request for {key} (reviewer={reviewer_type})")

        payload, status = begin_review(
            owner, repo, pr_number, pr_url, reviews_db,
            is_followup=is_followup,
            previous_review_id=previous_review_id,
            pr_title=pr_title,
            pr_author=pr_author,
            reviewer_type=reviewer_type,
        )
        return jsonify(payload), status

    except Exception as e:
        logger.exception(f"Unexpected error starting review: {e}")
        return error_response("Internal server error", 500)


@review_bp.route("/api/reviews/<owner>/<repo>/<int:pr_number>", methods=["DELETE"])
def cancel_review(owner, repo, pr_number):
    """Cancel/terminate a running review."""
    key = f"{owner}/{repo}/{pr_number}"
    logger.info(f"Received cancel request for review: {key}")

    result = cancel_active_review(key)
    if result == "not_found":
        logger.warning(f"Cancel request for non-existent review: {key}")
        return jsonify({"error": "Review not found"}), 404
    if result == "error":
        return error_response("Failed to terminate review process", 500)

    return jsonify({"message": "Review cancelled", "key": key})


@review_bp.route("/api/reviews/<owner>/<repo>/<int:pr_number>/status", methods=["GET"])
def get_review_status_endpoint(owner, repo, pr_number):
    """Get the status of a specific review."""
    key = f"{owner}/{repo}/{pr_number}"
    reviews_db = get_reviews_db()

    review = check_review_status(key, active_reviews, reviews_lock, reviews_db)
    if review is None:
        return jsonify({"error": "Review not found"}), 404

    return jsonify({
        "key": key,
        "status": review["status"],
        "started_at": review.get("started_at", ""),
        "completed_at": review.get("completed_at", ""),
        "pr_url": review.get("pr_url", ""),
        "review_file": review.get("review_file", ""),
        "exit_code": review.get("exit_code"),
        "error_output": review.get("error_output", "")
    })


@review_bp.route("/api/reviews/<int:review_id>/section-issues", methods=["GET"])
def preview_section_issues_endpoint(review_id):
    """Return parsed issues for a review section for preview/selection."""
    try:
        reviews_db = get_reviews_db()
        section = request.args.get("section", "critical")
        result, status_code = preview_section_issues(reviews_db, review_id, section=section)
        return jsonify(result), status_code
    except Exception as e:
        return error_response("Internal server error", 500, f"Error fetching section issues for review {review_id}: {e}")


@review_bp.route("/api/reviews/<int:review_id>/post-inline-comments", methods=["POST"])
def post_inline_comments_endpoint(review_id):
    """Post issues from a review section as inline PR comments."""
    try:
        reviews_db = get_reviews_db()
        data = request.get_json(silent=True) or {}
        section = data.get("section", "critical")
        selected_indices = data.get("selected_indices")
        result, status_code = post_inline_comments(
            reviews_db, review_id, section=section, selected_indices=selected_indices
        )
        return jsonify(result), status_code
    except Exception as e:
        return error_response("Internal server error", 500, f"Error posting inline comments for review {review_id}: {e}")


@review_bp.route("/api/reviews/check-new-commits/<owner>/<repo>/<int:pr_number>", methods=["GET"])
def check_new_commits(owner, repo, pr_number):
    """Check if a PR has new commits since the last review."""
    try:
        reviews_db = get_reviews_db()
        full_repo = f"{owner}/{repo}"
        latest_review = reviews_db.get_latest_review_for_pr(full_repo, pr_number)

        last_reviewed_sha = None
        if latest_review:
            last_reviewed_sha = latest_review.get("head_commit_sha")

        current_sha = fetch_pr_head_sha(owner, repo, pr_number)

        has_new_commits = False
        if last_reviewed_sha and current_sha:
            has_new_commits = last_reviewed_sha != current_sha
        elif current_sha and not last_reviewed_sha:
            has_new_commits = True if latest_review else False

        return jsonify({
            "has_new_commits": has_new_commits,
            "last_reviewed_sha": last_reviewed_sha,
            "current_sha": current_sha
        })

    except Exception as e:
        return error_response("Internal server error", 500, f"Error checking new commits for PR #{pr_number}: {e}")


@review_bp.route("/api/repos/<owner>/<repo>/prs/<int:pr_number>/verdict", methods=["POST"])
def post_verdict_endpoint(owner, repo, pr_number):
    """Post a formal PR review verdict (Approve, Request Changes, Comment)."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        event = data.get("event")
        body = data.get("body")
        inline_comments = data.get("inline_comments")
        review_id = data.get("review_id")

        if not event:
            return jsonify({"error": "Missing required field: event"}), 400

        result, status_code = post_verdict(
            owner, repo, pr_number, event, body,
            inline_comments=inline_comments, review_id=review_id,
        )
        # Log the post against the run that produced this review, so the Review
        # Logs tab shows hand-posted verdicts alongside auto ones. Verdicts sent
        # without a review_id have no run to attach to and are not recorded.
        if status_code == 200 and review_id:
            record_verdict_posted(
                f"{owner}/{repo}", pr_number, review_id=review_id,
                event=event, auto_started=False,
            )
        return jsonify(result), status_code
    except Exception as e:
        return error_response("Internal server error", 500, f"Error posting verdict for PR #{pr_number}: {e}")
