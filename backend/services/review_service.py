"""Claude CLI subprocess management: start, cancel, poll, save to DB."""

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from backend.config import get_reviews_dir
from backend.services.github_service import fetch_pr_head_sha, fetch_pr_state
from backend.services.review_schema import markdown_to_json, validate_review_json, json_to_markdown, SCHEMA_VERSION

logger = logging.getLogger(__name__)

# Compact schema instructions embedded in the review prompt
_SCHEMA_INSTRUCTIONS = (
    "The JSON must have these top-level keys: "
    '"schema_version" (set to "1.0.0"), '
    '"metadata" (object with pr_number, repository, pr_url, pr_title, author, branch {head, base}, '
    "review_date, review_type, files_changed, additions, deletions), "
    '"summary" (string), '
    '"sections" (array of objects with type=critical|major|minor, display_name, and issues array), '
    '"highlights" (array of strings), '
    '"recommendations" (array of {priority: must_fix|high|medium|low, text}), '
    '"score" (object with overall 0-10, optional breakdown array of {category, score, comment}, optional summary). '
    "Each issue MUST have: title (string), location (object with file, start_line, end_line), "
    "problem (string), and optionally principle (string — the engineering principle violated, "
    "e.g. 'DRY / Single Source of Truth (violates DRY)'), fix (string), and code_snippet (string). "
)


def save_review_to_db(key, review, status, reviews_db):
    """Save a completed/failed review to the database.

    Reads both .md and .json files. If .json exists and validates, uses it directly.
    Otherwise falls back to parsing the .md file via markdown_to_json().
    """
    try:
        parts = key.split("/")
        if len(parts) >= 3:
            owner = parts[0]
            repo = parts[1]
            pr_number = int(parts[2])
            full_repo = f"{owner}/{repo}"

            review_json_data = None
            review_file = review.get("review_file")

            if status == "completed" and review_file:
                review_path = Path(review_file)
                json_path = review_path.with_suffix(".json")

                # Try reading the .json file first (agent writes both .md and .json)
                if json_path.exists():
                    try:
                        raw = json_path.read_text(encoding="utf-8")
                        parsed = json.loads(raw)
                        valid, errs = validate_review_json(parsed)
                        if valid:
                            review_json_data = parsed
                            logger.info(f"Loaded validated JSON review from {json_path}")
                        else:
                            logger.warning(f"JSON review at {json_path} failed validation: {errs[:3]}")
                    except Exception as e:
                        logger.warning(f"Could not read/parse JSON review file {json_path}: {e}")

                # Fallback: read the .md file and convert to JSON
                if review_json_data is None and review_path.exists():
                    try:
                        md_content = review_path.read_text(encoding="utf-8")
                        metadata = {
                            "pr_number": pr_number,
                            "repo": full_repo,
                            "pr_url": review.get("pr_url", ""),
                            "pr_title": review.get("pr_title"),
                            "pr_author": review.get("pr_author"),
                            "is_followup": review.get("is_followup", False),
                            "parent_review_id": review.get("parent_review_id"),
                        }
                        review_json_data = markdown_to_json(md_content, metadata)
                        logger.info(f"Converted markdown review to JSON for {key}")
                    except Exception as e:
                        logger.warning(f"Could not read/convert review file {review_file}: {e}")

            # Build content_json string
            if review_json_data is None:
                # Distinguishable stub for failed/empty reviews
                review_json_data = {
                    "schema_version": SCHEMA_VERSION,
                    "error": True,
                    "metadata": {"pr_number": pr_number, "repository": full_repo},
                    "summary": "",
                    "sections": [],
                    "highlights": [],
                    "recommendations": [],
                    "score": {"overall": 0},
                }

            content_json_str = json.dumps(review_json_data, ensure_ascii=False)

            pr_url = review.get("pr_url", "")
            pr_title = review.get("pr_title")
            pr_author = review.get("pr_author")
            is_followup = review.get("is_followup", False)
            parent_review_id = review.get("parent_review_id")

            if not pr_title:
                pr_title = review_json_data.get("metadata", {}).get("pr_title")
            if not pr_title:
                pr_title = f"PR #{pr_number} Review"

            head_commit_sha = fetch_pr_head_sha(owner, repo, pr_number)
            pr_state_at_review = fetch_pr_state(owner, repo, pr_number)

            reviews_db.save_review(
                pr_number=pr_number,
                repo=full_repo,
                pr_title=pr_title,
                pr_author=pr_author,
                pr_url=pr_url,
                status=status,
                review_file_path=review_file,
                content_json=content_json_str,
                is_followup=is_followup,
                parent_review_id=parent_review_id,
                head_commit_sha=head_commit_sha,
                pr_state_at_review=pr_state_at_review
            )
            logger.info(f"Saved review to database for {key}")
    except Exception as e:
        logger.error(f"Failed to save review to database for {key}: {e}")


def check_review_status(key, active_reviews, reviews_lock, reviews_db):
    """Check and update the status of a review process."""
    with reviews_lock:
        if key not in active_reviews:
            return None
        review = active_reviews[key]
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

        return review


def start_review_process(pr_url, owner, repo, pr_number, is_followup=False, previous_review_content=None):
    """Start a Claude CLI review process in the background.

    Args:
        previous_review_content: For follow-ups, the JSON string of the previous review's content_json.

    Returns:
        tuple: (process, review_file_path_or_error, is_followup)
    """
    reviews_dir = get_reviews_dir()
    reviews_dir.mkdir(parents=True, exist_ok=True)

    repo_safe = repo.replace("/", "-")
    suffix = "-followup" if is_followup else ""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S") if is_followup else ""
    if is_followup:
        review_file = reviews_dir / f"{owner}-{repo_safe}-pr-{pr_number}{suffix}-{timestamp}.md"
    else:
        review_file = reviews_dir / f"{owner}-{repo_safe}-pr-{pr_number}.md"

    json_file = str(review_file).replace(".md", ".json")

    if is_followup and previous_review_content:
        # Convert raw JSON to readable markdown for the prompt
        previous_review_markdown = previous_review_content
        try:
            parsed_prev = json.loads(previous_review_content)
            previous_review_markdown = json_to_markdown(parsed_prev)
        except (json.JSONDecodeError, TypeError, Exception):
            pass  # Fall back to raw string if conversion fails

        prompt = (
            f"Review PR #{pr_number} at {pr_url}. "
            f"This is a FOLLOW-UP review. Previous review:\n\n"
            f"---PREVIOUS REVIEW---\n{previous_review_markdown[:8000]}\n---END PREVIOUS REVIEW---\n\n"
            f"Focus on: changes since last review, whether previous issues were addressed. "
            f"Include a 'followup' section with a 'resolution_status' array tracking each previous issue. "
            f"Each entry MUST be an object with exactly these fields: "
            f'"issue" (string — the human-readable title of the previous issue, copy it verbatim from the previous review), '
            f'"status" (one of: resolved, partially_addressed, not_addressed, wont_fix), '
            f'"notes" (string — brief explanation of what changed or why). '
            f'Do NOT use "title", "details", or "id" as alternative field names. '
            f"Use the elite-code-reviewer agent. "
            f"Write the review to {review_file}. "
            f"ALSO write a structured JSON version to {json_file} following this schema: "
            f"{_SCHEMA_INSTRUCTIONS} "
            f"IMPORTANT: Include a final score from 0-10 in both formats."
        )
    else:
        prompt = (
            f"Review PR #{pr_number} at {pr_url}. "
            f"Use the elite-code-reviewer agent. "
            f"Write the review to {review_file}. "
            f"ALSO write a structured JSON version to {json_file} following this schema: "
            f"{_SCHEMA_INSTRUCTIONS} "
            f"IMPORTANT: Include a final score from 0-10 in both formats."
        )

    # --dangerously-skip-permissions is required for non-interactive subprocess execution.
    # This app is single-user/local-only; the flag does not expose a network attack surface.
    # allowedTools is restricted to read-only git/gh commands + file tools.
    cmd = [
        "claude",
        "-p", prompt,
        "--allowedTools", (
            "Bash(git status*),Bash(git log*),Bash(git show*),"
            "Bash(git diff*),Bash(git blame*),Bash(git branch*),"
            "Bash(gh pr view*),Bash(gh pr diff*),Bash(gh pr checks*),"
            "Bash(gh api*),Read,Glob,Grep,Write,Task"
        ),
        "--dangerously-skip-permissions"
    ]

    review_type = "follow-up " if is_followup else ""
    logger.info(f"Starting {review_type}review for PR #{pr_number} ({owner}/{repo})")
    logger.debug(f"Review command: {' '.join(cmd)}")

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        logger.info(f"Review process started with PID {process.pid} for {owner}/{repo}/#{pr_number}")
        return process, str(review_file), is_followup
    except FileNotFoundError:
        error_msg = "Claude CLI not found. Please ensure 'claude' is installed and in PATH."
        logger.error(f"Failed to start review: {error_msg}")
        return None, error_msg, is_followup
    except Exception as e:
        logger.error(f"Failed to start review process: {e}")
        return None, str(e), is_followup
