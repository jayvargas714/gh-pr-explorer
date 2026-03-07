"""Human Gate step — pauses workflow execution for human review and approval."""

import logging

from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)


@register_step("human_gate")
class HumanGateExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        reviews = inputs.get("reviews", [])
        mode = inputs.get("mode", "team-review")

        gate_payload = {
            "mode": mode,
            "reviews": [],
        }

        for review in reviews:
            gate_payload["reviews"].append({
                "pr_number": review.get("pr_number"),
                "status": review.get("status"),
                "score": review.get("score"),
                "agent_name": review.get("agent_name"),
                "has_content": bool(review.get("content_md") or review.get("content_json")),
            })

        return StepResult(
            success=True,
            awaiting_gate=True,
            gate_payload=gate_payload,
        )
