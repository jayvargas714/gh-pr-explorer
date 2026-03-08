"""Agent Review step — dispatches prompts to a configured AI agent and collects results."""

import logging
import threading
import time

from backend.agents import get_agent, AgentStatus
from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 5

_live_output_store: dict[str, str] = {}
_live_output_lock = threading.Lock()


def get_agent_live_output(instance_id: int, step_id: str) -> str:
    """Retrieve live agent output for a running step (called from the API layer)."""
    key = f"{instance_id}:{step_id}"
    with _live_output_lock:
        return _live_output_store.get(key, "")


def _set_live_output(instance_id: int, step_id: str, text: str):
    key = f"{instance_id}:{step_id}"
    with _live_output_lock:
        _live_output_store[key] = text


def _clear_live_output(instance_id: int, step_id: str):
    key = f"{instance_id}:{step_id}"
    with _live_output_lock:
        _live_output_store.pop(key, None)


@register_step("agent_review")
class AgentReviewExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        agent_name = self.step_config.get("agent", "claude")
        prompts = inputs.get("prompts", [])
        inst_id = self.instance_config.get("_instance_id", 0)
        step_id = self.step_config.get("_step_id", "")

        if not prompts:
            return StepResult(success=False, error="No prompts provided to agent_review step")

        try:
            agent = get_agent(agent_name)
        except Exception as e:
            return StepResult(success=False, error=f"Failed to get agent '{agent_name}': {e}")

        reviews = []
        for prompt_data in prompts:
            pr_number = prompt_data.get("pr_number")
            prompt_text = prompt_data.get("prompt", "")
            context = {
                "pr_url": prompt_data.get("pr_url", ""),
                "pr_number": pr_number,
                "pr_title": prompt_data.get("pr_title", ""),
                "pr_author": prompt_data.get("pr_author", ""),
                "owner": prompt_data.get("owner", ""),
                "repo": prompt_data.get("repo", ""),
            }

            try:
                handle = agent.start_review(prompt_text, context)
            except Exception as e:
                logger.error(f"Failed to start review for PR #{pr_number}: {e}")
                reviews.append({
                    "pr_number": pr_number,
                    "status": "failed",
                    "error": str(e),
                })
                continue

            while True:
                status = agent.check_status(handle)
                if status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED):
                    break
                if inst_id and step_id:
                    live = agent.get_live_output(handle)
                    if live:
                        _set_live_output(inst_id, step_id, live)
                time.sleep(_POLL_INTERVAL)

            if status == AgentStatus.COMPLETED:
                artifact = agent.get_output(handle)
                reviews.append({
                    "pr_number": pr_number,
                    "status": "completed",
                    "agent_name": agent_name,
                    "content_md": artifact.content_md,
                    "content_json": artifact.content_json,
                    "file_path": artifact.file_path,
                    "score": artifact.score,
                    "head_sha": prompt_data.get("head_sha", ""),
                })
            else:
                artifact = agent.get_output(handle)
                reviews.append({
                    "pr_number": pr_number,
                    "status": "failed",
                    "agent_name": agent_name,
                    "error": artifact.error,
                })

        if inst_id and step_id:
            _clear_live_output(inst_id, step_id)

        completed_reviews = [r for r in reviews if r["status"] == "completed"]
        failed_reviews = [r for r in reviews if r["status"] == "failed"]

        if not completed_reviews and failed_reviews:
            errors = "; ".join(
                f'PR #{r["pr_number"]}: {r.get("error", "unknown")}'
                for r in failed_reviews
            )
            return StepResult(
                success=False,
                error=f"All reviews failed ({agent_name}): {errors}",
                outputs={"reviews": reviews, "agent_name": agent_name},
            )

        return StepResult(
            success=True,
            outputs={
                "reviews": reviews,
                "agent_name": agent_name,
            },
            artifacts=[
                {"type": "review", "pr_number": r["pr_number"], "data": r}
                for r in completed_reviews
            ],
        )
