from __future__ import annotations
"""Freshness Check step — compares HEAD SHA at review time vs current.

Supports SUPERSEDED classification (force-push/rebase detection),
per-finding staleness tagging, and justification summaries per the
legacy adversarial review specification.
"""

import json
import logging
import subprocess

from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)


@register_step("freshness_check")
class FreshnessCheckExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        reviews = inputs.get("reviews", [])
        synthesis = inputs.get("synthesis", {})
        owner = inputs.get("owner", "")
        repo = inputs.get("repo", "")

        if not owner or not repo:
            full_repo = inputs.get("full_repo", inputs.get("repo", ""))
            if "/" in str(full_repo):
                owner, repo = str(full_repo).split("/", 1)

        freshness_results = []
        prs_checked: set[int] = set()

        items_to_check = reviews if reviews else ([synthesis] if synthesis else [])
        for item in items_to_check:
            pr_number = item.get("pr_number")
            if not pr_number or pr_number in prs_checked:
                continue
            prs_checked.add(pr_number)

            current_sha = self._fetch_head_sha(owner, repo, pr_number)
            review_sha = item.get("head_sha")

            if not current_sha:
                classification = "UNKNOWN"
                changed_files: list[str] = []
            elif not review_sha:
                classification = "UNKNOWN"
                changed_files = []
            elif current_sha == review_sha:
                classification = "CURRENT"
                changed_files = []
            else:
                compare_status = self._compare_shas(owner, repo, review_sha, current_sha)
                changed_files = compare_status.get("files", [])

                if compare_status.get("status") == "diverged":
                    classification = "SUPERSEDED"
                elif len(changed_files) > 5:
                    classification = "STALE-MAJOR"
                elif changed_files:
                    classification = "STALE-MINOR"
                else:
                    classification = "STALE-MINOR"

            affected_findings, unaffected_findings = self._tag_finding_staleness(
                synthesis, changed_files, classification
            )

            recommendation = self._build_recommendation(
                classification, affected_findings
            )

            freshness_results.append({
                "pr_number": pr_number,
                "classification": classification,
                "review_sha": review_sha,
                "current_sha": current_sha,
                "changed_files": changed_files[:50],
                "affected_findings": affected_findings,
                "unaffected_findings": unaffected_findings,
                "recommendation": recommendation,
            })

        all_current = all(r["classification"] == "CURRENT" for r in freshness_results)
        any_major = any(r["classification"] in ("STALE-MAJOR", "SUPERSEDED")
                        for r in freshness_results)

        return StepResult(
            success=True,
            outputs={
                "freshness": freshness_results,
                "all_fresh": all_current,
                "any_stale_major": any_major,
                "synthesis": synthesis,
                "reviews": reviews,
            },
            artifacts=[{
                "type": "freshness",
                "data": {
                    "checks": freshness_results,
                    "all_fresh": all_current,
                    "any_stale_major": any_major,
                },
            }],
        )

    def _fetch_head_sha(self, owner: str, repo: str, pr_number: int) -> str:
        cmd = [
            "gh", "pr", "view", str(pr_number),
            "--repo", f"{owner}/{repo}",
            "--json", "headRefOid",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return data.get("headRefOid", "")
        except Exception as e:
            logger.error(f"Failed to fetch HEAD SHA for PR #{pr_number}: {e}")
        return ""

    def _compare_shas(self, owner: str, repo: str,
                      old_sha: str, new_sha: str) -> dict:
        cmd = [
            "gh", "api",
            f"repos/{owner}/{repo}/compare/{old_sha}...{new_sha}",
            "--jq", '{status: .status, files: [.files[].filename]}',
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                return {
                    "status": data.get("status", "ahead"),
                    "files": data.get("files", []),
                }
        except Exception as e:
            logger.warning(f"Failed to compare SHAs {old_sha[:8]}...{new_sha[:8]}: {e}")

        files = self._get_changed_files_between(owner, repo, old_sha, new_sha)
        return {"status": "ahead", "files": files}

    def _get_changed_files_between(self, owner: str, repo: str,
                                    old_sha: str, new_sha: str) -> list[str]:
        cmd = [
            "gh", "api",
            f"repos/{owner}/{repo}/compare/{old_sha}...{new_sha}",
            "--jq", ".files[].filename",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return [f for f in result.stdout.strip().split("\n") if f]
        except Exception as e:
            logger.warning(f"Failed to compare SHAs: {e}")
        return []

    @staticmethod
    def _tag_finding_staleness(synthesis: dict, changed_files: list[str],
                                classification: str) -> tuple[list[str], list[str]]:
        if classification in ("CURRENT", "UNKNOWN") or not changed_files:
            return [], []

        affected = []
        unaffected = []

        for category in ("agreed", "a_only", "b_only"):
            for finding in synthesis.get(category, []):
                inner = finding.get("finding_a", finding.get("finding", {}))
                finding_file = ""
                loc = inner.get("location", {})
                if isinstance(loc, dict):
                    finding_file = loc.get("file", loc.get("raw", ""))

                title = inner.get("title", f"unnamed-{id(finding)}")
                if finding_file and any(finding_file in cf for cf in changed_files):
                    finding["staleness"] = "potentially_affected"
                    affected.append(title)
                else:
                    finding["staleness"] = "unaffected"
                    unaffected.append(title)

        return affected, unaffected

    @staticmethod
    def _build_recommendation(classification: str,
                               affected_findings: list[str]) -> str:
        if classification == "CURRENT":
            return "Review is current. Safe to publish."
        if classification == "SUPERSEDED":
            return (
                "Review is SUPERSEDED — the branch was force-pushed or rebased since review. "
                "Consider re-running the review against the new head."
            )
        if classification == "STALE-MAJOR":
            if affected_findings:
                affected_str = ", ".join(affected_findings[:5])
                return (
                    f"Review is significantly stale. {len(affected_findings)} finding(s) "
                    f"may be affected by recent changes: {affected_str}. "
                    "Consider re-running or manually verifying affected findings."
                )
            return "Review is significantly stale. Manual verification recommended."
        if classification == "STALE-MINOR":
            if affected_findings:
                return (
                    f"Review is slightly stale. {len(affected_findings)} finding(s) "
                    "may be affected but most findings remain valid."
                )
            return "Review is slightly stale but findings are likely still valid."
        return "Freshness status unknown."
