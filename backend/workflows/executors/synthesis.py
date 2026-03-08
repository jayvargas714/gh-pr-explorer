from __future__ import annotations
"""Synthesis step — compares two review artifacts and classifies findings.

Supports single-tier (team-review) and two-tier (self/deep-review) synthesis
with source attribution, synthesis log, NEEDS_DISCUSSION verdict, and
enhanced finding matching per the legacy adversarial review specification.
"""

import logging
import re

from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)


@register_step("synthesis")
class SynthesisExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        reviews = inputs.get("reviews", [])
        mode = inputs.get("mode", "team-review")
        completed = [r for r in reviews if r.get("status") == "completed"]

        if not completed:
            return StepResult(
                success=True,
                outputs={"synthesis": {}, "reviews": reviews},
            )

        if mode in ("self-review", "deep-review"):
            return self._two_tier_synthesis(completed, reviews, mode)
        return self._single_tier_synthesis(completed, reviews)

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

            review_a = pr_reviews[0]
            review_b = pr_reviews[1]

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
            outputs={"synthesis": summary_synthesis, "reviews": reviews},
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

            review_a = domain_reviews[0]
            review_b = domain_reviews[1]

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

        summary_synthesis = {
            "agreed": all_agreed,
            "a_only": all_a_only,
            "b_only": all_b_only,
            "total_findings": total,
            "agreed_count": len(all_agreed),
            "disputed_count": len(all_a_only) + len(all_b_only),
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
                "reviews": reviews,
            },
            artifacts=artifacts,
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
