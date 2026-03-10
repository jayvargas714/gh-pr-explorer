from __future__ import annotations
"""Related Issue Scan step — scans codebase for patterns similar to findings.

Serves three purposes:
1. **Dedup**: Identifies findings that describe the same defect (same file,
   overlapping lines, same issue) and merges them — using codebase context
   to confirm whether two differently-worded findings are truly the same bug
2. **False positive detection**: Reveals that a "problem" pattern is actually
   standard/intentional across the codebase
3. **Wider issue detection**: Catches more instances of real issues beyond
   the PR diff

Runs after synthesis, before fp_severity_check.
"""

import logging
import time

from backend.agents import get_agent, AgentStatus
from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.executors.agent_review import _set_live_output, _clear_live_output
from backend.workflows.json_parser import extract_json
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)


@register_step("related_issue_scan")
class RelatedIssueScanExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        synthesis = inputs.get("synthesis", {})
        owner = inputs.get("owner", "")
        repo = inputs.get("repo", "")
        prs = inputs.get("prs", [])
        inst_id = self.instance_config.get("_instance_id", 0)
        step_id = self.step_config.get("_step_id", "")

        findings = self._collect_findings(synthesis)
        if not findings:
            return StepResult(
                success=True,
                outputs={"related_scan": {"scanned_findings": [], "skipped": "no findings"}},
            )

        prompt = self._build_scan_prompt(findings, owner, repo, prs)

        agent_name = self.step_config.get("agent", "claude-sonnet")
        try:
            agent = get_agent(agent_name)
        except Exception as e:
            logger.warning(f"Related issue scan failed to get agent: {e}")
            return self._passthrough(synthesis, str(e))

        context = {
            "pr_number": prs[0].get("number") if prs else 0,
            "owner": owner,
            "repo": repo,
            "phase": "related_scan",
            "task": "related_scan",
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
                        return self._passthrough(synthesis, "cancelled")
                    status = agent.check_status(handle)
                    if status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED):
                        break
                    if elapsed >= AGENT_POLL_TIMEOUT:
                        logger.error(f"Related issue scan timed out after {elapsed}s")
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
                scan_result = self._parse_scan_output(artifact.content_md)
                # Apply dedup: remove duplicate findings from synthesis
                deduped_synthesis = self._apply_dedup(synthesis, scan_result)
                outputs = {
                    "related_scan": scan_result,
                    "synthesis": deduped_synthesis,
                }
                if artifact.usage:
                    outputs["usage"] = artifact.usage
                return StepResult(
                    success=True,
                    outputs=outputs,
                    artifacts=[{
                        "type": "related_issue_scan",
                        "pr_number": prs[0].get("number") if prs else 0,
                        "data": scan_result,
                    }],
                )
            else:
                agent.cleanup(handle)
                return self._passthrough(synthesis, f"agent status: {status.value}")
        except Exception as e:
            logger.error(f"Related issue scan error: {e}")
            return self._passthrough(synthesis, str(e))

    @staticmethod
    def _collect_findings(synthesis: dict) -> list[dict]:
        """Gather all findings from synthesis for scanning, tagged with source."""
        findings = []
        for entry in synthesis.get("agreed", []):
            inner = entry.get("finding_a", {})
            if inner.get("title"):
                findings.append({**inner, "_source": "BOTH"})
            for extra in entry.get("additional_failure_modes", []):
                if extra.get("title"):
                    findings.append({**extra, "_source": "BOTH"})
        for entry in synthesis.get("a_only", []):
            inner = entry.get("finding", {})
            if inner.get("title"):
                findings.append({**inner, "_source": "A_ONLY"})
        for entry in synthesis.get("b_only", []):
            inner = entry.get("finding", {})
            if inner.get("title"):
                findings.append({**inner, "_source": "B_ONLY"})
        for sf in synthesis.get("synth_findings", []):
            if sf.get("title"):
                findings.append({**sf, "_source": "SYNTH"})
        return findings

    def _build_scan_prompt(self, findings: list[dict], owner: str, repo: str,
                           prs: list) -> str:
        sections = []

        sections.append(
            "You are a codebase analyst performing a RELATED ISSUE SCAN with DEDUPLICATION.\n\n"
            "You have two jobs:\n\n"
            "**Job 1 — Deduplication**: Compare all findings against each other to identify "
            "duplicates. Two findings are duplicates when they describe the **same defect** at "
            "the **same code location** (same file, overlapping line ranges). Use the codebase "
            "to verify: read the actual code and confirm whether two findings that look similar "
            "are truly the same bug or distinct issues.\n"
            "- Word-for-word identical findings at the same location → always a duplicate\n"
            "- Same file + overlapping lines + same root cause → duplicate even if worded differently\n"
            "- Same file but different functions/concerns → NOT a duplicate\n"
            "- Findings at different files that share a root cause → NOT duplicates (report as wider_issues)\n\n"
            "**Job 2 — Related Issue Scan**: For each *unique* finding (after dedup), search "
            "the repository for **structurally similar patterns** — not just textual matches. "
            "This means:\n"
            "- Same error handling approach (e.g., missing error check, swallowed errors)\n"
            "- Same architectural pattern (e.g., unbounded collect, lock-free shared state)\n"
            "- Same API usage shape (e.g., unchecked unwrap after fallible call)\n"
            "- Functionally equivalent code even if variable/function names differ\n\n"
            "This determines:\n"
            "- Whether the 'problem' pattern is actually standard/intentional in the codebase "
            "(suggesting the finding is a false positive)\n"
            "- Whether real issues extend beyond the PR diff (wider impact)\n\n"
            "Be thorough but efficient. Use grep/search to find actual code, then READ the "
            "surrounding context to confirm structural similarity — don't just count keyword hits."
        )

        pr_numbers = [p.get("number") for p in prs if p.get("number")]
        if pr_numbers:
            sections.append(
                "## Context Commands\n\n"
                "```bash\n"
                f"gh pr diff {pr_numbers[0]} --repo {owner}/{repo} --name-only\n"
                "```\n"
            )

        sections.append("## Findings to Scan\n")
        for i, f in enumerate(findings, 1):
            title = f.get("title", "Untitled")
            loc = f.get("location", {})
            file_ref = loc.get("file", loc.get("raw", "unknown"))
            line = loc.get("start_line", "?")
            problem = f.get("problem", "")[:300]
            severity = f.get("severity", "unknown")
            source = f.get("_source", "?")
            sections.append(
                f"### Finding {i}: [{severity}] {title}\n"
                f"- Source: {source}\n"
                f"- File: `{file_ref}:{line}`\n"
                f"- Problem: {problem}\n"
            )

        sections.append(
            "## Your Task\n\n"
            "### Step 1 — Deduplication\n"
            "Compare all findings above against each other:\n"
            "- For each pair of findings at the **same file** with overlapping line ranges, "
            "read the actual code to determine if they describe the same defect\n"
            "- If two findings are duplicates, keep the one with more detail/better evidence "
            "and list the other in `duplicates`\n"
            "- If a finding from A_ONLY or B_ONLY duplicates an AGREED/BOTH finding, "
            "the AGREED version takes priority\n"
            "- When merging, note both sources found the issue (increases confidence)\n\n"
            "### Step 2 — Related Issue Scan\n"
            "For each *unique* finding (not dropped as duplicate):\n"
            "1. **Decompose the finding into searchable signals:**\n"
            "   - The specific function/method/API call involved\n"
            "   - The *structural* pattern (e.g., 'error return ignored', 'mutex not held across "
            "await', 'unbounded buffer')\n"
            "   - The broader category (e.g., error handling, resource lifecycle, concurrency)\n\n"
            "2. **Search using multiple strategies** (don't rely on one grep):\n"
            "   - `Grep` for the specific function/API name\n"
            "   - `Grep` for the structural pattern (e.g., `\\.unwrap\\(\\)` after a function "
            "that returns Result, or `let _ =` for ignored errors)\n"
            "   - `Glob` for files with similar roles (same directory, same suffix)\n"
            "   - `Read` surrounding code at matches to verify structural similarity, not "
            "just textual overlap\n\n"
            "3. **Distinguish textual vs structural matches:**\n"
            "   - A grep hit for the same function name is a *textual* match — read the "
            "context to see if it uses the same pattern\n"
            "   - Same error-handling shape in a different function = structural match\n"
            "   - Same variable name but different usage = NOT a match\n\n"
            "4. **Report with evidence:**\n"
            "   - How many other files have this same *structural* pattern\n"
            "   - Whether the pattern appears intentional (comments, tests, consistent usage)\n"
            "   - If >5 structural instances: likely standard/intentional → probable false positive\n"
            "   - If 1-3 instances: real issue may be wider than the PR\n"
            "   - If 0 instances: unique to this PR, finding stands on its own\n\n"
            "## Communication Standards\n\n"
            "- Be objective and evidence-based — cite file:line for every claim\n"
            "- Report what you find, not what you assume\n"
            "- Clearly distinguish 'same keyword' from 'same bug pattern'\n"
            "- If uncertain, say so explicitly\n\n"
            "## Output Format — valid JSON only:\n"
            "```json\n"
            "{\n"
            '  "duplicates": [\n'
            '    {\n'
            '      "dropped_title": "title of the finding being removed",\n'
            '      "kept_title": "title of the finding being kept",\n'
            '      "file": "path/to/file",\n'
            '      "reason": "Same defect at same location — both describe X"\n'
            '    }\n'
            '  ],\n'
            '  "scanned_findings": [\n'
            '    {\n'
            '      "title": "original finding title",\n'
            '      "pattern_searched": "the grep pattern used",\n'
            '      "related_count": 0,\n'
            '      "pattern_is_standard": false,\n'
            '      "related_files": ["file1.rs", "file2.rs"],\n'
            '      "assessment": "1-2 sentence explanation"\n'
            '    }\n'
            '  ],\n'
            '  "likely_false_positives": ["finding title where pattern is standard"],\n'
            '  "confirmed_findings": ["finding title where pattern is unique/problematic"],\n'
            '  "wider_issues": [\n'
            '    {"finding": "title", "additional_files": ["other.rs"], "description": "..."}\n'
            '  ]\n'
            "}\n"
            "```\n"
        )

        return "\n\n".join(sections)

    def _parse_scan_output(self, content: str) -> dict:
        """Parse AI scan output."""
        if not content:
            return {"scanned_findings": [], "parse_failed": True}

        parsed = extract_json(content)
        if parsed is None:
            return {"scanned_findings": [], "raw_content": content, "parse_failed": True}

        return {
            "duplicates": parsed.get("duplicates", []),
            "scanned_findings": parsed.get("scanned_findings", []),
            "likely_false_positives": parsed.get("likely_false_positives", []),
            "confirmed_findings": parsed.get("confirmed_findings", []),
            "wider_issues": parsed.get("wider_issues", []),
            "total_scanned": len(parsed.get("scanned_findings", [])),
            "duplicates_removed": len(parsed.get("duplicates", [])),
            "fp_count": len(parsed.get("likely_false_positives", [])),
            "wider_count": len(parsed.get("wider_issues", [])),
        }

    @staticmethod
    def _apply_dedup(synthesis: dict, scan_result: dict) -> dict:
        """Remove duplicate findings from synthesis based on scan dedup results.

        The AI scanner identifies findings that describe the same defect.
        This method removes the dropped findings from the synthesis so
        downstream steps (FP check, publish) operate on a clean set.
        """
        duplicates = scan_result.get("duplicates", [])
        if not duplicates:
            return synthesis

        dropped_titles = {
            d.get("dropped_title", "").lower()
            for d in duplicates
            if d.get("dropped_title")
        }
        if not dropped_titles:
            return synthesis

        deduped = dict(synthesis)

        for key in ("agreed", "a_only", "b_only"):
            entries = deduped.get(key, [])
            filtered = []
            for entry in entries:
                inner = entry.get("finding_a", entry.get("finding", {}))
                if inner.get("title", "").lower() in dropped_titles:
                    continue
                # Also filter additional_failure_modes within agreed entries
                extras = entry.get("additional_failure_modes", [])
                if extras:
                    entry["additional_failure_modes"] = [
                        e for e in extras
                        if e.get("title", "").lower() not in dropped_titles
                    ]
                filtered.append(entry)
            deduped[key] = filtered

        # Update counts
        deduped["total_findings"] = (
            len(deduped.get("agreed", [])) +
            len(deduped.get("a_only", [])) +
            len(deduped.get("b_only", []))
        )
        deduped["agreed_count"] = len(deduped.get("agreed", []))
        deduped["disputed_count"] = (
            len(deduped.get("a_only", [])) + len(deduped.get("b_only", []))
        )
        deduped["dedup_applied"] = True
        deduped["dedup_log"] = duplicates

        return deduped

    @staticmethod
    def _passthrough(synthesis: dict, reason: str) -> StepResult:
        return StepResult(
            success=True,
            outputs={"related_scan": {"scanned_findings": [], "skipped": reason}},
        )
