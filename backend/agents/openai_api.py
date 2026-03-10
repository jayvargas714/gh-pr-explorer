"""OpenAI API agent backend — uses chat completions for review generation."""

import json
import logging
import os
import threading
import uuid
from typing import Optional

from backend.agents.base import AgentBackend, AgentHandle, AgentStatus, ReviewArtifact

logger = logging.getLogger(__name__)


class _CompletionState:
    """Tracks an in-flight OpenAI completion."""
    def __init__(self):
        self.status: AgentStatus = AgentStatus.RUNNING
        self.result: Optional[str] = None
        self.error: Optional[str] = None
        self.content_json: Optional[dict] = None
        self.usage: Optional[dict] = None


class OpenAIAgent(AgentBackend):
    """Runs reviews via the OpenAI chat completions API."""

    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self._completions: dict[str, _CompletionState] = {}
        self.model = config.get("model", "gpt-4o")
        api_key_env = config.get("api_key_env", "OPENAI_API_KEY")
        self.api_key = os.environ.get(api_key_env)

    def start_review(self, prompt: str, context: dict) -> AgentHandle:
        if not self.api_key:
            raise RuntimeError(
                f"OpenAI API key not found. Set {self.config.get('api_key_env', 'OPENAI_API_KEY')} env var."
            )

        handle_id = str(uuid.uuid4())
        state = _CompletionState()
        self._completions[handle_id] = state

        thread = threading.Thread(
            target=self._run_completion,
            args=(handle_id, prompt, context),
            daemon=True,
        )
        thread.start()

        pr_number = context.get("pr_number", 0)
        logger.info(f"OpenAI: started review for PR #{pr_number} (handle={handle_id[:8]}, model={self.model})")

        return AgentHandle(
            agent_name=self.name,
            handle_id=handle_id,
            metadata={"model": self.model},
        )

    def check_status(self, handle: AgentHandle) -> AgentStatus:
        state = self._completions.get(handle.handle_id)
        if state is None:
            return AgentStatus.FAILED
        return state.status

    def get_output(self, handle: AgentHandle) -> ReviewArtifact:
        state = self._completions.get(handle.handle_id)
        if state is None:
            return ReviewArtifact(error="Unknown handle")
        if state.error:
            return ReviewArtifact(error=state.error)
        return ReviewArtifact(
            content_md=state.result,
            content_json=state.content_json,
            score=state.content_json.get("score", {}).get("overall") if state.content_json else None,
            usage=state.usage,
        )

    def cancel(self, handle: AgentHandle) -> bool:
        state = self._completions.get(handle.handle_id)
        if state and state.status == AgentStatus.RUNNING:
            state.status = AgentStatus.CANCELLED
            return True
        return False

    def _run_completion(self, handle_id: str, prompt: str, context: dict):
        state = self._completions[handle_id]
        try:
            import httpx

            pr_url = context.get("pr_url", "")
            pr_number = context.get("pr_number", 0)
            diff_content = context.get("diff_content", "")

            system_msg = (
                "You are an elite code reviewer. Produce a thorough, structured code review. "
                "Output your review in markdown with these sections: "
                "Summary, Critical Issues, Major Concerns, Minor Issues, Highlights, Recommendations, Score (0-10). "
                "Each issue must include: title, location (file:line), problem description, and suggested fix."
            )

            user_msg = prompt
            if diff_content:
                user_msg += f"\n\n--- PR DIFF ---\n{diff_content[:50000]}\n--- END DIFF ---"

            if state.status == AgentStatus.CANCELLED:
                return

            response = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg},
                    ],
                    "max_tokens": 8000,
                    "temperature": 0.3,
                },
                timeout=300,
            )

            if state.status == AgentStatus.CANCELLED:
                return

            if response.status_code != 200:
                state.error = f"OpenAI API error {response.status_code}: {response.text[:500]}"
                state.status = AgentStatus.FAILED
                return

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            state.result = content

            api_usage = data.get("usage")
            if api_usage:
                state.usage = {
                    "input_tokens": api_usage.get("prompt_tokens", 0),
                    "output_tokens": api_usage.get("completion_tokens", 0),
                }

            state.status = AgentStatus.COMPLETED

            logger.info(f"OpenAI: completed review for handle {handle_id[:8]}")

        except Exception as e:
            logger.error(f"OpenAI completion failed: {e}")
            state.error = str(e)
            state.status = AgentStatus.FAILED
