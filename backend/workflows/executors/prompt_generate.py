from __future__ import annotations
"""Prompt Generate step — builds structured review prompts from PR context.

Produces prompts that match the legacy adversarial review specification:
header metadata, context commands, prior review deduplication, persona,
checklist, anti-patterns, cross-cutting concerns, and output format.

Supports two modes:
- team-review: one generic prompt per PR
- self-review / deep-review: one prompt per expert per PR (fan-out)
"""

import json
import logging
import re
import subprocess
from datetime import datetime, timezone
from typing import Optional

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
        experts = inputs.get("experts", [])
        self._human_feedback = self._collect_feedback(inputs)

        if not prs:
            return StepResult(success=False, error="No PRs to generate prompts for")

        per_expert = self.step_config.get("per_expert", False)

        prompts = []
        if per_expert and experts and mode in ("self-review", "deep-review"):
            for pr in prs:
                for expert in experts:
                    prompt_text = self._build_expert_prompt(
                        pr, expert, all_experts=experts, owner=owner, repo=repo, mode=mode
                    )
                    prompts.append(self._prompt_entry(
                        pr, owner, repo, prompt_text,
                        domain=expert["domain_id"],
                        domain_display_name=expert.get("display_name"),
                    ))
        else:
            dominant_domain = experts[0] if experts else None
            for pr in prs:
                prompt_text = self._build_team_prompt(
                    pr, dominant_domain, owner=owner, repo=repo, mode=mode
                )
                prompts.append(self._prompt_entry(pr, owner, repo, prompt_text))

        return StepResult(
            success=True,
            outputs={"prompts": prompts},
            artifacts=[{
                "type": "prompts",
                "data": {
                    "prompts": [
                        {"pr_number": p["pr_number"], "pr_title": p.get("pr_title", ""),
                         "domain": p.get("domain"), "prompt": p["prompt"]}
                        for p in prompts
                    ],
                    "mode": mode,
                    "count": len(prompts),
                },
            }],
        )

    @staticmethod
    def _prompt_entry(pr: dict, owner: str, repo: str, prompt: str,
                      domain: Optional[str] = None,
                      domain_display_name: Optional[str] = None) -> dict:
        pr_number = pr.get("number", 0)
        author = pr.get("author", {})
        author_login = author.get("login", "") if isinstance(author, dict) else str(author)
        entry = {
            "pr_number": pr_number,
            "pr_url": pr.get("url", f"https://github.com/{owner}/{repo}/pull/{pr_number}"),
            "pr_title": pr.get("title", ""),
            "pr_author": author_login,
            "prompt": prompt,
            "owner": owner,
            "repo": repo,
            "additions": pr.get("additions", 0),
            "deletions": pr.get("deletions", 0),
            "head_sha": pr.get("headRefOid", ""),
        }
        if domain:
            entry["domain"] = domain
        if domain_display_name:
            entry["domain_display_name"] = domain_display_name
        return entry

    @staticmethod
    def _collect_feedback(inputs: dict) -> list[dict]:
        """Gather human feedback relevant to prompt generation (targets 'experts' or 'prompt')."""
        all_fb = inputs.get("human_feedback", [])
        return [fb for fb in all_fb if fb.get("retry_target") in ("experts", "prompt")]

    def _feedback_section(self) -> str:
        """Build a prompt section from human feedback if present."""
        fb = getattr(self, "_human_feedback", [])
        if not fb:
            return ""
        latest = fb[-1]
        lines = [
            "## Human Reviewer Guidance",
            f"The human reviewer provided this direction (iteration {latest.get('iteration', '?')}):",
            f"> {latest['feedback']}",
            "Incorporate this guidance into your review focus and priorities.",
        ]
        if len(fb) > 1:
            lines.append("\nPrior guidance (already addressed):")
            for entry in fb[:-1]:
                lines.append(f"- (iteration {entry.get('iteration', '?')}): {entry['feedback']}")
        return "\n".join(lines)

    # --- Prompt builders ---

    def _build_team_prompt(self, pr: dict, dominant_domain: Optional[dict],
                           owner: str, repo: str, mode: str) -> str:
        sections = []
        sections.append(self._header(pr, owner, repo))
        sections.append(self._context_commands(pr, owner, repo))
        sections.append(self._dedup_section(owner, repo, pr.get("number", 0)))

        if dominant_domain:
            sections.append(self._persona_section(dominant_domain))
            sections.append(self._checklist_section(dominant_domain))
            sections.append(self._anti_patterns_section(dominant_domain))
        else:
            sections.append(self._generic_persona())

        fb = self._feedback_section()
        if fb:
            sections.append(fb)
        sections.append(self._depth_expectations_section(pr))
        sections.append(self._cross_file_analysis_section())
        sections.append(self._diff_ingestion_section(pr))
        sections.append(self._output_format(pr))
        return "\n\n".join(s for s in sections if s)

    def _build_expert_prompt(self, pr: dict, expert: dict,
                             all_experts: list[dict],
                             owner: str, repo: str, mode: str) -> str:
        sections = []
        sections.append(self._header(pr, owner, repo))
        sections.append(self._context_commands(pr, owner, repo))
        sections.append(self._dedup_section(owner, repo, pr.get("number", 0)))
        sections.append(self._persona_section(expert))
        sections.append(self._review_focus(expert))
        sections.append(self._checklist_section(expert))
        sections.append(self._anti_patterns_section(expert))
        sections.append(self._cross_cutting_section(expert, all_experts))
        fb = self._feedback_section()
        if fb:
            sections.append(fb)
        sections.append(self._depth_expectations_section(pr))
        sections.append(self._cross_file_analysis_section())
        sections.append(self._diff_ingestion_section(pr))
        sections.append(self._output_format(pr))
        return "\n\n".join(s for s in sections if s)

    # --- Prompt sections ---

    def _header(self, pr: dict, owner: str, repo: str) -> str:
        pr_number = pr.get("number", 0)
        title = pr.get("title", "")
        author = pr.get("author", {})
        author_login = author.get("login", "") if isinstance(author, dict) else str(author)
        body = pr.get("body", "") or ""
        head_sha = pr.get("headRefOid", "")[:8] if pr.get("headRefOid") else "unknown"

        jira_refs = re.findall(r'(SIM-\d+)', f"{title} {body}", re.IGNORECASE)
        jira_str = ", ".join(jira_refs[:3]) if jira_refs else "None"

        code_owner_reviews = self._fetch_code_owner_reviews(owner, repo, pr_number)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        additions = pr.get("additions", 0)
        deletions = pr.get("deletions", 0)
        total = additions + deletions
        size_note = ""
        if total > LARGE_DIFF_THRESHOLD:
            size_note = f"\nDiff Size: {total} lines (LARGE — use chunked review strategy)"

        lines = [
            f"# Review Prompt: PR #{pr_number} — {title}",
            f"Author: {author_login}",
            f"Head SHA: {head_sha}",
            f"Jira: {jira_str}",
            f"Code Owner Reviews: {code_owner_reviews or 'None'}",
            f"Generated: {now}",
        ]
        if size_note:
            lines.append(size_note)
        return "\n".join(lines)

    @staticmethod
    def _context_commands(pr: dict, owner: str, repo: str) -> str:
        pr_number = pr.get("number", 0)
        body = pr.get("body", "") or ""
        title = pr.get("title", "")
        jira_refs = re.findall(r'(SIM-\d+)', f"{title} {body}", re.IGNORECASE)
        total_lines = pr.get("additions", 0) + pr.get("deletions", 0)

        lines = [
            "## Context Acquisition Commands",
            "Run ALL of these before analysis:",
            "",
            "```bash",
            f"gh pr view {pr_number} --repo {owner}/{repo} "
            "--json body,title,author,labels,headRefName,baseRefName",
            f"gh pr diff {pr_number} --repo {owner}/{repo}",
            f"gh api repos/{owner}/{repo}/pulls/{pr_number}/comments",
            f"gh api repos/{owner}/{repo}/pulls/{pr_number}/reviews",
        ]
        for ref in jira_refs[:3]:
            lines.append(
                f'acli jira workitem view {ref} --fields "summary,status,description,assignee"'
            )
        lines.append("```")

        if total_lines > LARGE_DIFF_THRESHOLD:
            lines.extend([
                "",
                "For this large diff, also use file-by-file review:",
                "",
                "```bash",
                f"gh pr diff {pr_number} --repo {owner}/{repo} --name-only",
                f"# Then review specific paths:",
                f"# gh pr diff {pr_number} --repo {owner}/{repo} -- 'path/to/file'",
                "```",
            ])

        return "\n".join(lines)

    def _dedup_section(self, owner: str, repo: str, pr_number: int) -> str:
        lines = [
            "## Prior Review Deduplication (mandatory)",
            "",
            "After reading existing reviews and comments from the commands above:",
            "",
            "- Do NOT restate findings already flagged by other reviewers",
            "- Reference and reinforce findings you agree with if adding meaningful context",
            "- Disagree explicitly if you believe a prior finding is incorrect",
            "- Focus on gaps — what did prior reviewers miss?",
        ]

        dedup_summary = self._fetch_github_reviews(owner, repo, pr_number)
        if dedup_summary:
            lines.extend(["", dedup_summary])

        db_dedup = self._check_prior_reviews_db(owner, repo, pr_number)
        if db_dedup:
            lines.extend(["", db_dedup])

        return "\n".join(lines)

    @staticmethod
    def _persona_section(domain: dict) -> str:
        persona = domain.get("persona", "")
        if not persona:
            return ""
        return f"## Persona\n\n{persona}"

    @staticmethod
    def _generic_persona() -> str:
        return (
            "## Persona\n\n"
            "Senior software engineer with broad expertise across the full stack. "
            "Focus on code correctness, maintainability, error handling, edge cases, "
            "performance, and security. Be specific and actionable in your findings."
        )

    @staticmethod
    def _review_focus(domain: dict) -> str:
        scope = domain.get("scope", "")
        if not scope:
            return ""
        return f"## Review Focus\n\n{scope}"

    @staticmethod
    def _checklist_section(domain: dict) -> str:
        checklist = domain.get("checklist", [])
        if not checklist:
            return ""
        items = "\n".join(f"{i}. {item}" for i, item in enumerate(checklist, 1))
        return f"## Review Checklist\n\n{items}"

    @staticmethod
    def _anti_patterns_section(domain: dict) -> str:
        patterns = domain.get("anti_patterns", [])
        if not patterns:
            return ""
        items = "\n".join(f"- {p}" for p in patterns)
        return f"## Known Anti-Patterns\n\nWatch for these specific patterns in this domain:\n{items}"

    @staticmethod
    def _cross_cutting_section(expert: dict, all_experts: list[dict]) -> str:
        domain_id = expert.get("domain_id", "")
        siblings = [e["display_name"] for e in all_experts if e["domain_id"] != domain_id]
        if not siblings:
            return ""
        sibling_list = ", ".join(siblings)
        return (
            "## Cross-Cutting Concerns\n\n"
            f"You are the `{expert.get('display_name', domain_id)}` expert for this PR. "
            "Be extra critical within your domain.\n"
            "Flag cross-cutting concerns you notice outside your domain, but mark them as "
            "`[CROSS-CUTTING — defer to {other-domain} expert]` rather than analyzing them deeply.\n"
            f"Sibling experts covering other domains: {sibling_list}."
        )

    @staticmethod
    def _depth_expectations_section(pr: dict) -> str:
        changed_files = pr.get("changedFiles", 0)
        additions = pr.get("additions", 0)
        deletions = pr.get("deletions", 0)
        total = additions + deletions

        lines = [
            "## Depth Expectations",
            "",
            "Your review quality is measured by the synthesis phase. Calibration guidelines:",
            "",
        ]
        if changed_files >= 50 or total >= 5000:
            lines.append(f"- This is a LARGE PR ({changed_files} files, {total} lines). Expect 5-10+ findings.")
        elif changed_files >= 10 or total >= 1000:
            lines.append(f"- This is a medium PR ({changed_files} files, {total} lines). Expect 3+ findings.")
        else:
            lines.append(f"- This is a small PR ({changed_files} files, {total} lines). Findings should be proportionate.")

        lines.extend([
            "- Zero findings + zero questions = re-examine. Even clean PRs deserve questions about design intent.",
            "- These are guidelines, not quotas — don't fabricate findings to hit a number.",
            "- But if your review is significantly shorter than what the PR's complexity warrants, look harder.",
        ])
        return "\n".join(lines)

    @staticmethod
    def _cross_file_analysis_section() -> str:
        return (
            "## Cross-File Analysis\n\n"
            "After reading the diff, perform cross-file analysis. Many real bugs live at boundaries:\n\n"
            "- **Contract mismatches:** Does file A call a function with assumptions that file B's implementation doesn't satisfy?\n"
            "- **Naming inconsistencies:** Is the same concept named differently across files?\n"
            "- **Incomplete migrations:** If the PR changes a pattern in some files, does it miss applying the same change in others?\n"
            "- **Initialization order:** If file A removes a safety check, is there proof that file B guarantees the precondition?"
        )

    @staticmethod
    def _diff_ingestion_section(pr: dict) -> str:
        total = pr.get("additions", 0) + pr.get("deletions", 0)
        pr_number = pr.get("number", 0)

        if total <= 5000:
            return (
                "## Diff Ingestion\n\n"
                f"This PR has {total} lines changed. Read the ENTIRE diff — do not sample or skim."
            )

        return (
            "## Diff Ingestion\n\n"
            f"This PR has {total} lines changed (LARGE). Use a chunked strategy:\n\n"
            f"1. `gh pr diff {pr_number} --name-only` to get the complete file list\n"
            "2. Categorize files: source code, config, tests, docs, generated\n"
            "3. Read ALL source code and config changes in full\n"
            "4. Sample test files and generated code for anomalies\n"
            "5. Document which files you reviewed and which you skipped (with justification)"
        )

    @staticmethod
    def _output_format(pr: dict) -> str:
        pr_number = pr.get("number", 0)
        title = pr.get("title", "")
        changed_files = pr.get("changedFiles", 0)
        total = pr.get("additions", 0) + pr.get("deletions", 0)

        cap_note = ""
        if changed_files >= 50 or total >= 5000:
            cap_note = (
                "\n**Large PR note**: Cap your total findings at 15-20 max. "
                "Group minor issues by category rather than listing each individually.\n"
            )

        return (
            "## Severity Guide\n\n"
            "- **Blocking/Critical**: Production data loss, security vulnerability, crash in mainline path. "
            "You MUST describe a concrete production failure scenario — if you cannot, it is NOT blocking.\n"
            "- **Major**: Correctness issue with workaround, performance regression, missing error handling on external input. "
            "Non-blocking by default.\n"
            "- **Minor**: Style, naming, documentation, test coverage gap. Never blocking.\n\n"
            "Default to non-blocking. When in doubt, mark as major (non-blocking).\n"
            f"{cap_note}\n"
            "## Output Format\n\n"
            "Your review MUST use this exact structure:\n\n"
            f"# Review: PR #{pr_number} — {title}\n\n"
            "## Summary\n\n"
            "(2-3 sentence overview)\n\n"
            "## Verdict\n\n"
            "(APPROVE | CHANGES_REQUESTED | NEEDS_DISCUSSION)\n"
            "(1-2 sentence justification)\n\n"
            "## Blocking Findings\n\n"
            "(Numbered. Each: file:line, description, severity, evidence from diff, suggested fix)\n\n"
            "## Non-Blocking Findings\n\n"
            "(Numbered. Each: file:line, description, suggestion)\n\n"
            "## Questions for Author\n\n"
            "(Numbered list of clarifying questions)\n\n"
            "## Checklist Completion\n\n"
            "(Which checklist items were verified, which could not be verified and why)\n\n"
            "## Files Reviewed\n\n"
            "(List of key files inspected)"
        )

    # --- Data fetchers ---

    def _fetch_github_reviews(self, owner: str, repo: str, pr_number: int) -> str:
        if not owner or not repo or not pr_number:
            return ""
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{owner}/{repo}/pulls/{pr_number}/reviews",
                 "--paginate",
                 "--jq", '.[] | "\(.user.login): \(.state)"'],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                review_lines = result.stdout.strip().split("\n")[:20]
                code_owners = self._get_code_owners()
                owner_reviews = []
                other_reviews = []
                for line in review_lines:
                    user = line.split(":")[0].strip() if ":" in line else ""
                    if user in code_owners:
                        owner_reviews.append(line)
                    else:
                        other_reviews.append(line)

                parts = []
                if owner_reviews:
                    parts.append("Code owner reviews: " + "; ".join(owner_reviews))
                if other_reviews:
                    parts.append("Other reviews: " + "; ".join(other_reviews))
                return "\n".join(parts) if parts else ""
        except Exception as e:
            logger.debug(f"Failed to fetch GitHub reviews for PR #{pr_number}: {e}")
        return ""

    def _fetch_code_owner_reviews(self, owner: str, repo: str, pr_number: int) -> str:
        if not owner or not repo or not pr_number:
            return ""
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{owner}/{repo}/pulls/{pr_number}/reviews",
                 "--paginate",
                 "--jq", '.[] | "\(.user.login): \(.state)"'],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                code_owners = self._get_code_owners()
                lines = result.stdout.strip().split("\n")
                owner_lines = []
                for line in lines:
                    user = line.split(":")[0].strip() if ":" in line else ""
                    if user in code_owners:
                        owner_lines.append(line.strip())
                return "; ".join(owner_lines) if owner_lines else ""
        except Exception as e:
            logger.debug(f"Failed to fetch code owner reviews: {e}")
        return ""

    @staticmethod
    def _get_code_owners() -> set[str]:
        try:
            from backend.database import get_workflow_db
            db = get_workflow_db()
            with db.db.connection() as conn:
                rows = conn.execute(
                    "SELECT github_handle FROM code_owner_registry WHERE is_reviewer=1"
                ).fetchall()
                return {r["github_handle"] for r in rows}
        except Exception:
            return set()

    @staticmethod
    def _check_prior_reviews_db(owner: str, repo: str, pr_number: int) -> str:
        try:
            from backend.database import get_reviews_db
            reviews_db = get_reviews_db()
            full_repo = f"{owner}/{repo}"
            latest = reviews_db.get_latest_review_for_pr(full_repo, pr_number)
            if latest and latest.get("status") == "completed":
                return (
                    "Internal DB: A prior review exists for this PR. "
                    "Focus on gaps and new changes since the last review."
                )
        except Exception as e:
            logger.debug(f"Could not check prior reviews: {e}")
        return ""

    def _fetch_jira_context(self, body: str, title: str) -> str:
        combined = f"{title} {body}"
        jira_refs = re.findall(r'(SIM-\d+)', combined, re.IGNORECASE)
        if not jira_refs:
            return ""
        context_parts = []
        for ref in jira_refs[:3]:
            try:
                result = subprocess.run(
                    ["acli", "jira", "workitem", "view", ref],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    context_parts.append(f"{ref}: {result.stdout.strip()[:500]}")
            except FileNotFoundError:
                logger.debug("acli not available, skipping Jira context")
                return ""
            except Exception as e:
                logger.debug(f"Failed to fetch Jira context for {ref}: {e}")
        return "\n".join(context_parts) if context_parts else ""
