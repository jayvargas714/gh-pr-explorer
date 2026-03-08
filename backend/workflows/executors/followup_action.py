from __future__ import annotations
"""Follow-Up Action step — generates and posts follow-up comments to GitHub.

Reads classification from the upstream followup_check step and generates
appropriate follow-up comments using templates from the legacy adversarial
review specification. All comments pass through sanitize_comment().
"""

import logging
import subprocess

from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.executors.publish import sanitize_comment
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)

TEMPLATES = {
    "RESOLVED": (
        "Thanks {author} — all blocking items have been resolved. "
        "The adversarial review is satisfied.\n\n{note}"
    ),
    "PARTIALLY_RESOLVED": (
        "Thanks for the updates. {resolved_count} of {total_count} blocking items resolved.\n\n"
        "### Still Open\n\n{open_items}\n\n"
        "### Resolved\n\n{resolved_items}"
    ),
    "AUTHOR_DISAGREES": (
        "Noted — the author disagrees with the following finding(s):\n\n"
        "{disagreed_items}\n\n"
        "The review team will evaluate and respond."
    ),
    "NO_RESPONSE": (
        "Friendly follow-up: the adversarial review posted on this PR has "
        "{total_count} blocking finding(s) that have not yet been addressed.\n\n"
        "### Outstanding Items\n\n{open_items}"
    ),
}


@register_step("followup_action")
class FollowupActionExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        followup_results = inputs.get("followup_results", [])
        owner = inputs.get("owner", "")
        repo = inputs.get("repo", "")

        if not owner or not repo:
            full_repo = inputs.get("full_repo", inputs.get("repo", ""))
            if "/" in str(full_repo):
                owner, repo = str(full_repo).split("/", 1)

        actions_taken = []
        for result in followup_results:
            classification = result.get("classification", "")
            pr_number = result.get("pr_number")
            followup_id = result.get("followup_id")

            if classification in ("MERGED", "CLOSED", "WONTFIX", "CONCEDED"):
                actions_taken.append({
                    "pr_number": pr_number,
                    "action": "skip",
                    "reason": f"PR is {classification}, no action needed",
                })
                continue

            if classification == "DISCUSSING":
                actions_taken.append({
                    "pr_number": pr_number,
                    "action": "skip",
                    "reason": "Discussion in progress, waiting for resolution",
                })
                continue

            if not pr_number:
                actions_taken.append({
                    "pr_number": pr_number,
                    "action": "skip",
                    "reason": "Missing PR number",
                })
                continue

            comment = self._build_comment(result, followup_id)
            if not comment:
                actions_taken.append({
                    "pr_number": pr_number,
                    "action": "skip",
                    "reason": f"No comment template for classification: {classification}",
                })
                continue

            posted = self._post_comment(owner, repo, pr_number, comment)
            actions_taken.append({
                "pr_number": pr_number,
                "action": "comment_posted" if posted else "comment_failed",
                "classification": classification,
                "comment_length": len(comment),
            })

        return StepResult(
            success=True,
            outputs={"actions_taken": actions_taken},
            artifacts=[{
                "type": "followup_action",
                "data": {"actions": actions_taken, "count": len(actions_taken)},
            }],
        )

    def _build_comment(self, result: dict, followup_id) -> str:
        classification = result.get("classification", "")
        template = TEMPLATES.get(classification)
        if not template:
            return ""

        findings = self._get_findings(followup_id)
        open_findings = [f for f in findings if f.get("status") in ("OPEN", None)]
        resolved_findings = [f for f in findings if f.get("status") == "RESOLVED"]

        open_items = "\n".join(
            f"- **{f.get('finding_id', '?')}**: {f.get('original_text', '')}"
            for f in open_findings
        ) or "None"

        resolved_items = "\n".join(
            f"- ~~**{f.get('finding_id', '?')}**: {f.get('original_text', '')}~~"
            for f in resolved_findings
        ) or "None"

        disagreed_items = "\n".join(
            f"- **{f.get('finding_id', '?')}**: {f.get('original_text', '')}"
            for f in findings
            if f.get("status") == "AUTHOR_DISAGREES"
        ) or "See author comments above."

        author_responses = result.get("author_responses", [])
        author = author_responses[0].get("user", "author") if author_responses else "author"

        comment = template.format(
            author=author,
            note="",
            resolved_count=len(resolved_findings),
            total_count=len(findings),
            open_items=open_items,
            resolved_items=resolved_items,
            disagreed_items=disagreed_items,
        )

        return sanitize_comment(comment)

    @staticmethod
    def _get_findings(followup_id: int | None) -> list[dict]:
        if not followup_id:
            return []
        try:
            from backend.database import get_workflow_db
            db = get_workflow_db()
            return db.get_followup_findings(followup_id)
        except Exception:
            return []

    @staticmethod
    def _post_comment(owner: str, repo: str, pr_number: int, body: str) -> bool:
        cmd = [
            "gh", "pr", "comment", str(pr_number),
            "--repo", f"{owner}/{repo}",
            "--body", body,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                logger.info(f"Posted follow-up comment on {owner}/{repo} PR {pr_number}")
                return True
            else:
                logger.error(f"Failed to post follow-up: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Failed to post follow-up comment: {e}")
            return False
