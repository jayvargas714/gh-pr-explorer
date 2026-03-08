from __future__ import annotations
"""Expert Select step — selects relevant expert domains from DB for each PR.

Fetches changed files/diff via gh CLI, matches against domain trigger patterns
and keywords, applies relevance thresholds and expert count caps per the legacy
adversarial review specification.
"""

import logging
import re
import subprocess

from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)


@register_step("expert_select")
class ExpertSelectExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        prs = inputs.get("prs", [])
        owner = inputs.get("owner", "")
        repo = inputs.get("repo", "")
        if not prs:
            return StepResult(success=False, error="No PRs to analyze for expert selection")

        domains = self._load_domains()
        if not domains:
            return StepResult(success=False, error="No active expert domains configured")

        all_matched: dict[str, dict] = {}
        pr_domains: list[dict] = []
        total_lines = 0

        for pr in prs:
            pr_number = pr.get("number", 0)
            additions = pr.get("additions", 0)
            deletions = pr.get("deletions", 0)
            total_lines += additions + deletions

            files = self._fetch_changed_files(owner, repo, pr_number)
            diff_content = self._fetch_diff_content(owner, repo, pr_number)

            pr_matched = self._match_domains(domains, files, diff_content)
            for domain_id, info in pr_matched.items():
                if domain_id not in all_matched:
                    all_matched[domain_id] = info
                else:
                    all_matched[domain_id]["matched_files"] = list(
                        set(all_matched[domain_id]["matched_files"]) | set(info["matched_files"])
                    )
                    all_matched[domain_id]["relevance_pct"] = max(
                        all_matched[domain_id]["relevance_pct"], info["relevance_pct"]
                    )

            pr_domains.append({
                "pr_number": pr_number,
                "domains": sorted(pr_matched.keys()),
                "file_count": len(files),
            })

        max_experts = self._expert_count_cap(total_lines)
        sorted_domains = sorted(
            all_matched.values(), key=lambda d: d["relevance_pct"], reverse=True
        )[:max_experts]

        experts = []
        for d in sorted_domains:
            experts.append({
                "domain_id": d["domain_id"],
                "display_name": d["display_name"],
                "persona": d["persona"],
                "scope": d["scope"],
                "checklist": d["checklist"],
                "anti_patterns": d["anti_patterns"],
                "matched_files": d["matched_files"],
                "relevance_pct": d["relevance_pct"],
            })

        if not experts:
            experts = [self._generic_expert()]

        return StepResult(
            success=True,
            outputs={
                "experts": experts,
                "pr_domains": pr_domains,
                "prs": prs,
            },
            artifacts=[{
                "type": "expert_selection",
                "data": {
                    "experts": experts,
                    "pr_domains": pr_domains,
                    "total_domains": len(experts),
                    "total_lines_analyzed": total_lines,
                    "max_experts_cap": max_experts,
                },
            }],
        )

    def _load_domains(self) -> list[dict]:
        try:
            from backend.database import get_workflow_db
            db = get_workflow_db()
            return db.list_expert_domains(active_only=True)
        except Exception as e:
            logger.error(f"Failed to load expert domains: {e}")
            return []

    def _fetch_changed_files(self, owner: str, repo: str, pr_number: int) -> list[str]:
        if not owner or not repo or not pr_number:
            return []
        try:
            result = subprocess.run(
                ["gh", "pr", "diff", str(pr_number), "--name-only",
                 "--repo", f"{owner}/{repo}"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        except Exception as e:
            logger.warning(f"Failed to fetch changed files for PR #{pr_number}: {e}")
        return []

    def _fetch_diff_content(self, owner: str, repo: str, pr_number: int) -> str:
        if not owner or not repo or not pr_number:
            return ""
        try:
            result = subprocess.run(
                ["gh", "pr", "diff", str(pr_number), "--repo", f"{owner}/{repo}"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                return result.stdout[:500_000]
        except Exception as e:
            logger.warning(f"Failed to fetch diff for PR #{pr_number}: {e}")
        return ""

    def _match_domains(self, domains: list[dict], files: list[str],
                       diff_content: str) -> dict[str, dict]:
        total_files = max(len(files), 1)
        matched: dict[str, dict] = {}

        for domain in domains:
            triggers = domain.get("triggers", {})
            file_patterns = triggers.get("file_patterns", [])
            keywords = triggers.get("keywords", [])

            matched_files = set()
            for filepath in files:
                for pattern in file_patterns:
                    try:
                        if re.search(pattern, filepath, re.IGNORECASE):
                            matched_files.add(filepath)
                            break
                    except re.error:
                        pass

            keyword_match = False
            for kw in keywords:
                if kw.lower() in diff_content.lower():
                    keyword_match = True
                    break

            if not matched_files and not keyword_match:
                continue

            relevance = len(matched_files) / total_files * 100
            if keyword_match and relevance < 5:
                relevance = max(relevance, 10.0)

            if relevance < 5 and not keyword_match:
                continue

            matched[domain["domain_id"]] = {
                "domain_id": domain["domain_id"],
                "display_name": domain["display_name"],
                "persona": domain["persona"],
                "scope": domain["scope"],
                "checklist": domain.get("checklist", []),
                "anti_patterns": domain.get("anti_patterns", []),
                "matched_files": sorted(matched_files),
                "relevance_pct": round(relevance, 1),
            }

        return matched

    @staticmethod
    def _expert_count_cap(total_lines: int) -> int:
        if total_lines <= 300:
            return 2
        if total_lines <= 1500:
            return 3
        return 4

    @staticmethod
    def _generic_expert() -> dict:
        return {
            "domain_id": "general",
            "display_name": "General",
            "persona": "Senior software engineer with broad expertise across the stack.",
            "scope": "General code quality, architecture, correctness, and maintainability",
            "checklist": [
                "Is the code correct and free of obvious bugs?",
                "Are edge cases handled?",
                "Is error handling adequate?",
                "Is the code readable and maintainable?",
            ],
            "anti_patterns": [],
            "matched_files": [],
            "relevance_pct": 100.0,
        }
