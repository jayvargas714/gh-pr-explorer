from __future__ import annotations
"""Expert Select step — selects relevant expert domains for each PR.

For scala-computing/scala, uses static domain matching from the DB.
For all other repos, dispatches an AI agent to generate tailored expert
domains based on the actual changed files and diff content.
"""

import json
import logging
import re
import subprocess
import time

from backend.agents import get_agent, AgentStatus
from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.executors.agent_review import _set_live_output, _clear_live_output
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 5

EXPERT_GENERATION_PROMPT = """\
You are selecting expert reviewers for a code review. Analyze the changed files and diff below, then generate 2-4 expert domains that are ACTUALLY relevant to this codebase and these changes.

## Changed Files
{file_list}

## Diff Sample (first 3000 lines)
{diff_sample}

## Rules
- Select 2-4 expert domains based on PR scale (<=300 lines: 2, 301-1500: 3, >1500: 4)
- Each domain must be relevant to the ACTUAL languages, frameworks, and patterns in the diff
- Do NOT use generic domains like "General" — be specific to what the code actually does
- If the repo uses Python+Flask, create a "Python Backend" expert, not a "Rust API" expert
- If the repo uses React+TypeScript, create a "React Frontend" expert, not a "Go Backend" expert

## Output Format
You MUST output valid JSON and nothing else. No markdown, no explanation, just the JSON object:
{{"experts": [{{"domain_id": "python-flask-backend", "display_name": "Python Flask Backend", "persona": "Principal Python backend engineer specializing in Flask... (3-5 sentences)", "scope": "Flask routes, database access, error handling, API design", "checklist": ["Is error handling consistent across routes?", "Are database queries properly parameterized?"], "anti_patterns": ["Bare except clauses swallowing errors", "SQL injection via string formatting"]}}, ...]}}\
"""


@register_step("expert_select")
class ExpertSelectExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        prs = inputs.get("prs", [])
        owner = inputs.get("owner", "")
        repo = inputs.get("repo", "")
        if not prs:
            return StepResult(success=False, error="No PRs to analyze for expert selection")

        full_repo = f"{owner}/{repo}"

        if full_repo == "scala-computing/scala":
            return self._static_domain_match_flow(prs, owner, repo)

        return self._ai_expert_generation_flow(prs, owner, repo, full_repo)

    # ------------------------------------------------------------------ #
    #  Path A: static domain matching (scala-computing/scala only)
    # ------------------------------------------------------------------ #

    def _static_domain_match_flow(self, prs: list, owner: str, repo: str) -> StepResult:
        domains = self._load_domains(repo=f"{owner}/{repo}")
        if not domains:
            domains = self._load_domains()
        if not domains:
            return StepResult(success=False, error="No active expert domains configured")

        all_matched: dict[str, dict] = {}
        pr_domains: list[dict] = []
        total_lines = 0

        for pr in prs:
            pr_number = pr.get("number", 0)
            additions = pr.get("additions", 0)
            deletions = pr.get("deletions", 0)
            total_lines += additions + deletions

            files = self._fetch_changed_files(owner, repo, pr_number)
            diff_content = self._fetch_diff_content(owner, repo, pr_number)

            pr_matched = self._match_domains(domains, files, diff_content)
            for domain_id, info in pr_matched.items():
                if domain_id not in all_matched:
                    all_matched[domain_id] = info
                else:
                    all_matched[domain_id]["matched_files"] = list(
                        set(all_matched[domain_id]["matched_files"]) | set(info["matched_files"])
                    )
                    all_matched[domain_id]["relevance_pct"] = max(
                        all_matched[domain_id]["relevance_pct"], info["relevance_pct"]
                    )

            pr_domains.append({
                "pr_number": pr_number,
                "domains": sorted(pr_matched.keys()),
                "file_count": len(files),
            })

        max_experts = self._expert_count_cap(total_lines)
        sorted_domains = sorted(
            all_matched.values(), key=lambda d: d["relevance_pct"], reverse=True
        )[:max_experts]

        experts = []
        for d in sorted_domains:
            experts.append({
                "domain_id": d["domain_id"],
                "display_name": d["display_name"],
                "persona": d["persona"],
                "scope": d["scope"],
                "checklist": d["checklist"],
                "anti_patterns": d["anti_patterns"],
                "matched_files": d["matched_files"],
                "relevance_pct": d["relevance_pct"],
            })

        if not experts:
            experts = [self._generic_expert()]

        return StepResult(
            success=True,
            outputs={
                "experts": experts,
                "pr_domains": pr_domains,
            },
            artifacts=[{
                "type": "expert_selection",
                "data": {
                    "experts": experts,
                    "pr_domains": pr_domains,
                    "total_domains": len(experts),
                    "total_lines_analyzed": total_lines,
                    "max_experts_cap": max_experts,
                },
            }],
        )

    # ------------------------------------------------------------------ #
    #  Path B: AI-powered expert generation (all other repos)
    # ------------------------------------------------------------------ #

    def _ai_expert_generation_flow(self, prs: list, owner: str, repo: str,
                                   full_repo: str) -> StepResult:
        from backend.database import get_workflow_db
        db = get_workflow_db()

        cached = db.list_expert_domains(active_only=True, repo=full_repo)
        if cached:
            logger.info(f"Using {len(cached)} cached AI-generated domains for {full_repo}")
            return self._build_result_from_domains(cached, prs, owner, repo)

        all_files: list[str] = []
        all_diff_lines: list[str] = []
        total_lines = 0

        for pr in prs:
            pr_number = pr.get("number", 0)
            additions = pr.get("additions", 0)
            deletions = pr.get("deletions", 0)
            total_lines += additions + deletions

            files = self._fetch_changed_files(owner, repo, pr_number)
            all_files.extend(files)

            diff_content = self._fetch_diff_content(owner, repo, pr_number)
            if diff_content:
                all_diff_lines.extend(diff_content.splitlines())

        all_files = sorted(set(all_files))
        diff_sample = "\n".join(all_diff_lines[:3000])

        prompt = self._build_expert_generation_prompt(all_files, diff_sample)

        ai_experts = self._dispatch_ai_agent(prompt, owner, repo)

        if ai_experts:
            db.insert_ai_expert_domains(full_repo, ai_experts)
            logger.info(f"Cached {len(ai_experts)} AI-generated domains for {full_repo}")
            fresh = db.list_expert_domains(active_only=True, repo=full_repo)
            if fresh:
                return self._build_result_from_domains(fresh, prs, owner, repo)

        logger.warning(f"AI expert generation failed for {full_repo}, falling back to static matching")
        return self._fallback_static_match(prs, owner, repo, total_lines)

    def _build_expert_generation_prompt(self, files: list[str], diff_sample: str) -> str:
        file_list = "\n".join(f"- {f}" for f in files) if files else "(no files detected)"
        return EXPERT_GENERATION_PROMPT.format(
            file_list=file_list,
            diff_sample=diff_sample or "(no diff available)",
        )

    def _dispatch_ai_agent(self, prompt: str, owner: str, repo: str) -> list[dict] | None:
        agent_name = self.step_config.get("agent", "cursor-opus")
        inst_id = self.instance_config.get("_instance_id", 0)
        step_id = self.step_config.get("_step_id", "")

        try:
            agent = get_agent(agent_name)
        except Exception as e:
            logger.error(f"Failed to get agent '{agent_name}' for expert generation: {e}")
            return None

        context = {"owner": owner, "repo": repo, "task": "expert_generation", "instance_id": inst_id}

        try:
            handle = agent.start_review(prompt, context)
        except Exception as e:
            logger.error(f"Failed to start expert generation agent: {e}")
            return None

        while True:
            status = agent.check_status(handle)
            if status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED):
                break
            if inst_id and step_id:
                live = agent.get_live_output(handle)
                if live:
                    _set_live_output(inst_id, step_id, live)
            time.sleep(_POLL_INTERVAL)

        if inst_id and step_id:
            _clear_live_output(inst_id, step_id)

        if status != AgentStatus.COMPLETED:
            artifact = agent.get_output(handle)
            logger.error(f"Expert generation agent failed: {artifact.error}")
            return None

        artifact = agent.get_output(handle)
        raw = artifact.content_md
        if not raw:
            logger.error("Expert generation agent returned empty content_md")
            return None

        logger.info(f"Expert generation raw output length: {len(raw)}")
        logger.debug(f"Expert generation raw output (first 500): {raw[:500]}")

        result = self._parse_expert_json(raw)
        if result is None:
            logger.error(f"Failed to parse expert JSON. Full output:\n{raw[:2000]}")
        return result

    def _parse_expert_json(self, content: str | None) -> list[dict] | None:
        if not content:
            return None

        text = content.strip()

        # Strip all markdown fenced code blocks (```json ... ``` or ``` ... ```)
        fenced = re.findall(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
        if fenced:
            text = fenced[0].strip()

        # First try: direct parse
        data = None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            pass

        # Second try: extract the outermost { ... } block
        if data is None:
            depth = 0
            start_idx = -1
            for i, ch in enumerate(text):
                if ch == '{':
                    if depth == 0:
                        start_idx = i
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0 and start_idx >= 0:
                        try:
                            data = json.loads(text[start_idx:i + 1])
                            break
                        except json.JSONDecodeError:
                            start_idx = -1

        if data is None:
            logger.error("No valid JSON object found in AI expert generation output")
            return None

        experts = data.get("experts", [])
        if not isinstance(experts, list) or not experts:
            logger.error(f"AI output missing 'experts' array or empty. Keys: {list(data.keys())}")
            return None

        validated = []
        for e in experts:
            if not all(k in e for k in ("domain_id", "display_name", "persona", "scope")):
                logger.warning(f"Skipping malformed expert entry: {e.get('domain_id', '?')}")
                continue
            validated.append({
                "domain_id": e["domain_id"],
                "display_name": e["display_name"],
                "persona": e["persona"],
                "scope": e["scope"],
                "checklist": e.get("checklist", []),
                "anti_patterns": e.get("anti_patterns", []),
            })

        return validated if validated else None

    def _build_result_from_domains(self, domains: list[dict], prs: list,
                                   owner: str, repo: str) -> StepResult:
        total_lines = 0
        pr_domains: list[dict] = []

        for pr in prs:
            pr_number = pr.get("number", 0)
            additions = pr.get("additions", 0)
            deletions = pr.get("deletions", 0)
            total_lines += additions + deletions

            files = self._fetch_changed_files(owner, repo, pr_number)
            pr_domains.append({
                "pr_number": pr_number,
                "domains": [d["domain_id"] for d in domains],
                "file_count": len(files),
            })

        max_experts = self._expert_count_cap(total_lines)

        experts = []
        for d in domains[:max_experts]:
            experts.append({
                "domain_id": d["domain_id"],
                "display_name": d["display_name"],
                "persona": d["persona"],
                "scope": d["scope"],
                "checklist": d.get("checklist", []),
                "anti_patterns": d.get("anti_patterns", []),
                "matched_files": [],
                "relevance_pct": 100.0,
            })

        if not experts:
            experts = [self._generic_expert()]

        return StepResult(
            success=True,
            outputs={
                "experts": experts,
                "pr_domains": pr_domains,
            },
            artifacts=[{
                "type": "expert_selection",
                "data": {
                    "experts": experts,
                    "pr_domains": pr_domains,
                    "total_domains": len(experts),
                    "total_lines_analyzed": total_lines,
                    "max_experts_cap": max_experts,
                    "source": "ai_generated",
                },
            }],
        )

    def _fallback_static_match(self, prs: list, owner: str, repo: str,
                               total_lines: int) -> StepResult:
        """Fallback when AI generation fails: stricter static matching."""
        domains = self._load_domains()
        if not domains:
            return StepResult(
                success=True,
                outputs={"experts": [self._generic_expert()], "pr_domains": []},
            )

        all_matched: dict[str, dict] = {}
        pr_domains: list[dict] = []

        for pr in prs:
            pr_number = pr.get("number", 0)
            files = self._fetch_changed_files(owner, repo, pr_number)
            diff_content = self._fetch_diff_content(owner, repo, pr_number)

            pr_matched = self._match_domains(
                domains, files, diff_content,
                min_relevance=25.0, require_file_match=True,
            )
            for domain_id, info in pr_matched.items():
                if domain_id not in all_matched:
                    all_matched[domain_id] = info
                else:
                    all_matched[domain_id]["matched_files"] = list(
                        set(all_matched[domain_id]["matched_files"]) | set(info["matched_files"])
                    )
                    all_matched[domain_id]["relevance_pct"] = max(
                        all_matched[domain_id]["relevance_pct"], info["relevance_pct"]
                    )

            pr_domains.append({
                "pr_number": pr_number,
                "domains": sorted(pr_matched.keys()),
                "file_count": len(files),
            })

        max_experts = self._expert_count_cap(total_lines)
        sorted_domains = sorted(
            all_matched.values(), key=lambda d: d["relevance_pct"], reverse=True
        )[:max_experts]

        experts = []
        for d in sorted_domains:
            experts.append({
                "domain_id": d["domain_id"],
                "display_name": d["display_name"],
                "persona": d["persona"],
                "scope": d["scope"],
                "checklist": d["checklist"],
                "anti_patterns": d["anti_patterns"],
                "matched_files": d["matched_files"],
                "relevance_pct": d["relevance_pct"],
            })

        if not experts:
            experts = [self._generic_expert()]

        return StepResult(
            success=True,
            outputs={
                "experts": experts,
                "pr_domains": pr_domains,
            },
            artifacts=[{
                "type": "expert_selection",
                "data": {
                    "experts": experts,
                    "pr_domains": pr_domains,
                    "total_domains": len(experts),
                    "total_lines_analyzed": total_lines,
                    "max_experts_cap": max_experts,
                    "source": "fallback_static",
                },
            }],
        )

    # ------------------------------------------------------------------ #
    #  Shared helpers
    # ------------------------------------------------------------------ #

    def _load_domains(self, repo: str | None = None) -> list[dict]:
        try:
            from backend.database import get_workflow_db
            db = get_workflow_db()
            if repo:
                return db.list_expert_domains(active_only=True, repo=repo)
            return db.list_expert_domains(active_only=True)
        except Exception as e:
            logger.error(f"Failed to load expert domains: {e}")
            return []

    def _fetch_changed_files(self, owner: str, repo: str, pr_number: int) -> list[str]:
        if not owner or not repo or not pr_number:
            return []
        try:
            result = subprocess.run(
                ["gh", "pr", "diff", str(pr_number), "--name-only",
                 "--repo", f"{owner}/{repo}"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        except Exception as e:
            logger.warning(f"Failed to fetch changed files for PR #{pr_number}: {e}")
        return []

    def _fetch_diff_content(self, owner: str, repo: str, pr_number: int) -> str:
        if not owner or not repo or not pr_number:
            return ""
        try:
            result = subprocess.run(
                ["gh", "pr", "diff", str(pr_number), "--repo", f"{owner}/{repo}"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                return result.stdout[:500_000]
        except Exception as e:
            logger.warning(f"Failed to fetch diff for PR #{pr_number}: {e}")
        return ""

    def _match_domains(self, domains: list[dict], files: list[str],
                       diff_content: str, min_relevance: float = 5.0,
                       require_file_match: bool = False) -> dict[str, dict]:
        total_files = max(len(files), 1)
        matched: dict[str, dict] = {}

        for domain in domains:
            triggers = domain.get("triggers", {})
            file_patterns = triggers.get("file_patterns", [])
            keywords = triggers.get("keywords", [])

            matched_files = set()
            for filepath in files:
                for pattern in file_patterns:
                    try:
                        if re.search(pattern, filepath, re.IGNORECASE):
                            matched_files.add(filepath)
                            break
                    except re.error:
                        pass

            keyword_match = False
            for kw in keywords:
                if kw.lower() in diff_content.lower():
                    keyword_match = True
                    break

            if not matched_files and not keyword_match:
                continue

            if require_file_match and not matched_files:
                continue

            relevance = len(matched_files) / total_files * 100
            if keyword_match and relevance < min_relevance:
                relevance = max(relevance, 10.0)

            if relevance < min_relevance and not keyword_match:
                continue

            matched[domain["domain_id"]] = {
                "domain_id": domain["domain_id"],
                "display_name": domain["display_name"],
                "persona": domain["persona"],
                "scope": domain["scope"],
                "checklist": domain.get("checklist", []),
                "anti_patterns": domain.get("anti_patterns", []),
                "matched_files": sorted(matched_files),
                "relevance_pct": round(relevance, 1),
            }

        return matched

    @staticmethod
    def _expert_count_cap(total_lines: int) -> int:
        if total_lines <= 300:
            return 2
        if total_lines <= 1500:
            return 3
        return 4

    @staticmethod
    def _generic_expert() -> dict:
        return {
            "domain_id": "general",
            "display_name": "General",
            "persona": "Senior software engineer with broad expertise across the stack.",
            "scope": "General code quality, architecture, correctness, and maintainability",
            "checklist": [
                "Is the code correct and free of obvious bugs?",
                "Are edge cases handled?",
                "Is error handling adequate?",
                "Is the code readable and maintainable?",
            ],
            "anti_patterns": [],
            "matched_files": [],
            "relevance_pct": 100.0,
        }
