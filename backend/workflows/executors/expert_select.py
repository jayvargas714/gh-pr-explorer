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


def _get_relevant_feedback(inputs: dict, my_step_id: str) -> list[dict]:
    """Return only feedback entries whose retry_target matches this step."""
    return [fb for fb in inputs.get("human_feedback", [])
            if fb.get("retry_target") == my_step_id]


def _format_feedback_prompt_section(feedback: list[dict]) -> str:
    """Build a prompt section from human feedback history."""
    if not feedback:
        return ""
    lines = ["\n## Human Feedback"]
    latest = feedback[-1]
    lines.append(f"The reviewer provided this guidance (iteration {latest.get('iteration', '?')}):")
    lines.append(f"> {latest['feedback']}")
    lines.append("You MUST adjust your selection to address this feedback.")
    if len(feedback) > 1:
        lines.append("\nPrevious feedback (already addressed in prior iterations):")
        for fb in feedback[:-1]:
            lines.append(f"- (iteration {fb.get('iteration', '?')}): {fb['feedback']}")
    lines.append("")
    return "\n".join(lines)

EXPERT_GENERATION_PROMPT = """\
You are selecting expert reviewers for a code review. Analyze the changed files and diff below, then generate 2-5 expert domains that are ACTUALLY relevant to this codebase and these changes.

## Changed Files
{file_list}

## Diff Sample (first 3000 lines)
{diff_sample}

## Risk Assessment (evaluate BEFORE selecting experts)
Scan the diff for structural risk signals. When present, include a meta-expert whose persona and checklist target that specific risk. Meta-experts compete for the same 2-5 slots as domain experts — prioritize by actual danger over domain coverage.

Risk signals to look for:
- Heavy branching, complex conditionals, boundary math → Edge Case & Boundary Condition Analyst
- Concurrent, async, threaded code, shared mutable state → Concurrency Safety Reviewer
- Non-trivial algorithms, data structures, perf-critical paths → Algorithm Correctness & Complexity Reviewer
- State machines, workflow transitions, multi-phase orchestration → State Transition Integrity Analyst
- Auth, input validation, trust boundaries, secrets handling → Security Boundary Analyst
- Deep error recovery, retry logic, fallback chains → Failure Mode & Recovery Reviewer

A meta-expert's persona, checklist, and anti_patterns must reference the SPECIFIC risk patterns found in the diff — not generic boilerplate. If no significant risk signals exist, use all slots for domain experts.

## Rules
- Select 2-5 expert domains based on PR scale (<=300 lines: 2, 301-1500: 3-4, >1500: 4-5)
- Each domain must be relevant to the ACTUAL languages, frameworks, and patterns in the diff
- Do NOT use generic domains like "General" — be specific to what the code actually does
- If the repo uses Python+Flask, create a "Python Backend" expert, not a "Rust API" expert
- If the repo uses React+TypeScript, create a "React Frontend" expert, not a "Go Backend" expert
- Think about the DOMAIN PURPOSE of the code, not just the language — if the code constructs prompts for AI agents, include a "Prompt Engineering & AI Integration" expert; if it orchestrates LLM calls, include an "LLM Orchestration" expert; if it manages CI/CD pipelines, include a "DevOps" expert
- Consider cross-cutting concerns: security, observability, data integrity, prompt quality, UX coherence
{human_feedback_section}
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

        static_match_repos = self.step_config.get("static_match_repos", [])
        if full_repo in static_match_repos:
            return self._static_domain_match_flow(prs, owner, repo)

        return self._ai_expert_generation_flow(prs, owner, repo, full_repo, inputs)

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
                                   full_repo: str,
                                   inputs: dict | None = None) -> StepResult:
        from backend.database import get_workflow_db
        db = get_workflow_db()

        feedback = _get_relevant_feedback(inputs or {}, "experts")

        all_files, diff_sample, total_lines = self._collect_pr_content(prs, owner, repo)

        if not feedback:
            cached = db.list_expert_domains(active_only=True, repo=full_repo)
            if cached:
                scored = self._score_cached_domains(cached, prs, owner, repo,
                                                    all_files, diff_sample, total_lines)
                if scored is not None:
                    return scored
                logger.info(f"Cached domains not relevant to current PR(s), regenerating for {full_repo}")
        else:
            logger.info(f"Human feedback present (iteration {feedback[-1].get('iteration', '?')}), "
                        f"bypassing expert cache for {full_repo}")

        prompt = self._build_expert_generation_prompt(all_files, diff_sample, feedback)

        ai_experts = self._dispatch_ai_agent(prompt, owner, repo)

        if ai_experts:
            db.insert_ai_expert_domains(full_repo, ai_experts)
            logger.info(f"Cached {len(ai_experts)} AI-generated domains for {full_repo}")
            fresh = db.list_expert_domains(active_only=True, repo=full_repo)
            if fresh:
                scored = self._score_cached_domains(fresh, prs, owner, repo,
                                                    all_files, diff_sample, total_lines)
                if scored is not None:
                    return scored

        logger.warning(f"AI expert generation failed for {full_repo}, falling back to static matching")
        return self._fallback_static_match(prs, owner, repo, total_lines)

    def _collect_pr_content(self, prs: list, owner: str, repo: str
                            ) -> tuple[list[str], str, int]:
        all_files: list[str] = []
        all_diff_lines: list[str] = []
        total_lines = 0
        for pr in prs:
            total_lines += pr.get("additions", 0) + pr.get("deletions", 0)
            files = self._fetch_changed_files(owner, repo, pr.get("number", 0))
            all_files.extend(files)
            diff_content = self._fetch_diff_content(owner, repo, pr.get("number", 0))
            if diff_content:
                all_diff_lines.extend(diff_content.splitlines())
        return sorted(set(all_files)), "\n".join(all_diff_lines[:3000]), total_lines

    def _build_expert_generation_prompt(self, files: list[str], diff_sample: str,
                                        feedback: list[dict] | None = None) -> str:
        file_list = "\n".join(f"- {f}" for f in files) if files else "(no files detected)"
        fb_section = _format_feedback_prompt_section(feedback) if feedback else ""
        return EXPERT_GENERATION_PROMPT.format(
            file_list=file_list,
            diff_sample=diff_sample or "(no diff available)",
            human_feedback_section=fb_section,
        )

    def _dispatch_ai_agent(self, prompt: str, owner: str, repo: str) -> list[dict] | None:
        from backend.workflows.cancellation import (
            is_cancelled, register_agent, unregister_agent, AGENT_POLL_TIMEOUT,
        )
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
                    logger.error(f"Expert generation timed out after {elapsed}s")
                    agent.cancel(handle)
                    return None
                if inst_id and step_id:
                    live = agent.get_live_output(handle)
                    if live:
                        _set_live_output(inst_id, step_id, live)
                time.sleep(_POLL_INTERVAL)
                elapsed += _POLL_INTERVAL
        finally:
            if inst_id:
                unregister_agent(inst_id, handle)
            if inst_id and step_id:
                _clear_live_output(inst_id, step_id)

        if status != AgentStatus.COMPLETED:
            artifact = agent.get_output(handle)
            agent.cleanup(handle)
            logger.error(f"Expert generation agent failed: {artifact.error}")
            return None

        artifact = agent.get_output(handle)
        agent.cleanup(handle)
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

        if data is None:
            depth = 0
            start_idx = -1
            in_string = False
            escape = False
            for i, ch in enumerate(text):
                if escape:
                    escape = False
                    continue
                if ch == '\\' and in_string:
                    escape = True
                    continue
                if ch == '"' and not escape:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
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

    def _score_cached_domains(self, domains: list[dict], prs: list,
                              owner: str, repo: str,
                              all_files: list[str], diff_sample: str,
                              total_lines: int) -> StepResult | None:
        """Score cached domains against actual PR content. Returns None on cache miss."""
        files_lower = " ".join(f.lower() for f in all_files)
        diff_lower = diff_sample.lower()

        _MIN_RELEVANCE = 2.0

        scored: list[tuple[dict, float]] = []
        for d in domains:
            relevance = self._compute_domain_relevance(d, all_files, files_lower, diff_lower)
            if relevance >= _MIN_RELEVANCE:
                scored.append((d, relevance))

        if not scored:
            return None

        scored.sort(key=lambda x: x[1], reverse=True)
        max_experts = self._expert_count_cap(total_lines)
        selected = scored[:max_experts]
        selected_ids = {d["domain_id"] for d, _ in selected}

        logger.info(
            f"Scored {len(scored)}/{len(domains)} cached domains as relevant; "
            f"selected top {len(selected)}: "
            + ", ".join(f'{d["domain_id"]}({s:.0f}%)' for d, s in selected)
        )

        pr_domains: list[dict] = []
        for pr in prs:
            pr_files = self._fetch_changed_files(owner, repo, pr.get("number", 0))
            pr_files_lower = " ".join(f.lower() for f in pr_files)
            pr_matched = []
            for d, _ in selected:
                if self._compute_domain_relevance(d, pr_files, pr_files_lower, diff_lower) > 0:
                    pr_matched.append(d["domain_id"])
            pr_domains.append({
                "pr_number": pr.get("number", 0),
                "domains": pr_matched or [d["domain_id"] for d, _ in selected],
                "file_count": len(pr_files),
            })

        experts = []
        for d, relevance in selected:
            experts.append({
                "domain_id": d["domain_id"],
                "display_name": d["display_name"],
                "persona": d["persona"],
                "scope": d["scope"],
                "checklist": d.get("checklist", []),
                "anti_patterns": d.get("anti_patterns", []),
                "matched_files": [f for f in all_files
                                  if self._file_matches_domain(f, d)],
                "relevance_pct": round(relevance, 1),
            })

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
                    "source": "ai_cached_scored",
                },
            }],
        )

    _DOMAIN_STOP_WORDS = frozenset({
        "the", "and", "for", "with", "from", "that", "this", "are", "was",
        "has", "have", "been", "will", "can", "not", "but", "all", "any",
        "its", "also", "into", "more", "such", "each", "than", "other",
        "about", "over", "across", "review", "code", "expert", "engineer",
        "senior", "principal", "specializing", "experience", "including",
        "ensure", "check", "verify", "focus", "specific", "based",
    })

    _EXT_TO_LANG: dict[str, list[str]] = {
        ".py": ["python"], ".pyx": ["python", "cython"],
        ".js": ["javascript"], ".ts": ["typescript"], ".tsx": ["typescript", "react"],
        ".jsx": ["javascript", "react"],
        ".go": ["go", "golang"], ".rs": ["rust"],
        ".cpp": ["c++", "cpp"], ".cc": ["c++", "cpp"], ".cxx": ["c++", "cpp"],
        ".c": ["c"], ".h": ["c", "c++", "cpp"], ".hpp": ["c++", "cpp"],
        ".java": ["java"], ".kt": ["kotlin"], ".scala": ["scala"],
        ".rb": ["ruby"], ".php": ["php"],
        ".sql": ["sql", "database", "query"],
        ".sh": ["bash", "shell", "script", "ops", "infra"],
        ".yml": ["yaml", "config", "ci", "infra"], ".yaml": ["yaml", "config", "ci", "infra"],
        ".tf": ["terraform", "infra"], ".hcl": ["terraform", "infra"],
        ".dockerfile": ["docker", "container", "infra"],
        ".proto": ["protobuf", "grpc"],
        ".graphql": ["graphql", "api"],
        ".css": ["css", "frontend", "style"], ".scss": ["css", "frontend", "style"],
        ".html": ["html", "frontend"],
        ".md": ["docs", "documentation"],
    }

    _DIR_SIGNALS: dict[str, list[str]] = {
        "test": ["testing", "test"], "tests": ["testing", "test"],
        "spec": ["testing", "test"],
        "ops": ["ops", "operations", "infra", "infrastructure"],
        "deploy": ["deployment", "infra", "ci"],
        "ci": ["ci", "continuous", "pipeline"],
        "infra": ["infra", "infrastructure"],
        "db": ["database", "sql"], "database": ["database", "sql"],
        "migration": ["database", "migration", "sql"],
        "api": ["api", "backend"],
        "frontend": ["frontend", "ui"],
        "security": ["security", "auth"],
        "auth": ["auth", "security", "authentication"],
    }

    def _compute_domain_relevance(self, domain: dict, files: list[str],
                                  files_lower: str, diff_lower: str) -> float:
        """Score a domain's relevance to the given files and diff content.

        Returns 0-100. Uses keywords extracted from domain metadata matched
        against file paths and diff text.
        """
        name = (domain.get("display_name", "") or "").lower()
        scope = (domain.get("scope", "") or "").lower()
        persona = (domain.get("persona", "") or "").lower()

        raw_tokens = re.split(r'[\s,;/\-_&|():.]+', f"{name} {scope}")
        keywords = {t for t in raw_tokens
                    if len(t) >= 2 and t not in self._DOMAIN_STOP_WORDS}

        checklist_text = " ".join(domain.get("checklist", [])).lower()
        for tok in re.split(r'[\s,;/\-_&|():.?]+', checklist_text):
            if len(tok) >= 4 and tok not in self._DOMAIN_STOP_WORDS:
                keywords.add(tok)

        file_signals = self._extract_file_signals(files)
        keywords.update(self._extract_language_keywords(name, scope, persona))

        if not keywords:
            return 0

        file_hits = sum(1 for kw in keywords if kw in files_lower)
        signal_hits = sum(1 for kw in keywords if kw in file_signals)
        diff_hits = sum(1 for kw in keywords if kw in diff_lower)

        total_possible = len(keywords)
        score = ((file_hits * 4) + (signal_hits * 3) + diff_hits) / total_possible * 12.5

        return min(score, 100.0)

    def _extract_file_signals(self, files: list[str]) -> str:
        """Extract language/framework signals from file paths and extensions."""
        signals: list[str] = []
        for f in files:
            f_lower = f.lower()
            parts = f_lower.replace("\\", "/").split("/")
            for part in parts:
                dir_sigs = self._DIR_SIGNALS.get(part, [])
                signals.extend(dir_sigs)

            for ext, langs in self._EXT_TO_LANG.items():
                if f_lower.endswith(ext):
                    signals.extend(langs)
                    break

            if "dockerfile" in f_lower:
                signals.extend(["docker", "container", "infra"])
            if "makefile" in f_lower:
                signals.extend(["build", "make"])
            if "cron" in f_lower:
                signals.extend(["cron", "scheduling", "ops", "infra"])

        return " ".join(signals)

    @staticmethod
    def _extract_language_keywords(name: str, scope: str, persona: str) -> set[str]:
        """Pull language/framework identifiers that may need special handling."""
        combined = f"{name} {scope} {persona}"
        keywords: set[str] = set()
        lang_patterns = [
            (r'\bc\+\+\b', {"c++", "cpp"}),
            (r'\bc#\b', {"c#", "csharp"}),
            (r'\bnode\.?js\b', {"node", "nodejs", "javascript"}),
            (r'\breact\b', {"react", "jsx", "tsx"}),
            (r'\bflask\b', {"flask", "python"}),
            (r'\bdjango\b', {"django", "python"}),
            (r'\bfastapi\b', {"fastapi", "python"}),
            (r'\bspring\b', {"spring", "java"}),
            (r'\bgraphql\b', {"graphql"}),
            (r'\bgrpc\b', {"grpc", "protobuf"}),
            (r'\bpostgres(?:ql)?\b', {"postgres", "postgresql", "sql", "database"}),
            (r'\bmysql\b', {"mysql", "sql", "database"}),
            (r'\bredis\b', {"redis", "cache"}),
            (r'\bdocker\b', {"docker", "container"}),
            (r'\bkubernetes\b|k8s', {"kubernetes", "k8s", "infra"}),
            (r'\bterraform\b', {"terraform", "infra"}),
            (r'\baws\b', {"aws", "cloud"}),
            (r'\bgcp\b', {"gcp", "cloud"}),
            (r'\bazure\b', {"azure", "cloud"}),
            (r'\bs3\b', {"s3", "aws", "cloud", "storage"}),
        ]
        for pattern, kws in lang_patterns:
            if re.search(pattern, combined, re.IGNORECASE):
                keywords.update(kws)
        return keywords

    @staticmethod
    def _file_matches_domain(filepath: str, domain: dict) -> bool:
        """Quick check: does this file path relate to this domain?"""
        scope = (domain.get("scope", "") or "").lower()
        name = (domain.get("display_name", "") or "").lower()
        combined = f"{name} {scope}"
        f_lower = filepath.lower()
        parts = f_lower.replace("\\", "/").split("/")
        tokens = set(re.split(r'[\s,;/\-_&|():.]+', combined))
        return any(t in f_lower for t in tokens if len(t) >= 3) or \
               any(p in combined for p in parts if len(p) >= 3)

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
        if total_lines <= 800:
            return 3
        if total_lines <= 2000:
            return 4
        return 5

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
