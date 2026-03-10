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

    # Preserve title for tracking
    if comment.get("title"):
        validated["title"] = comment["title"]

    # Preserve section tag for per-section tracking
    if comment.get("section"):
        validated["section"] = comment["section"]

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


def _try_post_individual_comment(owner, repo, pr_number, current_sha, c):
    """Try posting an individual line comment, falling back to file-level.

    Returns True if posted successfully, False otherwise.
    """
    comment_payload = {
        "commit_id": current_sha,
        "path": c["path"],
        "body": c["body"],
    }
    if c["start_line"] == c["end_line"]:
        comment_payload["line"] = c["end_line"]
    else:
        comment_payload["start_line"] = c["start_line"]
        comment_payload["line"] = c["end_line"]

    try:
        subprocess.run(
            [
                "gh", "api",
                f"repos/{owner}/{repo}/pulls/{pr_number}/comments",
                "--method", "POST",
                "--input", "-",
            ],
            input=json.dumps(comment_payload),
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info(f"Posted individual line comment on {c['path']}:{c.get('start_line', '?')}-{c.get('end_line', '?')}")
        return True
    except subprocess.CalledProcessError:
        # Line-level failed — fall back to file-level comment
        try:
            _post_file_comment(owner, repo, pr_number, current_sha, c)
            logger.info(f"Posted file-level fallback comment on {c['path']}")
            return True
        except subprocess.CalledProcessError as e3:
            logger.warning(f"Failed to post comment on {c['path']} (both line and file): {e3.stderr[:200]}")
            return False


def post_verdict(owner, repo, pr_number, event, body, inline_comments=None, review_id=None):
    """Post a PR review verdict via the GitHub API.

    Args:
        owner: Repository owner.
        repo: Repository name.
        pr_number: PR number.
        event: One of APPROVE, REQUEST_CHANGES, COMMENT.
        body: Review body text.
        inline_comments: Optional list of inline comment dicts with keys:
            path (str), body (str), start_line (int|None), end_line (int|None),
            title (str, optional), section (str, optional: 'critical'|'major'|'minor').
        review_id: Optional review ID — if provided, section-posted counts
            will be updated in the database after posting.

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

    inline_fallback_used = False
    # Track success/failure per comment (parallel arrays with validated_line_comments)
    line_comment_success = [False] * len(validated_line_comments)
    file_comment_success = [False] * len(validated_file_comments)

    try:
        subprocess.run(
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
        # All line comments succeeded as part of the batch
        line_comment_success = [True] * len(validated_line_comments)
        logger.info(f"Posted {event} verdict on {owner}/{repo}#{pr_number} with {len(validated_line_comments)} line comments")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr or ""
        # If 422 and we had inline comments, the line numbers likely don't match the diff.
        # Fall back: post the review body without inline comments, then try each comment individually.
        if "422" in stderr and validated_line_comments:
            logger.warning(f"Review with inline comments got 422 on {owner}/{repo}#{pr_number}, "
                           f"falling back to body-only + individual comments")
            inline_fallback_used = True

            # Post the review body without inline comments
            body_only = {k: v for k, v in review_body.items() if k != "comments"}
            try:
                subprocess.run(
                    [
                        "gh", "api",
                        f"repos/{owner}/{repo}/pulls/{pr_number}/reviews",
                        "--method", "POST",
                        "--input", "-",
                    ],
                    input=json.dumps(body_only),
                    capture_output=True,
                    text=True,
                    check=True,
                )
                logger.info(f"Posted {event} verdict (body-only) on {owner}/{repo}#{pr_number}")
            except subprocess.CalledProcessError as e2:
                logger.error(f"Failed to post body-only verdict on {owner}/{repo}#{pr_number}: {e2.stderr[:500]}")
                return {"error": f"Failed to post review to GitHub: {e2.stderr[:300]}"}, 500

            # Now try each inline comment individually
            for i, c in enumerate(validated_line_comments):
                line_comment_success[i] = _try_post_individual_comment(
                    owner, repo, pr_number, current_sha, c
                )
        else:
            logger.error(f"Failed to post verdict on {owner}/{repo}#{pr_number}: {stderr[:500]}")
            logger.error(f"Verdict payload that failed: {payload_json[:1000]}")
            return {"error": f"Failed to post review to GitHub: {stderr[:300]}"}, 500

    # Post file-level comments individually (no line numbers)
    for i, fc in enumerate(validated_file_comments):
        try:
            _post_file_comment(owner, repo, pr_number, current_sha, fc)
            file_comment_success[i] = True
            logger.info(f"Posted file-level comment on {fc['path']} for {owner}/{repo}#{pr_number}")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to post file comment on {fc['path']}: {e.stderr[:200]}")

    # Build per-section breakdown
    all_comments = validated_line_comments + validated_file_comments
    all_success = line_comment_success + file_comment_success
    section_details = _build_section_details(all_comments, all_success)

    # Update review DB with section posted counts
    if review_id and section_details:
        _update_review_section_counts(review_id, section_details)

    inline_posted = sum(all_success)
    inline_total = len(all_comments)
    inline_errors = [c["path"] for c, ok in zip(all_comments, all_success) if not ok]

    message = f"Review verdict posted: {event}"
    if inline_total:
        message += f" with {inline_posted}/{inline_total} inline comment(s)"
    if inline_fallback_used:
        message += " (comments posted individually due to diff mismatch)"
    if inline_errors:
        message += f" — {len(inline_errors)} comment(s) could not be posted"

    return {
        "message": message,
        "event": event,
        "pr_number": pr_number,
        "inline_posted": inline_posted,
        "inline_errors": inline_errors if inline_errors else None,
        "fallback_used": inline_fallback_used,
        "section_details": section_details if section_details else None,
    }, 200


def _build_section_details(all_comments, all_success):
    """Build per-section posted/found/failed_titles breakdown."""
    sections = {}  # section_key -> {found, posted, failed_titles}
    for comment, ok in zip(all_comments, all_success):
        section = comment.get("section")
        if not section:
            continue
        if section not in sections:
            sections[section] = {"found": 0, "posted": 0, "failed_titles": []}
        sections[section]["found"] += 1
        if ok:
            sections[section]["posted"] += 1
        else:
            title = comment.get("title", comment["path"])
            sections[section]["failed_titles"].append(title)
    return sections if sections else None


def _update_review_section_counts(review_id, section_details):
    """Update the review DB with per-section posted counts from the verdict."""
    try:
        from backend.database import get_reviews_db
        reviews_db = get_reviews_db()
        for section_key, details in section_details.items():
            reviews_db.update_section_posted(
                review_id,
                section_key,
                posted=True,
                posted_count=details["posted"],
                found_count=details["found"],
            )
            logger.info(f"Updated review {review_id} section '{section_key}': "
                        f"{details['posted']}/{details['found']} posted")
    except Exception as e:
        logger.error(f"Failed to update review section counts for review {review_id}: {e}")
