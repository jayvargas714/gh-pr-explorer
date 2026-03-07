"""PR Select step — resolves which PRs to review based on mode and config."""

import json
import logging
import subprocess

from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)


@register_step("pr_select")
class PRSelectExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        mode = self.step_config.get("mode", "team-review")
        manual_prs = self.step_config.get("pr_numbers", [])
        repo = self.instance_config.get("repo", "")

        if not repo:
            return StepResult(success=False, error="No repo specified in instance config")

        owner, repo_name = repo.split("/", 1) if "/" in repo else (repo, repo)

        if manual_prs:
            prs = self._fetch_specific_prs(owner, repo_name, manual_prs)
        else:
            prs = self._fetch_open_prs(owner, repo_name)

        return StepResult(
            success=True,
            outputs={
                "prs": prs,
                "mode": mode,
                "owner": owner,
                "repo": repo_name,
                "full_repo": repo,
            },
        )

    def _fetch_open_prs(self, owner: str, repo: str) -> list[dict]:
        cmd = [
            "gh", "pr", "list", "--repo", f"{owner}/{repo}",
            "--state", "open", "--limit", "50",
            "--json", "number,title,author,createdAt,updatedAt,additions,deletions,"
                      "changedFiles,headRefName,baseRefName,isDraft,url,body,labels,"
                      "reviewDecision",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return json.loads(result.stdout)
        except Exception as e:
            logger.error(f"Failed to fetch PRs: {e}")
        return []

    def _fetch_specific_prs(self, owner: str, repo: str, numbers: list[int]) -> list[dict]:
        prs = []
        for num in numbers:
            cmd = [
                "gh", "pr", "view", str(num), "--repo", f"{owner}/{repo}",
                "--json", "number,title,author,createdAt,updatedAt,additions,deletions,"
                          "changedFiles,headRefName,baseRefName,isDraft,url,body,labels,"
                          "reviewDecision",
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    prs.append(json.loads(result.stdout))
            except Exception as e:
                logger.error(f"Failed to fetch PR #{num}: {e}")
        return prs
