from __future__ import annotations
"""Synthesis step — compares two review artifacts and classifies findings.

Supports single-tier (team-review) and two-tier (self/deep-review) synthesis
with source attribution, synthesis log, NEEDS_DISCUSSION verdict, and
enhanced finding matching per the legacy adversarial review specification.

AI verification runs per-domain in parallel (up to 4 concurrent agents),
matching the Phase 3 Tier 1 architecture.
"""

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.agents import get_agent, AgentStatus
from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.executors.agent_review import (
    _set_live_output, _clear_live_output,
    _agent_domain_store, _agent_domain_lock, _register_domain,
)
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)



@register_step("synthesis")
class SynthesisExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        reviews = inputs.get("reviews", [])
        mode = inputs.get("mode", "team-review")
        prs = inputs.get("prs", [])
        self._human_feedback = [fb for fb in inputs.get("human_feedback", [])
                                if fb.get("retry_target") == "synth"]
        completed = [r for r in reviews if r.get("status") == "completed"]

        if not completed:
            return StepResult(
                success=True,
                outputs={"synthesis": {}},
            )

        if mode in ("self-review", "deep-review"):
            result = self._two_tier_synthesis(completed, reviews, mode)
        else:
            result = self._single_tier_synthesis(completed, reviews)

        if self.step_config.get("ai_verify", False):
            return self._ai_verify(result, completed, inputs)

        return result

    # --- Single tier (team-review) ---

    def _single_tier_synthesis(self, completed: list, reviews: list) -> StepResult:
        by_pr: dict[int, list[dict]] = {}
        for r in completed:
            pr = r.get("pr_number", 0)
            by_pr.setdefault(pr, []).append(r)

        all_agreed, all_a_only, all_b_only = [], [], []
        synthesis_log: list[dict] = []
        all_questions: list[str] = []
        artifacts = []

        for pr_number, pr_reviews in by_pr.items():
            if len(pr_reviews) < 2:
                continue

            review_a = next((r for r in pr_reviews if r.get("phase") == "a"), pr_reviews[0])
            review_b = next((r for r in pr_reviews if r.get("phase") == "b"), pr_reviews[1])

            findings_a = self._extract_findings(review_a)
            findings_b = self._extract_findings(review_b)
            classified = self._classify_findings(findings_a, findings_b,
                                                  review_a, review_b)

            log_entries = self._build_synthesis_log(classified, review_a, review_b)
            synthesis_log.extend(log_entries)

            questions_a = self._extract_questions(review_a)
            questions_b = self._extract_questions(review_b)
            all_questions.extend(questions_a + questions_b)

            verdict = self._compute_verdict(classified, review_a, review_b)

            pr_synthesis = {
                "pr_number": pr_number,
                "agent_a": review_a.get("agent_name", "Agent A"),
                "agent_b": review_b.get("agent_name", "Agent B"),
                "score_a": review_a.get("score"),
                "score_b": review_b.get("score"),
                "agreed": classified["agreed"],
                "a_only": classified["a_only"],
                "b_only": classified["b_only"],
                "total_findings": (
                    len(classified["agreed"]) + len(classified["a_only"]) + len(classified["b_only"])
                ),
                "agreed_count": len(classified["agreed"]),
                "disputed_count": len(classified["a_only"]) + len(classified["b_only"]),
                "verdict": verdict,
            }

            all_agreed.extend(classified["agreed"])
            all_a_only.extend(classified["a_only"])
            all_b_only.extend(classified["b_only"])

            artifacts.append({"type": "synthesis", "pr_number": pr_number, "data": pr_synthesis})

        total = len(all_agreed) + len(all_a_only) + len(all_b_only)
        first_synth = artifacts[0]["data"] if artifacts else {}
        summary_synthesis = first_synth if len(artifacts) == 1 else {
            "pr_count": len(artifacts),
            "agreed": all_agreed,
            "a_only": all_a_only,
            "b_only": all_b_only,
            "total_findings": total,
            "agreed_count": len(all_agreed),
            "disputed_count": len(all_a_only) + len(all_b_only),
            "verdict": first_synth.get("verdict", "COMMENT") if first_synth else "COMMENT",
            "per_pr": [a["data"] for a in artifacts],
            **({k: first_synth[k] for k in ("pr_number", "agent_a", "agent_b", "score_a", "score_b")
                if k in first_synth}),
        }

        summary_synthesis["synthesis_log"] = synthesis_log
        summary_synthesis["questions"] = list(dict.fromkeys(all_questions))

        return StepResult(
            success=True,
            outputs={"synthesis": summary_synthesis},
            artifacts=artifacts,
        )

    # --- Two tier (self-review / deep-review) ---

    def _two_tier_synthesis(self, completed: list, reviews: list, mode: str) -> StepResult:
        by_pr_domain: dict[tuple, list[dict]] = {}
        for r in completed:
            key = (r.get("pr_number", 0), r.get("domain", "general"))
            by_pr_domain.setdefault(key, []).append(r)

        per_domain_synthesis: list[dict] = []
        synthesis_log: list[dict] = []
        all_questions: list[str] = []
        all_agreed, all_a_only, all_b_only = [], [], []
        artifacts = []

        for (pr_number, domain), domain_reviews in by_pr_domain.items():
            if len(domain_reviews) < 2:
                continue

            review_a = next((r for r in domain_reviews if r.get("phase") == "a"), domain_reviews[0])
            review_b = next((r for r in domain_reviews if r.get("phase") == "b"), domain_reviews[1])

            findings_a = self._extract_findings(review_a)
            findings_b = self._extract_findings(review_b)
            classified = self._classify_findings(findings_a, findings_b,
                                                  review_a, review_b)

            log_entries = self._build_synthesis_log(classified, review_a, review_b)
            synthesis_log.extend(log_entries)

            questions_a = self._extract_questions(review_a)
            questions_b = self._extract_questions(review_b)
            all_questions.extend(questions_a + questions_b)

            verdict = self._compute_verdict(classified, review_a, review_b)

            domain_synth = {
                "pr_number": pr_number,
                "domain": domain,
                "agent_a": review_a.get("agent_name", "Agent A"),
                "agent_b": review_b.get("agent_name", "Agent B"),
                "agreed": classified["agreed"],
                "a_only": classified["a_only"],
                "b_only": classified["b_only"],
                "verdict": verdict,
                "total_findings": (
                    len(classified["agreed"]) + len(classified["a_only"]) + len(classified["b_only"])
                ),
            }
            per_domain_synthesis.append(domain_synth)

            all_agreed.extend(classified["agreed"])
            all_a_only.extend(classified["a_only"])
            all_b_only.extend(classified["b_only"])

            artifacts.append({
                "type": "synthesis",
                "pr_number": pr_number,
                "data": domain_synth,
            })

        total = len(all_agreed) + len(all_a_only) + len(all_b_only)
        verdicts = [d["verdict"] for d in per_domain_synthesis]
        if "CHANGES_REQUESTED" in verdicts:
            overall_verdict = "CHANGES_REQUESTED"
        elif "NEEDS_DISCUSSION" in verdicts:
            overall_verdict = "NEEDS_DISCUSSION"
        elif any(v == "COMMENT" for v in verdicts):
            overall_verdict = "COMMENT"
        else:
            overall_verdict = "APPROVE"

        agreement_rate = (
            f"{len(all_agreed)} of {total} findings agreed"
            if total > 0 else "No findings to compare"
        )

        summary_synthesis = {
            "agreed": all_agreed,
            "a_only": all_a_only,
            "b_only": all_b_only,
            "total_findings": total,
            "agreed_count": len(all_agreed),
            "disputed_count": len(all_a_only) + len(all_b_only),
            "agreement_rate": agreement_rate,
            "verdict": overall_verdict,
            "per_domain_synthesis": per_domain_synthesis,
            "synthesis_log": synthesis_log,
            "questions": list(dict.fromkeys(all_questions)),
        }

        return StepResult(
            success=True,
            outputs={
                "synthesis": summary_synthesis,
                "per_domain_synthesis": per_domain_synthesis,
            },
            artifacts=artifacts,
        )

    # --- AI verification pass (per-domain parallel) ---

    def _ai_verify(self, mechanical_result: StepResult, reviews: list, inputs: dict) -> StepResult:
        """Dispatch per-domain AI agents in parallel to verify mechanical synthesis."""
        from backend.workflows.cancellation import (
            is_cancelled, register_agent, unregister_agent, AGENT_POLL_TIMEOUT,
        )
        synthesis = mechanical_result.outputs.get("synthesis", {})
        owner = inputs.get("owner", "")
        repo = inputs.get("repo", "")
        prs = inputs.get("prs", [])
        inst_id = self.instance_config.get("_instance_id", 0)
        step_id = self.step_config.get("_step_id", "")

        agent_name = self.step_config.get("agent", "claude-opus")
        try:
            agent = get_agent(agent_name)
        except Exception as e:
            logger.warning(f"AI verify failed to get agent: {e}, returning mechanical result")
            return mechanical_result

        per_domain = synthesis.get("per_domain_synthesis", [])
        if not per_domain:
            return self._ai_verify_single(agent, synthesis, reviews, owner, repo, prs, inst_id, step_id)

        reviews_by_domain: dict[str, dict] = {}
        for r in reviews:
            domain = r.get("domain", "general")
            phase = r.get("phase", "")
            reviews_by_domain.setdefault(domain, {})
            if phase == "a":
                reviews_by_domain[domain]["a"] = r
            elif phase == "b":
                reviews_by_domain[domain]["b"] = r
            elif "a" not in reviews_by_domain[domain]:
                reviews_by_domain[domain]["a"] = r
            else:
                reviews_by_domain[domain]["b"] = r

        domain_live: dict[str, str] = {}
        domain_lock = threading.Lock()

        synth_key = f"{inst_id}:{step_id}"

        def verify_single_domain(domain_synth: dict) -> dict:
            domain = domain_synth.get("domain", "general")
            domain_reviews = reviews_by_domain.get(domain, {})
            review_a = domain_reviews.get("a")
            review_b = domain_reviews.get("b")

            if not review_a or not review_b:
                logger.warning(f"Missing A or B review for domain {domain}, skipping AI verify")
                domain_synth["ai_verified"] = False
                return domain_synth

            prompt = self._build_domain_verification_prompt(
                domain_synth, review_a, review_b, owner, repo, prs
            )
            context = {
                "pr_number": prs[0].get("number") if prs else 0,
                "owner": owner, "repo": repo,
                "phase": "synthesis", "task": "synthesis",
                "domain": domain,
                "instance_id": inst_id,
                "step_id": step_id,
            }

            try:
                handle = agent.start_review(prompt, context)
                _register_domain(synth_key, domain, agent, handle, {}, agent_name)
                if inst_id:
                    register_agent(inst_id, agent, handle)
                elapsed = 0
                try:
                    while True:
                        if inst_id and is_cancelled(inst_id):
                            agent.cancel(handle)
                            self._update_domain_status(synth_key, domain, "cancelled")
                            domain_synth["ai_verified"] = False
                            return domain_synth
                        status = agent.check_status(handle)
                        if status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED):
                            break
                        if elapsed >= AGENT_POLL_TIMEOUT:
                            logger.error(f"AI verify timed out for domain {domain} after {elapsed}s")
                            agent.cancel(handle)
                            break
                        live = agent.get_live_output(handle)
                        if live and inst_id and step_id:
                            with _agent_domain_lock:
                                if synth_key in _agent_domain_store and domain in _agent_domain_store[synth_key]:
                                    _agent_domain_store[synth_key][domain]["live_output"] = live
                            with domain_lock:
                                domain_live[domain] = live
                                composite = "\n\n".join(
                                    f"--- [{d}] ---\n{text}" for d, text in domain_live.items()
                                )
                            _set_live_output(inst_id, step_id, composite)
                        time.sleep(5)
                        elapsed += 5
                finally:
                    if inst_id:
                        unregister_agent(inst_id, handle)
                if status == AgentStatus.COMPLETED:
                    artifact = agent.get_output(handle)
                    agent.cleanup(handle)
                    result = self._parse_domain_verification(artifact.content_md, domain_synth)
                    self._update_domain_status(synth_key, domain, "completed",
                                               content_md=artifact.content_md)
                    return result
                else:
                    agent.cleanup(handle)
                    logger.warning(f"AI verification failed for domain {domain}")
                    self._update_domain_status(synth_key, domain, "failed",
                                               error=f"Agent status: {status.value}")
                    domain_synth["ai_verified"] = False
                    return domain_synth
            except Exception as e:
                logger.error(f"AI verify error for domain {domain}: {e}")
                self._update_domain_status(synth_key, domain, "failed", error=str(e))
                domain_synth["ai_verified"] = False
                return domain_synth

        verified_domains: list[dict] = []
        try:
            with ThreadPoolExecutor(max_workers=max(len(per_domain), 1)) as pool:
                futures = {pool.submit(verify_single_domain, d): d for d in per_domain}
                for future in as_completed(futures):
                    try:
                        verified_domains.append(future.result())
                    except Exception as e:
                        original = futures[future]
                        original["ai_verified"] = False
                        verified_domains.append(original)
        finally:
            if inst_id and step_id:
                _clear_live_output(inst_id, step_id)
            with _agent_domain_lock:
                _agent_domain_store.pop(synth_key, None)

        return self._merge_verified_domains(synthesis, verified_domains, mechanical_result)

    @staticmethod
    def _update_domain_status(key: str, domain: str, status: str, *,
                              content_md: str | None = None,
                              error: str | None = None):
        with _agent_domain_lock:
            store = _agent_domain_store.get(key, {})
            info = store.get(domain)
            if not info:
                return
            info["status"] = status
            info["completed_at"] = time.time()
            if content_md is not None:
                info["result"] = {"content_md": content_md, "status": status}
            if error:
                info["error"] = error
                info.setdefault("result", {})["error"] = error

    def _ai_verify_single(self, agent, synthesis: dict, reviews: list,
                          owner: str, repo: str, prs: list,
                          inst_id: int, step_id: str) -> StepResult:
        """Fallback: single AI verification for team-review (no per-domain)."""
        from backend.workflows.cancellation import (
            is_cancelled, register_agent, unregister_agent, AGENT_POLL_TIMEOUT,
        )
        review_a = next((r for r in reviews if r.get("phase") == "a"), reviews[0] if reviews else None)
        review_b = next((r for r in reviews if r.get("phase") == "b"), reviews[1] if len(reviews) > 1 else None)

        if not review_a or not review_b:
            synthesis["ai_verified"] = False
            return StepResult(success=True, outputs={"synthesis": synthesis})

        prompt = self._build_domain_verification_prompt(
            synthesis, review_a, review_b, owner, repo, prs
        )
        context = {
            "pr_number": prs[0].get("number") if prs else 0,
            "owner": owner, "repo": repo,
            "phase": "synthesis", "task": "synthesis",
            "instance_id": inst_id,
        }

        try:
            handle = agent.start_review(prompt, context)
            if inst_id:
                register_agent(inst_id, agent, handle)
            elapsed = 0
            while True:
                if inst_id and is_cancelled(inst_id):
                    agent.cancel(handle)
                    break
                status = agent.check_status(handle)
                if status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED):
                    break
                if elapsed >= AGENT_POLL_TIMEOUT:
                    logger.error(f"AI verify single timed out after {elapsed}s")
                    agent.cancel(handle)
                    break
                live = agent.get_live_output(handle)
                if live and inst_id and step_id:
                    _set_live_output(inst_id, step_id, live)
                time.sleep(5)
                elapsed += 5

            if inst_id:
                unregister_agent(inst_id, handle)
            if inst_id and step_id:
                _clear_live_output(inst_id, step_id)

            if status == AgentStatus.COMPLETED:
                artifact = agent.get_output(handle)
                agent.cleanup(handle)
                verified = self._parse_domain_verification(artifact.content_md, synthesis)
                return StepResult(success=True, outputs={"synthesis": verified})
            agent.cleanup(handle)
        except Exception as e:
            logger.error(f"AI verify single error: {e}")
            if inst_id and step_id:
                _clear_live_output(inst_id, step_id)

        synthesis["ai_verified"] = False
        return StepResult(success=True, outputs={"synthesis": synthesis})

    def _build_domain_verification_prompt(self, domain_synth: dict,
                                          review_a: dict, review_b: dict,
                                          owner: str, repo: str, prs: list) -> str:
        """Build a per-domain AI synthesis verification prompt."""
        domain = domain_synth.get("domain", "general")
        agent_a_name = review_a.get("agent_name", "Agent A")
        agent_b_name = review_b.get("agent_name", "Agent B")
        sections = []

        sections.append(
            f"You are a senior engineering lead performing SYNTHESIS of two independent code reviews "
            f"for the **{domain}** domain.\n"
            f"Agent A: {agent_a_name}\nAgent B: {agent_b_name}\n"
            f"Your job: verify every finding against the actual diff, resolve disputes with evidence, "
            f"generate SYNTH findings for issues both reviewers missed, and flag cross-cutting concerns.\n"
        )

        pr_numbers = [p.get("number") for p in prs if p.get("number")]
        for pr_num in pr_numbers:
            sections.append(
                f"## Context Commands (run these to verify findings)\n"
                f"```bash\n"
                f"gh pr diff {pr_num} --repo {owner}/{repo}\n"
                f"gh api repos/{owner}/{repo}/pulls/{pr_num}/reviews --paginate\n"
                f"gh api repos/{owner}/{repo}/pulls/{pr_num}/comments --paginate\n"
                f"```\n"
            )

        sections.append("## Pre-Classified Findings (mechanical)\n")
        for category in ("agreed", "a_only", "b_only"):
            findings = domain_synth.get(category, [])
            if findings:
                sections.append(f"### {category.upper()} ({len(findings)})")
                for i, f in enumerate(findings):
                    inner = f.get("finding_a", f.get("finding_b", f.get("finding", {})))
                    title = inner.get("title", f"Finding {i+1}")
                    severity = inner.get("severity", "unknown")
                    loc = inner.get("location", {})
                    loc_str = loc.get("raw", loc.get("file", ""))
                    problem = inner.get("problem", "")[:300]
                    sections.append(f"  {i+1}. [{severity}] **{title}** at `{loc_str}`\n     {problem}")
                sections.append("")

        md_a = review_a.get("content_md", "")
        md_b = review_b.get("content_md", "")
        sections.append(f"## Review A ({agent_a_name}) — Full Content\n\n{md_a[:8000]}")
        sections.append(f"## Review B ({agent_b_name}) — Full Content\n\n{md_b[:8000]}")

        fb = getattr(self, "_human_feedback", [])
        if fb:
            latest = fb[-1]
            sections.append(
                f"## Human Reviewer Feedback (iteration {latest.get('iteration', '?')})\n"
                f"The human reviewer has requested reconsideration with this guidance:\n"
                f"> {latest['feedback']}\n"
                f"You MUST address this feedback in your synthesis.\n"
            )

        sections.append(
            "\n## Your Task\n\n"
            "For EVERY pre-classified finding:\n"
            "1. **Verify** against the actual diff — read the code at the cited location\n"
            "2. **Classify**: CONFIRMED | FALSE_POSITIVE | RECLASSIFIED (with new severity)\n"
            "3. **For disputed findings** (A_ONLY, B_ONLY): determine validity with code evidence\n"
            "4. **Drop false positives** with explicit reasoning\n\n"
            "Additionally:\n"
            "- **Generate SYNTH findings**: issues BOTH reviewers missed (source: 'SYNTH')\n"
            "- **Extract cross-cutting flags**: any issues outside this domain's scope → list them\n"
            "- If Jira tickets (SIM-XXXX) are mentioned, consider the ticket intent\n\n"
            "## Output Format — valid JSON only:\n"
            "```json\n"
            "{\n"
            '  "domain": "' + domain + '",\n'
            '  "verified_findings": [\n'
            '    {"title": "...", "severity": "critical|major|minor", '
            '"classification": "CONFIRMED|FALSE_POSITIVE|RECLASSIFIED",\n'
            '     "original_category": "AGREED|A_ONLY|B_ONLY", "evidence": "...", '
            '"source": "review_a|review_b|BOTH"}\n'
            "  ],\n"
            '  "synth_findings": [\n'
            '    {"title": "...", "severity": "...", "description": "...", '
            '"evidence": "...", "source": "SYNTH"}\n'
            "  ],\n"
            '  "cross_cutting_flags": ["description 1", ...],\n'
            '  "false_positives_dropped": [{"title": "...", "reason": "..."}],\n'
            '  "synthesis_log": [{"finding": "...", "action": "CONFIRMED|DROPPED|RECLASSIFIED", "reasoning": "..."}],\n'
            '  "domain_verdict": "APPROVE|CHANGES_REQUESTED|NEEDS_DISCUSSION|COMMENT",\n'
            '  "domain_summary": "2-3 sentence summary for this domain"\n'
            "}\n"
            "```\n"
        )

        return "\n\n".join(sections)

    def _parse_domain_verification(self, content: str | None, original: dict) -> dict:
        """Parse AI domain verification output and merge into domain synthesis."""
        import json as json_mod

        if not content:
            original["ai_verified"] = False
            return original

        # Extract JSON from possible markdown wrapping
        text = content.strip()
        fenced = re.findall(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
        if fenced:
            text = fenced[0].strip()

        data = None
        try:
            data = json_mod.loads(text)
        except json_mod.JSONDecodeError:
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
                            data = json_mod.loads(text[start_idx:i + 1])
                            break
                        except json_mod.JSONDecodeError:
                            start_idx = -1

        if data is None:
            logger.warning("Could not parse AI domain verification JSON")
            original["ai_verified"] = False
            return original

        result = dict(original)
        result["ai_verified"] = True
        result["verified_findings"] = data.get("verified_findings", [])
        result["synth_findings"] = data.get("synth_findings", [])
        result["cross_cutting_flags"] = data.get("cross_cutting_flags", [])
        result["false_positives_dropped"] = data.get("false_positives_dropped", [])
        result["ai_synthesis_log"] = data.get("synthesis_log", [])

        if data.get("domain_verdict"):
            result["verdict"] = data["domain_verdict"]
        if data.get("domain_summary"):
            result["summary"] = data["domain_summary"]

        confirmed = [f for f in result["verified_findings"]
                     if f.get("classification") != "FALSE_POSITIVE"]
        synth_count = len(result.get("synth_findings", []))
        fp_count = len(result.get("false_positives_dropped", []))
        result["total_findings"] = len(confirmed) + synth_count
        result["synth_findings_count"] = synth_count
        result["false_positives_dropped_count"] = fp_count
        result["cross_cutting_count"] = len(result.get("cross_cutting_flags", []))

        return result

    def _merge_verified_domains(self, original_synthesis: dict,
                                verified_domains: list[dict],
                                mechanical_result: StepResult) -> StepResult:
        """Merge per-domain AI verification results into the overall synthesis."""
        all_synth_findings = []
        all_cross_cutting = []
        all_fp_dropped = []
        total_confirmed = 0

        for d in verified_domains:
            all_synth_findings.extend(d.get("synth_findings", []))
            all_cross_cutting.extend(d.get("cross_cutting_flags", []))
            all_fp_dropped.extend(d.get("false_positives_dropped", []))
            total_confirmed += d.get("total_findings", 0)

        any_verified = any(d.get("ai_verified") for d in verified_domains)

        verdicts = [d.get("verdict", "COMMENT") for d in verified_domains]
        if "CHANGES_REQUESTED" in verdicts:
            overall_verdict = "CHANGES_REQUESTED"
        elif "NEEDS_DISCUSSION" in verdicts:
            overall_verdict = "NEEDS_DISCUSSION"
        elif any(v == "COMMENT" for v in verdicts):
            overall_verdict = "COMMENT"
        else:
            overall_verdict = "APPROVE"

        result = dict(original_synthesis)
        result["ai_verified"] = any_verified
        result["per_domain_synthesis"] = verified_domains
        result["synth_findings"] = all_synth_findings
        result["cross_cutting_flags"] = all_cross_cutting
        result["false_positives_dropped"] = all_fp_dropped
        result["total_findings"] = total_confirmed
        result["synth_findings_count"] = len(all_synth_findings)
        result["false_positives_dropped_count"] = len(all_fp_dropped)
        result["cross_cutting_count"] = len(all_cross_cutting)
        result["verdict"] = overall_verdict

        # Aggregate all AI synthesis logs
        all_logs = []
        for d in verified_domains:
            for entry in d.get("ai_synthesis_log", []):
                entry["domain"] = d.get("domain", "general")
                all_logs.append(entry)
        if all_logs:
            result["synthesis_log"] = all_logs

        return StepResult(
            success=True,
            outputs={"synthesis": result, "per_domain_synthesis": verified_domains},
            artifacts=mechanical_result.artifacts,
        )

    # --- Finding extraction ---

    def _extract_findings(self, review: dict) -> list[dict]:
        content_json = review.get("content_json")
        if content_json and isinstance(content_json, dict):
            findings = []
            for section in content_json.get("sections", []):
                severity = section.get("type", "minor")
                for issue in section.get("issues", []):
                    findings.append({
                        "title": issue.get("title", ""),
                        "severity": severity,
                        "location": issue.get("location", {}),
                        "problem": issue.get("problem", ""),
                        "fix": issue.get("fix", ""),
                    })
            return findings

        content_md = review.get("content_md", "")
        if content_md:
            return self._parse_markdown_findings(content_md)
        return []

    def _parse_markdown_findings(self, md: str) -> list[dict]:
        findings = []
        current_severity = "minor"
        lines = md.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            lower = line.lower()
            if line.startswith("#"):
                if "blocking" in lower and "non" not in lower:
                    current_severity = "critical"
                elif "non-blocking" in lower or "non_blocking" in lower:
                    current_severity = "minor"
                elif "critical" in lower:
                    current_severity = "critical"
                elif "major" in lower:
                    current_severity = "major"
                elif "minor" in lower:
                    current_severity = "minor"
            elif line.startswith("**") and line.endswith("**") and not line.startswith("***"):
                title = line.strip("*").strip()
                if title and len(title) > 3:
                    finding = {
                        "title": title,
                        "severity": current_severity,
                        "location": {},
                        "problem": "",
                    }
                    j = i + 1
                    while j < len(lines) and j < i + 15:
                        fline = lines[j].strip()
                        if fline.startswith("- Location:") or fline.startswith("- File:"):
                            loc_match = re.search(r"`([^`]+)`", fline)
                            if loc_match:
                                raw = loc_match.group(1)
                                parts = raw.split(":")
                                loc = {"file": parts[0], "raw": raw}
                                if len(parts) > 1:
                                    try:
                                        loc["start_line"] = int(parts[1])
                                    except ValueError:
                                        pass
                                finding["location"] = loc
                        elif fline.startswith("- Problem:"):
                            finding["problem"] = fline[len("- Problem:"):].strip()
                        elif fline.startswith("- Fix:") or fline.startswith("- Suggested fix:"):
                            finding["fix"] = fline.split(":", 1)[1].strip() if ":" in fline else ""
                        elif fline.startswith("- Evidence:"):
                            finding["evidence"] = fline[len("- Evidence:"):].strip()
                        elif fline.startswith("---") or (fline.startswith("**") and fline.endswith("**")):
                            break
                        j += 1
                    findings.append(finding)
            elif re.match(r"^\d+\.\s+\*\*", line):
                title_match = re.match(r"^\d+\.\s+\*\*(.+?)\*\*", line)
                if title_match:
                    title = title_match.group(1).strip()
                    loc_match = re.search(r"`([^`]+:\d+)`", line)
                    loc = {}
                    if loc_match:
                        raw = loc_match.group(1)
                        parts = raw.split(":")
                        loc = {"file": parts[0], "raw": raw}
                        if len(parts) > 1:
                            try:
                                loc["start_line"] = int(parts[1])
                            except ValueError:
                                pass
                    rest = re.sub(r"^\d+\.\s+\*\*.*?\*\*\s*", "", line)
                    rest = re.sub(r"`[^`]+`\s*[-—]\s*", "", rest)
                    findings.append({
                        "title": title,
                        "severity": current_severity,
                        "location": loc,
                        "problem": rest.strip(),
                    })
            i += 1
        return findings

    @staticmethod
    def _extract_questions(review: dict) -> list[str]:
        md = review.get("content_md", "")
        if not md:
            return []
        questions = []
        in_questions_section = False
        for line in md.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## Questions"):
                in_questions_section = True
                continue
            if in_questions_section:
                if stripped.startswith("## "):
                    break
                q_match = re.match(r"^\d+\.\s+(.+)", stripped)
                if q_match:
                    questions.append(q_match.group(1).strip())
                elif stripped.startswith("- "):
                    questions.append(stripped[2:].strip())
        return questions

    # --- Classification ---

    def _classify_findings(self, findings_a: list, findings_b: list,
                           review_a: dict, review_b: dict) -> dict:
        agreed = []
        a_only = []
        b_matched = set()
        agent_a = review_a.get("agent_name", "Agent A")
        agent_b = review_b.get("agent_name", "Agent B")

        for fa in findings_a:
            matched = False
            for idx, fb in enumerate(findings_b):
                if idx in b_matched:
                    continue
                if self._findings_match(fa, fb):
                    agreed.append({
                        "source": "BOTH",
                        "finding_a": fa,
                        "finding_b": fb,
                        "resolution": "Both agents identified this issue independently",
                    })
                    b_matched.add(idx)
                    matched = True
                    break
            if not matched:
                a_only.append({
                    "source": "A",
                    "finding": fa,
                    "agent": agent_a,
                    "resolution": f"Only {agent_a} flagged this; no contradicting evidence from {agent_b}",
                })

        b_only = [
            {
                "source": "B",
                "finding": fb,
                "agent": agent_b,
                "resolution": f"Only {agent_b} flagged this; {agent_a} did not identify this pattern",
            }
            for idx, fb in enumerate(findings_b)
            if idx not in b_matched
        ]

        return {"agreed": agreed, "a_only": a_only, "b_only": b_only}

    def _findings_match(self, fa: dict, fb: dict) -> bool:
        loc_a = fa.get("location", {})
        loc_b = fb.get("location", {})
        same_file = False

        if loc_a and loc_b:
            file_a = loc_a.get("file", loc_a.get("raw", ""))
            file_b = loc_b.get("file", loc_b.get("raw", ""))
            if file_a and file_b and file_a == file_b:
                same_file = True
                line_a = loc_a.get("start_line", 0)
                line_b = loc_b.get("start_line", 0)
                if line_a and line_b and abs(line_a - line_b) <= 10:
                    return True

        title_a = fa.get("title", "").lower()
        title_b = fb.get("title", "").lower()
        if title_a and title_b:
            words_a = set(re.findall(r'\w+', title_a))
            words_b = set(re.findall(r'\w+', title_b))
            stop_words = {"the", "a", "an", "is", "in", "of", "to", "and", "or", "for", "not", "this"}
            words_a -= stop_words
            words_b -= stop_words
            overlap = len(words_a & words_b)
            threshold = 2 if same_file else 3
            if overlap >= threshold and overlap >= max(1, min(len(words_a), len(words_b)) // 2):
                return True

        prob_a = fa.get("problem", "").lower()
        prob_b = fb.get("problem", "").lower()
        if prob_a and prob_b and same_file:
            func_names = set(re.findall(r'\b[a-z_][a-z_0-9]*\b', prob_a))
            func_names_b = set(re.findall(r'\b[a-z_][a-z_0-9]*\b', prob_b))
            shared = func_names & func_names_b - {"the", "a", "is", "in", "to", "and", "or", "for"}
            if len(shared) >= 3:
                return True

        return False

    # --- Synthesis log ---

    @staticmethod
    def _build_synthesis_log(classified: dict, review_a: dict, review_b: dict) -> list[dict]:
        log = []
        agent_a = review_a.get("agent_name", "Agent A")
        agent_b = review_b.get("agent_name", "Agent B")

        for entry in classified["a_only"]:
            finding = entry.get("finding", {})
            log.append({
                "type": "disagreement",
                "finding_source": "A",
                "agent": agent_a,
                "finding": finding,
                "counterpart": None,
                "resolution": f"Retained: {agent_a} flagged '{finding.get('title', '')}' "
                              f"at {finding.get('location', {}).get('raw', 'unknown')}",
                "evidence": finding.get("problem", ""),
            })

        for entry in classified["b_only"]:
            finding = entry.get("finding", {})
            log.append({
                "type": "disagreement",
                "finding_source": "B",
                "agent": agent_b,
                "finding": finding,
                "counterpart": None,
                "resolution": f"Retained: {agent_b} flagged '{finding.get('title', '')}' "
                              f"at {finding.get('location', {}).get('raw', 'unknown')}",
                "evidence": finding.get("problem", ""),
            })

        return log

    # --- Verdict ---

    def _compute_verdict(self, classified: dict, review_a: dict, review_b: dict) -> str:
        has_critical_agreed = any(
            f.get("finding_a", {}).get("severity") == "critical"
            for f in classified["agreed"]
        )
        if has_critical_agreed:
            return "CHANGES_REQUESTED"

        has_critical_a = any(
            f.get("finding", {}).get("severity") == "critical"
            for f in classified["a_only"]
        )
        has_critical_b = any(
            f.get("finding", {}).get("severity") == "critical"
            for f in classified["b_only"]
        )

        has_major_agreed = any(
            f.get("finding_a", {}).get("severity") == "major"
            for f in classified["agreed"]
        )
        if has_major_agreed or has_critical_a or has_critical_b:
            return "CHANGES_REQUESTED"

        verdict_a = self._extract_verdict(review_a)
        verdict_b = self._extract_verdict(review_b)
        if ((verdict_a == "APPROVE" and verdict_b == "CHANGES_REQUESTED") or
                (verdict_a == "CHANGES_REQUESTED" and verdict_b == "APPROVE")):
            return "NEEDS_DISCUSSION"

        disputed_count = len(classified["a_only"]) + len(classified["b_only"])
        total = disputed_count + len(classified["agreed"])
        if total > 0 and (disputed_count / total) > 0.5:
            return "NEEDS_DISCUSSION"

        if classified["agreed"] or classified["a_only"] or classified["b_only"]:
            return "COMMENT"

        return "APPROVE"

    @staticmethod
    def _extract_verdict(review: dict) -> str:
        cj = review.get("content_json")
        if cj and isinstance(cj, dict):
            v = cj.get("verdict", "")
            if isinstance(v, str) and v in ("APPROVE", "CHANGES_REQUESTED", "NEEDS_DISCUSSION", "COMMENT"):
                return v

        md = review.get("content_md", "")
        if md:
            for line in md.split("\n"):
                stripped = line.strip().upper()
                if "CHANGES_REQUESTED" in stripped:
                    return "CHANGES_REQUESTED"
                if "NEEDS_DISCUSSION" in stripped:
                    return "NEEDS_DISCUSSION"
                if stripped == "APPROVE" or stripped.startswith("APPROVE"):
                    return "APPROVE"
        return ""
