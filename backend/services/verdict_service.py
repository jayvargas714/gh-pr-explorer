"""Post a formal PR review verdict (Approve, Request Changes, Comment) to GitHub."""

import json
import logging
import subprocess

from backend.services.github_service import fetch_pr_head_sha

logger = logging.getLogger(__name__)

VALID_EVENTS = {"APPROVE", "REQUEST_CHANGES", "COMMENT"}


def _validate_inline_comment(comment):
    """Validate an inline comment dict has the required location fields.

    Returns (validated_comment, error_string). error_string is None on success.
    """
    path = comment.get("path")
    if not path or not isinstance(path, str) or not path.strip():
        return None, "Inline comment missing file path"

    body = comment.get("body")
    if not body or not isinstance(body, str) or not body.strip():
        return None, f"Inline comment for {path} has empty body"

    start_line = comment.get("start_line")
    end_line = comment.get("end_line")

    validated = {
        "path": path.strip(),
        "body": body.strip(),
    }

    # Line-level comment
    if start_line is not None and end_line is not None:
        try:
            start_line = int(start_line)
            end_line = int(end_line)
        except (ValueError, TypeError):
            return None, f"Invalid line numbers for {path}"
        if start_line < 1 or end_line < 1:
            return None, f"Line numbers must be positive for {path}"
        validated["start_line"] = start_line
        validated["end_line"] = end_line
    elif start_line is not None or end_line is not None:
        return None, f"Both start_line and end_line must be provided for {path}"
    # else: file-level comment (no lines) — valid

    return validated, None


def _post_file_comment(owner, repo, pr_number, commit_sha, comment):
    """Post a single file-level comment (no line numbers)."""
    comment_body = {
        "commit_id": commit_sha,
        "path": comment["path"],
        "body": comment["body"],
        "subject_type": "file",
    }
    subprocess.run(
        [
            "gh", "api",
            f"repos/{owner}/{repo}/pulls/{pr_number}/comments",
            "--method", "POST",
            "--input", "-",
        ],
        input=json.dumps(comment_body),
        capture_output=True,
        text=True,
        check=True,
    )


def post_verdict(owner, repo, pr_number, event, body, inline_comments=None):
    """Post a PR review verdict via the GitHub API.

    Args:
        owner: Repository owner.
        repo: Repository name.
        pr_number: PR number.
        event: One of APPROVE, REQUEST_CHANGES, COMMENT.
        body: Review body text.
        inline_comments: Optional list of inline comment dicts with keys:
            path (str), body (str), start_line (int|None), end_line (int|None).

    Returns:
        tuple: (response_dict, status_code)
    """
    if event not in VALID_EVENTS:
        return {"error": f"Invalid event: {event}. Must be one of {sorted(VALID_EVENTS)}"}, 400

    has_inline = inline_comments and len(inline_comments) > 0

    if (not body or not body.strip()) and not has_inline:
        return {"error": "Review body cannot be empty"}, 400

    # Validate inline comments
    validated_line_comments = []
    validated_file_comments = []
    if has_inline:
        for i, ic in enumerate(inline_comments):
            validated, err = _validate_inline_comment(ic)
            if err:
                return {"error": f"Inline comment #{i + 1}: {err}"}, 400
            if "start_line" in validated:
                validated_line_comments.append(validated)
            else:
                validated_file_comments.append(validated)

    current_sha = fetch_pr_head_sha(owner, repo, pr_number)
    if not current_sha:
        return {"error": "Could not fetch PR head commit SHA"}, 500

    # Build the review API payload
    review_body = {
        "commit_id": current_sha,
        "event": event,
        "body": (body or "").strip() or f"Review with {len(validated_line_comments) + len(validated_file_comments)} inline comment(s)",
    }

    # Add line-level inline comments to the review
    if validated_line_comments:
        comments = []
        for c in validated_line_comments:
            comment = {"path": c["path"], "body": c["body"]}
            if c["start_line"] == c["end_line"]:
                comment["line"] = c["end_line"]
            else:
                comment["start_line"] = c["start_line"]
                comment["line"] = c["end_line"]
            comments.append(comment)
        review_body["comments"] = comments

    payload_json = json.dumps(review_body)
    logger.info(f"Posting verdict on {owner}/{repo}#{pr_number}: event={event}, "
                f"body_len={len(review_body.get('body', ''))}, "
                f"comments={len(review_body.get('comments', []))}")
    logger.debug(f"Verdict payload: {payload_json[:500]}")

    try:
        result = subprocess.run(
            [
                "gh", "api",
                f"repos/{owner}/{repo}/pulls/{pr_number}/reviews",
                "--method", "POST",
                "--input", "-",
            ],
            input=payload_json,
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info(f"Posted {event} verdict on {owner}/{repo}#{pr_number} with {len(validated_line_comments)} line comments")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to post verdict on {owner}/{repo}#{pr_number}: {e.stderr[:500]}")
        logger.error(f"Verdict payload that failed: {payload_json[:1000]}")
        return {"error": f"Failed to post review to GitHub: {e.stderr[:300]}"}, 500

    # Post file-level comments individually (no line numbers)
    file_errors = []
    for fc in validated_file_comments:
        try:
            _post_file_comment(owner, repo, pr_number, current_sha, fc)
            logger.info(f"Posted file-level comment on {fc['path']} for {owner}/{repo}#{pr_number}")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to post file comment on {fc['path']}: {e.stderr[:200]}")
            file_errors.append(fc["path"])

    inline_total = len(validated_line_comments) + len(validated_file_comments)
    return {
        "message": f"Review verdict posted: {event}"
                   + (f" with {inline_total} inline comment(s)" if inline_total else ""),
        "event": event,
        "pr_number": pr_number,
        "inline_posted": inline_total - len(file_errors),
        "inline_errors": file_errors if file_errors else None,
    }, 200
