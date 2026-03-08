"""Claude CLI agent backend — wraps the existing subprocess-based review flow."""

import json
import logging
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.agents.base import AgentBackend, AgentHandle, AgentStatus, ReviewArtifact
from backend.config import get_reviews_dir
from backend.services.review_schema import (
    markdown_to_json, validate_review_json, json_to_markdown, SCHEMA_VERSION,
)

logger = logging.getLogger(__name__)

_NON_INTERACTIVE = (
    "\n\nCRITICAL: You are running in a fully automated, non-interactive pipeline. "
    "NEVER ask the user questions, request clarification, or wait for input. "
    "Make your own best-judgment decisions and continue autonomously. "
    "Do NOT output phrases like 'How would you like me to proceed?' or similar.\n"
)

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
    "problem (string), and optionally fix (string) and code_snippet (string). "
)

_ALLOWED_TOOLS = (
    "Bash(git status*),Bash(git log*),Bash(git show*),"
    "Bash(git diff*),Bash(git blame*),Bash(git branch*),"
    "Bash(gh pr view*),Bash(gh pr diff*),Bash(gh pr checks*),"
    "Bash(gh api*),Read,Glob,Grep,Write,Task"
)


class _ProcessState:
    """Tracks a running Claude CLI subprocess."""
    def __init__(self, process: subprocess.Popen, review_file: str, json_file: str):
        self.process = process
        self.review_file = review_file
        self.json_file = json_file
        self.stdout: Optional[str] = None
        self.stderr: Optional[str] = None
        self.exit_code: Optional[int] = None
        self._live_lines: list[str] = []
        self._lock = threading.Lock()
        self._stdout_thread = threading.Thread(target=self._read_stream,
                                                args=(self.process.stdout,), daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stream,
                                                args=(self.process.stderr,), daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _read_stream(self, stream):
        """Read from a process stream (stdout or stderr) into _live_lines."""
        try:
            for line in stream:
                with self._lock:
                    self._live_lines.append(line)
                    if len(self._live_lines) > 500:
                        self._live_lines = self._live_lines[-300:]
        except (ValueError, OSError):
            pass

    def get_live_text(self, tail: int = 200) -> str:
        with self._lock:
            lines = self._live_lines[-tail:]
        return "".join(lines)


class ClaudeCLIAgent(AgentBackend):
    """Runs reviews via the `claude` CLI tool as a subprocess."""

    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self._processes: dict[str, _ProcessState] = {}

    def start_review(self, prompt: str, context: dict) -> AgentHandle:
        base_reviews_dir = get_reviews_dir()
        instance_id = context.get("instance_id")
        reviews_dir = base_reviews_dir / f"run-{instance_id}" if instance_id else base_reviews_dir
        reviews_dir.mkdir(parents=True, exist_ok=True)

        owner = context.get("owner", "unknown")
        repo = context.get("repo", "unknown")
        pr_number = context.get("pr_number", 0)
        is_followup = context.get("is_followup", False)

        repo_safe = repo.replace("/", "-")
        phase = context.get("phase", "")
        domain = context.get("domain", "")
        phase_suffix = f"-review-{phase}" if phase else ""
        domain_suffix = f"-{domain}" if domain else ""
        if is_followup:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            review_file = reviews_dir / f"{owner}-{repo_safe}-pr-{pr_number}-followup-{timestamp}.md"
        else:
            review_file = reviews_dir / f"{owner}-{repo_safe}-pr-{pr_number}{phase_suffix}{domain_suffix}.md"
        json_file = str(review_file).replace(".md", ".json")

        full_prompt = self._build_prompt(prompt, context, str(review_file), json_file)

        cmd = [
            "claude",
            "-p", full_prompt,
            "--allowedTools", _ALLOWED_TOOLS,
            "--dangerously-skip-permissions",
        ]

        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
        except FileNotFoundError:
            raise RuntimeError("Claude CLI not found. Ensure 'claude' is installed and in PATH.")

        handle_id = str(uuid.uuid4())
        self._processes[handle_id] = _ProcessState(process, str(review_file), json_file)

        logger.info(
            f"ClaudeCLI: started PID {process.pid} for {owner}/{repo}#{pr_number} (handle={handle_id[:8]})"
        )
        return AgentHandle(
            agent_name=self.name,
            handle_id=handle_id,
            metadata={"pid": process.pid, "review_file": str(review_file)},
        )

    def check_status(self, handle: AgentHandle) -> AgentStatus:
        state = self._processes.get(handle.handle_id)
        if state is None:
            return AgentStatus.FAILED

        if state.exit_code is not None:
            return AgentStatus.COMPLETED if state.exit_code == 0 else AgentStatus.FAILED

        exit_code = state.process.poll()
        if exit_code is None:
            return AgentStatus.RUNNING

        state._stdout_thread.join(timeout=3)
        state._stderr_thread.join(timeout=2)
        state.stdout = state.get_live_text()
        state.stderr = None

        state.exit_code = exit_code
        return AgentStatus.COMPLETED if exit_code == 0 else AgentStatus.FAILED

    def get_live_output(self, handle: AgentHandle) -> str:
        state = self._processes.get(handle.handle_id)
        if state is None:
            return ""
        return state.get_live_text()

    def cleanup(self, handle: AgentHandle) -> None:
        """Remove process state and close pipes to prevent FD leaks."""
        state = self._processes.pop(handle.handle_id, None)
        if state is None:
            return
        for pipe in (state.process.stdout, state.process.stderr):
            try:
                if pipe and not pipe.closed:
                    pipe.close()
            except Exception:
                pass
        try:
            state.process.wait(timeout=1)
        except Exception:
            pass

    def get_output(self, handle: AgentHandle) -> ReviewArtifact:
        state = self._processes.get(handle.handle_id)
        if state is None:
            return ReviewArtifact(error="Unknown handle")

        if state.exit_code != 0:
            return ReviewArtifact(error=state.stderr or f"Exit code {state.exit_code}")

        review_path = Path(state.review_file)
        json_path = Path(state.json_file)

        content_json = None
        content_md = None

        if json_path.exists():
            try:
                raw = json_path.read_text(encoding="utf-8")
                parsed = json.loads(raw)
                valid, errs = validate_review_json(parsed)
                if valid:
                    content_json = parsed
                else:
                    logger.warning(f"JSON validation failed: {errs[:3]}")
            except Exception as e:
                logger.warning(f"Could not parse JSON review: {e}")

        if review_path.exists():
            try:
                content_md = review_path.read_text(encoding="utf-8")
                if content_json is None:
                    content_json = markdown_to_json(content_md, {})
            except Exception as e:
                logger.warning(f"Could not read markdown review: {e}")

        if content_md is None and state.stdout:
            content_md = state.stdout

        score = None
        if content_json and "score" in content_json:
            score = content_json["score"].get("overall")

        return ReviewArtifact(
            content_md=content_md,
            content_json=content_json,
            file_path=state.review_file,
            score=score,
        )

    def cancel(self, handle: AgentHandle) -> bool:
        state = self._processes.get(handle.handle_id)
        if state is None or state.exit_code is not None:
            return False
        try:
            state.process.terminate()
            state.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            state.process.kill()
        state.exit_code = -1
        logger.info(f"ClaudeCLI: cancelled handle {handle.handle_id[:8]}")
        self.cleanup(handle)
        return True

    def _build_prompt(self, user_prompt: str, context: dict, review_file: str, json_file: str) -> str:
        pr_url = context.get("pr_url", "")
        pr_number = context.get("pr_number", 0)
        is_followup = context.get("is_followup", False)
        previous_review = context.get("previous_review_content")
        task = context.get("task", "")

        if task and task != "review":
            return user_prompt + _NON_INTERACTIVE

        if is_followup and previous_review:
            prev_md = previous_review
            try:
                parsed_prev = json.loads(previous_review)
                prev_md = json_to_markdown(parsed_prev)
            except (json.JSONDecodeError, TypeError):
                pass
            return (
                f"Review PR #{pr_number} at {pr_url}. "
                f"This is a FOLLOW-UP review. Previous review:\n\n"
                f"---PREVIOUS REVIEW---\n{prev_md[:8000]}\n---END PREVIOUS REVIEW---\n\n"
                f"Focus on: changes since last review, whether previous issues were addressed. "
                f"Include a 'followup' section with 'resolution_status' array tracking each previous issue. "
                f"Use the elite-code-reviewer agent. "
                f"Write the review to {review_file}. "
                f"ALSO write a structured JSON version to {json_file} following this schema: "
                f"{_SCHEMA_INSTRUCTIONS} "
                f"IMPORTANT: Include a final score from 0-10 in both formats."
                f"{_NON_INTERACTIVE}"
            )

        if user_prompt:
            return (
                f"{user_prompt}\n\n"
                f"Write the review to {review_file}. "
                f"ALSO write a structured JSON version to {json_file} following this schema: "
                f"{_SCHEMA_INSTRUCTIONS} "
                f"IMPORTANT: Include a final score from 0-10 in both formats."
                f"{_NON_INTERACTIVE}"
            )

        return (
            f"Review PR #{pr_number} at {pr_url}. "
            f"Use the elite-code-reviewer agent. "
            f"Write the review to {review_file}. "
            f"ALSO write a structured JSON version to {json_file} following this schema: "
            f"{_SCHEMA_INSTRUCTIONS} "
            f"IMPORTANT: Include a final score from 0-10 in both formats."
            f"{_NON_INTERACTIVE}"
        )
