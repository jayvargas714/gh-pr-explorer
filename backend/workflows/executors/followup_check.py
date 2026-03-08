from __future__ import annotations
"""Follow-Up Check step — checks the current state of PRs needing follow-up.

Loads active follow-ups from the DB, uses gh CLI to check PR state, new
commits, and author responses. Classifies each follow-up per the legacy
adversarial review specification state machine.
"""

import json
import logging
import subprocess

from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)


@register_step("followup_check")
class FollowupCheckExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        full_repo = inputs.get("full_repo", "")
        owner = inputs.get("owner", "")
        repo_name = inputs.get("repo", "")

        if not owner and "/" in full_repo:
            owner, repo_name = full_repo.split("/", 1)
        repo_full = f"{owner}/{repo_name}" if owner and repo_name else full_repo

        from backend.database import get_workflow_db
        db = get_workflow_db()
        active_followups = db.list_followups(repo=repo_full, status="active")

        if not active_followups:
            return StepResult(
                success=True,
                outputs={"followup_results": [], "message": "No active follow-ups found"},
            )

        results = []
        for fu in active_followups:
            pr_number = fu["pr_number"]
            followup_id = fu["id"]

            pr_state = self._check_pr_state(owner, repo_name, pr_number)
            if pr_state.get("state") in ("CLOSED", "MERGED"):
                classification = pr_state["state"]
                db.update_followup_status(followup_id, classification)
                results.append({
                    "followup_id": followup_id,
                    "pr_number": pr_number,
                    "classification": classification,
                    "has_new_commits": False,
                    "author_responses": [],
                    "new_comment_count": 0,
                })
                continue

            current_sha = pr_state.get("headSha", "")
            has_new_commits = current_sha != fu.get("review_sha", "")

            our_review_ts = fu.get("published_at", "")
            author_responses = self._get_author_responses(
                owner, repo_name, pr_number, our_review_ts,
                pr_state.get("author", "")
            )
            new_comment_count = self._count_new_comments(
                owner, repo_name, pr_number, our_review_ts
            )

            findings = db.get_followup_findings(followup_id)
            classification = self._classify(
                fu, has_new_commits, author_responses, new_comment_count,
                findings
            )

            db.update_followup_status(followup_id, classification)

            results.append({
                "followup_id": followup_id,
                "pr_number": pr_number,
                "classification": classification,
                "has_new_commits": has_new_commits,
                "current_sha": current_sha,
                "author_responses": author_responses[:10],
                "new_comment_count": new_comment_count,
                "findings_status": [
                    {"finding_id": f["finding_id"], "status": f["status"]}
                    for f in findings
                ],
            })

        return StepResult(
            success=True,
            outputs={"followup_results": results},
            artifacts=[{
                "type": "followup_check",
                "data": {"results": results, "checked": len(results)},
            }],
        )

    @staticmethod
    def _check_pr_state(owner: str, repo: str, pr_number: int) -> dict:
        cmd = [
            "gh", "pr", "view", str(pr_number),
            "--repo", f"{owner}/{repo}",
            "--json", "state,headRefOid,updatedAt,author",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return {
                    "state": data.get("state", "OPEN"),
                    "headSha": data.get("headRefOid", ""),
                    "updatedAt": data.get("updatedAt", ""),
                    "author": data.get("author", {}).get("login", ""),
                }
        except Exception as e:
            logger.error(f"Failed to check PR #{pr_number} state: {e}")
        return {"state": "OPEN"}

    @staticmethod
    def _get_author_responses(owner: str, repo: str, pr_number: int,
                               since: str, author: str) -> list[dict]:
        cmd = [
            "gh", "api", f"repos/{owner}/{repo}/pulls/{pr_number}/comments",
            "--paginate", "--jq",
            f'.[] | select(.user.login == "{author}") | '
            '{{user: .user.login, body: .body, created_at: .created_at}}'
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                responses = []
                for line in result.stdout.strip().split("\n"):
                    try:
                        resp = json.loads(line)
                        if not since or resp.get("created_at", "") > since:
                            responses.append(resp)
                    except json.JSONDecodeError:
                        pass
                return responses
        except Exception as e:
            logger.warning(f"Failed to get author responses: {e}")
        return []

    @staticmethod
    def _count_new_comments(owner: str, repo: str, pr_number: int,
                             since: str) -> int:
        cmd = [
            "gh", "api", f"repos/{owner}/{repo}/issues/{pr_number}/comments",
            "--paginate", "--jq", "length",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                return int(result.stdout.strip() or "0")
        except Exception as e:
            logger.warning(f"Failed to count comments: {e}")
        return 0

    @staticmethod
    def _classify(fu: dict, has_new_commits: bool,
                  author_responses: list, new_comment_count: int,
                  findings: list) -> str:
        current_status = fu.get("status", "NO_RESPONSE")

        if not has_new_commits and not author_responses and new_comment_count == 0:
            return "NO_RESPONSE"

        if author_responses:
            response_texts = " ".join(r.get("body", "").lower() for r in author_responses)
            if any(kw in response_texts for kw in ["disagree", "won't fix", "by design", "intentional"]):
                return "AUTHOR_DISAGREES"
            if has_new_commits:
                all_open = [f for f in findings if f.get("status") in ("OPEN", None)]
                if not all_open:
                    return "RESOLVED"
                return "PARTIALLY_RESOLVED"
            return "DISCUSSING"

        if has_new_commits:
            return "PARTIALLY_RESOLVED"

        return current_status
