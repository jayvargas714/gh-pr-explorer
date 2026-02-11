"""Review history routes: list, detail, PR reviews, stats, check."""

from flask import Blueprint, jsonify, request

from backend.extensions import logger
from backend.database import get_reviews_db

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

        return jsonify({"reviews": formatted})

    except Exception as e:
        logger.error(f"Error getting review history: {e}")
        return jsonify({"error": str(e)}), 500


@history_bp.route("/api/review-history/<int:review_id>", methods=["GET"])
def get_review_detail(review_id):
    """Get a single review with full content."""
    try:
        reviews_db = get_reviews_db()
        review = reviews_db.get_review(review_id)
        if not review:
            return jsonify({"error": "Review not found"}), 404

        return jsonify({"review": dict(review)})

    except Exception as e:
        logger.error(f"Error getting review {review_id}: {e}")
        return jsonify({"error": str(e)}), 500


@history_bp.route("/api/review-history/pr/<owner>/<repo>/<int:pr_number>", methods=["GET"])
def get_pr_reviews(owner, repo, pr_number):
    """Get all reviews for a specific PR."""
    try:
        reviews_db = get_reviews_db()
        full_repo = f"{owner}/{repo}"
        reviews = reviews_db.get_reviews_for_pr(full_repo, pr_number)

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
                "content": review["content"],
                "is_followup": review["is_followup"],
                "parent_review_id": review["parent_review_id"]
            })

        return jsonify({"reviews": formatted})

    except Exception as e:
        logger.error(f"Error getting reviews for PR #{pr_number}: {e}")
        return jsonify({"error": str(e)}), 500


@history_bp.route("/api/review-history/stats", methods=["GET"])
def get_review_stats():
    """Get review statistics."""
    try:
        reviews_db = get_reviews_db()
        stats = reviews_db.get_review_stats()
        return jsonify({"stats": stats})

    except Exception as e:
        logger.error(f"Error getting review stats: {e}")
        return jsonify({"error": str(e)}), 500


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
        logger.error(f"Error checking review for PR #{pr_number}: {e}")
        return jsonify({"error": str(e)}), 500
