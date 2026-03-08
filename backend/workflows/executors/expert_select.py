"""Expert Select step — infers domain areas from PR changed files and assigns review perspectives."""

import logging
import re

from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)

DOMAIN_PATTERNS: list[tuple[str, list[str]]] = [
    ("backend", [r"backend/", r"server/", r"api/", r"\.py$", r"\.go$", r"\.rs$", r"\.java$"]),
    ("frontend", [r"frontend/", r"src/components/", r"\.tsx?$", r"\.jsx?$", r"\.css$", r"\.scss$"]),
    ("infra", [r"infra/", r"terraform/", r"k8s/", r"docker", r"Dockerfile", r"\.ya?ml$", r"helm/"]),
    ("security", [r"auth", r"security", r"crypt", r"\.pem$", r"\.key$", r"token", r"secret"]),
    ("database", [r"migration", r"schema", r"\.sql$", r"models/", r"database/"]),
    ("testing", [r"test", r"spec/", r"__tests__/", r"\.test\.", r"\.spec\.", r"e2e/", r"cypress/"]),
    ("ci-cd", [r"\.github/", r"ci/", r"pipeline", r"\.circleci/", r"jenkinsfile"]),
    ("docs", [r"docs/", r"README", r"CHANGELOG", r"\.md$"]),
]


@register_step("expert_select")
class ExpertSelectExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        prs = inputs.get("prs", [])
        if not prs:
            return StepResult(success=False, error="No PRs to analyze for expert selection")

        all_domains: set[str] = set()
        pr_domains: list[dict] = []

        for pr in prs:
            files = self._get_changed_files(pr)
            domains = self._classify_files(files)
            if not domains:
                domains = {"backend"}
            all_domains.update(domains)
            pr_domains.append({
                "pr_number": pr.get("number", 0),
                "domains": sorted(domains),
                "file_count": len(files),
            })

        experts = [
            {"domain": d, "perspective": self._domain_perspective(d)}
            for d in sorted(all_domains)
        ]

        return StepResult(
            success=True,
            outputs={
                "experts": experts,
                "pr_domains": pr_domains,
                "prs": prs,
            },
            artifacts=[{
                "type": "expert_selection",
                "data": {
                    "experts": experts,
                    "pr_domains": pr_domains,
                    "total_domains": len(experts),
                },
            }],
        )

    def _get_changed_files(self, pr: dict) -> list[str]:
        files = pr.get("files", [])
        if files:
            return [f.get("path", f.get("filename", "")) if isinstance(f, dict) else str(f) for f in files]
        head_ref = pr.get("headRefName", "")
        if head_ref:
            parts = head_ref.replace("-", "/").split("/")
            return ["/".join(parts)]
        title = pr.get("title", "")
        return [title] if title else []

    def _classify_files(self, files: list[str]) -> set[str]:
        matched = set()
        for filepath in files:
            for domain, patterns in DOMAIN_PATTERNS:
                for pat in patterns:
                    if re.search(pat, filepath, re.IGNORECASE):
                        matched.add(domain)
                        break
        return matched

    @staticmethod
    def _domain_perspective(domain: str) -> str:
        perspectives = {
            "backend": "Focus on API design, error handling, data validation, performance, and service architecture.",
            "frontend": "Focus on component structure, state management, accessibility, UX patterns, and rendering performance.",
            "infra": "Focus on infrastructure security, resource sizing, networking, IAM policies, and deployment reliability.",
            "security": "Focus on authentication flows, authorization checks, secret management, input sanitization, and vulnerability patterns.",
            "database": "Focus on schema design, migration safety, query performance, indexing, and data integrity constraints.",
            "testing": "Focus on test coverage, test reliability, mocking patterns, edge cases, and CI integration.",
            "ci-cd": "Focus on pipeline efficiency, caching, parallelization, failure handling, and deployment gates.",
            "docs": "Focus on accuracy, completeness, clarity, and consistency with the actual implementation.",
        }
        return perspectives.get(domain, "Perform a general code quality review.")
