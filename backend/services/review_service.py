"""Review subprocess management: start, cancel, poll, save to DB.

Routes through the pluggable AgentBackend abstraction. The legacy Claude CLI
subprocess flow is preserved via ClaudeCLIAgent.
"""

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from backend.agents import get_agent, AgentHandle, AgentStatus
from backend.config import get_reviews_dir
from backend.services.github_service import fetch_pr_head_sha, fetch_pr_state
from backend.services.review_schema import markdown_to_json, validate_review_json, json_to_markdown, SCHEMA_VERSION

logger = logging.getLogger(__name__)


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
    """Check and update the status of a review process.

    Supports both the legacy subprocess path (process key) and the new
    agent abstraction path (handle key).
    """
    with reviews_lock:
        if key not in active_reviews:
            return None
        review = active_reviews[key]

        if review["status"] != "running":
            return review

        handle = review.get("handle")
        process = review.get("process")

        if handle and isinstance(handle, AgentHandle):
            agent_status = check_agent_review_status(handle)
            if agent_status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED):
                status = "completed" if agent_status == AgentStatus.COMPLETED else "failed"
                review["status"] = status
                review["completed_at"] = datetime.now(timezone.utc).isoformat()

                if agent_status == AgentStatus.COMPLETED:
                    logger.info(f"Review completed successfully: {key}")
                    try:
                        agent = get_agent(handle.agent_name)
                        artifact = agent.get_output(handle)
                        if artifact.file_path:
                            review["review_file"] = artifact.file_path
                    except Exception as e:
                        logger.warning(f"Could not get agent output for {key}: {e}")
                else:
                    try:
                        agent = get_agent(handle.agent_name)
                        artifact = agent.get_output(handle)
                        review["error_output"] = artifact.error or "Unknown error"
                    except Exception:
                        review["error_output"] = "Unknown error"
                    logger.error(f"Review failed: {key}")

                save_review_to_db(key, review, status, reviews_db)

        elif process:
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


def start_review_process(pr_url, owner, repo, pr_number, is_followup=False,
                         previous_review_content=None, agent_name="claude"):
    """Start a review process via the agent abstraction layer.

    Uses the pluggable AgentBackend. Defaults to 'claude' (ClaudeCLIAgent)
    which preserves the original subprocess behaviour.

    Returns:
        tuple: (handle_or_process, review_file_path_or_error, is_followup)
               handle_or_process is an AgentHandle for the new path.
               For backward compat, callers can still check `.process` on the handle metadata.
    """
    context = {
        "pr_url": pr_url,
        "owner": owner,
        "repo": repo,
        "pr_number": pr_number,
        "is_followup": is_followup,
        "previous_review_content": previous_review_content,
    }

    prompt = f"Review PR #{pr_number} at {pr_url}. Use the elite-code-reviewer agent."

    try:
        agent = get_agent(agent_name)
        handle = agent.start_review(prompt, context)
        review_file = handle.metadata.get("review_file", "")
        logger.info(
            f"Started review via '{agent_name}' for PR #{pr_number} ({owner}/{repo})"
        )
        return handle, review_file, is_followup
    except Exception as e:
        logger.error(f"Failed to start review process: {e}")
        return None, str(e), is_followup


def check_agent_review_status(handle: AgentHandle) -> AgentStatus:
    """Check the status of an agent-based review."""
    try:
        agent = get_agent(handle.agent_name)
        return agent.check_status(handle)
    except Exception:
        return AgentStatus.FAILED
