"""Prioritize step — scores and ranks PRs for review order."""

import logging
from datetime import datetime, timezone

from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)

PRIORITY_LABELS = {0: "P0 — Critical", 1: "P1 — High", 2: "P2 — Normal", 3: "P3 — Low"}


@register_step("prioritize")
class PrioritizeExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        prs = inputs.get("prs", [])
        if not prs:
            return StepResult(success=False, error="No PRs to prioritize")

        skip_list = self._get_skip_list()
        code_owners = self._get_code_owners()
        max_batch = self.step_config.get("max_batch", 10)

        scored = []
        skipped = []
        for pr in prs:
            pr_number = pr.get("number", 0)
            if pr_number in skip_list:
                skipped.append({"pr_number": pr_number, "reason": skip_list[pr_number]})
                continue

            if pr.get("isDraft", False):
                skipped.append({"pr_number": pr_number, "reason": "draft PR"})
                continue

            score, rationale = self._score_pr(pr, code_owners)
            scored.append({
                **pr,
                "priority_score": score,
                "priority_level": self._level(score),
                "priority_rationale": rationale,
            })

        scored.sort(key=lambda x: x["priority_score"], reverse=True)
        batch = scored[:max_batch]

        return StepResult(
            success=True,
            outputs={
                "prs": batch,
                "all_scored_prs": scored,
                "skipped_prs": skipped,
                "batch_size": len(batch),
            },
            artifacts=[{
                "type": "scored_prs",
                "data": {
                    "prs": [
                        {"number": p.get("number"), "title": p.get("title"),
                         "priority_score": p.get("priority_score"),
                         "priority_level": p.get("priority_level"),
                         "priority_rationale": p.get("priority_rationale")}
                        for p in batch
                    ],
                    "skipped": skipped,
                    "total_scored": len(scored),
                    "batch_size": len(batch),
                },
            }],
        )

    def _score_pr(self, pr: dict, code_owners: dict) -> tuple[float, list[str]]:
        score = 50.0
        rationale = []

        additions = pr.get("additions", 0)
        deletions = pr.get("deletions", 0)
        changed_files = pr.get("changedFiles", 0)
        total_lines = additions + deletions

        if total_lines > 1500:
            score += 15
            rationale.append(f"Large PR ({total_lines} lines)")
        elif total_lines > 500:
            score += 10
            rationale.append(f"Medium PR ({total_lines} lines)")
        elif total_lines < 50:
            score -= 10
            rationale.append(f"Small PR ({total_lines} lines)")

        labels = pr.get("labels", [])
        label_names = [l.get("name", "") if isinstance(l, dict) else str(l) for l in labels]

        if any(l in ("priority:critical", "urgent", "hotfix", "P0") for l in label_names):
            score += 30
            rationale.append("Critical priority label")
        if any(l in ("bug", "fix", "bugfix") for l in label_names):
            score += 10
            rationale.append("Bug fix")
        if any(l in ("wip", "do-not-review", "draft") for l in label_names):
            score -= 40
            rationale.append("WIP/no-review label")

        author = pr.get("author", {})
        author_login = author.get("login", "") if isinstance(author, dict) else str(author)
        if author_login in code_owners:
            boost = code_owners[author_login].get("priority_boost", 0)
            if boost:
                score += boost
                rationale.append(f"Code owner boost (+{boost})")

        created = pr.get("createdAt", "")
        if created:
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - created_dt).days
                if age_days > 14:
                    score += 10
                    rationale.append(f"Stale ({age_days}d old)")
                elif age_days > 7:
                    score += 5
                    rationale.append(f"Aging ({age_days}d old)")
            except (ValueError, TypeError):
                pass

        review_decision = pr.get("reviewDecision", "")
        if review_decision == "CHANGES_REQUESTED":
            score -= 5
            rationale.append("Already has changes requested")
        elif review_decision == "APPROVED":
            score -= 20
            rationale.append("Already approved")

        if changed_files > 20:
            score += 5
            rationale.append(f"Many files changed ({changed_files})")

        return max(0, min(100, score)), rationale

    def _level(self, score: float) -> int:
        if score >= 80:
            return 0
        if score >= 60:
            return 1
        if score >= 40:
            return 2
        return 3

    def _get_skip_list(self) -> dict[int, str]:
        repo = self.instance_config.get("repo", "")
        try:
            from backend.database import get_workflow_db
            db = get_workflow_db()
            with db.db.connection() as conn:
                rows = conn.execute(
                    "SELECT pr_number, reason FROM skip_list WHERE repo = ?",
                    (repo,),
                ).fetchall()
                return {r["pr_number"]: r["reason"] for r in rows}
        except Exception:
            return {}

    def _get_code_owners(self) -> dict:
        try:
            from backend.database import get_workflow_db
            db = get_workflow_db()
            with db.db.connection() as conn:
                rows = conn.execute(
                    "SELECT github_handle, display_name, priority_boost "
                    "FROM code_owner_registry"
                ).fetchall()
                return {r["github_handle"]: dict(r) for r in rows}
        except Exception:
            return {}
