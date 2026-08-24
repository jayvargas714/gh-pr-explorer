"""Auto verdicts: evaluate a completed review against thresholds and post the verdict.

A PR is "armed" via merge_queue.auto_verdict_enabled. When a review for an armed PR
completes, the issue counts in its content_json are compared against the global
criteria; exceeding any threshold posts REQUEST_CHANGES, staying within all of them
posts APPROVE (or nothing, when auto-approve is disabled).
"""

import json
import logging
from typing import Any, Dict, Optional, Tuple

from backend.services.auto_verdict_config import get_criteria
from backend.services.github_service import (
    fetch_pr_state_and_sha,
    get_authenticated_login,
)
from backend.services.review_event_log import (
    REASON_AUTO_SKIPPED,
    REASON_AUTO_SUPPRESSED,
    REASON_POST_FAILED,
    record_verdict_not_posted,
    record_verdict_posted,
)
from backend.services.review_schema import (
    format_issue_lines,
    format_recommendation_lines,
    get_section_display_names,
)
from backend.services.verdict_service import post_verdict

logger = logging.getLogger(__name__)

SEVERITIES = ("critical", "major", "minor")

# GitHub caps a review body at 65536 characters. Leave headroom for the notice.
MAX_BODY_CHARS = 60000
_TRUNCATION_NOTICE = "\n\n---\n\n_Review report truncated to fit GitHub's comment size limit._"


def count_issues(content_json: Dict[str, Any]) -> Dict[str, int]:
    """Count issues per severity in a review's content_json."""
    tallies = {sev: 0 for sev in SEVERITIES}
    for section in content_json.get("sections", []) or []:
        section_type = section.get("type", "")
        if section_type in tallies:
            issues = section.get("issues") or []
            tallies[section_type] = len(issues)
    return tallies


def evaluate_criteria(
    content_json: Dict[str, Any],
    criteria: Dict[str, Any],
) -> Tuple[str, Dict[str, int], str]:
    """Compare a review's issue counts against the thresholds.

    Returns (decision, tallies, reason) where decision is 'request_changes' or 'pass'.
    """
    tallies = count_issues(content_json)
    limits = {
        "critical": criteria["maxCritical"],
        "major": criteria["maxMajor"],
        "minor": criteria["maxMinor"],
    }

    breaches = [
        f"{tallies[sev]} {sev} > {limits[sev]} allowed"
        for sev in SEVERITIES
        if tallies[sev] > limits[sev]
    ]

    if breaches:
        return "request_changes", tallies, "; ".join(breaches)

    within = ", ".join(f"{tallies[sev]} {sev}" for sev in SEVERITIES)
    allowed = "/".join(str(limits[sev]) for sev in SEVERITIES)
    return "pass", tallies, f"{within} — within limits ({allowed})"


def compose_report_body(content_json: Dict[str, Any]) -> str:
    """Compose the verdict body the same way the manual verdict modal does.

    Summary, each severity section that has issues, and recommendations —
    joined with horizontal rules. Deliberately excludes the report title,
    metadata block, highlights, and the 0-10 score so auto-posted verdicts
    match manually posted ones.
    """
    parts = []

    summary = (content_json.get("summary") or "").strip()
    if summary:
        parts.append(f"**Summary**\n\n{summary}")

    section_names = get_section_display_names()
    for section in content_json.get("sections", []) or []:
        issues = section.get("issues") or []
        if not issues:
            continue
        sec_type = section.get("type", "")
        display_name = section.get("display_name") or section_names.get(sec_type, sec_type.title())
        content = "\n".join(format_issue_lines(issues)).strip()
        parts.append(f"**{display_name}**\n\n{content}")

    recs = content_json.get("recommendations") or []
    if recs:
        content = "\n".join(format_recommendation_lines(recs)).strip()
        parts.append(f"**Recommendations**\n\n{content}")

    body = "\n\n---\n\n".join(parts)
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + _TRUNCATION_NOTICE
    return body


def _load_review_content(review: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse a review row's content_json, or None if unusable."""
    raw = review.get("content_json")
    if not raw:
        return None
    try:
        parsed = raw if isinstance(raw, dict) else json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict) or parsed.get("error"):
        return None
    return parsed


def maybe_post_auto_verdict(repo: str, pr_number: int, review_id: int) -> Optional[Dict[str, Any]]:
    """Evaluate a completed review and post an auto verdict if the PR is armed.

    Args:
        repo: Repository in ``owner/repo`` form.
        pr_number: PR number.
        review_id: The reviews row that just completed.

    Returns:
        The recorded decision dict, or None when no auto verdict applies.
    """
    from backend.database import get_auto_verdicts_db, get_queue_db, get_reviews_db

    criteria = get_criteria()
    if not criteria.get("enabled"):
        return None

    queue_db = get_queue_db()
    queue_item = queue_db.get_queue_item(pr_number, repo)
    if not queue_item or not queue_item.get("auto_verdict_enabled"):
        return None

    owner, _, repo_name = repo.partition("/")
    if not owner or not repo_name:
        logger.warning(f"Auto verdict: malformed repo '{repo}' — skipping")
        return None

    auto_db = get_auto_verdicts_db()
    review = get_reviews_db().get_review(review_id)
    if not review:
        logger.warning(f"Auto verdict: review {review_id} not found — skipping")
        return None

    pr_state, head_sha = fetch_pr_state_and_sha(owner, repo_name, pr_number)

    # Claim before doing anything observable so a concurrent poll cannot double-post.
    if not auto_db.claim(repo, pr_number, review_id, head_sha):
        return None

    def record(outcome, event=None, reason=None, tallies=None, error_detail=None):
        auto_db.finalize(
            review_id, outcome, event=event, reason=reason,
            tallies=tallies, criteria=criteria, error_detail=error_detail,
        )
        # Mirror the terminal outcome into the review event log so the Review
        # Logs tab can show whether the run's verdict actually reached GitHub.
        if outcome == "posted":
            record_verdict_posted(
                repo, pr_number, review_id=review_id, event=event,
                auto_started=True, detail=reason,
            )
        else:
            record_verdict_not_posted(
                repo, pr_number, review_id=review_id,
                reason={
                    "suppressed": REASON_AUTO_SUPPRESSED,
                    "skipped": REASON_AUTO_SKIPPED,
                }.get(outcome, REASON_POST_FAILED),
                event=event,
                detail=error_detail or reason,
            )
        return {"outcome": outcome, "event": event, "reason": reason}

    if review.get("status") != "completed":
        return record("skipped", reason=f"Review status is '{review.get('status')}'")

    content_json = _load_review_content(review)
    if content_json is None:
        return record("skipped", reason="Review has no usable structured content")

    if pr_state and pr_state != "OPEN":
        return record("skipped", reason=f"PR is {pr_state}")

    decision, tallies, reason = evaluate_criteria(content_json, criteria)

    if decision == "request_changes":
        event = "REQUEST_CHANGES"
    elif not criteria.get("allowAutoApprove"):
        return record(
            "suppressed", reason=f"{reason} — auto-approve disabled", tallies=tallies
        )
    elif review.get("pr_author") and review["pr_author"] == get_authenticated_login():
        # GitHub rejects APPROVE on your own PR (422), so deliver the report as a comment.
        event = "COMMENT"
        reason = f"{reason} — self-authored, posted as comment instead of approval"
    else:
        event = "APPROVE"

    body = compose_report_body(content_json)
    try:
        result, status_code = post_verdict(
            owner, repo_name, pr_number, event, body, review_id=review_id
        )
    except Exception as e:
        logger.error(f"Auto verdict post failed for {repo}#{pr_number}: {e}")
        return record("error", event=event, reason=reason, tallies=tallies, error_detail=str(e))

    if status_code != 200:
        return record(
            "error", event=event, reason=reason, tallies=tallies,
            error_detail=str(result.get("error", result))[:500],
        )

    return record("posted", event=event, reason=reason, tallies=tallies)
