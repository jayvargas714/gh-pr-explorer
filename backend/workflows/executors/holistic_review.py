from __future__ import annotations
"""Holistic Review step — Tier 2 analysis as a principal/staff engineer.

Consolidates per-domain synthesis (from self/deep review) or single-tier
synthesis (team review) into a unified high-level review with cross-domain
interaction analysis, promotion/demotion logic, and final verdict.
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
        mode = inputs.get("mode", "team-review")
        per_domain_synthesis = inputs.get("per_domain_synthesis",
                                          synthesis.get("per_domain_synthesis", []))

        agreed = synthesis.get("agreed", [])
        a_only = synthesis.get("a_only", [])
        b_only = synthesis.get("b_only", [])

        holistic_log: list[dict] = []

        # Per-domain verdict summary (for self/deep review)
        domain_verdicts: list[dict] = []
        if per_domain_synthesis:
            for ds in per_domain_synthesis:
                domain_verdicts.append({
                    "domain": ds.get("domain", "general"),
                    "verdict": ds.get("verdict", "COMMENT"),
                    "finding_count": ds.get("total_findings", 0),
                    "agent_a": ds.get("agent_a", ""),
                    "agent_b": ds.get("agent_b", ""),
                })

        blocking, non_blocking = self._categorize_with_promotion(
            agreed, a_only, b_only, holistic_log
        )

        cross_domain = self._detect_cross_domain(blocking + non_blocking, experts)
        if cross_domain:
            holistic_log.append({
                "type": "cross_domain",
                "detail": f"Detected {len(cross_domain)} cross-domain interactions",
                "interactions": cross_domain,
            })

        overall_verdict, confidence, summary = self._compute_verdict_and_summary(
            blocking, non_blocking, agreed, a_only, b_only,
            domain_verdicts, mode
        )

        domain_coverage = [e.get("domain_id", e.get("domain", "general")) for e in experts]

        holistic = {
            "verdict": overall_verdict,
            "confidence": confidence,
            "summary": summary,
            "blocking_count": len(blocking),
            "non_blocking_count": len(non_blocking),
            "blocking": blocking,
            "non_blocking": non_blocking,
            "domain_coverage": domain_coverage,
            "domain_verdicts": domain_verdicts,
            "agent_agreement_rate": self._agreement_rate(synthesis),
            "recommendations": self._build_recommendations(blocking, non_blocking, synthesis),
            "cross_domain_interactions": cross_domain,
            "holistic_analysis_log": holistic_log,
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

    def _categorize_with_promotion(self, agreed: list, a_only: list,
                                    b_only: list,
                                    log: list[dict]) -> tuple[list, list]:
        blocking = []
        non_blocking = []

        for f in agreed:
            sev = self._severity(f, "finding_a")
            if sev in ("critical", "major"):
                blocking.append(f)
            else:
                non_blocking.append(f)

        for f in a_only + b_only:
            sev = self._severity(f, "finding")
            if sev == "critical":
                blocking.append(f)
            elif sev == "major":
                non_blocking.append(f)
                log.append({
                    "type": "demotion",
                    "detail": (
                        f"Demoted from blocking — single-agent major finding: "
                        f"{self._finding_title(f, 'finding')}"
                    ),
                })
            else:
                non_blocking.append(f)

        high_agreement_non_blocking = []
        for f in list(non_blocking):
            if f.get("source") == "BOTH" and self._severity(f, "finding_a") == "minor":
                inner = f.get("finding_a", {})
                problem = inner.get("problem", "")
                if len(problem) > 100:
                    non_blocking.remove(f)
                    f["_promoted"] = True
                    blocking.append(f)
                    log.append({
                        "type": "promotion",
                        "detail": (
                            f"Promoted from non-blocking — both agents agree and "
                            f"detailed evidence provided: {inner.get('title', '')}"
                        ),
                    })

        return blocking, non_blocking

    @staticmethod
    def _detect_cross_domain(findings: list, experts: list) -> list[dict]:
        if not experts or len(experts) < 2:
            return []

        domain_ids = {e.get("domain_id", e.get("domain", "")) for e in experts}
        interactions = []

        files_by_domain: dict[str, set[str]] = {}
        for e in experts:
            did = e.get("domain_id", e.get("domain", ""))
            files_by_domain[did] = set(e.get("matched_files", []))

        for f in findings:
            inner = f.get("finding_a", f.get("finding", {}))
            loc = inner.get("location", {})
            fpath = loc.get("file", loc.get("raw", ""))
            if not fpath:
                continue
            touching_domains = [d for d, files in files_by_domain.items() if fpath in files]
            if len(touching_domains) >= 2:
                interactions.append({
                    "file": fpath,
                    "domains": touching_domains,
                    "finding_title": inner.get("title", ""),
                })

        return interactions

    def _compute_verdict_and_summary(self, blocking, non_blocking,
                                      agreed, a_only, b_only,
                                      domain_verdicts, mode):
        if blocking:
            critical_count = sum(
                1 for f in blocking
                if self._severity(f, "finding_a") == "critical"
                or self._severity(f, "finding") == "critical"
            )
            if critical_count > 0:
                return (
                    "CHANGES_REQUESTED", "high",
                    f"{critical_count} critical blocking issue(s) identified. Must be addressed before merge."
                )
            return (
                "CHANGES_REQUESTED", "high" if any(f.get("source") == "BOTH" for f in blocking) else "medium",
                f"{len(blocking)} blocking issue(s) identified. Review and address before merge."
            )

        if domain_verdicts:
            domain_cr = [d for d in domain_verdicts if d["verdict"] == "CHANGES_REQUESTED"]
            domain_nd = [d for d in domain_verdicts if d["verdict"] == "NEEDS_DISCUSSION"]
            if domain_cr:
                domains_str = ", ".join(d["domain"] for d in domain_cr)
                return (
                    "CHANGES_REQUESTED", "medium",
                    f"Domain expert(s) ({domains_str}) request changes."
                )
            if domain_nd:
                domains_str = ", ".join(d["domain"] for d in domain_nd)
                return (
                    "NEEDS_DISCUSSION", "medium",
                    f"Domain expert(s) ({domains_str}) flagged items needing team discussion."
                )

        disputed_count = len(a_only) + len(b_only)
        total = disputed_count + len(agreed)
        if total > 0 and disputed_count / total > 0.5:
            return (
                "NEEDS_DISCUSSION", "medium",
                f"Agents disagree on {disputed_count} of {total} finding(s). Team discussion recommended."
            )

        if a_only or b_only:
            return (
                "COMMENT", "medium",
                f"Agents found {total} issue(s) with some disagreement. Review disputed items."
            )

        if agreed:
            return (
                "COMMENT", "high",
                f"Both agents agree on {len(agreed)} finding(s). Consider addressing before merge."
            )

        return ("APPROVE", "high", "No significant issues found by either agent.")

    @staticmethod
    def _severity(finding: dict, key: str) -> str:
        f = finding.get(key, {})
        return f.get("severity", "minor") if isinstance(f, dict) else "minor"

    @staticmethod
    def _finding_title(finding: dict, key: str) -> str:
        f = finding.get(key, {})
        return f.get("title", "unknown") if isinstance(f, dict) else "unknown"

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
