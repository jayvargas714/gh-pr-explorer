"""Synthesis step — diffs two review artifacts and classifies findings."""

import logging
import re

from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)


@register_step("synthesis")
class SynthesisExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        reviews = inputs.get("reviews", [])
        completed = [r for r in reviews if r.get("status") == "completed"]

        if not completed:
            return StepResult(
                success=True,
                outputs={"synthesis": {}, "reviews": reviews},
            )

        by_pr: dict[int, list[dict]] = {}
        for r in completed:
            pr = r.get("pr_number", 0)
            by_pr.setdefault(pr, []).append(r)

        all_agreed = []
        all_a_only = []
        all_b_only = []
        artifacts = []

        for pr_number, pr_reviews in by_pr.items():
            if len(pr_reviews) < 2:
                continue

            review_a = pr_reviews[0]
            review_b = pr_reviews[1]

            findings_a = self._extract_findings(review_a)
            findings_b = self._extract_findings(review_b)
            classified = self._classify_findings(findings_a, findings_b)

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
                "verdict": self._compute_verdict(classified, review_a, review_b),
            }

            all_agreed.extend(classified["agreed"])
            all_a_only.extend(classified["a_only"])
            all_b_only.extend(classified["b_only"])

            artifacts.append({
                "type": "synthesis",
                "pr_number": pr_number,
                "data": pr_synthesis,
            })

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

        return StepResult(
            success=True,
            outputs={"synthesis": summary_synthesis, "reviews": reviews},
            artifacts=artifacts,
        )

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
            if "critical" in lower and line.startswith("#"):
                current_severity = "critical"
            elif "major" in lower and line.startswith("#"):
                current_severity = "major"
            elif "minor" in lower and line.startswith("#"):
                current_severity = "minor"
            elif line.startswith("**") and line.endswith("**") and not line.startswith("***"):
                title = line.strip("*").strip()
                if title and len(title) > 3:
                    finding = {"title": title, "severity": current_severity, "location": {}, "problem": ""}
                    j = i + 1
                    while j < len(lines) and j < i + 10:
                        fline = lines[j].strip()
                        if fline.startswith("- Location:"):
                            loc_match = re.search(r"`([^`]+)`", fline)
                            if loc_match:
                                finding["location"] = {"raw": loc_match.group(1)}
                        elif fline.startswith("- Problem:"):
                            finding["problem"] = fline[len("- Problem:"):].strip()
                        elif fline.startswith("- Fix:"):
                            finding["fix"] = fline[len("- Fix:"):].strip()
                        elif fline.startswith("---") or (fline.startswith("**") and fline.endswith("**")):
                            break
                        j += 1
                    findings.append(finding)
            i += 1
        return findings

    def _classify_findings(self, findings_a: list, findings_b: list) -> dict:
        agreed = []
        a_only = []
        b_matched = set()

        for fa in findings_a:
            matched = False
            for idx, fb in enumerate(findings_b):
                if idx in b_matched:
                    continue
                if self._findings_match(fa, fb):
                    agreed.append({
                        "finding_a": fa,
                        "finding_b": fb,
                        "classification": "AGREED",
                    })
                    b_matched.add(idx)
                    matched = True
                    break
            if not matched:
                a_only.append({"finding": fa, "classification": "A-ONLY"})

        b_only = [
            {"finding": fb, "classification": "B-ONLY"}
            for idx, fb in enumerate(findings_b)
            if idx not in b_matched
        ]

        return {"agreed": agreed, "a_only": a_only, "b_only": b_only}

    def _findings_match(self, fa: dict, fb: dict) -> bool:
        loc_a = fa.get("location", {})
        loc_b = fb.get("location", {})
        if loc_a and loc_b:
            file_a = loc_a.get("file", loc_a.get("raw", ""))
            file_b = loc_b.get("file", loc_b.get("raw", ""))
            if file_a and file_b and file_a == file_b:
                return True

        title_a = fa.get("title", "").lower()
        title_b = fb.get("title", "").lower()
        if title_a and title_b:
            words_a = set(title_a.split())
            words_b = set(title_b.split())
            if len(words_a & words_b) >= max(2, len(words_a) // 2):
                return True

        return False

    def _compute_verdict(self, classified: dict, review_a: dict, review_b: dict) -> str:
        has_critical_agreed = any(
            f["finding_a"].get("severity") == "critical"
            for f in classified["agreed"]
        )
        has_critical_a = any(
            f["finding"].get("severity") == "critical"
            for f in classified["a_only"]
        )
        has_critical_b = any(
            f["finding"].get("severity") == "critical"
            for f in classified["b_only"]
        )

        if has_critical_agreed:
            return "CHANGES_REQUESTED"

        has_major_agreed = any(
            f["finding_a"].get("severity") == "major"
            for f in classified["agreed"]
        )
        if has_major_agreed or has_critical_a or has_critical_b:
            return "CHANGES_REQUESTED"

        if classified["agreed"] or classified["a_only"] or classified["b_only"]:
            return "COMMENT"

        return "APPROVE"
