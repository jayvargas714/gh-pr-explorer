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

from backend.agents.base import AgentBackend, AgentHandle, AgentStatus, ReviewArtifact, normalize_usage
from backend.agents.pid_tracker import register_pid, unregister_pid
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
        self._usage: Optional[dict] = None
        self._cost_usd: Optional[float] = None
        self._duration_ms: Optional[int] = None
        self._num_turns: Optional[int] = None
        self._lock = threading.Lock()
        self._last_full: str = ""
        self._stdout_thread = threading.Thread(target=self._read_stream_json, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _read_stream_json(self):
        """Parse stream-json stdout, extracting text deltas for live display.

        Each ``assistant`` message from ``--stream-partial-output`` is
        *cumulative* within a turn.  We track the cumulative length and
        only append the delta so the live display shows a continuous
        stream across multiple turns rather than replacing on each update.
        """
        try:
            for raw_line in self.process.stdout:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                if not isinstance(raw_line, str):
                    continue
                try:
                    msg = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(msg, dict):
                    continue
                msg_type = msg.get("type", "")
                if msg_type == "assistant":
                    content = msg.get("message", {}).get("content", [])
                    parts: list[str] = []
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                parts.append(text)
                        elif block.get("type") == "tool_use":
                            tool_name = block.get("name", "tool")
                            parts.append(f"\n[Using tool: {tool_name}]\n")
                    full = "".join(parts)
                    if full != self._last_full:
                        prefix_len = 0
                        min_len = min(len(full), len(self._last_full))
                        while prefix_len < min_len and full[prefix_len] == self._last_full[prefix_len]:
                            prefix_len += 1
                        new_text = full[prefix_len:]
                        if new_text:
                            with self._lock:
                                self._live_lines.append(new_text)
                                if len(self._live_lines) > 500:
                                    self._live_lines = self._live_lines[-300:]
                        self._last_full = full
                elif msg_type == "result":
                    with self._lock:
                        self._result_text = msg.get("result", "")
                        self._usage = msg.get("usage")
                        self._cost_usd = msg.get("cost_usd")
                        self._duration_ms = msg.get("duration_ms")
                        self._num_turns = msg.get("num_turns")
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
            phase_b_dir = base_reviews_dir / "phase-b"
            phase_b_dir.mkdir(parents=True, exist_ok=True)
            cmd.extend(["--workspace", str(phase_b_dir)])

        cmd.append(full_prompt)

        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                start_new_session=True,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "Cursor CLI not found. Install via: curl https://cursor.com/install -fsS | bash"
            )

        handle_id = str(uuid.uuid4())
        self._processes[handle_id] = _ProcessState(process, str(review_file), json_file)

        register_pid(
            process.pid,
            instance_id=context.get("instance_id"),
            step_id=context.get("step_id"),
            agent_name=self.name,
            domain=context.get("domain"),
        )

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

    def cleanup(self, handle: AgentHandle) -> None:
        """Remove process state and close pipes to prevent FD leaks."""
        state = self._processes.pop(handle.handle_id, None)
        if state is None:
            return
        unregister_pid(state.process.pid)
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

        # If files not at expected path, search workspace and phase-b dirs
        if not review_path.exists() or not json_path.exists():
            base_name = review_path.name
            json_name = Path(state.json_file).name
            search_dirs = [
                review_path.parent,
                Path(get_reviews_dir()) / "phase-b",
                Path.cwd(),
            ]
            for d in search_dirs:
                if not d.exists():
                    continue
                for found in d.rglob(base_name):
                    review_path = found
                    break
                for found in d.rglob(json_name):
                    json_path = found
                    break
                if review_path.exists():
                    break

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
                    logger.warning(f"JSON validation failed for {json_path}: {errs[:3]}")
            except Exception as e:
                logger.warning(f"Could not parse JSON review: {e}")

        if review_path.exists():
            try:
                content_md = review_path.read_text(encoding="utf-8")
                if content_json is None:
                    content_json = markdown_to_json(content_md, {})
            except Exception as e:
                logger.warning(f"Could not read markdown review: {e}")

        # Fall back to captured output when no files were written.
        # Prefer full live text over _result_text (which is just a summary).
        if content_md is None:
            live = state.get_live_text()
            content_md = live if live else state.stdout

        score = None
        if content_json and "score" in content_json:
            score = content_json["score"].get("overall")

        usage = None
        with state._lock:
            if state._usage:
                usage = normalize_usage(state._usage)
                if state._cost_usd is not None:
                    usage["cost_usd"] = state._cost_usd
                if state._duration_ms is not None:
                    usage["duration_ms"] = state._duration_ms
                if state._num_turns is not None:
                    usage["num_turns"] = state._num_turns

        return ReviewArtifact(
            content_md=content_md,
            content_json=content_json,
            file_path=state.review_file,
            score=score,
            usage=usage,
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
            import os, signal
            os.killpg(os.getpgid(state.process.pid), signal.SIGTERM)
            state.process.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            try:
                import os, signal
                os.killpg(os.getpgid(state.process.pid), signal.SIGKILL)
            except OSError:
                state.process.kill()
        state.exit_code = -1
        logger.info(f"CursorCLI: cancelled handle {handle.handle_id[:8]}")
        self.cleanup(handle)
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
        task = context.get("task", "")

        # Non-review tasks (expert_generation, synthesis, holistic) — return
        # the user prompt as-is, no file-write instructions.
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
