"""Review history routes: list, detail, PR reviews, stats, check."""

import json

from flask import Blueprint, jsonify, request

from backend.extensions import logger
from backend.database import get_reviews_db
from backend.routes import error_response
from backend.services.review_schema import json_to_markdown, markdown_to_json, validate_review_json

history_bp = Blueprint("history", __name__)


@history_bp.route("/api/review-history", methods=["GET"])
def get_review_history():
    """List reviews with optional filtering."""
    try:
        reviews_db = get_reviews_db()
        repo = request.args.get("repo")
        author = request.args.get("author")
        pr_number = request.args.get("pr_number", type=int)
        search = request.args.get("search")
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)

        if search:
            reviews = reviews_db.search_reviews(search, limit=limit)
        else:
            reviews = reviews_db.list_reviews(
                repo=repo,
                author=author,
                pr_number=pr_number,
                limit=limit,
                offset=offset
            )

        formatted = []
        for review in reviews:
            formatted.append({
                "id": review["id"],
                "pr_number": review["pr_number"],
                "repo": review["repo"],
                "pr_title": review["pr_title"],
                "pr_author": review["pr_author"],
                "pr_url": review["pr_url"],
                "review_timestamp": review["review_timestamp"],
                "status": review["status"],
                "score": review["score"],
                "is_followup": review["is_followup"],
                "parent_review_id": review["parent_review_id"],
                "head_commit_sha": review.get("head_commit_sha"),
                "inline_comments_posted": review.get("inline_comments_posted", False),
                "pr_state": review.get("pr_state_at_review")
            })

        total_all = reviews_db.count_all()

        return jsonify({"reviews": formatted, "total": total_all})

    except Exception as e:
        return error_response("Internal server error", 500, f"Error getting review history: {e}")


@history_bp.route("/api/review-history/<int:review_id>", methods=["GET"])
def get_review_detail(review_id):
    """Get a single review with full content (JSON + generated markdown)."""
    try:
        reviews_db = get_reviews_db()
        review = reviews_db.get_review(review_id)
        if not review:
            return jsonify({"error": "Review not found"}), 404

        result = dict(review)
        # Parse content_json and provide generated markdown for rendering
        content_json_str = result.get("content_json")
        if content_json_str:
            try:
                parsed = json.loads(content_json_str)
                result["content_json"] = parsed
                result["content"] = json_to_markdown(parsed)
            except (json.JSONDecodeError, TypeError):
                result["content_json"] = None
                result["content"] = ""
        else:
            result["content_json"] = None
            result["content"] = ""

        return jsonify({"review": result})

    except Exception as e:
        return error_response("Internal server error", 500, f"Error getting review {review_id}: {e}")


@history_bp.route("/api/review-history/pr/<owner>/<repo>/<int:pr_number>", methods=["GET"])
def get_pr_reviews(owner, repo, pr_number):
    """Get all reviews for a specific PR."""
    try:
        reviews_db = get_reviews_db()
        full_repo = f"{owner}/{repo}"
        reviews = reviews_db.get_reviews_for_pr(full_repo, pr_number)

        formatted = []
        for review in reviews:
            item = {
                "id": review["id"],
                "pr_number": review["pr_number"],
                "repo": review["repo"],
                "pr_title": review["pr_title"],
                "pr_author": review["pr_author"],
                "pr_url": review["pr_url"],
                "review_timestamp": review["review_timestamp"],
                "status": review["status"],
                "score": review["score"],
                "is_followup": review["is_followup"],
                "parent_review_id": review["parent_review_id"]
            }
            # Generate markdown content from JSON
            content_json_str = review.get("content_json")
            if content_json_str:
                try:
                    parsed = json.loads(content_json_str)
                    item["content_json"] = parsed
                    item["content"] = json_to_markdown(parsed)
                except (json.JSONDecodeError, TypeError):
                    item["content_json"] = None
                    item["content"] = ""
            else:
                item["content_json"] = None
                item["content"] = ""
            formatted.append(item)

        return jsonify({"reviews": formatted})

    except Exception as e:
        return error_response("Internal server error", 500, f"Error getting reviews for PR #{pr_number}: {e}")


@history_bp.route("/api/review-history/stats", methods=["GET"])
def get_review_stats():
    """Get review statistics."""
    try:
        reviews_db = get_reviews_db()
        stats = reviews_db.get_review_stats()
        return jsonify({"stats": stats})

    except Exception as e:
        return error_response("Internal server error", 500, f"Error getting review stats: {e}")


@history_bp.route("/api/review-history/check/<owner>/<repo>/<int:pr_number>", methods=["GET"])
def check_pr_review_exists(owner, repo, pr_number):
    """Check if a PR has been reviewed and get latest review info."""
    try:
        reviews_db = get_reviews_db()
        full_repo = f"{owner}/{repo}"
        latest_review = reviews_db.get_latest_review_for_pr(full_repo, pr_number)

        if latest_review:
            return jsonify({
                "has_review": True,
                "latest_review": {
                    "id": latest_review["id"],
                    "score": latest_review["score"],
                    "review_timestamp": latest_review["review_timestamp"],
                    "is_followup": latest_review["is_followup"],
                    "head_commit_sha": latest_review.get("head_commit_sha"),
                    "inline_comments_posted": latest_review.get("inline_comments_posted", False)
                }
            })
        else:
            return jsonify({"has_review": False})

    except Exception as e:
        return error_response("Internal server error", 500, f"Error checking review for PR #{pr_number}: {e}")


@history_bp.route("/api/review-history/<int:review_id>/reparse", methods=["POST"])
def reparse_review(review_id):
    """Re-parse a review's .md file from disk to refresh its content_json.

    Useful for backfilling fields (like 'principle') that were added after
    the review was originally saved.
    """
    try:
        from pathlib import Path

        reviews_db = get_reviews_db()
        review = reviews_db.get_review(review_id)
        if not review:
            return jsonify({"error": "Review not found"}), 404

        file_path = review.get("review_file_path")
        if not file_path:
            return jsonify({"error": "No review file path stored for this review"}), 400

        md_path = Path(file_path)
        if not md_path.exists():
            return jsonify({"error": f"Review file not found on disk: {file_path}"}), 404

        md_content = md_path.read_text(encoding="utf-8")

        metadata = {
            "pr_number": review["pr_number"],
            "repo": review["repo"],
            "pr_url": review.get("pr_url", ""),
            "pr_title": review.get("pr_title"),
            "pr_author": review.get("pr_author"),
            "is_followup": review.get("is_followup", False),
            "parent_review_id": review.get("parent_review_id"),
        }
        new_json = markdown_to_json(md_content, metadata)

        valid, errs = validate_review_json(new_json)
        if not valid:
            return jsonify({"error": "Re-parsed JSON failed validation", "details": errs[:5]}), 400

        reviews_db.update_review(review_id, content_json=json.dumps(new_json))
        logger.info(f"Re-parsed review {review_id} from {file_path}")

        return jsonify({"success": True, "review_id": review_id})

    except Exception as e:
        return error_response("Internal server error", 500, f"Error re-parsing review {review_id}: {e}")
