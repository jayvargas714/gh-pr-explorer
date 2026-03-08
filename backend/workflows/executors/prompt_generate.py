"""Prompt Generate step — builds review prompts from PR context.

Supports prior review deduplication, Jira context injection, and large
diff handling (>5000 lines -> chunked strategy).
"""

import json
import logging
import re
import subprocess

from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)

LARGE_DIFF_THRESHOLD = 5000


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
            body = pr.get("body", "") or ""

            context_parts = [
                f"Review PR #{pr_number} — {title}",
                f"Author: {author_login}",
                f"URL: {pr_url}",
                "",
            ]

            additions = pr.get("additions", 0)
            deletions = pr.get("deletions", 0)
            total_lines = additions + deletions

            if total_lines > LARGE_DIFF_THRESHOLD:
                context_parts.append(
                    f"**Large PR ({total_lines} lines).** Use chunked review strategy: "
                    f"review file-by-file, prioritize changed files with most additions."
                )

            dedup_directive = self._check_prior_reviews(owner, repo, pr_number)
            if dedup_directive:
                context_parts.append(dedup_directive)

            jira_context = self._fetch_jira_context(body, title)
            if jira_context:
                context_parts.append(jira_context)

            context_parts.append(
                "Use the elite-code-reviewer agent. "
                "Perform a thorough code review of this PR."
            )

            context_parts.append(
                "\nContext commands to run:\n"
                f"  gh pr view {pr_number} --repo {owner}/{repo}\n"
                f"  gh pr diff {pr_number} --repo {owner}/{repo}\n"
                f"  gh pr checks {pr_number} --repo {owner}/{repo}"
            )

            prompts.append({
                "pr_number": pr_number,
                "pr_url": pr_url,
                "pr_title": title,
                "pr_author": author_login,
                "prompt": "\n".join(context_parts),
                "owner": owner,
                "repo": repo,
                "additions": additions,
                "deletions": deletions,
                "head_sha": pr.get("headRefOid", ""),
            })

        return StepResult(
            success=True,
            outputs={"prompts": prompts, "mode": mode},
            artifacts=[{
                "type": "prompts",
                "data": {
                    "prompts": [
                        {"pr_number": p["pr_number"], "pr_title": p.get("pr_title", ""),
                         "prompt": p["prompt"]}
                        for p in prompts
                    ],
                    "mode": mode,
                    "count": len(prompts),
                },
            }],
        )

    def _check_prior_reviews(self, owner: str, repo: str, pr_number: int) -> str:
        try:
            from backend.database import get_reviews_db
            reviews_db = get_reviews_db()
            full_repo = f"{owner}/{repo}"
            latest = reviews_db.get_latest_review_for_pr(full_repo, pr_number)
            if latest and latest.get("status") == "completed":
                return (
                    "\n**Prior review exists.** Focus on gaps, new changes since "
                    "the last review, and issues that were not addressed. "
                    "Do not repeat findings from the previous review unless they are still present."
                )
        except Exception as e:
            logger.debug(f"Could not check prior reviews: {e}")
        return ""

    def _fetch_jira_context(self, body: str, title: str) -> str:
        combined = f"{title} {body}"
        jira_refs = re.findall(r'(SIM-\d+)', combined, re.IGNORECASE)
        if not jira_refs:
            return ""

        context_parts = ["\n**Jira context:**"]
        for ref in jira_refs[:3]:
            try:
                result = subprocess.run(
                    ["acli", "jira", "workitem", "view", ref],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    summary = result.stdout.strip()[:500]
                    context_parts.append(f"  {ref}: {summary}")
            except FileNotFoundError:
                logger.debug("acli not available, skipping Jira context")
                return ""
            except Exception as e:
                logger.debug(f"Failed to fetch Jira context for {ref}: {e}")

        return "\n".join(context_parts) if len(context_parts) > 1 else ""
