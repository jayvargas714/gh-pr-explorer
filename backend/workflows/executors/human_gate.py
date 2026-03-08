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
        synthesis = inputs.get("synthesis", {})
        freshness = inputs.get("freshness", [])

        gate_payload = {
            "mode": mode,
            "reviews": [],
            "synthesis": synthesis,
            "freshness": freshness,
            "all_fresh": inputs.get("all_fresh", True),
            "any_stale_major": inputs.get("any_stale_major", False),
        }

        for review in reviews:
            gate_payload["reviews"].append({
                "pr_number": review.get("pr_number"),
                "status": review.get("status"),
                "score": review.get("score"),
                "agent_name": review.get("agent_name"),
                "content_md": review.get("content_md"),
                "content_json": review.get("content_json"),
                "file_path": review.get("file_path"),
            })

        return StepResult(
            success=True,
            awaiting_gate=True,
            gate_payload=gate_payload,
        )
