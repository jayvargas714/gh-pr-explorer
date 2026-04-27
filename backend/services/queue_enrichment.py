"""Queue enrichment helpers - shared between /api/merge-queue and /api/swimlanes/board.

Given the raw rows from the merge_queue table, attaches the per-card live data
that the frontend QueueItem component expects: PR state, review status,
inline-comment counts, current reviewers, etc.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional

from backend.database import get_queue_db, get_reviews_db
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

    def enrich(item: Dict[str, Any]) -> Dict[str, Any]:
        return _enrich_one(item, queue_db, reviews_db)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(enrich, items))


def _enrich_one(item: Dict[str, Any], queue_db, reviews_db) -> Dict[str, Any]:
    notes_count = queue_db.get_notes_count(item["id"])
    repo_parts = item["repo"].split("/")
    pr_state: Optional[str] = None
    has_new_commits = False
    last_reviewed_sha: Optional[str] = None
    current_sha: Optional[str] = None
    review_score: Optional[float] = None
    has_review = False
    review_id: Optional[int] = None
    inline_comments_posted = False
    major_concerns_posted = False
    minor_issues_posted = False
    critical_posted_count = None
    critical_found_count = None
    major_posted_count = None
    major_found_count = None
    minor_posted_count = None
    minor_found_count = None
    critical_issue_titles = None
    major_issue_titles = None
    minor_issue_titles = None
    is_followup = False
    review_decision: Optional[str] = None
    ci_status: Optional[str] = None
    is_draft = False
    current_reviewers: List[Dict[str, Any]] = []

    if len(repo_parts) == 2:
        owner, repo = repo_parts
        queue_data = fetch_pr_queue_data(owner, repo, item["pr_number"])
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
        is_draft = queue_data.get("isDraft", False)
        current_reviewers = get_current_reviewers(queue_reviews)

        latest_review = reviews_db.get_latest_review_for_pr(item["repo"], item["pr_number"])
        if latest_review:
            has_review = True
            review_score = latest_review.get("score")
            review_id = latest_review.get("id")
            inline_comments_posted = latest_review.get("inline_comments_posted", False)
            major_concerns_posted = latest_review.get("major_concerns_posted", False)
            minor_issues_posted = latest_review.get("minor_issues_posted", False)
            critical_posted_count = latest_review.get("critical_posted_count")
            critical_found_count = latest_review.get("critical_found_count")
            major_posted_count = latest_review.get("major_posted_count")
            major_found_count = latest_review.get("major_found_count")
            minor_posted_count = latest_review.get("minor_posted_count")
            minor_found_count = latest_review.get("minor_found_count")
            is_followup = bool(latest_review.get("is_followup", False))
            if latest_review.get("head_commit_sha"):
                last_reviewed_sha = latest_review["head_commit_sha"]
                if current_sha and last_reviewed_sha:
                    has_new_commits = current_sha != last_reviewed_sha

            critical_issue_titles, major_issue_titles, minor_issue_titles = \
                _extract_issue_titles(latest_review.get("content_json"))
    else:
        pr_state = item.get("pr_state")

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
        "lastReviewedSha": last_reviewed_sha,
        "currentSha": current_sha,
        "hasReview": has_review,
        "reviewScore": review_score,
        "reviewId": review_id,
        "inlineCommentsPosted": inline_comments_posted,
        "majorConcernsPosted": major_concerns_posted,
        "minorIssuesPosted": minor_issues_posted,
        "criticalPostedCount": critical_posted_count,
        "criticalFoundCount": critical_found_count,
        "majorPostedCount": major_posted_count,
        "majorFoundCount": major_found_count,
        "minorPostedCount": minor_posted_count,
        "minorFoundCount": minor_found_count,
        "criticalIssueTitles": critical_issue_titles,
        "majorIssueTitles": major_issue_titles,
        "minorIssueTitles": minor_issue_titles,
        "isFollowup": is_followup,
        "reviewDecision": review_decision,
        "ciStatus": ci_status,
        "isDraft": is_draft,
        "currentReviewers": current_reviewers,
    }


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
