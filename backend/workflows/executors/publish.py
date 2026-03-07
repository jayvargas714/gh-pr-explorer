"""Publish step — posts review to GitHub as PR comment/review."""

import json
import logging
import re
import subprocess

from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)


def sanitize_comment(text: str) -> str:
    """Enforce comment safety rules: strip issue refs, AI branding."""
    text = re.sub(r'(?<!\w)#(\d+)', r'\1', text)

    ai_patterns = [
        r'(?i)\b(as an? (?:ai|language model|llm|assistant))\b',
        r'(?i)\bgenerated (?:by|using|with) (?:ai|claude|gpt|openai|anthropic)\b',
        r'(?i)\b(?:claude|chatgpt|gpt-4|gpt-4o|opus)\b(?! (?:cli|api))',
    ]
    for pattern in ai_patterns:
        text = re.sub(pattern, '', text)

    return text.strip()


def build_gh_comment(synthesis: dict, mode: str = "team-review") -> str:
    """Build the GitHub comment body from a synthesis result."""
    verdict = synthesis.get("verdict", "COMMENT")
    pr_number = synthesis.get("pr_number", "")
    agreed = synthesis.get("agreed", [])
    a_only = synthesis.get("a_only", [])
    b_only = synthesis.get("b_only", [])

    lines = [
        "## Adversarial Review",
        "",
        f"**Verdict:** {verdict}",
        f"**Findings:** {synthesis.get('total_findings', 0)} total "
        f"({synthesis.get('agreed_count', 0)} agreed, "
        f"{synthesis.get('disputed_count', 0)} disputed)",
        "",
    ]

    blocking = [f for f in agreed if f["finding_a"].get("severity") == "critical"]
    blocking += [f for f in a_only if f["finding"].get("severity") == "critical"]
    blocking += [f for f in b_only if f["finding"].get("severity") == "critical"]

    if blocking:
        lines.append("### Blocking")
        lines.append("")
        for i, finding in enumerate(blocking, 1):
            f = finding.get("finding_a", finding.get("finding", {}))
            title = f.get("title", "Untitled")
            problem = f.get("problem", "")
            classification = finding.get("classification", "")
            lines.append(f"{i}. **{title}** [{classification}]")
            if problem:
                lines.append(f"   {problem}")
            lines.append("")

    non_blocking = [f for f in agreed if f["finding_a"].get("severity") != "critical"]
    non_blocking += [f for f in a_only if f["finding"].get("severity") != "critical"]
    non_blocking += [f for f in b_only if f["finding"].get("severity") != "critical"]

    if non_blocking:
        lines.append("### Non-Blocking")
        lines.append("")
        for i, finding in enumerate(non_blocking, 1):
            f = finding.get("finding_a", finding.get("finding", {}))
            title = f.get("title", "Untitled")
            classification = finding.get("classification", "")
            lines.append(f"{i}. **{title}** [{classification}]")
        lines.append("")

    return sanitize_comment("\n".join(lines))


@register_step("publish")
class PublishExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        synthesis = inputs.get("synthesis", {})
        mode = inputs.get("mode", "team-review")
        owner = inputs.get("owner", "")
        repo = inputs.get("repo", "")
        freshness = inputs.get("freshness", [])

        if mode == "self-review":
            return StepResult(
                success=True,
                outputs={"published": False, "reason": "self-review mode: local only"},
            )

        pr_number = synthesis.get("pr_number")
        if not pr_number:
            return StepResult(success=False, error="No PR number in synthesis")

        verdict = synthesis.get("verdict", "COMMENT")
        comment_body = build_gh_comment(synthesis, mode)

        stale_prs = [f for f in freshness if f.get("classification", "").startswith("STALE")]
        if stale_prs:
            comment_body += (
                "\n\n> **Note:** PR has new commits since review began. "
                "Some findings may be outdated.\n"
            )

        event_map = {
            "APPROVE": "APPROVE",
            "CHANGES_REQUESTED": "REQUEST_CHANGES",
            "COMMENT": "COMMENT",
        }
        gh_event = event_map.get(verdict, "COMMENT")

        success = self._post_to_github(owner, repo, pr_number, comment_body, gh_event)

        return StepResult(
            success=True,
            outputs={
                "published": success,
                "pr_number": pr_number,
                "verdict": verdict,
                "gh_event": gh_event,
            },
            artifacts=[{
                "type": "gh_comment",
                "pr_number": pr_number,
                "data": {"body": comment_body, "event": gh_event, "posted": success},
            }],
        )

    def _post_to_github(self, owner: str, repo: str, pr_number: int,
                         body: str, event: str) -> bool:
        if event in ("APPROVE", "REQUEST_CHANGES"):
            cmd = [
                "gh", "pr", "review", str(pr_number),
                "--repo", f"{owner}/{repo}",
                "--body", body,
            ]
            if event == "APPROVE":
                cmd.append("--approve")
            else:
                cmd.append("--request-changes")
        else:
            cmd = [
                "gh", "pr", "comment", str(pr_number),
                "--repo", f"{owner}/{repo}",
                "--body", body,
            ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"Published {event} review to {owner}/{repo} PR {pr_number}")
                return True
            else:
                logger.error(f"gh command failed: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Failed to publish to GitHub: {e}")
            return False
