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
        gate_type = self.step_config.get("gate_type", "default")

        if gate_type == "prompt_review":
            return self._execute_prompt_gate(inputs)

        return self._execute_review_gate(inputs)

    def _execute_prompt_gate(self, inputs: dict) -> StepResult:
        experts = inputs.get("experts", [])
        prompts = inputs.get("prompts", [])
        prs = inputs.get("prs", [])

        expert_source = "unknown"
        for e in experts:
            if e.get("relevance_pct", 0) == 100.0 and not e.get("matched_files"):
                expert_source = "ai_generated"
                break
            if e.get("matched_files"):
                expert_source = "static_match"
                break

        unique_domains = sorted({p.get("domain", "") for p in prompts if p.get("domain")})

        gate_id = self.step_config.get("_step_id", "")
        fb_history, iteration = self._feedback_context(inputs, gate_id)

        gate_payload = {
            "type": "prompt_review",
            "prompts": prompts,
            "experts": experts,
            "mode": inputs.get("mode", ""),
            "pr_count": len(prs),
            "expert_source": expert_source,
            "domain_count": len(unique_domains),
            "domains_list": unique_domains,
            "prompts_per_pr": len(prompts) // max(len(prs), 1),
            "feedback_history": fb_history,
            "iteration": iteration,
        }

        return StepResult(
            success=True,
            awaiting_gate=True,
            gate_payload=gate_payload,
        )

    def _execute_review_gate(self, inputs: dict) -> StepResult:
        reviews = inputs.get("reviews", [])
        mode = inputs.get("mode", "team-review")
        synthesis = inputs.get("synthesis", {})
        freshness = inputs.get("freshness", [])

        gate_id = self.step_config.get("_step_id", "")
        fb_history, iteration = self._feedback_context(inputs, gate_id)

        gate_payload = {
            "type": "review_gate",
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
            "related_scan": inputs.get("related_scan", {}),
            "fp_check": inputs.get("fp_check", {}),
            "questions": synthesis.get("questions",
                                       self._aggregate_questions(reviews)),
            "checklist_completion": self._aggregate_checklists(reviews),
            "finding_staleness": self._extract_staleness(freshness),
        }

        gate_payload["feedback_history"] = fb_history
        gate_payload["iteration"] = iteration

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
    def _feedback_context(inputs: dict, gate_id: str) -> tuple[list[dict], int]:
        """Extract feedback history relevant to this gate and compute iteration."""
        all_fb = inputs.get("human_feedback", [])
        relevant = [f for f in all_fb if f.get("gate_step_id") == gate_id]
        return relevant, len(relevant) + 1

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
