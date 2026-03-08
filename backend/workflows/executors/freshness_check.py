"""Freshness Check step — compares HEAD SHA at review time vs current."""

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
        prs_to_check = reviews if reviews else ([synthesis] if synthesis else [])

        for item in prs_to_check:
            pr_number = item.get("pr_number")
            if not pr_number:
                continue

            current_sha = self._fetch_head_sha(owner, repo, pr_number)
            review_sha = item.get("head_sha")

            if not current_sha:
                classification = "UNKNOWN"
            elif not review_sha:
                classification = "CURRENT"
            elif current_sha == review_sha:
                classification = "CURRENT"
            else:
                changed_files = self._get_changed_files_between(
                    owner, repo, pr_number, review_sha, current_sha
                )
                if not changed_files:
                    classification = "STALE-MINOR"
                elif len(changed_files) > 5:
                    classification = "STALE-MAJOR"
                else:
                    classification = "STALE-MINOR"

            freshness_results.append({
                "pr_number": pr_number,
                "classification": classification,
                "review_sha": review_sha,
                "current_sha": current_sha,
            })

        all_current = all(r["classification"] == "CURRENT" for r in freshness_results)
        any_major = any(r["classification"] == "STALE-MAJOR" for r in freshness_results)

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
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return data.get("headRefOid", "")
        except Exception as e:
            logger.error(f"Failed to fetch HEAD SHA for PR #{pr_number}: {e}")
        return ""

    def _get_changed_files_between(self, owner: str, repo: str, pr_number: int,
                                    old_sha: str, new_sha: str) -> list[str]:
        cmd = [
            "gh", "api",
            f"repos/{owner}/{repo}/compare/{old_sha}...{new_sha}",
            "--jq", ".files[].filename",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return [f for f in result.stdout.strip().split("\n") if f]
        except Exception as e:
            logger.warning(f"Failed to compare SHAs: {e}")
        return []
