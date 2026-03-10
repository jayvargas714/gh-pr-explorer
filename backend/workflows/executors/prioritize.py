"""Prioritize step — scores and ranks PRs for review order.

Includes a preflight check that auto-skips PRs the authenticated user
has already reviewed on GitHub (e.g. from a prior Deep Review run).
"""

import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
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

        # Preflight: detect PRs the current user already reviewed
        prs_to_check = [pr for pr in prs if pr.get("number", 0) not in skip_list]
        already_reviewed = self._preflight_already_reviewed(prs_to_check)
        if already_reviewed:
            self._auto_skip(already_reviewed)
            skip_list.update(already_reviewed)

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

    # ------------------------------------------------------------------
    # Preflight: skip PRs the authenticated user already reviewed
    # ------------------------------------------------------------------

    def _get_current_user(self) -> str:
        """Get the authenticated GitHub username via gh CLI."""
        try:
            result = subprocess.run(
                ["gh", "api", "user", "--jq", ".login"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            logger.warning("Failed to fetch authenticated user for preflight check")
        return ""

    def _check_user_reviewed(self, owner: str, repo: str, pr_number: int,
                             username: str) -> tuple[int, bool]:
        """Check if username has submitted a review on the given PR."""
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{owner}/{repo}/pulls/{pr_number}/reviews",
                 "--jq", f'[.[] | select(.user.login == "{username}" and .state != "DISMISSED")] | length'],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                count = int(result.stdout.strip() or "0")
                return pr_number, count > 0
        except Exception:
            pass
        return pr_number, False

    def _preflight_already_reviewed(self, prs: list[dict]) -> dict[int, str]:
        """Check which PRs the current user has already reviewed.

        Returns a dict of {pr_number: reason} for PRs to skip.
        """
        repo = self.instance_config.get("repo", "")
        if not repo or "/" not in repo:
            return {}
        owner, repo_name = repo.split("/", 1)

        username = self._get_current_user()
        if not username:
            return {}

        logger.info("Preflight: checking %d PRs for existing reviews by %s", len(prs), username)
        already_reviewed: dict[int, str] = {}

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(self._check_user_reviewed, owner, repo_name,
                                pr.get("number", 0), username)
                for pr in prs
            ]
            for future in futures:
                pr_number, reviewed = future.result()
                if reviewed:
                    already_reviewed[pr_number] = f"already reviewed by {username}"

        if already_reviewed:
            logger.info("Preflight: auto-skipping %d PRs already reviewed: %s",
                        len(already_reviewed), list(already_reviewed.keys()))

        return already_reviewed

    def _auto_skip(self, reviewed: dict[int, str]) -> None:
        """Add already-reviewed PRs to the persistent skip list."""
        repo = self.instance_config.get("repo", "")
        instance_id = self.instance_config.get("_instance_id")
        try:
            from backend.database import get_workflow_db
            db = get_workflow_db()
            with db.db.connection() as conn:
                for pr_number, reason in reviewed.items():
                    conn.execute(
                        "INSERT OR IGNORE INTO skip_list (pr_number, repo, reason, instance_id) "
                        "VALUES (?, ?, ?, ?)",
                        (pr_number, repo, reason, instance_id),
                    )
                conn.commit()
        except Exception:
            logger.warning("Failed to persist auto-skip entries", exc_info=True)
