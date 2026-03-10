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

    holistic_blocking = synthesis.get("_holistic_blocking", [])
    holistic_non_blocking = synthesis.get("_holistic_non_blocking", [])
    cross_cutting = synthesis.get("_cross_cutting", [])

    if holistic_blocking or holistic_non_blocking:
        blocking = holistic_blocking
        non_blocking_items = holistic_non_blocking
    else:
        blocking = _collect_blocking(agreed, a_only, b_only)
        non_blocking_items = _collect_non_blocking(agreed, a_only, b_only)

    if blocking:
        lines.append("### Blocking Findings")
        lines.append("")
        counter = 1
        for f in blocking:
            inner = f.get("finding_a", f.get("finding", f))
            loc = inner.get("location", {})
            file_ref = _format_file_ref(loc, inner)
            severity = inner.get("severity", "")
            sev_tag = f" [{severity}]" if severity else ""
            lines.append(f'{counter}. **{inner.get("title", "Untitled")}**{sev_tag} — `{file_ref}`')
            if inner.get("problem") or inner.get("description"):
                lines.append(f'   {inner.get("problem") or inner.get("description")}')
            if inner.get("evidence"):
                lines.append(f'   Evidence: {inner["evidence"]}')
            if inner.get("fix") or inner.get("suggestion"):
                lines.append(f'   **Suggested fix:** {inner.get("fix") or inner.get("suggestion")}')
            lines.append("")
            counter += 1

            # Emit additional failure modes as separate line items to prevent
            # synthesis loss (multi-path findings collapsed into one entry)
            for extra in f.get("additional_failure_modes", []):
                extra_loc = extra.get("location", {})
                extra_ref = _format_file_ref(extra_loc, extra)
                extra_sev = extra.get("severity", "")
                extra_tag = f" [{extra_sev}]" if extra_sev else ""
                lines.append(f'{counter}. **{extra.get("title", "Untitled")}**{extra_tag} — `{extra_ref}`')
                if extra.get("problem") or extra.get("description"):
                    lines.append(f'   {extra.get("problem") or extra.get("description")}')
                if extra.get("evidence"):
                    lines.append(f'   Evidence: {extra["evidence"]}')
                if extra.get("fix") or extra.get("suggestion"):
                    lines.append(f'   **Suggested fix:** {extra.get("fix") or extra.get("suggestion")}')
                lines.append("")
                counter += 1
    else:
        lines.extend(["### Blocking Findings", "", "None — approving.", ""])

    if non_blocking_items:
        lines.append("### Non-Blocking Suggestions")
        lines.append("")
        for i, f in enumerate(non_blocking_items, 1):
            inner = f.get("finding_a", f.get("finding", f))
            loc = inner.get("location", {})
            file_ref = _format_file_ref(loc, inner)
            severity = inner.get("severity", "")
            sev_tag = f" [{severity}]" if severity else ""
            lines.append(f'{i}. **{inner.get("title", "Untitled")}**{sev_tag} — `{file_ref}`')
            if inner.get("problem") or inner.get("description"):
                lines.append(f'   {inner.get("problem") or inner.get("description")}')
            lines.append("")

    if cross_cutting:
        lines.append("### Cross-Cutting Concerns")
        lines.append("")
        for i, cc in enumerate(cross_cutting, 1):
            title = cc.get("title", "Untitled")
            desc = cc.get("description", "")
            domains = cc.get("domains", [])
            domain_str = f" ({', '.join(domains)})" if domains else ""
            lines.append(f"{i}. **{title}**{domain_str}")
            if desc:
                lines.append(f"   {desc}")
            lines.append("")

    silent_pass = synthesis.get("_silent_pass", [])
    if silent_pass:
        lines.append("### Silent-Pass Test Warnings")
        lines.append("")
        for i, sp in enumerate(silent_pass, 1):
            test_name = sp.get("test_name", "unknown")
            file_ref = sp.get("file", "unknown")
            line_num = sp.get("line")
            loc_str = f"{file_ref}:{line_num}" if line_num else file_ref
            lines.append(f"{i}. **{test_name}** — `{loc_str}`")
            if sp.get("issue"):
                lines.append(f"   {sp['issue']}")
            lines.append("")

    questions = synthesis.get("questions", [])
    if questions:
        # Cap at 5 most actionable questions to avoid information overload
        capped = questions[:5]
        lines.append("### Questions")
        lines.append("")
        for i, q in enumerate(capped, 1):
            lines.append(f"{i}. {q}")
        if len(questions) > 5:
            lines.append(f"\n_({len(questions) - 5} additional questions omitted for brevity)_")
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


def _format_file_ref(loc: dict, finding: dict | None = None) -> str:
    if not loc and not finding:
        return "unknown"
    if loc:
        f = loc.get("file", loc.get("raw", ""))
        line = loc.get("start_line")
        if f and line:
            return f"{f}:{line}"
        if f:
            return f
    # Holistic findings use "domain" instead of "location"
    if finding:
        domain = finding.get("domain", "")
        if domain:
            return domain
    return "unknown"


@register_step("publish")
class PublishExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        synthesis = inputs.get("synthesis", {})
        holistic = inputs.get("holistic", {})
        mode = inputs.get("mode", "team-review")
        owner = inputs.get("owner", "")
        repo_name = inputs.get("repo", "")
        freshness = inputs.get("freshness", [])
        prs = inputs.get("prs", [])

        if not owner or not repo_name:
            full = inputs.get("full_repo", "")
            if "/" in full:
                owner, repo_name = full.split("/", 1)

        if mode == "self-review":
            return StepResult(
                success=True,
                outputs={"published": False, "reason": "self-review mode: local only"},
            )

        if holistic:
            synthesis = self._enrich_synthesis_with_holistic(synthesis, holistic)

        fallback_pr = prs[0].get("number") if prs else None

        per_pr = synthesis.get("per_pr", [])
        if per_pr:
            results = []
            for pr_synth in per_pr:
                if not pr_synth.get("pr_number") and fallback_pr:
                    pr_synth = {**pr_synth, "pr_number": fallback_pr}
                pr_freshness = [f for f in freshness if f.get("pr_number") == pr_synth.get("pr_number")]
                result = self._publish_single_pr(pr_synth, owner, repo_name, mode, pr_freshness)
                results.append(result)
            all_success = all(r.get("published", False) for r in results)
            any_failed = any(not r.get("published", False) for r in results)
            return StepResult(
                success=not any_failed,
                error="Some PRs failed to publish" if any_failed else None,
                outputs={"published": results, "all_published": all_success},
                artifacts=[
                    {"type": "gh_comment", "pr_number": r.get("pr_number"), "data": r}
                    for r in results
                ],
            )
        else:
            if not synthesis.get("pr_number") and fallback_pr:
                synthesis = {**synthesis, "pr_number": fallback_pr}
            return self._publish_single_pr_result(synthesis, owner, repo_name, mode, freshness)

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

        # Auto-promote COMMENT to APPROVE when there are no blocking findings
        if verdict == "COMMENT":
            agreed = synthesis.get("agreed", [])
            a_only = synthesis.get("a_only", [])
            b_only = synthesis.get("b_only", [])
            blocking = synthesis.get("_holistic_blocking", []) or _collect_blocking(agreed, a_only, b_only)
            if not blocking:
                verdict = "APPROVE"

        event_map = {
            "APPROVE": "APPROVE",
            "CHANGES_REQUESTED": "REQUEST_CHANGES",
            "REQUEST_CHANGES": "REQUEST_CHANGES",
            "NEEDS_DISCUSSION": "COMMENT",
            "COMMENT": "COMMENT",
        }
        gh_event = event_map.get(verdict, "COMMENT")

        post_result = self._post_to_github(owner, repo, pr_number, comment_body, gh_event)
        success = post_result.get("ok", False)
        comment_url = post_result.get("url")

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
            "comment_url": comment_url,
        }

    def _publish_single_pr_result(self, synthesis: dict, owner: str, repo: str,
                                  mode: str, freshness: list) -> StepResult:
        """Wrap single-PR publish in a StepResult for the non-per_pr path."""
        result = self._publish_single_pr(synthesis, owner, repo, mode, freshness)
        if "error" in result:
            return StepResult(success=False, error=result["error"])
        posted = result.get("posted", False)
        return StepResult(
            success=posted,
            error=f"Failed to post review to GitHub PR #{result.get('pr_number')}" if not posted else None,
            outputs={
                "published": result["published"],
                "pr_number": result["pr_number"],
                "verdict": result["verdict"],
                "gh_event": result["gh_event"],
                "comment_url": result.get("comment_url"),
                "comment_body": result.get("body"),
                "event_type": result["gh_event"],
            },
            artifacts=[{
                "type": "gh_comment",
                "pr_number": result["pr_number"],
                "data": {"body": result["body"], "event": result["gh_event"],
                         "posted": result["posted"], "published": result["published"],
                         "verdict": result.get("verdict"), "pr_number": result["pr_number"],
                         "comment_url": result.get("comment_url")},
            }],
        )

    @staticmethod
    def _enrich_synthesis_with_holistic(synthesis: dict, holistic: dict) -> dict:
        """Overlay holistic blocking/non-blocking onto synthesis for richer publication."""
        enriched = dict(synthesis)
        blocking = holistic.get("blocking_findings", [])
        non_blocking = holistic.get("non_blocking_findings", [])
        if blocking or non_blocking:
            enriched["_holistic_blocking"] = blocking
            enriched["_holistic_non_blocking"] = non_blocking
        if holistic.get("verdict"):
            enriched["verdict"] = holistic["verdict"]
        if holistic.get("summary"):
            enriched["summary"] = holistic["summary"]
        if holistic.get("cross_cutting_findings"):
            enriched["_cross_cutting"] = holistic["cross_cutting_findings"]
        if holistic.get("silent_pass_findings"):
            enriched["_silent_pass"] = holistic["silent_pass_findings"]
        return enriched

    def _fetch_existing_findings(self, owner: str, repo: str, pr_number: int) -> set[str]:
        """Fetch keyword fragments from all existing review/comment bodies on the PR.

        Stores the full body text (lowercased) so we can do substring matching
        against finding titles and key phrases, not just first 200 chars.
        """
        existing_bodies: list[str] = []
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{owner}/{repo}/pulls/{pr_number}/reviews",
                 "--paginate", "--jq", '.[].body'],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                for body in result.stdout.strip().split("\n"):
                    if body.strip():
                        existing_bodies.append(body.strip().lower())
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
                        existing_bodies.append(body.strip().lower())
        except Exception:
            pass
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{owner}/{repo}/issues/{pr_number}/comments",
                 "--paginate", "--jq", '.[].body'],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                for body in result.stdout.strip().split("\n"):
                    if body.strip():
                        existing_bodies.append(body.strip().lower())
        except Exception:
            pass
        # Concatenate all bodies into one big searchable blob
        return set(existing_bodies) if existing_bodies else set()

    @staticmethod
    def _finding_matches_existing(finding: dict, existing: set[str]) -> bool:
        """Check if a finding was already raised using multi-signal matching.

        Checks: exact title, key noun phrases from the title (3+ word chunks),
        and distinctive technical terms that are unlikely to be coincidental.
        """
        inner = finding.get("finding_a", finding.get("finding", finding))
        title = inner.get("title", "").lower()
        if not title:
            return False

        # Direct title match in any existing body
        if any(title in body for body in existing):
            return True

        # Extract distinctive key phrases (3+ consecutive words)
        words = re.split(r'\s+', title)
        if len(words) >= 4:
            for start in range(len(words) - 2):
                phrase = " ".join(words[start:start + 3])
                if len(phrase) > 15 and any(phrase in body for body in existing):
                    return True

        # Check for distinctive technical terms that indicate the same finding
        tech_terms = re.findall(
            r'(?:cors|mfa|multi.az|ecr.*mutable|logs:\*|permission.boundary'
            r'|abort.*multipart|lifecycle.?config|tag.?mutab)',
            title,
        )
        if tech_terms:
            for term in tech_terms:
                if any(term in body for body in existing):
                    return True

        return False

    def _filter_already_raised(self, synthesis: dict, existing: set[str]) -> dict:
        """Remove findings that were already raised by other reviewers.

        Filters synthesis-level findings (agreed/a_only/b_only) and also
        holistic findings (_holistic_blocking/_holistic_non_blocking).
        """
        if not existing:
            return synthesis

        filtered = dict(synthesis)

        # Filter standard synthesis findings
        for key in ("agreed", "a_only", "b_only"):
            if key in filtered and isinstance(filtered[key], list):
                filtered[key] = [f for f in filtered[key]
                                 if not self._finding_matches_existing(f, existing)]

        # Filter holistic findings too
        for key in ("_holistic_blocking", "_holistic_non_blocking"):
            if key in filtered and isinstance(filtered[key], list):
                filtered[key] = [f for f in filtered[key]
                                 if not self._finding_matches_existing(f, existing)]

        # Filter cross-cutting concerns
        if "_cross_cutting" in filtered and isinstance(filtered["_cross_cutting"], list):
            filtered["_cross_cutting"] = [
                f for f in filtered["_cross_cutting"]
                if not self._finding_matches_existing(f, existing)
            ]

        filtered["total_findings"] = (
            len(filtered.get("agreed", [])) +
            len(filtered.get("a_only", [])) +
            len(filtered.get("b_only", []))
        )
        filtered["agreed_count"] = len(filtered.get("agreed", []))
        filtered["disputed_count"] = len(filtered.get("a_only", [])) + len(filtered.get("b_only", []))

        return filtered

    def _post_to_github(self, owner: str, repo: str, pr_number: int,
                         body: str, event: str) -> dict:
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
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                logger.info(f"Published {event} review to {owner}/{repo} PR {pr_number}")
                url = result.stdout.strip() if result.stdout.strip().startswith("http") else None
                return {"ok": True, "url": url}
            else:
                logger.error(f"gh command failed: {result.stderr}")
                return {"ok": False, "error": result.stderr}
        except Exception as e:
            logger.error(f"Failed to publish to GitHub: {e}")
            return {"ok": False, "error": str(e)}

    @staticmethod
    def _create_followup_entries(owner: str, repo: str, pr_number: int,
                                  synthesis: dict, instance_id: int):
        try:
            from backend.database import get_workflow_db
            db = get_workflow_db()
            review_sha = synthesis.get("head_sha", "")
            if not review_sha:
                for cat in ("agreed", "a_only", "b_only"):
                    for f in synthesis.get(cat, []):
                        inner = f.get("finding_a", f.get("finding", {}))
                        loc = inner.get("location", {}) if isinstance(inner, dict) else {}
                        sha = inner.get("head_sha", "") or loc.get("head_sha", "")
                        if sha:
                            review_sha = sha
                            break
                    if review_sha:
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
