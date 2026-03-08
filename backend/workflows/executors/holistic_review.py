from __future__ import annotations
"""Holistic Review step — Tier 2 analysis as a principal/staff engineer.

Consolidates per-domain synthesis (from self/deep review) or single-tier
synthesis (team review) into a unified high-level review with cross-domain
interaction analysis, promotion/demotion logic, and final verdict.

Uses an AI agent for holistic analysis, with a heuristic fallback if the
agent is unavailable or fails.
"""

import json
import logging
import re
import time

from backend.agents import get_agent, AgentStatus
from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.executors.agent_review import _set_live_output, _clear_live_output
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)


@register_step("holistic_review")
class HolisticReviewExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        synthesis = inputs.get("synthesis", {})
        reviews = inputs.get("reviews", [])
        experts = inputs.get("experts", [])
        prs = inputs.get("prs", [])
        owner = inputs.get("owner", "")
        repo = inputs.get("repo", "")
        mode = inputs.get("mode", "")
        inst_id = self.instance_config.get("_instance_id", 0)
        step_id = self.step_config.get("_step_id", "")

        prompt = self._build_holistic_prompt(synthesis, reviews, experts, prs, owner, repo)

        agent_name = self.step_config.get("agent", "cursor-opus")
        try:
            agent = get_agent(agent_name)
        except Exception as e:
            logger.warning(f"AI holistic review failed to get agent: {e}, falling back to heuristic")
            return self._heuristic_holistic(synthesis, reviews, experts)

        context = {
            "pr_number": prs[0].get("number") if prs else 0,
            "owner": owner,
            "repo": repo,
            "phase": "holistic",
            "task": "holistic",
        }

        try:
            handle = agent.start_review(prompt, context)
            while True:
                status = agent.check_status(handle)
                if status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED):
                    break
                live = agent.get_live_output(handle)
                if live and inst_id and step_id:
                    _set_live_output(inst_id, step_id, live)
                time.sleep(5)

            if inst_id and step_id:
                _clear_live_output(inst_id, step_id)

            if status == AgentStatus.COMPLETED:
                artifact = agent.get_output(handle)
                holistic = self._parse_holistic_output(artifact.content_md, synthesis)
                return StepResult(
                    success=True,
                    outputs={"holistic": holistic},
                )
            else:
                logger.warning("AI holistic review failed, falling back to heuristic")
                return self._heuristic_holistic(synthesis, reviews, experts)
        except Exception as e:
            logger.error(f"AI holistic review error: {e}")
            if inst_id and step_id:
                _clear_live_output(inst_id, step_id)
            return self._heuristic_holistic(synthesis, reviews, experts)

    # ------------------------------------------------------------------
    # Heuristic fallback (original mechanical promotion/demotion logic)
    # ------------------------------------------------------------------

    def _heuristic_holistic(self, synthesis: dict, reviews: list,
                            experts: list) -> StepResult:
        per_domain_synthesis = synthesis.get("per_domain_synthesis", [])

        agreed = synthesis.get("agreed", [])
        a_only = synthesis.get("a_only", [])
        b_only = synthesis.get("b_only", [])

        holistic_log: list[dict] = []

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
            domain_verdicts, synthesis.get("mode", "team-review")
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
            outputs={"holistic": holistic},
            artifacts=[{
                "type": "holistic_review",
                "pr_number": synthesis.get("pr_number"),
                "data": holistic,
            }],
        )

    # ------------------------------------------------------------------
    # AI prompt construction
    # ------------------------------------------------------------------

    def _build_holistic_prompt(self, synthesis: dict, reviews: list,
                               experts: list, prs: list,
                               owner: str, repo: str) -> str:
        sections = []

        sections.append(
            "You are a principal engineer with 15+ years of experience performing a HOLISTIC REVIEW.\n"
            "You have read all per-domain synthesis results. Your job is cross-domain analysis:\n"
            "finding interactions, contradictions, and gaps that domain experts missed."
        )

        for pr in prs:
            pr_num = pr.get("number")
            if pr_num:
                sections.append(
                    f"## Context for PR #{pr_num}\n"
                    f"- `gh pr diff {pr_num}` — full diff\n"
                    f"- `gh api repos/{owner}/{repo}/pulls/{pr_num}/reviews --paginate` — reviews\n"
                )

        if experts:
            sections.append("## Expert Domains Analyzed")
            for e in experts:
                name = e.get("display_name", e.get("domain_id", "unknown"))
                scope = e.get("scope", "")
                sections.append(f"- **{name}**: {scope}")

        cross_cutting = synthesis.get("cross_cutting_flags", [])
        if cross_cutting:
            sections.append("## Cross-Cutting Flags (Deferred from Tier 1)")
            sections.append("You MUST process every cross-cutting flag. Assign each to the correct domain's findings or elevate as a new holistic finding:")
            for flag in cross_cutting:
                sections.append(f"- {flag}")

        per_domain = synthesis.get("per_domain_synthesis", {})
        if per_domain:
            sections.append("## Per-Domain Synthesis Results")
            for domain, domain_synth in (per_domain.items() if isinstance(per_domain, dict) else
                                         ((d.get("domain", "unknown"), d) for d in per_domain)):
                sections.append(f"### Domain: {domain}")
                verdict = domain_synth.get("verdict", "unknown")
                sections.append(f"Verdict: {verdict}")
                for cat in ("agreed", "a_only", "b_only"):
                    findings = domain_synth.get(cat, [])
                    if findings:
                        sections.append(f"  {cat.upper()}: {len(findings)} findings")
                        for f in findings[:5]:
                            inner = f.get("finding_a", f.get("finding_b", f.get("finding", {})))
                            title = inner.get("title", "untitled")
                            sev = inner.get("severity", "?")
                            sections.append(f"  - [{sev}] {title}")
        else:
            sections.append("## Synthesis Results")
            for cat in ("agreed", "a_only", "b_only"):
                findings = synthesis.get(cat, [])
                if findings:
                    sections.append(f"### {cat.upper()} ({len(findings)} findings)")
                    for f in findings[:10]:
                        inner = f.get("finding_a", f.get("finding_b", f.get("finding", {})))
                        title = inner.get("title", "untitled")
                        sev = inner.get("severity", "?")
                        sections.append(f"- [{sev}] {title}")

        synth_findings = synthesis.get("synth_findings", [])
        if synth_findings:
            sections.append("## SYNTH Findings (from Tier 1)")
            for f in synth_findings:
                sections.append(f"- [{f.get('severity', '?')}] {f.get('title', 'untitled')}: {f.get('description', '')[:200]}")

        sections.append(
            "\n## Your Task\n\n"
            "1. **Cross-domain interaction analysis**: Identify where changes in one domain affect another\n"
            "2. **Contradiction resolution**: Flag where domain experts disagree and determine the correct interpretation\n"
            "3. **Severity calibration**: Adjust severities considering the holistic impact\n"
            "4. **Gap detection**: Find issues that fall between domain boundaries\n"
            "5. **Process ALL cross-cutting flags**: Assign each to a domain or elevate as a holistic finding\n"
            "6. **Final verdict**: APPROVE, REQUEST_CHANGES, or COMMENT\n\n"
            "## Output Format\n\n"
            "Output valid JSON only:\n"
            "{\n"
            '  "verdict": "APPROVE|REQUEST_CHANGES|COMMENT",\n'
            '  "blocking_findings": [{"title": "...", "severity": "critical|major", "domain": "...", "description": "...", "evidence": "..."}],\n'
            '  "non_blocking_findings": [{"title": "...", "severity": "minor|suggestion", "domain": "...", "description": "..."}],\n'
            '  "cross_cutting_findings": [{"title": "...", "domains": ["...", "..."], "description": "...", "origin": "flag|new"}],\n'
            '  "domain_verdicts": [{"domain": "...", "verdict": "...", "finding_count": 0}],\n'
            '  "domain_coverage": ["domain-1", "domain-2"],\n'
            '  "cross_domain_interactions": [{"files": ["..."], "domains": ["..."], "description": "..."}],\n'
            '  "holistic_analysis_log": [{"action": "PROMOTED|DEMOTED|CONFIRMED", "finding": "...", "reasoning": "..."}],\n'
            '  "summary": "2-3 sentence overall assessment"\n'
            "}\n"
        )

        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # AI output parsing
    # ------------------------------------------------------------------

    def _parse_holistic_output(self, content: str, synthesis: dict) -> dict:
        """Parse AI holistic review output."""
        json_match = re.search(r'\{[\s\S]*\}', content)
        if not json_match:
            logger.warning("Could not parse AI holistic JSON, falling back")
            return {
                "verdict": synthesis.get("verdict", "COMMENT"),
                "raw_content": content,
                "ai_powered": True,
                "parse_failed": True,
            }

        try:
            parsed = json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError):
            logger.warning("Invalid JSON from AI holistic, falling back")
            return {
                "verdict": synthesis.get("verdict", "COMMENT"),
                "raw_content": content,
                "ai_powered": True,
                "parse_failed": True,
            }

        result = {
            "verdict": parsed.get("verdict", "COMMENT"),
            "blocking_findings": parsed.get("blocking_findings", []),
            "non_blocking_findings": parsed.get("non_blocking_findings", []),
            "cross_cutting_findings": parsed.get("cross_cutting_findings", []),
            "domain_verdicts": parsed.get("domain_verdicts", []),
            "domain_coverage": parsed.get("domain_coverage", []),
            "cross_domain_interactions": parsed.get("cross_domain_interactions", []),
            "holistic_analysis_log": parsed.get("holistic_analysis_log", []),
            "summary": parsed.get("summary", ""),
            "total_blocking": len(parsed.get("blocking_findings", [])),
            "total_non_blocking": len(parsed.get("non_blocking_findings", [])),
            "ai_powered": True,
        }

        return result

    # ------------------------------------------------------------------
    # Shared helpers (used by heuristic fallback)
    # ------------------------------------------------------------------

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
