from __future__ import annotations
"""Human Gate step — pauses workflow execution for human review and approval.

Enriches the gate payload with synthesis log, questions, checklist completion,
per-domain synthesis, holistic review, and finding staleness for the GateView UI.
"""

import logging
import re

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
            "synthesis_log": synthesis.get("synthesis_log",
                                           inputs.get("synthesis_log", [])),
            "per_domain_synthesis": inputs.get("per_domain_synthesis",
                                               synthesis.get("per_domain_synthesis", [])),
            "holistic": inputs.get("holistic", {}),
            "questions": synthesis.get("questions",
                                       self._aggregate_questions(reviews)),
            "checklist_completion": self._aggregate_checklists(reviews),
            "finding_staleness": self._extract_staleness(freshness),
        }

        # Also pass through follow-up results if this is a follow-up gate
        followup_results = inputs.get("followup_results")
        if followup_results is not None:
            gate_payload["followup_results"] = followup_results

        for review in reviews:
            gate_payload["reviews"].append({
                "pr_number": review.get("pr_number"),
                "status": review.get("status"),
                "score": review.get("score"),
                "agent_name": review.get("agent_name"),
                "domain": review.get("domain"),
                "content_md": review.get("content_md"),
                "content_json": review.get("content_json"),
                "file_path": review.get("file_path"),
            })

        return StepResult(
            success=True,
            awaiting_gate=True,
            gate_payload=gate_payload,
        )

    @staticmethod
    def _aggregate_questions(reviews: list) -> list[str]:
        questions = []
        for r in reviews:
            md = r.get("content_md", "")
            if not md:
                continue
            in_section = False
            for line in md.split("\n"):
                stripped = line.strip()
                if stripped.startswith("## Questions"):
                    in_section = True
                    continue
                if in_section:
                    if stripped.startswith("## "):
                        break
                    q_match = re.match(r"^\d+\.\s+(.+)", stripped)
                    if q_match:
                        questions.append(q_match.group(1).strip())
                    elif stripped.startswith("- "):
                        questions.append(stripped[2:].strip())
        return list(dict.fromkeys(questions))

    @staticmethod
    def _aggregate_checklists(reviews: list) -> list[dict]:
        checklists = []
        for r in reviews:
            md = r.get("content_md", "")
            if not md:
                continue
            in_section = False
            items = []
            for line in md.split("\n"):
                stripped = line.strip()
                if stripped.startswith("## Checklist"):
                    in_section = True
                    continue
                if in_section:
                    if stripped.startswith("## "):
                        break
                    if stripped.startswith("- "):
                        items.append(stripped[2:].strip())
            if items:
                checklists.append({
                    "agent": r.get("agent_name", "unknown"),
                    "domain": r.get("domain"),
                    "items": items,
                })
        return checklists

    @staticmethod
    def _extract_staleness(freshness: list) -> list[dict]:
        staleness = []
        for f in freshness:
            if f.get("classification", "CURRENT") != "CURRENT":
                staleness.append({
                    "pr_number": f.get("pr_number"),
                    "classification": f.get("classification"),
                    "affected": f.get("affected_findings", []),
                    "unaffected": f.get("unaffected_findings", []),
                    "recommendation": f.get("recommendation", ""),
                })
        return staleness
