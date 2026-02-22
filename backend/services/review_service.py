"""Claude CLI subprocess management: start, cancel, poll, save to DB."""

import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from backend.config import get_reviews_dir
from backend.services.github_service import fetch_pr_head_sha, fetch_pr_state

logger = logging.getLogger(__name__)


def save_review_to_db(key, review, status, reviews_db):
    """Save a completed/failed review to the database."""
    try:
        parts = key.split("/")
        if len(parts) >= 3:
            owner = parts[0]
            repo = parts[1]
            pr_number = int(parts[2])
            full_repo = f"{owner}/{repo}"

            content = None
            review_file = review.get("review_file")
            if status == "completed" and review_file:
                try:
                    review_path = Path(review_file)
                    if review_path.exists():
                        content = review_path.read_text(encoding='utf-8')
                except Exception as e:
                    logger.warning(f"Could not read review file {review_file}: {e}")

            pr_url = review.get("pr_url", "")
            pr_title = review.get("pr_title")
            pr_author = review.get("pr_author")
            is_followup = review.get("is_followup", False)
            parent_review_id = review.get("parent_review_id")

            if not pr_title and content:
                h1_match = re.search(r'^#\s+(.+?)$', content, re.MULTILINE)
                if h1_match:
                    pr_title = h1_match.group(1).strip()
                else:
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
                content=content,
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

    if is_followup and previous_review_content:
        prompt = (
            f"Review PR #{pr_number} at {pr_url}. "
            f"This is a FOLLOW-UP review. Here is the previous review for context:\n\n"
            f"---PREVIOUS REVIEW---\n{previous_review_content[:8000]}\n---END PREVIOUS REVIEW---\n\n"
            f"Focus on: changes since last review, whether previous issues were addressed. "
            f"Use the elite-code-reviewer agent. "
            f"Write the review to {review_file} "
            f"IMPORTANT: Include a final score from 0-10 in the review."
        )
    else:
        prompt = (
            f"Review PR #{pr_number} at {pr_url}. "
            f"Use the elite-code-reviewer agent. "
            f"Write the review to {review_file} "
            f"IMPORTANT: Include a final score from 0-10 in the review."
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
