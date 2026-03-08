"""Holistic Review step — produces a unified high-level review from synthesis results.

Consolidates per-agent synthesis into a single coherent review with
cross-cutting concerns, overall assessment, and final recommendations.
"""

import logging

from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)


@register_step("holistic_review")
class HolisticReviewExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        synthesis = inputs.get("synthesis", {})
        reviews = inputs.get("reviews", [])
        experts = inputs.get("experts", [])

        agreed = synthesis.get("agreed", [])
        a_only = synthesis.get("a_only", [])
        b_only = synthesis.get("b_only", [])

        critical_agreed = [f for f in agreed if self._severity(f, "finding_a") == "critical"]
        major_agreed = [f for f in agreed if self._severity(f, "finding_a") == "major"]
        minor_agreed = [f for f in agreed if self._severity(f, "finding_a") == "minor"]

        critical_disputed = (
            [f for f in a_only if self._severity(f, "finding") == "critical"] +
            [f for f in b_only if self._severity(f, "finding") == "critical"]
        )
        major_disputed = (
            [f for f in a_only if self._severity(f, "finding") == "major"] +
            [f for f in b_only if self._severity(f, "finding") == "major"]
        )

        blocking = critical_agreed + critical_disputed + major_agreed
        non_blocking = minor_agreed + major_disputed

        if critical_agreed:
            overall_verdict = "CHANGES_REQUESTED"
            confidence = "high"
            summary = (
                f"Both agents agree on {len(critical_agreed)} critical issue(s). "
                "These must be addressed before merge."
            )
        elif critical_disputed:
            overall_verdict = "CHANGES_REQUESTED"
            confidence = "medium"
            summary = (
                f"One agent flagged {len(critical_disputed)} critical issue(s) "
                "that the other did not find. Manual verification recommended."
            )
        elif major_agreed:
            overall_verdict = "COMMENT"
            confidence = "high"
            summary = (
                f"Both agents agree on {len(major_agreed)} major issue(s). "
                "Consider addressing before merge."
            )
        elif a_only or b_only:
            overall_verdict = "COMMENT"
            confidence = "medium"
            summary = (
                f"Agents disagree on {len(a_only) + len(b_only)} finding(s). "
                "Review disputed items for relevance."
            )
        else:
            overall_verdict = "APPROVE"
            confidence = "high"
            summary = "No significant issues found by either agent."

        domain_coverage = [e.get("domain", "general") for e in experts] if experts else []

        holistic = {
            "verdict": overall_verdict,
            "confidence": confidence,
            "summary": summary,
            "blocking_count": len(blocking),
            "non_blocking_count": len(non_blocking),
            "blocking": blocking,
            "non_blocking": non_blocking,
            "domain_coverage": domain_coverage,
            "agent_agreement_rate": self._agreement_rate(synthesis),
            "recommendations": self._build_recommendations(blocking, non_blocking, synthesis),
        }

        return StepResult(
            success=True,
            outputs={
                "holistic": holistic,
                "synthesis": synthesis,
                "reviews": reviews,
            },
            artifacts=[{
                "type": "holistic_review",
                "pr_number": synthesis.get("pr_number"),
                "data": holistic,
            }],
        )

    @staticmethod
    def _severity(finding: dict, key: str) -> str:
        f = finding.get(key, {})
        return f.get("severity", "minor") if isinstance(f, dict) else "minor"

    @staticmethod
    def _agreement_rate(synthesis: dict) -> float:
        agreed = len(synthesis.get("agreed", []))
        total = synthesis.get("total_findings", 0)
        return round((agreed / total) * 100, 1) if total > 0 else 100.0

    @staticmethod
    def _build_recommendations(blocking: list, non_blocking: list, synthesis: dict) -> list[dict]:
        recs = []

        for f in blocking:
            inner = f.get("finding_a", f.get("finding", {}))
            recs.append({
                "priority": "must_fix",
                "text": inner.get("title", "Address blocking issue"),
                "severity": inner.get("severity", "critical"),
            })

        for f in non_blocking[:5]:
            inner = f.get("finding_a", f.get("finding", {}))
            recs.append({
                "priority": "medium",
                "text": inner.get("title", "Consider addressing"),
                "severity": inner.get("severity", "minor"),
            })

        return recs
