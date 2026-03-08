"""Cursor CLI agent backend — wraps the `agent` command for code reviews.

Supports any model available through Cursor (Claude, GPT, etc.) via --model flag.
Uses print mode (-p) for non-interactive subprocess execution.
"""

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


class _ProcessState:
    """Tracks a running Cursor CLI subprocess using stream-json for live output."""
    def __init__(self, process: subprocess.Popen, review_file: str, json_file: str):
        self.process = process
        self.review_file = review_file
        self.json_file = json_file
        self.stdout: Optional[str] = None
        self.stderr: Optional[str] = None
        self.exit_code: Optional[int] = None
        self._live_lines: list[str] = []
        self._stderr_lines: list[str] = []
        self._result_text: Optional[str] = None
        self._lock = threading.Lock()
        self._stdout_thread = threading.Thread(target=self._read_stream_json, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _read_stream_json(self):
        """Parse stream-json stdout, extracting text deltas for live display."""
        try:
            for raw_line in self.process.stdout:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    msg = json.loads(raw_line)
                except json.JSONDecodeError:
                    with self._lock:
                        self._live_lines.append(raw_line + "\n")
                    continue
                msg_type = msg.get("type", "")
                if msg_type == "assistant":
                    content = msg.get("message", {}).get("content", [])
                    for block in content:
                        if block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                with self._lock:
                                    self._live_lines.append(text)
                                    if len(self._live_lines) > 1000:
                                        self._live_lines = self._live_lines[-500:]
                        elif block.get("type") == "tool_use":
                            tool_name = block.get("name", "tool")
                            with self._lock:
                                self._live_lines.append(f"\n[Using tool: {tool_name}]\n")
                elif msg_type == "result":
                    self._result_text = msg.get("result", "")
        except (ValueError, OSError):
            pass

    def _read_stderr(self):
        """Capture stderr for error reporting."""
        try:
            for line in self.process.stderr:
                with self._lock:
                    self._stderr_lines.append(line)
                    if len(self._stderr_lines) > 200:
                        self._stderr_lines = self._stderr_lines[-100:]
        except (ValueError, OSError):
            pass

    def get_live_text(self, tail: int = 200) -> str:
        with self._lock:
            lines = self._live_lines[-tail:]
        return "".join(lines)

    def get_stderr_text(self) -> str:
        with self._lock:
            return "".join(self._stderr_lines[-50:])


class CursorCLIAgent(AgentBackend):
    """Runs reviews via the Cursor `agent` CLI tool as a subprocess.

    Config options:
      - model: model name to pass via --model (e.g. "gpt-4o", "claude-3.5-sonnet")
      - sandbox: "enabled" or "disabled" (default: "disabled" for review tool access)
      - mode: agent mode — "agent" (default), "plan", or "ask"
    """

    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self._processes: dict[str, _ProcessState] = {}
        self.model = config.get("model")
        self.sandbox = config.get("sandbox", "disabled")
        self.mode = config.get("mode")

    def start_review(self, prompt: str, context: dict) -> AgentHandle:
        reviews_dir = get_reviews_dir()
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

        agent_bin = self.config.get("agent_path") or self._find_agent_binary()
        cmd = [
            agent_bin, "--print", "--trust", "--force",
            "--output-format", "stream-json",
            "--stream-partial-output",
        ]

        if self.model:
            cmd.extend(["--model", self.model])
        if self.sandbox:
            cmd.extend(["--sandbox", self.sandbox])
        if self.mode:
            cmd.extend(["--mode", self.mode])

        if context.get("phase") == "b":
            phase_b_dir = reviews_dir / "phase-b"
            phase_b_dir.mkdir(parents=True, exist_ok=True)
            cmd.extend(["--workspace", str(phase_b_dir)])

        cmd.append(full_prompt)

        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
        except FileNotFoundError:
            raise RuntimeError(
                "Cursor CLI not found. Install via: curl https://cursor.com/install -fsS | bash"
            )

        handle_id = str(uuid.uuid4())
        self._processes[handle_id] = _ProcessState(process, str(review_file), json_file)

        logger.info(
            f"CursorCLI: started PID {process.pid} for {owner}/{repo}#{pr_number} "
            f"(handle={handle_id[:8]}, model={self.model or 'default'})"
        )
        return AgentHandle(
            agent_name=self.name,
            handle_id=handle_id,
            metadata={"pid": process.pid, "review_file": str(review_file), "model": self.model},
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
        state.stdout = state._result_text or state.get_live_text()
        state.stderr = state.get_stderr_text() or None

        state.exit_code = exit_code
        return AgentStatus.COMPLETED if exit_code == 0 else AgentStatus.FAILED

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

        score = None
        if content_json and "score" in content_json:
            score = content_json["score"].get("overall")

        return ReviewArtifact(
            content_md=content_md,
            content_json=content_json,
            file_path=state.review_file,
            score=score,
        )

    def get_live_output(self, handle: AgentHandle) -> str:
        state = self._processes.get(handle.handle_id)
        if state is None:
            return ""
        return state.get_live_text()

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
        logger.info(f"CursorCLI: cancelled handle {handle.handle_id[:8]}")
        return True

    @staticmethod
    def _find_agent_binary() -> str:
        """Locate the Cursor `agent` binary, checking common install paths."""
        import shutil
        from pathlib import Path as _P

        found = shutil.which("agent")
        if found:
            return found

        candidates = [
            _P.home() / ".local" / "bin" / "agent",
            _P("/usr/local/bin/agent"),
        ]
        for p in candidates:
            if p.exists() and p.is_file():
                return str(p)

        return "agent"

    def _build_prompt(self, user_prompt: str, context: dict, review_file: str, json_file: str) -> str:
        pr_url = context.get("pr_url", "")
        pr_number = context.get("pr_number", 0)
        is_followup = context.get("is_followup", False)
        previous_review = context.get("previous_review_content")

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
            )

        if user_prompt:
            return (
                f"{user_prompt}\n\n"
                f"Write the review to {review_file}. "
                f"ALSO write a structured JSON version to {json_file} following this schema: "
                f"{_SCHEMA_INSTRUCTIONS} "
                f"IMPORTANT: Include a final score from 0-10 in both formats."
            )

        return (
            f"Review PR #{pr_number} at {pr_url}. "
            f"Use the elite-code-reviewer agent. "
            f"Write the review to {review_file}. "
            f"ALSO write a structured JSON version to {json_file} following this schema: "
            f"{_SCHEMA_INSTRUCTIONS} "
            f"IMPORTANT: Include a final score from 0-10 in both formats."
        )
