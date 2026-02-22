"""Merge queue routes: CRUD, reorder, notes."""

from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, jsonify, request

from backend.extensions import logger
from backend.database import get_queue_db, get_reviews_db
from backend.services.github_service import fetch_pr_state_and_sha
from backend.routes import error_response

queue_bp = Blueprint("queue", __name__)


@queue_bp.route("/api/merge-queue", methods=["GET"])
def get_merge_queue():
    """Get all items in the merge queue with fresh PR states and review info."""
    try:
        queue_db = get_queue_db()
        reviews_db = get_reviews_db()
        queue_items = queue_db.get_queue()
        if not queue_items:
            return jsonify({"queue": []})

        def enrich_queue_item(item):
            notes_count = queue_db.get_notes_count(item["id"])
            repo_parts = item["repo"].split("/")
            pr_state = None
            has_new_commits = False
            last_reviewed_sha = None
            current_sha = None
            review_score = None
            has_review = False
            review_id = None
            inline_comments_posted = False
            major_concerns_posted = False
            minor_issues_posted = False
            critical_posted_count = None
            critical_found_count = None
            major_posted_count = None
            major_found_count = None
            minor_posted_count = None
            minor_found_count = None

            if len(repo_parts) == 2:
                owner, repo = repo_parts
                pr_state, current_sha = fetch_pr_state_and_sha(owner, repo, item["pr_number"])

                latest_review = reviews_db.get_latest_review_for_pr(item["repo"], item["pr_number"])
                if latest_review:
                    has_review = True
                    review_score = latest_review.get("score")
                    review_id = latest_review.get("id")
                    inline_comments_posted = latest_review.get("inline_comments_posted", False)
                    major_concerns_posted = latest_review.get("major_concerns_posted", False)
                    minor_issues_posted = latest_review.get("minor_issues_posted", False)
                    critical_posted_count = latest_review.get("critical_posted_count")
                    critical_found_count = latest_review.get("critical_found_count")
                    major_posted_count = latest_review.get("major_posted_count")
                    major_found_count = latest_review.get("major_found_count")
                    minor_posted_count = latest_review.get("minor_posted_count")
                    minor_found_count = latest_review.get("minor_found_count")
                    if latest_review.get("head_commit_sha"):
                        last_reviewed_sha = latest_review["head_commit_sha"]
                        if current_sha and last_reviewed_sha:
                            has_new_commits = current_sha != last_reviewed_sha
            else:
                pr_state = item.get("pr_state")

            return {
                "id": item["id"],
                "number": item["pr_number"],
                "title": item["pr_title"],
                "url": item["pr_url"],
                "author": item["pr_author"],
                "additions": item["additions"],
                "deletions": item["deletions"],
                "repo": item["repo"],
                "addedAt": item["added_at"],
                "notesCount": notes_count,
                "prState": pr_state or item.get("pr_state"),
                "hasNewCommits": has_new_commits,
                "lastReviewedSha": last_reviewed_sha,
                "currentSha": current_sha,
                "hasReview": has_review,
                "reviewScore": review_score,
                "reviewId": review_id,
                "inlineCommentsPosted": inline_comments_posted,
                "majorConcernsPosted": major_concerns_posted,
                "minorIssuesPosted": minor_issues_posted,
                "criticalPostedCount": critical_posted_count,
                "criticalFoundCount": critical_found_count,
                "majorPostedCount": major_posted_count,
                "majorFoundCount": major_found_count,
                "minorPostedCount": minor_posted_count,
                "minorFoundCount": minor_found_count
            }

        with ThreadPoolExecutor(max_workers=5) as executor:
            queue = list(executor.map(enrich_queue_item, queue_items))

        return jsonify({"queue": queue})
    except Exception as e:
        return error_response("Internal server error", 500, f"Error getting merge queue: {e}")


@queue_bp.route("/api/merge-queue", methods=["POST"])
def add_to_merge_queue():
    """Add a PR to the merge queue."""
    try:
        queue_db = get_queue_db()
        pr_data = request.get_json()
        if not pr_data:
            return jsonify({"error": "No data provided"}), 400

        required_fields = ["number", "title", "url", "author", "repo"]
        for field in required_fields:
            if field not in pr_data:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        repo_parts = pr_data["repo"].split("/")
        pr_state = None
        if len(repo_parts) == 2:
            pr_state, _ = fetch_pr_state_and_sha(repo_parts[0], repo_parts[1], pr_data["number"])

        item = queue_db.add_to_queue(
            pr_number=pr_data["number"],
            repo=pr_data["repo"],
            pr_title=pr_data["title"],
            pr_author=pr_data["author"],
            pr_url=pr_data["url"],
            additions=pr_data.get("additions", 0),
            deletions=pr_data.get("deletions", 0),
            pr_state=pr_state
        )

        queue_item = {
            "id": item["id"],
            "number": item["pr_number"],
            "title": item["pr_title"],
            "url": item["pr_url"],
            "author": item["pr_author"],
            "additions": item["additions"],
            "deletions": item["deletions"],
            "repo": item["repo"],
            "addedAt": item["added_at"],
            "notesCount": 0,
            "prState": pr_state
        }

        return jsonify({"message": "PR added to queue", "item": queue_item}), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        return error_response("Internal server error", 500, f"Error adding to merge queue: {e}")


@queue_bp.route("/api/merge-queue/<int:pr_number>", methods=["DELETE"])
def remove_from_merge_queue(pr_number):
    """Remove a PR from the merge queue."""
    try:
        queue_db = get_queue_db()
        repo = request.args.get("repo")
        removed = queue_db.remove_from_queue(pr_number, repo)

        if not removed:
            return jsonify({"error": "PR not found in queue"}), 404

        return jsonify({"message": "PR removed from queue"})

    except Exception as e:
        return error_response("Internal server error", 500, f"Error removing from merge queue: {e}")


@queue_bp.route("/api/merge-queue/reorder", methods=["POST"])
def reorder_merge_queue():
    """Reorder items in the merge queue."""
    try:
        queue_db = get_queue_db()
        order_data = request.get_json()
        if not order_data or "order" not in order_data:
            return jsonify({"error": "No order provided"}), 400

        order = order_data["order"]
        queue_items = queue_db.reorder_queue(order)

        new_queue = []
        for item in queue_items:
            new_queue.append({
                "number": item["pr_number"],
                "title": item["pr_title"],
                "url": item["pr_url"],
                "author": item["pr_author"],
                "additions": item["additions"],
                "deletions": item["deletions"],
                "repo": item["repo"],
                "addedAt": item["added_at"]
            })

        return jsonify({"message": "Queue reordered", "queue": new_queue})

    except Exception as e:
        return error_response("Internal server error", 500, f"Error reordering merge queue: {e}")


# --- Queue Notes ---

@queue_bp.route("/api/merge-queue/<int:pr_number>/notes", methods=["GET"])
def get_queue_notes(pr_number):
    """Get all notes for a queue item."""
    try:
        queue_db = get_queue_db()
        repo = request.args.get("repo")
        if not repo:
            return jsonify({"error": "repo parameter required"}), 400

        queue_item_id = queue_db.get_queue_item_id(pr_number, repo)
        if not queue_item_id:
            return jsonify({"error": "PR not found in queue"}), 404

        notes = queue_db.get_notes(queue_item_id)

        formatted_notes = []
        for note in notes:
            formatted_notes.append({
                "id": note["id"],
                "content": note["content"],
                "createdAt": note["created_at"]
            })

        return jsonify({"notes": formatted_notes})

    except Exception as e:
        return error_response("Internal server error", 500, f"Error getting queue notes: {e}")


@queue_bp.route("/api/merge-queue/<int:pr_number>/notes", methods=["POST"])
def add_queue_note(pr_number):
    """Add a note to a queue item."""
    try:
        queue_db = get_queue_db()
        repo = request.args.get("repo")
        if not repo:
            return jsonify({"error": "repo parameter required"}), 400

        data = request.get_json()
        if not data or "content" not in data:
            return jsonify({"error": "content is required"}), 400

        content = data["content"].strip()
        if not content:
            return jsonify({"error": "content cannot be empty"}), 400

        queue_item_id = queue_db.get_queue_item_id(pr_number, repo)
        if not queue_item_id:
            return jsonify({"error": "PR not found in queue"}), 404

        note = queue_db.add_note(queue_item_id, content)

        return jsonify({
            "message": "Note added",
            "note": {
                "id": note["id"],
                "content": note["content"],
                "createdAt": note["created_at"]
            }
        }), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return error_response("Internal server error", 500, f"Error adding queue note: {e}")


@queue_bp.route("/api/merge-queue/notes/<int:note_id>", methods=["DELETE"])
def delete_queue_note(note_id):
    """Delete a note from a queue item."""
    try:
        queue_db = get_queue_db()
        deleted = queue_db.delete_note(note_id)
        if not deleted:
            return jsonify({"error": "Note not found"}), 404

        return jsonify({"message": "Note deleted"})

    except Exception as e:
        return error_response("Internal server error", 500, f"Error deleting queue note: {e}")
