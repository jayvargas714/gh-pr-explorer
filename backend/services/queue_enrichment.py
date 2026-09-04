"""Queue enrichment helpers - shared between /api/merge-queue and /api/swimlanes/board.

Given the raw rows from the merge_queue table, attaches the per-card live data
that the frontend QueueItem component expects: PR state, review status,
inline-comment counts, current reviewers, etc.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional

from backend.database import (
    get_queue_db, get_reviews_db, get_audits_db, get_auto_verdicts_db,
    get_automation_dispatches_db, get_auto_verdict_arming_db,
)
from backend.services.github_service import fetch_pr_queue_data
from backend.services.pr_service import get_ci_status, get_current_reviewers, get_review_status


def enrich_queue_items(items: List[Dict[str, Any]], max_workers: int = 5) -> List[Dict[str, Any]]:
    """Enrich a list of raw merge_queue rows with live PR + review data.

    Returned dicts use the same keys the frontend QueueItem expects, so they can be
    rendered identically in the merge queue panel and the swimlane board.
    """
    if not items:
        return []

    queue_db = get_queue_db()
    reviews_db = get_reviews_db()
    audits_db = get_audits_db()
    auto_verdicts_db = get_auto_verdicts_db()

    def enrich(item: Dict[str, Any]) -> Dict[str, Any]:
        return _enrich_one(item, queue_db, reviews_db, audits_db, auto_verdicts_db)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(enrich, items))


def _enrich_one(item: Dict[str, Any], queue_db, reviews_db, audits_db, auto_verdicts_db) -> Dict[str, Any]:
    notes_count = queue_db.get_notes_count(item["id"])
    repo_parts = item["repo"].split("/")
    pr_state: Optional[str] = None
    has_new_commits = False
    last_reviewed_sha: Optional[str] = None
    current_sha: Optional[str] = None
    review_summary: Optional[Dict[str, Any]] = None
    review_decision: Optional[str] = None
    ci_status: Optional[str] = None
    status_check_rollup: Optional[List[Dict[str, Any]]] = None
    is_draft = False
    current_reviewers: List[Dict[str, Any]] = []
    rev_log: List[Dict[str, Any]] = []
    auto_verdict_last: Optional[Dict[str, Any]] = None
    review_requested_from_me = False

    if len(repo_parts) == 2:
        owner, repo = repo_parts
        queue_data = fetch_pr_queue_data(owner, repo, item["pr_number"])
        review_requested_from_me = _review_requested_from_me(queue_data)
        pr_state = queue_data["state"]
        current_sha = queue_data["headRefOid"]
        queue_reviews = queue_data.get("reviews")
        effective_status = get_review_status(queue_data["reviewDecision"], queue_reviews)
        status_to_decision = {
            "changes_requested": "CHANGES_REQUESTED",
            "approved": "APPROVED",
            "review_required": "REVIEW_REQUIRED",
            "pending": None,
        }
        review_decision = status_to_decision.get(effective_status, queue_data["reviewDecision"])
        ci_status = get_ci_status(queue_data["statusCheckRollup"])
        rollup = queue_data.get("statusCheckRollup")
        if isinstance(rollup, list):
            status_check_rollup = rollup
        elif isinstance(rollup, dict):
            contexts = rollup.get("contexts")
            status_check_rollup = contexts if isinstance(contexts, list) else None
        is_draft = queue_data.get("isDraft", False)
        current_reviewers = get_current_reviewers(queue_reviews)

        pr_reviews = reviews_db.get_reviews_for_pr(item["repo"], item["pr_number"])
        pr_audits = audits_db.get_audits_for_pr(item["repo"], item["pr_number"])
        pr_auto_verdicts = auto_verdicts_db.get_for_pr(item["repo"], item["pr_number"])
        rev_log = build_rev_log(pr_reviews, pr_audits, pr_auto_verdicts)
        auto_verdict_last = _format_auto_verdict(pr_auto_verdicts[0]) if pr_auto_verdicts else None
        review_summary = summarize_reviews(pr_reviews)
        latest_review = pr_reviews[0] if pr_reviews else None
        if latest_review:
            stored_sha = latest_review.get("head_commit_sha")
            if stored_sha:
                last_reviewed_sha = stored_sha
                if current_sha and last_reviewed_sha:
                    has_new_commits = current_sha != last_reviewed_sha
            elif current_sha:
                # Review exists but no SHA was captured (typically because GitHub
                # returned a 5xx during the original fetch_pr_head_sha call).
                # Treat this as "potentially has new commits" so the follow-up
                # signal still surfaces — losing the badge entirely defeats the
                # whole point of the indicator.
                has_new_commits = True
    else:
        pr_state = item.get("pr_state")

    rs = review_summary or {}
    return {
        "id": item["id"],
        "number": item["pr_number"],
        "title": item["pr_title"],
        "url": item["pr_url"],
        "author": item["pr_author"],
        "additions": item["additions"],
        "deletions": item["deletions"],
        "repo": item["repo"],
        "addedAt": item["added_at"],
        "notesCount": notes_count,
        "prState": pr_state or item.get("pr_state"),
        "hasNewCommits": has_new_commits,
        "reviewRequestedFromMe": review_requested_from_me,
        "lastReviewedSha": last_reviewed_sha,
        "currentSha": current_sha,
        "hasReview": review_summary is not None,
        "reviewScore": rs.get("score"),
        "reviewId": rs.get("reviewId"),
        "inlineCommentsPosted": rs.get("inlineCommentsPosted", False),
        "majorConcernsPosted": rs.get("majorConcernsPosted", False),
        "minorIssuesPosted": rs.get("minorIssuesPosted", False),
        "criticalPostedCount": rs.get("critical", {}).get("posted"),
        "criticalFoundCount": rs.get("critical", {}).get("found"),
        "majorPostedCount": rs.get("major", {}).get("posted"),
        "majorFoundCount": rs.get("major", {}).get("found"),
        "minorPostedCount": rs.get("minor", {}).get("posted"),
        "minorFoundCount": rs.get("minor", {}).get("found"),
        "criticalIssueTitles": rs.get("critical", {}).get("titles"),
        "majorIssueTitles": rs.get("major", {}).get("titles"),
        "minorIssueTitles": rs.get("minor", {}).get("titles"),
        "isFollowup": rs.get("isFollowup", False),
        "autoVerdict": format_auto_verdict_state(
            get_auto_verdict_arming_db().get(item["repo"], item["pr_number"]) or {},
            auto_verdict_last,
        ),
        "automation": format_automation_state(
            get_automation_dispatches_db().get_by_pr(item["repo"], item["pr_number"])
        ),
        "reviewDecision": review_decision,
        "ciStatus": ci_status,
        "statusCheckRollup": status_check_rollup,
        "isDraft": is_draft,
        "currentReviewers": current_reviewers,
        "revLog": rev_log,
    }


def summarize_reviews(pr_reviews: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Summarize the newest review of a PR (rows newest first) for card and
    pipeline payloads: score, follow-up flag, posted flags and per-severity
    posted/found counts + issue titles. None when the PR has no review."""
    if not pr_reviews:
        return None
    latest = pr_reviews[0]
    critical_titles, major_titles, minor_titles = _extract_issue_titles(latest.get("content_json"))
    titles = {"critical": critical_titles, "major": major_titles, "minor": minor_titles}
    return {
        "reviewId": latest.get("id"),
        "score": latest.get("score"),
        "isFollowup": bool(latest.get("is_followup", False)),
        "createdAt": latest.get("review_timestamp"),
        "inlineCommentsPosted": bool(latest.get("inline_comments_posted", False)),
        "majorConcernsPosted": bool(latest.get("major_concerns_posted", False)),
        "minorIssuesPosted": bool(latest.get("minor_issues_posted", False)),
        **{
            sev: {
                "posted": latest.get(f"{sev}_posted_count"),
                "found": latest.get(f"{sev}_found_count"),
                "titles": titles[sev],
            }
            for sev in ("critical", "major", "minor")
        },
    }


def format_automation_state(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Shape an automation_dispatches row for the card payload. None -> None."""
    if not row:
        return None
    rule_name = None
    matched_rules: List[str] = []
    raw = row.get("outcome_json")
    if raw:
        try:
            outcome = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(outcome, dict):
                rule_name = outcome.get("rule")
                matched = outcome.get("matched_rules")
                if isinstance(matched, list):
                    matched_rules = matched
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "status": row.get("status"),
        "reviewerKey": row.get("reviewer_key"),
        "ruleName": rule_name,
        "matchedRules": matched_rules,
        "detail": row.get("detail"),
        "updatedAt": row.get("updated_at"),
    }


def format_auto_verdict_state(item: Dict[str, Any], last: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Shape an auto_verdict_arming row ({} when the PR was never armed) for the card payload."""
    override = None
    raw = item.get("auto_verdict_criteria")
    if raw:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, dict):
                override = parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "enabled": bool(item.get("auto_verdict_enabled")),
        "reviewerType": item.get("auto_verdict_reviewer") or "default",
        "mode": item.get("auto_verdict_mode") or "verdict",
        "criteriaOverride": override,
        "last": last,
    }


def _format_auto_verdict(row):
    """Shape an auto_verdicts row for the card payload."""
    return {
        "reviewId": row.get("review_id"),
        "event": row.get("event"),
        "outcome": row.get("outcome"),
        "reason": row.get("reason"),
        "criticalCount": row.get("critical_count"),
        "majorCount": row.get("major_count"),
        "minorCount": row.get("minor_count"),
        "createdAt": row.get("created_at"),
    }


def build_rev_log(reviews, audits, auto_verdicts=None):
    """Merge review + audit + auto-verdict rows into one newest-first summary list.

    Auto verdicts are folded into the review entry they were derived from
    (verdictEvent/verdictOutcome/verdictReason), so each review round occupies a
    single entry. A verdict only gets its own entry when its review is not in
    the list. Each entry carries only summary fields (no content_json parsing).
    """
    entries = []
    review_by_id = {}
    for r in reviews:
        entry = {
            "kind": "review",
            "id": r["id"],
            "timestamp": r["review_timestamp"],
            "status": r["status"],
            "score": r.get("score"),
            "isFollowup": bool(r.get("is_followup", False)),
            "autoStarted": bool(r.get("auto_started", False)),
        }
        if r.get("reviewer_agent"):
            entry["reviewerAgent"] = r["reviewer_agent"]
        entries.append(entry)
        review_by_id[r["id"]] = entry
    for a in audits:
        entries.append({
            "kind": "audit",
            "id": a["id"],
            "timestamp": a["audit_timestamp"],
            "status": a["status"],
            "findingCount": a.get("finding_count", 0),
            "blockingCount": a.get("blocking_count", 0),
            "reviewerAgent": "pb_ed",
        })
    for v in auto_verdicts or []:
        parent = review_by_id.get(v.get("review_id"))
        if parent is not None and "verdictOutcome" not in parent:
            # Verdicts arrive newest-first, so the first match is the latest
            # verdict for that review; any older duplicates fall through to
            # standalone entries below.
            parent["verdictOutcome"] = v.get("outcome")
            parent["verdictEvent"] = v.get("event")
            parent["verdictReason"] = v.get("reason")
            continue
        entries.append({
            "kind": "auto_verdict",
            "id": v["id"],
            "timestamp": v.get("created_at"),
            "status": v.get("outcome"),
            "event": v.get("event"),
            "reason": v.get("reason"),
            "reviewId": v.get("review_id"),
        })
    entries.sort(key=lambda e: e["timestamp"] or "", reverse=True)
    return entries


def _extract_issue_titles(content_json_raw):
    """Return (critical_titles, major_titles, minor_titles) — each a list of strings or None."""
    if not content_json_raw:
        return None, None, None
    try:
        data = content_json_raw if isinstance(content_json_raw, dict) else json.loads(content_json_raw)
        section_map = {"critical": [], "major": [], "minor": []}
        for section in data.get("sections", []):
            stype = section.get("type", "")
            if stype in section_map:
                for issue in section.get("issues", []):
                    title = issue.get("title", "").strip()
                    if title:
                        section_map[stype].append(title)
        return (
            section_map["critical"] or None,
            section_map["major"] or None,
            section_map["minor"] or None,
        )
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None, None, None


def _review_requested_from_me(queue_data) -> bool:
    """Badge flag from the per-card gh fetch; a login lookup failure hides it."""
    try:
        from backend.services.github_service import get_authenticated_login
        from backend.services.review_request_service import review_requested_from
        return review_requested_from(queue_data, get_authenticated_login())
    except Exception:
        return False
