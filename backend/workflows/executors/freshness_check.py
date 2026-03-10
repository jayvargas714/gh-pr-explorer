from __future__ import annotations
"""Freshness Check step — AI-powered PR state verification before publication.

Goes beyond simple SHA comparison to evaluate the full live PR state:
new commits (with messages/diffs), new reviews from other reviewers,
new comments, and author responses. An AI agent classifies each finding
as STILL_VALID, RESOLVED, NEEDS_RECHECK, or SUPERSEDED with justification.

Falls back to mechanical file-based staleness tagging when no agent is
configured or when the PR is CURRENT (SHA unchanged).
"""

import json
import logging
import subprocess
import time

from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.json_parser import extract_json
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)


@register_step("freshness_check")
class FreshnessCheckExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        reviews = inputs.get("reviews", [])
        synthesis = inputs.get("synthesis", {})
        holistic = inputs.get("holistic", {})
        owner = inputs.get("owner", "")
        repo = inputs.get("repo", "")
        inst_id = self.instance_config.get("_instance_id", 0)
        step_id = self.step_config.get("_step_id", "")

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

            # Get synthesis for this PR
            per_pr = synthesis.get("per_pr", [])
            pr_synthesis = next(
                (p for p in per_pr if p.get("pr_number") == pr_number),
                synthesis,
            )

            # Collect findings; only include holistic for the first PR to
            # avoid attributing global findings to every PR in multi-PR runs
            pr_holistic = holistic if len(prs_checked) == 1 else {}
            all_findings = self._collect_findings(pr_synthesis, pr_holistic)

            # Try AI-powered freshness verification if agent configured and PR is not current
            ai_result = None
            agent_name = self.step_config.get("agent")
            if agent_name and classification != "CURRENT" and all_findings:
                pr_state = self._fetch_full_pr_state(
                    owner, repo, pr_number, review_sha
                )
                ai_result = self._ai_freshness_check(
                    agent_name, all_findings, pr_state, classification,
                    changed_files, owner, repo, pr_number, inst_id, step_id,
                )

            if ai_result:
                freshness_results.append({
                    "pr_number": pr_number,
                    "classification": ai_result.get("classification", classification),
                    "review_sha": review_sha,
                    "current_sha": current_sha,
                    "changed_files": changed_files[:50],
                    "finding_assessments": ai_result.get("finding_assessments", []),
                    "affected_findings": [
                        a["title"] for a in ai_result.get("finding_assessments", [])
                        if a.get("status") in ("NEEDS_RECHECK", "SUPERSEDED")
                    ],
                    "unaffected_findings": [
                        a["title"] for a in ai_result.get("finding_assessments", [])
                        if a.get("status") == "STILL_VALID"
                    ],
                    "resolved_findings": [
                        a["title"] for a in ai_result.get("finding_assessments", [])
                        if a.get("status") == "RESOLVED"
                    ],
                    "recommendation": ai_result.get("recommendation", ""),
                    "pr_state_summary": ai_result.get("pr_state_summary", ""),
                    "ai_powered": True,
                })
            else:
                # Mechanical fallback
                affected, unaffected = self._tag_finding_staleness(
                    pr_synthesis, changed_files, classification
                )
                recommendation = self._build_recommendation(
                    classification, affected
                )
                freshness_results.append({
                    "pr_number": pr_number,
                    "classification": classification,
                    "review_sha": review_sha,
                    "current_sha": current_sha,
                    "changed_files": changed_files[:50],
                    "affected_findings": affected,
                    "unaffected_findings": unaffected,
                    "recommendation": recommendation,
                    "ai_powered": False,
                })

        all_current = all(r["classification"] == "CURRENT" for r in freshness_results)
        any_major = any(r["classification"] in ("STALE-MAJOR", "SUPERSEDED")
                        for r in freshness_results)

        outputs = {
            "freshness": freshness_results,
            "all_fresh": all_current,
            "any_stale_major": any_major,
            "synthesis": synthesis,
            "reviews": reviews,
        }
        # Propagate usage from AI freshness results
        for r in freshness_results:
            if r.get("usage"):
                outputs["usage"] = r.pop("usage")
                break

        return StepResult(
            success=True,
            outputs=outputs,
            artifacts=[{
                "type": "freshness",
                "data": {
                    "checks": freshness_results,
                    "all_fresh": all_current,
                    "any_stale_major": any_major,
                },
            }],
        )

    # ------------------------------------------------------------------
    # Full PR state fetching
    # ------------------------------------------------------------------

    def _fetch_full_pr_state(self, owner: str, repo: str,
                             pr_number: int, review_sha: str | None) -> dict:
        """Fetch comprehensive PR state: new commits, reviews, comments."""
        state: dict = {
            "new_commits": [],
            "new_reviews": [],
            "new_comments": [],
            "pr_status": {},
        }

        # PR metadata (state, labels, assignees, mergeable)
        state["pr_status"] = self._fetch_pr_metadata(owner, repo, pr_number)

        # New commits since review SHA
        review_cutoff = None
        if review_sha:
            state["new_commits"] = self._fetch_commits_since(
                owner, repo, pr_number, review_sha
            )
            # Derive temporal cutoff from the first new commit's date
            if state["new_commits"]:
                review_cutoff = state["new_commits"][0].get("date")

        # Reviews and comments since the review was created
        state["new_reviews"] = self._fetch_recent_reviews(
            owner, repo, pr_number, since=review_cutoff
        )
        state["new_comments"] = self._fetch_recent_comments(
            owner, repo, pr_number, since=review_cutoff
        )

        return state

    def _fetch_pr_metadata(self, owner: str, repo: str, pr_number: int) -> dict:
        cmd = [
            "gh", "pr", "view", str(pr_number),
            "--repo", f"{owner}/{repo}",
            "--json", "state,labels,assignees,mergeable,title,author,reviewDecision",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return {
                    "state": data.get("state", ""),
                    "title": data.get("title", ""),
                    "author": data.get("author", {}).get("login", ""),
                    "labels": [l.get("name", "") for l in data.get("labels", [])],
                    "mergeable": data.get("mergeable", ""),
                    "review_decision": data.get("reviewDecision", ""),
                }
        except Exception as e:
            logger.warning(f"Failed to fetch PR metadata for #{pr_number}: {e}")
        return {}

    def _fetch_commits_since(self, owner: str, repo: str,
                             pr_number: int, since_sha: str) -> list[dict]:
        """Fetch commits on the PR, returning those after the review SHA."""
        cmd = [
            "gh", "api",
            f"repos/{owner}/{repo}/pulls/{pr_number}/commits",
            "--paginate",
            "--jq", '[.[] | {sha: .sha, message: .commit.message, author: .commit.author.name, date: .commit.author.date}]',
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                all_commits = json.loads(result.stdout)
                # Find commits after the review SHA
                found_review = False
                new_commits = []
                for c in all_commits:
                    if found_review:
                        new_commits.append(c)
                    if c.get("sha", "").startswith(since_sha[:12]):
                        found_review = True
                # If we didn't find the review SHA (force-push), return all
                return new_commits if found_review else all_commits[-10:]
        except Exception as e:
            logger.warning(f"Failed to fetch commits for PR #{pr_number}: {e}")
        return []

    def _fetch_recent_reviews(self, owner: str, repo: str,
                              pr_number: int, since: str | None = None) -> list[dict]:
        """Fetch PR reviews, optionally filtered to those after `since` timestamp."""
        cmd = [
            "gh", "api",
            f"repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            "--paginate",
            "--jq", '[.[] | {user: .user.login, state: .state, body: (.body // "")[0:500], submitted_at: .submitted_at}]',
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                reviews = json.loads(result.stdout)
                if since:
                    reviews = [r for r in reviews if (r.get("submitted_at") or "") >= since]
                return reviews
        except Exception as e:
            logger.warning(f"Failed to fetch reviews for PR #{pr_number}: {e}")
        return []

    def _fetch_recent_comments(self, owner: str, repo: str,
                               pr_number: int, since: str | None = None) -> list[dict]:
        """Fetch issue comments and review comments, optionally filtered by `since`."""
        comments = []

        # Issue comments (general discussion)
        cmd = [
            "gh", "api",
            f"repos/{owner}/{repo}/issues/{pr_number}/comments",
            "--paginate",
            "--jq", '[.[] | {user: .user.login, body: (.body // "")[0:500], created_at: .created_at}]',
        ]
        if since:
            # GitHub API supports ?since= for issue comments
            cmd[2] = f"repos/{owner}/{repo}/issues/{pr_number}/comments?since={since}"
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                for c in json.loads(result.stdout):
                    c["type"] = "issue_comment"
                    comments.append(c)
        except Exception as e:
            logger.warning(f"Failed to fetch issue comments for PR #{pr_number}: {e}")

        # Review comments (inline code comments)
        cmd2 = [
            "gh", "api",
            f"repos/{owner}/{repo}/pulls/{pr_number}/comments",
            "--paginate",
            "--jq", '[.[] | {user: .user.login, body: (.body // "")[0:300], path: .path, line: .line, created_at: .created_at}]',
        ]
        if since:
            cmd2[2] = f"repos/{owner}/{repo}/pulls/{pr_number}/comments?since={since}"
        try:
            result = subprocess.run(cmd2, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                for c in json.loads(result.stdout):
                    c["type"] = "review_comment"
                    comments.append(c)
        except Exception as e:
            logger.warning(f"Failed to fetch review comments for PR #{pr_number}: {e}")

        return comments

    # ------------------------------------------------------------------
    # AI-powered freshness verification
    # ------------------------------------------------------------------

    def _ai_freshness_check(self, agent_name: str, findings: list[dict],
                            pr_state: dict, classification: str,
                            changed_files: list[str],
                            owner: str, repo: str, pr_number: int,
                            inst_id: int, step_id: str) -> dict | None:
        """Dispatch findings + PR state to an AI agent for freshness evaluation."""
        from backend.agents import get_agent, AgentStatus
        from backend.workflows.executors.agent_review import _set_live_output, _clear_live_output

        try:
            agent = get_agent(agent_name)
        except Exception as e:
            logger.warning(f"Freshness AI agent '{agent_name}' unavailable: {e}")
            return None

        prompt = self._build_freshness_prompt(
            findings, pr_state, classification, changed_files,
            owner, repo, pr_number,
        )

        context = {
            "pr_number": pr_number,
            "owner": owner,
            "repo": repo,
            "phase": "freshness",
            "task": "freshness_check",
            "instance_id": inst_id,
        }

        from backend.workflows.cancellation import (
            is_cancelled, register_agent, unregister_agent, AGENT_POLL_TIMEOUT,
        )
        try:
            handle = agent.start_review(prompt, context)
            if inst_id:
                register_agent(inst_id, agent, handle)
            elapsed = 0
            try:
                while True:
                    if inst_id and is_cancelled(inst_id):
                        agent.cancel(handle)
                        return None
                    status = agent.check_status(handle)
                    if status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED):
                        break
                    if elapsed >= AGENT_POLL_TIMEOUT:
                        logger.error(f"Freshness AI timed out after {elapsed}s")
                        agent.cancel(handle)
                        break
                    live = agent.get_live_output(handle)
                    if live and inst_id and step_id:
                        _set_live_output(inst_id, step_id, live)
                    time.sleep(5)
                    elapsed += 5
            finally:
                if inst_id:
                    unregister_agent(inst_id, handle)
                if inst_id and step_id:
                    _clear_live_output(inst_id, step_id)

            if status == AgentStatus.COMPLETED:
                artifact = agent.get_output(handle)
                agent.cleanup(handle)
                result = self._parse_ai_freshness_output(artifact.content_md, classification)
                if result is not None and artifact.usage:
                    result["usage"] = artifact.usage
                return result
            else:
                agent.cleanup(handle)
                logger.warning("Freshness AI failed, falling back to mechanical")
                return None
        except Exception as e:
            logger.error(f"Freshness AI error: {e}")
            return None

    def _build_freshness_prompt(self, findings: list[dict], pr_state: dict,
                                classification: str, changed_files: list[str],
                                owner: str, repo: str, pr_number: int) -> str:
        sections = []

        sections.append(
            "You are a senior code review analyst performing a FRESHNESS CHECK.\n"
            "A code review was completed, but the PR has changed since then.\n"
            "Your job: evaluate each review finding against the current PR state\n"
            "to determine if the finding is still valid, resolved, or needs rechecking.\n"
        )

        sections.append(f"## PR #{pr_number} ({owner}/{repo})")
        sections.append(f"Staleness classification: **{classification}**")

        # PR metadata
        meta = pr_state.get("pr_status", {})
        if meta:
            sections.append(f"- State: {meta.get('state', 'unknown')}")
            sections.append(f"- Author: {meta.get('author', 'unknown')}")
            sections.append(f"- Review decision: {meta.get('review_decision', 'none')}")
            sections.append(f"- Mergeable: {meta.get('mergeable', 'unknown')}")
            labels = meta.get("labels", [])
            if labels:
                sections.append(f"- Labels: {', '.join(labels)}")

        # Changed files
        if changed_files:
            sections.append(f"\n## Changed Files Since Review ({len(changed_files)} files)")
            for f in changed_files[:30]:
                sections.append(f"- `{f}`")

        # New commits
        new_commits = pr_state.get("new_commits", [])
        if new_commits:
            sections.append(f"\n## New Commits Since Review ({len(new_commits)} commits)")
            for c in new_commits[:15]:
                msg = c.get("message", "").split("\n")[0][:200]
                sections.append(f"- `{c.get('sha', '')[:8]}` ({c.get('author', '')}): {msg}")

        # Reviews from other reviewers
        new_reviews = pr_state.get("new_reviews", [])
        if new_reviews:
            sections.append(f"\n## PR Reviews ({len(new_reviews)} reviews)")
            for r in new_reviews[:10]:
                body = r.get("body", "").strip()
                body_preview = f": {body[:200]}..." if body else ""
                sections.append(
                    f"- **{r.get('user', '?')}** [{r.get('state', '?')}] "
                    f"({r.get('submitted_at', '')}){body_preview}"
                )

        # Comments (author responses, discussion)
        new_comments = pr_state.get("new_comments", [])
        if new_comments:
            sections.append(f"\n## PR Comments ({len(new_comments)} comments)")
            pr_author = meta.get("author", "")
            for c in new_comments[:20]:
                user = c.get("user", "?")
                is_author = " [PR AUTHOR]" if user == pr_author else ""
                body = c.get("body", "").strip()[:300]
                ctype = "inline" if c.get("type") == "review_comment" else "comment"
                path = f" on `{c.get('path', '')}`" if c.get("path") else ""
                sections.append(
                    f"- **{user}**{is_author} ({ctype}{path}, {c.get('created_at', '')}):\n  > {body}"
                )

        # Findings to evaluate
        sections.append(f"\n## Findings to Evaluate ({len(findings)} findings)")
        for i, f in enumerate(findings, 1):
            title = f.get("title", "Untitled")
            severity = f.get("severity", "unknown")
            file_loc = f.get("file", "")
            problem = f.get("problem", "")[:300]
            fix = f.get("fix", "")[:200]
            source = f.get("source", "")
            domain = f.get("domain", "")

            loc_str = f" in `{file_loc}`" if file_loc else ""
            source_str = f" (source: {source})" if source else ""
            domain_str = f" [domain: {domain}]" if domain else ""

            sections.append(
                f"### Finding {i}: {title}\n"
                f"- Severity: {severity}{source_str}{domain_str}\n"
                f"- Location: {loc_str}\n"
                f"- Problem: {problem}\n"
                f"- Suggested fix: {fix}"
            )

        # Instructions
        sections.append(
            "\n## Your Task\n\n"
            "For each finding, evaluate whether it is still valid given:\n"
            "1. New commits — did the author address this issue?\n"
            "2. Changed files — was the relevant code modified?\n"
            "3. Author comments — did the author respond to or acknowledge this?\n"
            "4. Other reviewer feedback — did another reviewer confirm or dismiss this?\n"
            "5. PR state — is the PR merged/closed, making findings moot?\n\n"
            "Classify each finding as:\n"
            "- **STILL_VALID**: Issue has not been addressed\n"
            "- **RESOLVED**: Evidence that the issue was fixed (commit, comment, or code change)\n"
            "- **NEEDS_RECHECK**: Related code changed but unclear if issue is fixed\n"
            "- **SUPERSEDED**: Branch was force-pushed/rebased, finding may not apply\n\n"
            "Also provide an overall recommendation for the reviewer at the human gate.\n\n"
            "## Output Format\n\n"
            "Output valid JSON only:\n"
            "```json\n"
            "{\n"
            '  "classification": "CURRENT|STALE-MINOR|STALE-MAJOR|SUPERSEDED",\n'
            '  "pr_state_summary": "1-2 sentence summary of what changed on the PR since review",\n'
            '  "finding_assessments": [\n'
            "    {\n"
            '      "title": "Finding title",\n'
            '      "status": "STILL_VALID|RESOLVED|NEEDS_RECHECK|SUPERSEDED",\n'
            '      "justification": "Why this status was assigned",\n'
            '      "evidence": "Specific commit/comment/change that supports this assessment"\n'
            "    }\n"
            "  ],\n"
            '  "recommendation": "Overall recommendation for the human reviewer"\n'
            "}\n"
            "```\n"
        )

        return "\n".join(sections)

    def _parse_ai_freshness_output(self, content: str, fallback_classification: str) -> dict | None:
        """Parse AI freshness output JSON."""
        parsed = extract_json(content)
        if parsed is None:
            logger.warning("Could not parse AI freshness JSON")
            return None

        return {
            "classification": parsed.get("classification", fallback_classification),
            "pr_state_summary": parsed.get("pr_state_summary", ""),
            "finding_assessments": parsed.get("finding_assessments", []),
            "recommendation": parsed.get("recommendation", ""),
        }

    # ------------------------------------------------------------------
    # Finding collection helpers
    # ------------------------------------------------------------------

    def _collect_findings(self, synthesis: dict, holistic: dict) -> list[dict]:
        """Flatten findings from synthesis + holistic into a uniform list."""
        findings = []

        # From synthesis: agreed, a_only, b_only
        for category in ("agreed", "a_only", "b_only"):
            for finding in synthesis.get(category, []):
                inner = finding.get("finding_a", finding.get("finding_b", finding.get("finding", {})))
                if not inner:
                    continue
                loc = inner.get("location", {})
                file_path = ""
                if isinstance(loc, dict):
                    file_path = loc.get("file", loc.get("raw", ""))
                findings.append({
                    "title": inner.get("title", "Untitled"),
                    "severity": inner.get("severity", "unknown"),
                    "file": file_path,
                    "problem": inner.get("problem", ""),
                    "fix": inner.get("fix", ""),
                    "source": finding.get("source", category),
                    "domain": finding.get("domain", ""),
                    "origin": "synthesis",
                })

        # From holistic: blocking and non-blocking findings
        for cat_key in ("blocking", "blocking_findings"):
            for f in holistic.get(cat_key, []):
                findings.append({
                    "title": f.get("title", "Untitled"),
                    "severity": f.get("severity", "critical"),
                    "file": f.get("file", ""),
                    "problem": f.get("description", f.get("problem", "")),
                    "fix": f.get("fix", ""),
                    "source": "holistic",
                    "domain": f.get("domain", ""),
                    "origin": "holistic",
                })

        for cat_key in ("non_blocking", "non_blocking_findings"):
            for f in holistic.get(cat_key, []):
                findings.append({
                    "title": f.get("title", "Untitled"),
                    "severity": f.get("severity", "minor"),
                    "file": f.get("file", ""),
                    "problem": f.get("description", f.get("problem", "")),
                    "fix": f.get("fix", ""),
                    "source": "holistic",
                    "domain": f.get("domain", ""),
                    "origin": "holistic",
                })

        return findings

    # ------------------------------------------------------------------
    # Mechanical SHA comparison helpers (unchanged)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Mechanical fallback helpers
    # ------------------------------------------------------------------

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
