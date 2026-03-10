from __future__ import annotations
"""False Positive & Severity Check step — validates findings and calibrates severity.

Expert verification stage that traces full code flow and context for each finding.
Three checks per finding:
1. Correctness: does the code actually exhibit the claimed behavior?
2. Intentionality: is the pattern used deliberately? (informed by related_issue_scan)
3. Impact: concrete production failure scenario, or demote

Runs after related_issue_scan, before holistic_review or freshness_check.
Outputs calibrated findings that replace raw synthesis downstream.
"""

import logging
import time

from backend.agents import get_agent, AgentStatus
from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.executors.agent_review import _set_live_output, _clear_live_output
from backend.workflows.json_parser import extract_json
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)


def _recalculate_verdict(synthesis: dict) -> str:
    """Recalculate verdict from remaining findings after FP calibration.

    Uses the same severity-based logic as synthesis._compute_verdict:
    - agreed critical/major → CHANGES_REQUESTED
    - single-agent critical → NEEDS_DISCUSSION
    - any findings remain → COMMENT
    - nothing left → APPROVE
    """
    agreed = synthesis.get("agreed", [])
    a_only = synthesis.get("a_only", [])
    b_only = synthesis.get("b_only", [])

    if any(f.get("finding_a", {}).get("severity") in ("critical", "major")
           for f in agreed):
        return "CHANGES_REQUESTED"

    if any(f.get("finding", {}).get("severity") == "critical"
           for f in a_only + b_only):
        return "NEEDS_DISCUSSION"

    if agreed or a_only or b_only:
        return "COMMENT"

    return "APPROVE"


@register_step("fp_severity_check")
class FPSeverityCheckExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        synthesis = inputs.get("synthesis", {})
        related_scan = inputs.get("related_scan", {})
        owner = inputs.get("owner", "")
        repo = inputs.get("repo", "")
        prs = inputs.get("prs", [])
        inst_id = self.instance_config.get("_instance_id", 0)
        step_id = self.step_config.get("_step_id", "")

        findings = self._collect_findings(synthesis)
        if not findings:
            return StepResult(
                success=True,
                outputs={"fp_check": {"verified_findings": [], "skipped": "no findings"}},
            )

        prompt = self._build_check_prompt(findings, related_scan, owner, repo, prs)

        agent_name = self.step_config.get("agent", "claude-sonnet")
        try:
            agent = get_agent(agent_name)
        except Exception as e:
            logger.warning(f"FP severity check failed to get agent: {e}")
            return self._passthrough(str(e))

        context = {
            "pr_number": prs[0].get("number") if prs else 0,
            "owner": owner,
            "repo": repo,
            "phase": "fp_check",
            "task": "fp_check",
            "instance_id": inst_id,
        }

        from backend.workflows.cancellation import (
            is_cancelled, register_agent, unregister_agent, AGENT_POLL_TIMEOUT,
        )
        try:
            handle = agent.start_review(prompt, context)
            if inst_id:
                register_agent(inst_id, agent, handle)
            elapsed = 0
            try:
                while True:
                    if inst_id and is_cancelled(inst_id):
                        agent.cancel(handle)
                        return self._passthrough("cancelled")
                    status = agent.check_status(handle)
                    if status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED):
                        break
                    if elapsed >= AGENT_POLL_TIMEOUT:
                        logger.error(f"FP severity check timed out after {elapsed}s")
                        agent.cancel(handle)
                        break
                    live = agent.get_live_output(handle)
                    if live and inst_id and step_id:
                        _set_live_output(inst_id, step_id, live)
                    time.sleep(5)
                    elapsed += 5
            finally:
                if inst_id:
                    unregister_agent(inst_id, handle)
                if inst_id and step_id:
                    _clear_live_output(inst_id, step_id)

            if status == AgentStatus.COMPLETED:
                artifact = agent.get_output(handle)
                agent.cleanup(handle)
                check_result = self._parse_check_output(artifact.content_md)
                calibrated_synthesis = self._apply_calibration(synthesis, check_result)
                outputs = {
                    "fp_check": check_result,
                    "synthesis": calibrated_synthesis,
                }
                if artifact.usage:
                    outputs["usage"] = artifact.usage
                return StepResult(
                    success=True,
                    outputs=outputs,
                    artifacts=[{
                        "type": "fp_severity_check",
                        "pr_number": prs[0].get("number") if prs else 0,
                        "data": check_result,
                    }],
                )
            else:
                agent.cleanup(handle)
                return self._passthrough(f"agent status: {status.value}")
        except Exception as e:
            logger.error(f"FP severity check error: {e}")
            return self._passthrough(str(e))

    @staticmethod
    def _collect_findings(synthesis: dict) -> list[dict]:
        """Gather all findings with their source category for verification."""
        findings = []
        for entry in synthesis.get("agreed", []):
            inner = entry.get("finding_a", {})
            if inner.get("title"):
                findings.append({**inner, "_source": "BOTH", "_severity_original": inner.get("severity", "minor")})
            for extra in entry.get("additional_failure_modes", []):
                if extra.get("title"):
                    findings.append({**extra, "_source": "BOTH", "_severity_original": extra.get("severity", "minor")})
        for entry in synthesis.get("a_only", []):
            inner = entry.get("finding", {})
            if inner.get("title"):
                findings.append({**inner, "_source": "A_ONLY", "_severity_original": inner.get("severity", "minor")})
        for entry in synthesis.get("b_only", []):
            inner = entry.get("finding", {})
            if inner.get("title"):
                findings.append({**inner, "_source": "B_ONLY", "_severity_original": inner.get("severity", "minor")})
        for sf in synthesis.get("synth_findings", []):
            if sf.get("title"):
                findings.append({**sf, "_source": "SYNTH", "_severity_original": sf.get("severity", "minor")})
        return findings

    def _build_check_prompt(self, findings: list[dict], related_scan: dict,
                            owner: str, repo: str, prs: list) -> str:
        sections = []

        sections.append(
            "You are a senior engineering lead performing FALSE POSITIVE & SEVERITY verification.\n\n"
            "Your job: for each finding from a code review, verify it against the actual code and "
            "determine whether it is real, a false positive, or mis-calibrated in severity.\n\n"
            "Key principles:\n"
            "- **Read the actual code** — never judge a finding from its description alone\n"
            "- **Trace the full execution path** — a function that looks unsafe may be guarded by callers\n"
            "- **Check for upstream invariants** — an 'unchecked unwrap' might be guaranteed safe "
            "by a prior validation step\n"
            "- **Distinguish 'could fail' from 'will fail in production'** — theoretical vs practical\n\n"
            "You are the last line of defense before findings are published. Be rigorous but fair."
        )

        pr_numbers = [p.get("number") for p in prs if p.get("number")]
        base_branch = prs[0].get("base", "main") if prs else "main"
        for pr_num in pr_numbers:
            sections.append(
                "## Context Commands\n\n"
                "```bash\n"
                f"gh pr diff {pr_num} --repo {owner}/{repo}\n"
                f"gh api repos/{owner}/{repo}/pulls/{pr_num}/files --paginate --jq '.[].filename'\n"
                "```\n\n"
                "### Base-Branch Verification Commands\n"
                "Use these to verify 'missing X' claims against the base branch:\n"
                "```bash\n"
                f"# Check if a file/symbol exists on the base branch (before this PR)\n"
                f"gh api repos/{owner}/{repo}/contents/{{FILE_PATH}}?ref={base_branch} --jq '.name' 2>/dev/null\n"
                f"# Search for a symbol/attribute on the base branch\n"
                f"gh api -X GET 'search/code?q={{SEARCH_TERM}}+repo:{owner}/{repo}' --jq '.items[].path'\n"
                f"# View a specific file on the base branch\n"
                f"gh api repos/{owner}/{repo}/contents/{{FILE_PATH}}?ref={base_branch} --jq '.content' | base64 -d\n"
                "```\n"
            )

        sections.append("## Findings to Verify\n")
        for i, f in enumerate(findings, 1):
            title = f.get("title", "Untitled")
            loc = f.get("location", {})
            file_ref = loc.get("file", loc.get("raw", "unknown"))
            line = loc.get("start_line", "?")
            problem = f.get("problem", "")[:400]
            severity = f.get("severity", "unknown")
            source = f.get("_source", "?")
            sections.append(
                f"### Finding {i}: [{severity}] {title}\n"
                f"- Source: {source}\n"
                f"- File: `{file_ref}:{line}`\n"
                f"- Problem: {problem}\n"
            )

        # Include related scan results for context
        scanned = related_scan.get("scanned_findings", [])
        fp_hints = related_scan.get("likely_false_positives", [])
        if scanned or fp_hints:
            sections.append("## Related Issue Scan Results\n")
            if fp_hints:
                sections.append(
                    "**Likely false positives** (pattern is standard in codebase):\n" +
                    "\n".join(f"- {fp}" for fp in fp_hints) + "\n"
                )
            for sf in scanned:
                title = sf.get("title", "")
                count = sf.get("related_count", 0)
                standard = sf.get("pattern_is_standard", False)
                assessment = sf.get("assessment", "")
                tag = " [STANDARD]" if standard else ""
                sections.append(f"- **{title}**{tag}: {count} related instances. {assessment}")
            sections.append("")

        sections.append(
            "## Your Task\n\n"
            "For EACH finding, perform three verification checks:\n\n"
            "### 1. Correctness Check\n"
            "Read the code at the cited location. Does it ACTUALLY exhibit the claimed behavior?\n"
            "- **Read the file** — do not rely on the finding description alone\n"
            "- Trace the execution path: follow callers and callees at least one level\n"
            "- Check whether the problem is real or based on a misreading of the code\n"
            "- Look for upstream guards (validation, type narrowing, early returns) that may "
            "make the 'unsafe' path unreachable\n"
            "- If the file is NEW (not modified in the PR diff), verify the finding isn't "
            "claiming something was 'changed' or 'removed'\n"
            "- Check git blame context: is this code new in the PR or pre-existing?\n\n"
            "#### MANDATORY: Base-Branch Verification for 'Missing X' Claims\n"
            "Before confirming ANY finding that claims something is 'missing', 'not defined', "
            "'not present', or 'removed':\n"
            "1. **Search the base branch** for the allegedly missing item using the commands above\n"
            "2. If a test references a selector/attribute/component not in the diff, "
            "search the base branch — it may already exist in the codebase\n"
            "3. If a finding claims a function/variable/import is 'not defined', grep the "
            "full codebase — it may be defined in a file not touched by the PR\n"
            "4. If a finding claims something was 'removed' or 'deleted', verify the file "
            "existed before the PR and that the removal actually happened in this diff\n"
            "5. Mark as FALSE_POSITIVE any finding where the 'missing' item exists on the "
            "base branch and was not removed by this PR\n\n"
            "**Checklist** (confirm for each 'missing X' finding):\n"
            "- [ ] Confirmed X does not exist on the base branch\n"
            "- [ ] Confirmed X was not imported/defined in a file outside the PR diff\n"
            "- [ ] If X exists elsewhere, verified this PR actually breaks the reference\n\n"
            "### 2. Intentionality Check\n"
            "Is the pattern used deliberately elsewhere in the codebase?\n"
            "- Use the related scan results above as a starting point\n"
            "- Check for comments, docs, ADRs, or design decisions that explain the pattern\n"
            "- A pattern used consistently in 5+ files is likely intentional — but verify "
            "it's the same *structural* pattern, not just the same keyword\n"
            "- Consider language idioms: some patterns that look wrong are standard in the "
            "ecosystem (e.g., `let _ = sender.send()` in Rust is idiomatic for fire-and-forget)\n\n"
            "### 3. Impact Assessment\n"
            "If this IS a real bug, what is the concrete production impact?\n"
            "- Describe a **specific, realistic scenario** where this causes user-visible harm\n"
            "- 'An attacker could...' requires: the input actually reaches this code path "
            "from an external boundary\n"
            "- 'This could panic' requires: the panic isn't caught by a framework handler\n"
            "- If you cannot describe a realistic scenario, demote severity\n"
            "- 'Best practice violation' without production impact = minor at most\n"
            "- Style/naming issues = nitpick, not minor\n\n"
            "## Communication Standards\n\n"
            "- Be objective — cite code evidence for every judgment\n"
            "- Frame demotions constructively: 'This is a valid observation but the impact is limited because...'\n"
            "- Never use accusatory language about the original reviewers\n\n"
            "## Output Format — valid JSON only:\n"
            "```json\n"
            "{\n"
            '  "verified_findings": [\n'
            '    {\n'
            '      "title": "...",\n'
            '      "original_severity": "critical",\n'
            '      "calibrated_severity": "major",\n'
            '      "fp_status": "CONFIRMED|FALSE_POSITIVE|DOWNGRADED|UNCERTAIN",\n'
            '      "correctness_check": "The code at line 123 does/does not...",\n'
            '      "base_branch_verified": true,\n'
            '      "base_branch_note": "Checked base branch: X exists/does not exist at ...",\n'
            '      "intentionality_check": "Pattern found in N other files...",\n'
            '      "impact_assessment": "Production scenario: ... / No production impact because...",\n'
            '      "evidence": "code snippet or reference"\n'
            '    }\n'
            '  ],\n'
            '  "false_positives_removed": [\n'
            '    {"title": "...", "reason": "..."}\n'
            '  ],\n'
            '  "severity_changes": [\n'
            '    {"title": "...", "from": "critical", "to": "major", "reason": "..."}\n'
            '  ],\n'
            '  "final_counts": {"blocking": 0, "non_blocking": 0, "removed": 0}\n'
            "}\n"
            "```\n"
        )

        return "\n\n".join(sections)

    def _parse_check_output(self, content: str) -> dict:
        """Parse AI FP/severity check output."""
        if not content:
            return {"verified_findings": [], "parse_failed": True}

        parsed = extract_json(content)
        if parsed is None:
            return {"verified_findings": [], "raw_content": content, "parse_failed": True}

        # Normalize common AI key variations
        parsed = self._normalize_keys(parsed)

        expected_keys = {"verified_findings", "false_positives_removed", "severity_changes", "final_counts"}
        if not expected_keys.intersection(parsed.keys()):
            logger.warning(f"FP check: parsed JSON has no expected keys. Got: {list(parsed.keys())[:10]}")
            return {
                "verified_findings": [],
                "raw_content": content,
                "parse_failed": True,
                "actual_keys": list(parsed.keys()),
            }

        return {
            "verified_findings": parsed.get("verified_findings", []),
            "false_positives_removed": parsed.get("false_positives_removed", []),
            "severity_changes": parsed.get("severity_changes", []),
            "final_counts": parsed.get("final_counts", {}),
            "total_verified": len(parsed.get("verified_findings", [])),
            "fp_removed_count": len(parsed.get("false_positives_removed", [])),
            "severity_changed_count": len(parsed.get("severity_changes", [])),
        }

    @staticmethod
    def _normalize_keys(parsed: dict) -> dict:
        """Map common AI key variations to expected schema keys."""
        key_aliases = {
            "findings": "verified_findings",
            "verified": "verified_findings",
            "results": "verified_findings",
            "verification_results": "verified_findings",
            "false_positives": "false_positives_removed",
            "fp_removed": "false_positives_removed",
            "removed_findings": "false_positives_removed",
            "severity_adjustments": "severity_changes",
            "calibrations": "severity_changes",
            "counts": "final_counts",
            "summary_counts": "final_counts",
        }
        normalized = dict(parsed)
        for alias, canonical in key_aliases.items():
            if alias in normalized and canonical not in normalized:
                normalized[canonical] = normalized.pop(alias)
        return normalized

    @staticmethod
    def _apply_calibration(synthesis: dict, check_result: dict) -> dict:
        """Apply FP/severity calibration to synthesis, preserving originals for audit."""
        fp_titles = {fp.get("title", "").lower()
                     for fp in check_result.get("false_positives_removed", [])}
        sev_map = {
            sc.get("title", "").lower(): sc.get("to", "minor")
            for sc in check_result.get("severity_changes", [])
        }

        if not fp_titles and not sev_map:
            return synthesis

        calibrated = dict(synthesis)
        calibrated["_pre_calibration_verdict"] = synthesis.get("verdict")

        for key in ("agreed", "a_only", "b_only"):
            entries = calibrated.get(key, [])
            filtered = []
            for entry in entries:
                inner = entry.get("finding_a", entry.get("finding", {}))
                title_lower = inner.get("title", "").lower()

                if title_lower in fp_titles:
                    continue

                if title_lower in sev_map:
                    inner["_original_severity"] = inner.get("severity", "minor")
                    inner["severity"] = sev_map[title_lower]

                # Also calibrate additional_failure_modes within the entry
                extras = entry.get("additional_failure_modes", [])
                if extras:
                    calibrated_extras = []
                    for extra in extras:
                        extra_title = extra.get("title", "").lower()
                        if extra_title in fp_titles:
                            continue
                        if extra_title in sev_map:
                            extra["_original_severity"] = extra.get("severity", "minor")
                            extra["severity"] = sev_map[extra_title]
                        calibrated_extras.append(extra)
                    entry["additional_failure_modes"] = calibrated_extras

                filtered.append(entry)
            calibrated[key] = filtered

        # Recalculate counts
        calibrated["total_findings"] = (
            len(calibrated.get("agreed", [])) +
            len(calibrated.get("a_only", [])) +
            len(calibrated.get("b_only", []))
        )
        calibrated["agreed_count"] = len(calibrated.get("agreed", []))
        calibrated["disputed_count"] = (
            len(calibrated.get("a_only", [])) + len(calibrated.get("b_only", []))
        )
        calibrated["fp_calibrated"] = True

        # Recalculate verdict based on remaining findings to prevent stale
        # CHANGES_REQUESTED from reaching publish after FP removal.
        calibrated["verdict"] = _recalculate_verdict(calibrated)

        return calibrated

    @staticmethod
    def _passthrough(reason: str) -> StepResult:
        return StepResult(
            success=True,
            outputs={"fp_check": {"verified_findings": [], "skipped": reason}},
        )
