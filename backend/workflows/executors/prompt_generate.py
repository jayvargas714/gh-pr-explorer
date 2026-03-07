"""Prompt Generate step — builds review prompts from PR context."""

import logging

from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)


@register_step("prompt_generate")
class PromptGenerateExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        prs = inputs.get("prs", [])
        mode = inputs.get("mode", "team-review")
        owner = inputs.get("owner", "")
        repo = inputs.get("repo", "")

        if not prs:
            return StepResult(success=False, error="No PRs to generate prompts for")

        prompts = []
        for pr in prs:
            pr_number = pr.get("number", 0)
            pr_url = pr.get("url", f"https://github.com/{owner}/{repo}/pull/{pr_number}")
            title = pr.get("title", "")
            author = pr.get("author", {})
            author_login = author.get("login", "") if isinstance(author, dict) else str(author)

            prompt_text = (
                f"Review PR #{pr_number} — {title}\n"
                f"Author: {author_login}\n"
                f"URL: {pr_url}\n\n"
                f"Use the elite-code-reviewer agent. "
                f"Perform a thorough code review of this PR."
            )

            prompts.append({
                "pr_number": pr_number,
                "pr_url": pr_url,
                "pr_title": title,
                "pr_author": author_login,
                "prompt": prompt_text,
                "owner": owner,
                "repo": repo,
            })

        return StepResult(
            success=True,
            outputs={"prompts": prompts, "mode": mode},
        )
