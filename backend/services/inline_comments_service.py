"""Critical issue parsing from review content + posting to GitHub."""

import json
import logging
import re
import subprocess

from backend.services.github_service import fetch_pr_head_sha

logger = logging.getLogger(__name__)


def _parse_location(location):
    """Parse a location string into (file_path, start_line, end_line) or None.

    Returns file_path with None lines when only a file path is found (no line numbers).
    """
    if not location:
        return None

    loc_match = re.match(r'`?([^`:\s]+)`?\s*:\s*(\d+)(?:\s*-\s*(\d+))?', location)
    if loc_match:
        file_path = loc_match.group(1).strip()
        start_line = int(loc_match.group(2))
        end_line = int(loc_match.group(3)) if loc_match.group(3) else start_line
        return file_path, start_line, end_line

    path_match = re.match(r'`([^`]+)`', location)
    if path_match:
        file_path = path_match.group(1).strip()
        line_match = re.search(r'lines?\s+(\d+)\s*[-\u2013]\s*(\d+)', location)
        if line_match:
            return file_path, int(line_match.group(1)), int(line_match.group(2))
        line_match = re.search(r'line\s+(\d+)', location)
        if line_match:
            line_num = int(line_match.group(1))
            return file_path, line_num, line_num
        # File path found but no line numbers - return as file-level location
        return file_path, None, None

    return None


def _extract_issue_field(content, field_name):
    """Extract a field's full content from an issue block."""
    pattern = re.compile(
        rf'-\s*{field_name}:\s*(.*?)(?=\n-\s*(?:Location|Problem|Fix):|\Z)',
        re.DOTALL
    )
    match = pattern.search(content)
    if match:
        return match.group(1).strip()
    return None


def parse_critical_issues(content):
    """Parse critical issues from review markdown content.

    Returns:
        List of dicts: [{ title, path, start_line, end_line, body }]
        start_line/end_line may be None for file-level issues.
    """
    issues = []
    if not content:
        return issues

    critical_match = re.search(
        r'\*\*Critical Issues\*\*\s*(.*?)(?=\n---|\n\*\*[A-Z]|\Z)',
        content,
        re.DOTALL | re.IGNORECASE
    )

    if not critical_match:
        return issues

    critical_section = critical_match.group(1)
    issue_headers = list(re.finditer(r'\*\*(\d+)\.\s*(.+?)\*\*', critical_section))

    for idx, header_match in enumerate(issue_headers):
        title = header_match.group(2).strip()

        start = header_match.end()
        end = issue_headers[idx + 1].start() if idx + 1 < len(issue_headers) else len(critical_section)
        issue_content = critical_section[start:end]

        location = _extract_issue_field(issue_content, 'Location')
        problem = _extract_issue_field(issue_content, 'Problem')
        fix = _extract_issue_field(issue_content, 'Fix')

        if not location:
            continue

        parsed = _parse_location(location)
        if not parsed:
            continue

        file_path, start_line, end_line = parsed

        body_parts = [f"**{title}**"]
        if problem:
            body_parts.append(f"\n**Problem:** {problem}")
        if fix:
            body_parts.append(f"\n**Fix:** {fix}")

        issues.append({
            "title": title,
            "path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "body": "\n".join(body_parts)
        })

    return issues


def _post_file_comment(owner, repo_name, pr_number, commit_sha, issue):
    """Post a single file-level comment via the individual comments endpoint."""
    comment_body = {
        "commit_id": commit_sha,
        "path": issue["path"],
        "body": issue["body"],
        "subject_type": "file"
    }
    result = subprocess.run(
        [
            "gh", "api",
            f"repos/{owner}/{repo_name}/pulls/{pr_number}/comments",
            "--method", "POST",
            "--input", "-"
        ],
        input=json.dumps(comment_body),
        capture_output=True,
        text=True,
        check=True
    )
    return result


def post_inline_comments(reviews_db, review_id):
    """Post critical issues from a review as inline PR comments.

    Line-level issues are batched into a review. File-level issues (no line numbers)
    are posted individually via the single comment endpoint.

    Returns:
        tuple: (response_dict, status_code)
    """
    review = reviews_db.get_review(review_id)
    if not review:
        return {"error": "Review not found"}, 404

    if review.get("inline_comments_posted"):
        return {"error": "Inline comments have already been posted for this review"}, 409

    content = review.get("content")
    if not content:
        return {"error": "Review has no content to parse"}, 400

    issues = parse_critical_issues(content)
    if not issues:
        return {"error": "No critical issues found in review content", "issues_found": 0}, 400

    repo = review.get("repo")
    pr_number = review.get("pr_number")

    if not repo or not pr_number:
        return {"error": "Review is missing repo or PR number"}, 400

    repo_parts = repo.split("/")
    if len(repo_parts) != 2:
        return {"error": f"Invalid repo format: {repo}"}, 400

    owner, repo_name = repo_parts

    current_sha = fetch_pr_head_sha(owner, repo_name, pr_number)
    if not current_sha:
        return {"error": "Could not fetch PR head commit SHA"}, 500

    # Separate line-level and file-level issues
    line_issues = [i for i in issues if i["start_line"] is not None]
    file_issues = [i for i in issues if i["start_line"] is None]

    posted_count = 0
    errors = []

    # Post line-level issues as a batch review
    if line_issues:
        comments = []
        for issue in line_issues:
            comment = {
                "path": issue["path"],
                "body": issue["body"]
            }
            if issue["start_line"] == issue["end_line"]:
                comment["line"] = issue["end_line"]
            else:
                comment["start_line"] = issue["start_line"]
                comment["line"] = issue["end_line"]
            comments.append(comment)

        review_body = {
            "commit_id": current_sha,
            "event": "COMMENT",
            "body": f"**Code Review Critical Issues** ({len(issues)} issue(s) flagged)",
            "comments": comments
        }

        try:
            result = subprocess.run(
                [
                    "gh", "api",
                    f"repos/{owner}/{repo_name}/pulls/{pr_number}/reviews",
                    "--method", "POST",
                    "--input", "-"
                ],
                input=json.dumps(review_body),
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"Posted {len(line_issues)} line-level comments for review {review_id}")
            posted_count += len(line_issues)
        except subprocess.CalledProcessError as e:
            logger.warning(f"Batch line-level comments failed: {e.stderr[:200]}")
            # Fall back to individual file-level comments for these too
            for issue in line_issues:
                issue_with_lines = dict(issue)
                issue_with_lines["body"] += f"\n\n*(Lines ~{issue['start_line']}-{issue['end_line']})*"
                file_issues.append(issue_with_lines)

    # Post file-level issues individually via the comments endpoint
    if file_issues:
        # If no line-level review was posted, post a summary review first
        if not line_issues or posted_count == 0:
            try:
                summary_body = {
                    "commit_id": current_sha,
                    "event": "COMMENT",
                    "body": f"**Code Review Critical Issues** ({len(issues)} issue(s) flagged)"
                }
                subprocess.run(
                    [
                        "gh", "api",
                        f"repos/{owner}/{repo_name}/pulls/{pr_number}/reviews",
                        "--method", "POST",
                        "--input", "-"
                    ],
                    input=json.dumps(summary_body),
                    capture_output=True,
                    text=True,
                    check=True
                )
            except subprocess.CalledProcessError:
                pass  # Non-critical, continue posting individual comments

        for issue in file_issues:
            try:
                _post_file_comment(owner, repo_name, pr_number, current_sha, issue)
                posted_count += 1
                logger.info(f"Posted file-level comment on {issue['path']} for review {review_id}")
            except subprocess.CalledProcessError as e:
                logger.warning(f"Failed to post file comment on {issue['path']}: {e.stderr[:200]}")
                errors.append(issue["path"])

    if posted_count == 0:
        return {
            "error": f"Failed to post any comments to GitHub",
            "issues_parsed": len(issues),
            "failed_paths": errors
        }, 500

    reviews_db.update_inline_comments_posted(review_id, True)

    return {
        "message": "Inline comments posted successfully",
        "issues_posted": posted_count,
        "issues_found": len(issues),
        "file_level_errors": errors if errors else None
    }, 200
