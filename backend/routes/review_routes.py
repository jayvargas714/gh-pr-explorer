"""Code review routes: start, cancel, status, list active, post inline comments, check new commits."""

import subprocess
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from backend.extensions import logger, active_reviews, reviews_lock
from backend.database import get_reviews_db
from backend.services.github_service import fetch_pr_head_sha
from backend.services.review_service import save_review_to_db, check_review_status, start_review_process
from backend.services.inline_comments_service import post_inline_comments

review_bp = Blueprint("review", __name__)


@review_bp.route("/api/reviews", methods=["GET"])
def get_reviews():
    """Get all active/recent reviews with updated statuses."""
    reviews_db = get_reviews_db()
    reviews_list = []
    with reviews_lock:
        for key, review in active_reviews.items():
            process = review.get("process")
            if process and review["status"] == "running":
                exit_code = process.poll()
                if exit_code is not None:
                    try:
                        stdout, stderr = process.communicate(timeout=1)
                        if stderr:
                            review["error_output"] = stderr.strip()[-2000:]
                        if stdout:
                            review["stdout"] = stdout.strip()[-500:]
                    except subprocess.TimeoutExpired:
                        pass
                    except Exception as e:
                        logger.error(f"Error reading process output for {key}: {e}")

                    status = "completed" if exit_code == 0 else "failed"
                    review["status"] = status
                    review["exit_code"] = exit_code
                    review["completed_at"] = datetime.now(timezone.utc).isoformat()

                    if exit_code == 0:
                        logger.info(f"Review completed successfully: {key}")
                    else:
                        error_msg = review.get("error_output", "Unknown error")
                        logger.error(f"Review failed: {key} (exit code: {exit_code})\nError: {error_msg}")

                    save_review_to_db(key, review, status, reviews_db)

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
                "is_followup": review.get("is_followup", False)
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

        logger.info(f"Received {'follow-up ' if is_followup else ''}review request for {key}")

        with reviews_lock:
            if key in active_reviews:
                existing = active_reviews[key]
                if existing["status"] == "running":
                    logger.warning(f"Review already in progress for {key}")
                    return jsonify({"error": "Review already in progress for this PR"}), 409

        previous_review_content = None
        parent_id = None
        if is_followup:
            full_repo = f"{owner}/{repo}"
            if previous_review_id:
                prev_review = reviews_db.get_review(previous_review_id)
                if prev_review:
                    previous_review_content = prev_review.get("content")
                    parent_id = previous_review_id
            else:
                prev_review = reviews_db.get_latest_review_for_pr(full_repo, pr_number)
                if prev_review:
                    previous_review_content = prev_review.get("content")
                    parent_id = prev_review.get("id")

            if not previous_review_content:
                logger.warning(f"No previous review found for follow-up, proceeding as normal review")
                is_followup = False

        process, result, is_followup = start_review_process(
            pr_url, owner, repo, pr_number,
            is_followup=is_followup,
            previous_review_content=previous_review_content
        )

        if process is None:
            logger.error(f"Failed to start review for {key}: {result}")
            return jsonify({"error": result}), 500

        with reviews_lock:
            active_reviews[key] = {
                "process": process,
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "pr_url": pr_url,
                "review_file": result,
                "is_followup": is_followup,
                "parent_review_id": parent_id,
                "pr_title": pr_title,
                "pr_author": pr_author
            }

        return jsonify({
            "message": "Review started",
            "key": key,
            "status": "running",
            "review_file": result,
            "is_followup": is_followup
        }), 201

    except Exception as e:
        logger.exception(f"Unexpected error starting review: {e}")
        return jsonify({"error": str(e)}), 500


@review_bp.route("/api/reviews/<owner>/<repo>/<int:pr_number>", methods=["DELETE"])
def cancel_review(owner, repo, pr_number):
    """Cancel/terminate a running review."""
    key = f"{owner}/{repo}/{pr_number}"
    logger.info(f"Received cancel request for review: {key}")

    with reviews_lock:
        if key not in active_reviews:
            logger.warning(f"Cancel request for non-existent review: {key}")
            return jsonify({"error": "Review not found"}), 404

        review = active_reviews[key]
        process = review.get("process")

        if process and review["status"] == "running":
            try:
                logger.info(f"Terminating review process (PID {process.pid}) for {key}")
                process.terminate()
                try:
                    process.wait(timeout=2)
                    logger.info(f"Review process terminated gracefully for {key}")
                except subprocess.TimeoutExpired:
                    process.kill()
                    logger.warning(f"Review process killed (did not terminate gracefully) for {key}")
                review["status"] = "cancelled"
            except Exception as e:
                logger.error(f"Failed to terminate review process for {key}: {e}")
                return jsonify({"error": f"Failed to terminate process: {e}"}), 500

        del active_reviews[key]
        logger.info(f"Review cancelled and removed: {key}")

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


@review_bp.route("/api/reviews/<int:review_id>/post-inline-comments", methods=["POST"])
def post_inline_comments_endpoint(review_id):
    """Post issues from a review section as inline PR comments."""
    try:
        reviews_db = get_reviews_db()
        data = request.get_json(silent=True) or {}
        section = data.get("section", "critical")
        result, status_code = post_inline_comments(reviews_db, review_id, section=section)
        return jsonify(result), status_code
    except Exception as e:
        logger.error(f"Error posting inline comments for review {review_id}: {e}")
        return jsonify({"error": str(e)}), 500


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
        logger.error(f"Error checking new commits for PR #{pr_number}: {e}")
        return jsonify({"error": str(e)}), 500
