from __future__ import annotations
"""Publish step — posts review to GitHub as PR comment/review.

Produces rich GitHub comment format with blocking findings (file locations,
evidence, suggested fixes), non-blocking suggestions, questions, staleness
notes, and auto-creates follow-up entries for CHANGES_REQUESTED/NEEDS_DISCUSSION.
"""

import json
import logging
import re
import subprocess

from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)


def sanitize_comment(text: str) -> str:
    """Enforce comment safety: strip issue auto-links, AI branding."""
    text = re.sub(r'(?<!\w)#(\d+)', r'\1', text)

    ai_patterns = [
        r'(?i)\b(as an? (?:ai|language model|llm|assistant))\b',
        r'(?i)\bgenerated (?:by|using|with) (?:ai|claude|gpt|openai|anthropic)\b',
        r'(?i)\b(?:claude|chatgpt|gpt-4|gpt-4o|opus)\b(?! (?:cli|api))',
    ]
    for pattern in ai_patterns:
        text = re.sub(pattern, '', text)

    return text.strip()


def build_gh_comment(synthesis: dict, mode: str = "team-review",
                     freshness=None) -> str:
    """Build a rich GitHub comment body from synthesis results."""
    verdict = synthesis.get("verdict", "COMMENT")
    agreed = synthesis.get("agreed", [])
    a_only = synthesis.get("a_only", [])
    b_only = synthesis.get("b_only", [])

    lines = ["## Adversarial Review", ""]

    summary = synthesis.get("summary", "")
    if summary:
        lines.extend([summary, ""])
    else:
        lines.extend([
            f"**Verdict:** {verdict}",
            f"**Findings:** {synthesis.get('total_findings', 0)} total "
            f"({synthesis.get('agreed_count', 0)} agreed, "
            f"{synthesis.get('disputed_count', 0)} disputed)",
            "",
        ])

    blocking = _collect_blocking(agreed, a_only, b_only)
    if blocking:
        lines.append("### Blocking Findings")
        lines.append("")
        for i, f in enumerate(blocking, 1):
            inner = f.get("finding_a", f.get("finding", {}))
            loc = inner.get("location", {})
            file_ref = _format_file_ref(loc)
            source = f.get("source", "")
            lines.append(f'{i}. **{inner.get("title", "Untitled")}** [{source}] — `{file_ref}`')
            if inner.get("problem"):
                lines.append(f'   {inner["problem"]}')
            if inner.get("evidence"):
                lines.append(f'   Evidence: {inner["evidence"]}')
            if inner.get("fix"):
                lines.append(f'   **Suggested fix:** {inner["fix"]}')
            lines.append("")
    else:
        lines.extend(["### Blocking Findings", "", "None — approving.", ""])

    non_blocking = _collect_non_blocking(agreed, a_only, b_only)
    if non_blocking:
        lines.append("### Non-Blocking Suggestions")
        lines.append("")
        for i, f in enumerate(non_blocking, 1):
            inner = f.get("finding_a", f.get("finding", {}))
            loc = inner.get("location", {})
            file_ref = _format_file_ref(loc)
            source = f.get("source", "")
            lines.append(f'{i}. **{inner.get("title", "Untitled")}** [{source}] — `{file_ref}`')
            if inner.get("problem"):
                lines.append(f'   {inner["problem"]}')
            lines.append("")

    questions = synthesis.get("questions", [])
    if questions:
        lines.append("### Questions")
        lines.append("")
        for i, q in enumerate(questions, 1):
            lines.append(f"{i}. {q}")
        lines.append("")

    if freshness:
        stale_prs = [f for f in freshness
                     if f.get("classification", "").startswith("STALE")
                     or f.get("classification") == "SUPERSEDED"]
        for pf in stale_prs:
            affected = pf.get("affected_findings", [])
            sha = pf.get("review_sha", "?")[:8]
            cls = pf.get("classification", "STALE")
            if cls == "SUPERSEDED":
                lines.extend([
                    f"> **Staleness Warning ({cls}):** This review was generated against "
                    f"commit `{sha}`. The branch has been force-pushed/rebased since.",
                    "",
                ])
            elif affected:
                affected_str = ", ".join(affected[:5])
                lines.extend([
                    f"> **Staleness Note:** Review generated against `{sha}`. "
                    f"Findings that may be affected by recent changes: {affected_str}.",
                    "",
                ])
            else:
                lines.extend([
                    f"> **Note:** PR has new commits since review (generated against `{sha}`). "
                    "Findings are likely still valid.",
                    "",
                ])

    return sanitize_comment("\n".join(lines))


def _collect_blocking(agreed: list, a_only: list, b_only: list) -> list:
    blocking = []
    for f in agreed:
        if f.get("finding_a", {}).get("severity") in ("critical", "major"):
            blocking.append(f)
    for f in a_only + b_only:
        if f.get("finding", {}).get("severity") == "critical":
            blocking.append(f)
    return blocking


def _collect_non_blocking(agreed: list, a_only: list, b_only: list) -> list:
    non_blocking = []
    for f in agreed:
        if f.get("finding_a", {}).get("severity") not in ("critical", "major"):
            non_blocking.append(f)
    for f in a_only + b_only:
        if f.get("finding", {}).get("severity") != "critical":
            non_blocking.append(f)
    return non_blocking


def _format_file_ref(loc: dict) -> str:
    if not loc:
        return "unknown"
    f = loc.get("file", loc.get("raw", ""))
    line = loc.get("start_line")
    if f and line:
        return f"{f}:{line}"
    return f or "unknown"


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

        per_pr = synthesis.get("per_pr", [])
        if per_pr:
            results = []
            for pr_synth in per_pr:
                result = self._publish_single_pr(pr_synth, owner, repo, mode, freshness)
                results.append(result)
            all_success = all(r.get("published", False) for r in results)
            return StepResult(
                success=True,
                outputs={"published": results, "all_published": all_success},
                artifacts=[
                    {"type": "gh_comment", "pr_number": r.get("pr_number"), "data": r}
                    for r in results
                ],
            )
        else:
            return self._publish_single_pr_result(synthesis, owner, repo, mode, freshness)

    def _publish_single_pr(self, synthesis: dict, owner: str, repo: str,
                           mode: str, freshness: list) -> dict:
        """Publish a single PR review and return a result dict."""
        pr_number = synthesis.get("pr_number")
        if not pr_number:
            return {"published": False, "error": "No PR number in synthesis"}

        existing = self._fetch_existing_findings(owner, repo, pr_number)
        synthesis = self._filter_already_raised(synthesis, existing)

        verdict = synthesis.get("verdict", "COMMENT")
        comment_body = build_gh_comment(synthesis, mode, freshness)

        event_map = {
            "APPROVE": "APPROVE",
            "CHANGES_REQUESTED": "REQUEST_CHANGES",
            "NEEDS_DISCUSSION": "COMMENT",
            "COMMENT": "COMMENT",
        }
        gh_event = event_map.get(verdict, "COMMENT")

        success = self._post_to_github(owner, repo, pr_number, comment_body, gh_event)

        instance_id = self.instance_config.get("_instance_id", 0)
        if success and verdict in ("CHANGES_REQUESTED", "NEEDS_DISCUSSION"):
            self._create_followup_entries(
                owner, repo, pr_number, synthesis, instance_id
            )

        return {
            "published": success,
            "pr_number": pr_number,
            "verdict": verdict,
            "gh_event": gh_event,
            "body": comment_body,
            "posted": success,
        }

    def _publish_single_pr_result(self, synthesis: dict, owner: str, repo: str,
                                  mode: str, freshness: list) -> StepResult:
        """Wrap single-PR publish in a StepResult for the non-per_pr path."""
        result = self._publish_single_pr(synthesis, owner, repo, mode, freshness)
        if "error" in result:
            return StepResult(success=False, error=result["error"])
        return StepResult(
            success=True,
            outputs={
                "published": result["published"],
                "pr_number": result["pr_number"],
                "verdict": result["verdict"],
                "gh_event": result["gh_event"],
            },
            artifacts=[{
                "type": "gh_comment",
                "pr_number": result["pr_number"],
                "data": {"body": result["body"], "event": result["gh_event"],
                         "posted": result["posted"]},
            }],
        )

    def _fetch_existing_findings(self, owner: str, repo: str, pr_number: int) -> set[str]:
        """Fetch titles/summaries of findings already raised by other reviewers."""
        existing: set[str] = set()
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{owner}/{repo}/pulls/{pr_number}/reviews",
                 "--paginate", "--jq", '.[].body'],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                for body in result.stdout.strip().split("\n"):
                    if body.strip():
                        existing.add(body.strip()[:200].lower())
        except Exception:
            pass
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{owner}/{repo}/pulls/{pr_number}/comments",
                 "--paginate", "--jq", '.[].body'],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                for body in result.stdout.strip().split("\n"):
                    if body.strip():
                        existing.add(body.strip()[:200].lower())
        except Exception:
            pass
        return existing

    def _filter_already_raised(self, synthesis: dict, existing: set[str]) -> dict:
        """Remove findings that were already raised by other reviewers."""
        if not existing:
            return synthesis

        def is_new(finding: dict) -> bool:
            inner = finding.get("finding_a", finding.get("finding", {}))
            title = inner.get("title", "").lower()
            return not any(title in ex for ex in existing)

        filtered = dict(synthesis)
        for key in ("agreed", "a_only", "b_only"):
            if key in filtered and isinstance(filtered[key], list):
                filtered[key] = [f for f in filtered[key] if is_new(f)]

        filtered["total_findings"] = (
            len(filtered.get("agreed", [])) +
            len(filtered.get("a_only", [])) +
            len(filtered.get("b_only", []))
        )
        filtered["agreed_count"] = len(filtered.get("agreed", []))
        filtered["disputed_count"] = len(filtered.get("a_only", [])) + len(filtered.get("b_only", []))

        return filtered

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
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                logger.info(f"Published {event} review to {owner}/{repo} PR {pr_number}")
                return True
            else:
                logger.error(f"gh command failed: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Failed to publish to GitHub: {e}")
            return False

    @staticmethod
    def _create_followup_entries(owner: str, repo: str, pr_number: int,
                                  synthesis: dict, instance_id: int):
        try:
            from backend.database import get_workflow_db
            db = get_workflow_db()
            review_sha = ""
            for cat in ("agreed", "a_only", "b_only"):
                for f in synthesis.get(cat, []):
                    inner = f.get("finding_a", f.get("finding", {}))
                    if inner:
                        break

            followup_id = db.create_followup(
                instance_id=instance_id,
                pr_number=pr_number,
                repo=f"{owner}/{repo}",
                source_run_id=instance_id,
                verdict=synthesis.get("verdict", "COMMENT"),
                review_sha=review_sha or None,
            )

            agreed = synthesis.get("agreed", [])
            a_only = synthesis.get("a_only", [])
            b_only = synthesis.get("b_only", [])
            blocking = _collect_blocking(agreed, a_only, b_only)

            for i, f in enumerate(blocking):
                inner = f.get("finding_a", f.get("finding", {}))
                db.create_followup_finding(
                    followup_id=followup_id,
                    finding_id=f"B{i+1}",
                    original_text=inner.get("title", ""),
                    severity=inner.get("severity", "major"),
                )

            logger.info(
                f"Created follow-up entry {followup_id} for PR {pr_number} "
                f"with {len(blocking)} blocking findings"
            )
        except Exception as e:
            logger.error(f"Failed to create follow-up entries: {e}")
