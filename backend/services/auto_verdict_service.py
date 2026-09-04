"""Auto verdicts: evaluate a completed review against thresholds and post the verdict.

A PR is "armed" via auto_verdict_arming.auto_verdict_enabled, in one of two modes
(auto_verdict_arming.auto_verdict_mode). In verdict mode, the issue counts in a completed
review's content_json are compared against the criteria; exceeding any threshold
posts REQUEST_CHANGES, staying within all of them posts APPROVE (or nothing, when
auto-approve is disabled). In comment mode, thresholds are ignored and the review
findings are always posted as a COMMENT — the self-review path, since GitHub
rejects both APPROVE and REQUEST_CHANGES on your own PR.

Criteria are the global config, optionally replaced per PR by the stored
override (auto_verdict_arming.auto_verdict_criteria); the master 'enabled' switch
is always global.
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from backend.services.auto_verdict_config import apply_override, get_criteria
from backend.services.github_service import (
    fetch_pr_state_and_sha,
    get_authenticated_login,
)
from backend.services.review_event_log import (
    REASON_AUTO_SKIPPED,
    REASON_AUTO_SUPPRESSED,
    REASON_POST_FAILED,
    REASON_RATE_LIMITED,
    record_verdict_not_posted,
    record_verdict_posted,
)
from backend.services.review_schema import (
    SEVERITIES,
    count_issues,
    format_issue_lines,
    format_resolution_lines,
    get_section_display_names,
)
from backend.services.verdict_service import post_verdict

logger = logging.getLogger(__name__)

# GitHub caps a review body at 65536 characters. Leave headroom for the notice.
MAX_BODY_CHARS = 60000
_TRUNCATION_NOTICE = "\n\n---\n\n_Review report truncated to fit GitHub's comment size limit._"

# A rate-limited post is deferred, not failed: the quota window resets within
# the hour, so the watcher re-attempts with doubling backoff until the row is
# older than the age cap. The schedule is in-memory only — a restart just means
# one immediate retry, which the rate limit itself throttles if still active.
RETRY_INITIAL_BACKOFF_SECONDS = 300
RETRY_MAX_BACKOFF_SECONDS = 3600
RETRY_MAX_AGE_HOURS = 24

# review_id -> (rate-limited retry attempts so far, next attempt unix time)
_retry_schedule: Dict[int, Tuple[int, float]] = {}


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

    Summary and each severity section that has issues — joined with
    horizontal rules. Deliberately excludes the report title,
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

    # Follow-ups: tell the author how each previous finding was resolved —
    # including which pushback was accepted (withdrawn) and which was held
    # (disputed). Rendered after the findings so the verdict reads first.
    resolution = (content_json.get("followup") or {}).get("resolution_status") or []
    if resolution:
        content = "\n".join(format_resolution_lines(resolution)).strip()
        parts.append(f"**Dispositions**\n\n{content}")

    body = "\n\n---\n\n".join(parts)
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + _TRUNCATION_NOTICE
    return body


def _finalize_and_log(
    auto_db, repo: str, pr_number: int, review_id: int, criteria,
    outcome: str, event=None, reason=None, tallies=None, error_detail=None,
) -> Dict[str, Any]:
    """Record a verdict outcome on the claimed row and mirror it into the
    review event log, so the Review Logs tab shows whether the run's verdict
    actually reached GitHub. Also posts the matching PR status comment."""
    auto_db.finalize(
        review_id, outcome, event=event, reason=reason,
        tallies=tallies, criteria=criteria, error_detail=error_detail,
    )
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
                "deferred": REASON_RATE_LIMITED,
            }.get(outcome, REASON_POST_FAILED),
            event=event,
            detail=error_detail or reason,
        )
    _post_outcome_status_comment(repo, pr_number, outcome, event, reason,
                                 tallies, error_detail)
    return {"outcome": outcome, "event": event, "reason": reason}


def _post_outcome_status_comment(repo, pr_number, outcome, event, reason,
                                 tallies, error_detail):
    """Mirror a verdict outcome onto the PR as a status comment.

    A posted verdict needs no comment — the formal review IS the message —
    but the stale "review in progress" comment is cleaned up. Skips on a
    closed/merged PR are silent: nobody is watching, and the post may 422.
    """
    from backend.services.pr_status_comments import (
        delete_status_comments,
        post_verdict_deferred_comment,
        post_verdict_error_comment,
        post_verdict_skipped_comment,
        post_verdict_suppressed_comment,
    )

    owner, _, repo_name = repo.partition("/")
    if not owner or not repo_name:
        return
    if outcome == "posted":
        delete_status_comments(owner, repo_name, pr_number)
    elif outcome == "suppressed":
        post_verdict_suppressed_comment(
            owner, repo_name, pr_number, tallies=tallies, reason=reason)
    elif outcome == "deferred":
        post_verdict_deferred_comment(
            owner, repo_name, pr_number, event=event, tallies=tallies)
    elif outcome == "error":
        post_verdict_error_comment(
            owner, repo_name, pr_number, event=event, tallies=tallies,
            error_detail=error_detail or reason)
    elif outcome == "skipped" and "PR is " not in (reason or ""):
        post_verdict_skipped_comment(owner, repo_name, pr_number, reason=reason)


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
    from backend.database import get_auto_verdicts_db, get_auto_verdict_arming_db, get_reviews_db

    # The master switch is global and not overridable per PR.
    criteria = get_criteria()
    if not criteria.get("enabled"):
        return None

    arming = get_auto_verdict_arming_db().get(repo, pr_number)
    if not arming or not arming.get("auto_verdict_enabled"):
        return None

    criteria = apply_override(criteria, arming)
    mode = arming.get("auto_verdict_mode") or "verdict"

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
        return _finalize_and_log(
            auto_db, repo, pr_number, review_id, criteria,
            outcome, event=event, reason=reason, tallies=tallies, error_detail=error_detail,
        )

    if review.get("status") != "completed":
        return record("skipped", reason=f"Review status is '{review.get('status')}'")

    content_json = _load_review_content(review)
    if content_json is None:
        return record("skipped", reason="Review has no usable structured content")

    if pr_state and pr_state != "OPEN":
        return record("skipped", reason=f"PR is {pr_state}")

    if mode == "comment":
        # Comment mode ignores the thresholds entirely: every completed review's
        # findings are delivered as a COMMENT, clean reviews included.
        tallies = count_issues(content_json)
        counts = ", ".join(f"{tallies[sev]} {sev}" for sev in SEVERITIES)
        event = "COMMENT"
        reason = f"comment mode — review findings posted as comment ({counts})"
    else:
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

    if status_code == 429 and result.get("rate_limited"):
        # Retryable: the quota window resets within the hour. Keep the decision
        # on the row and let the watcher's retry sweep post it later.
        _retry_schedule[review_id] = (0, time.time() + RETRY_INITIAL_BACKOFF_SECONDS)
        logger.warning(f"Auto verdict for {repo}#{pr_number} deferred: GitHub API rate limit exhausted")
        return record(
            "deferred", event=event, reason=reason, tallies=tallies,
            error_detail=str(result.get("error", "GitHub API rate limit exceeded"))[:500],
        )

    if status_code != 200:
        return record(
            "error", event=event, reason=reason, tallies=tallies,
            error_detail=str(result.get("error", result))[:500],
        )

    return record("posted", event=event, reason=reason, tallies=tallies)


def _parse_row_timestamp(value: Optional[str]) -> Optional[float]:
    """SQLite CURRENT_TIMESTAMP ('YYYY-MM-DD HH:MM:SS', UTC) -> unix time."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except (ValueError, TypeError):
        return None


def retry_deferred_verdicts(now: Optional[float] = None) -> None:
    """Re-attempt rate-limit-deferred verdict posts whose backoff has elapsed.

    Called from the auto-verdict watcher loop. The decision (event, thresholds,
    tallies) was already made at defer time and is kept on the row; this only
    re-checks that the PR is still open and armed, recomposes the body from the
    stored review, and posts. A row deferred before a restart has no schedule
    entry and is retried on the first sweep.
    """
    from backend.database import get_auto_verdicts_db, get_auto_verdict_arming_db, get_reviews_db

    auto_db = get_auto_verdicts_db()
    deferred = auto_db.get_deferred()
    if not deferred:
        return
    now = time.time() if now is None else now

    for row in deferred:
        review_id = row["review_id"]
        repo = row["repo"]
        pr_number = row["pr_number"]
        try:
            criteria = json.loads(row["criteria_json"]) if row.get("criteria_json") else None
        except (json.JSONDecodeError, TypeError):
            criteria = None
        tallies = {sev: row.get(f"{sev}_count") for sev in SEVERITIES}
        event = row.get("event")

        def record(outcome, **kwargs):
            _retry_schedule.pop(review_id, None)
            return _finalize_and_log(
                auto_db, repo, pr_number, review_id, criteria, outcome, **kwargs
            )

        created = _parse_row_timestamp(row.get("created_at"))
        if created is not None and now - created > RETRY_MAX_AGE_HOURS * 3600:
            record(
                "error", event=event, reason=row.get("reason"), tallies=tallies,
                error_detail=f"rate-limit retry window expired after {RETRY_MAX_AGE_HOURS}h",
            )
            continue

        attempts, next_attempt = _retry_schedule.get(review_id, (0, now))
        if now < next_attempt:
            continue

        arming = get_auto_verdict_arming_db().get(repo, pr_number)
        if not arming or not arming.get("auto_verdict_enabled"):
            record("skipped", event=event, tallies=tallies,
                   reason="card disarmed while verdict was deferred")
            continue

        review = get_reviews_db().get_review(review_id)
        content_json = _load_review_content(review) if review else None
        if content_json is None:
            record("skipped", event=event, tallies=tallies,
                   reason="review content no longer usable")
            continue

        owner, _, repo_name = repo.partition("/")
        pr_state, _head_sha = fetch_pr_state_and_sha(owner, repo_name, pr_number)
        if pr_state and pr_state != "OPEN":
            record("skipped", event=event, tallies=tallies, reason=f"PR is {pr_state}")
            continue

        body = compose_report_body(content_json)
        logger.info(
            f"Retrying deferred auto verdict for {repo}#{pr_number} "
            f"(review {review_id}, retry attempt {attempts + 1})"
        )
        try:
            result, status_code = post_verdict(
                owner, repo_name, pr_number, event, body, review_id=review_id
            )
        except Exception as e:
            logger.error(f"Deferred auto verdict retry failed for {repo}#{pr_number}: {e}")
            record("error", event=event, reason=row.get("reason"), tallies=tallies,
                   error_detail=str(e))
            continue

        if status_code == 429 and result.get("rate_limited"):
            backoff = min(
                RETRY_INITIAL_BACKOFF_SECONDS * (2 ** (attempts + 1)),
                RETRY_MAX_BACKOFF_SECONDS,
            )
            _retry_schedule[review_id] = (attempts + 1, now + backoff)
            continue

        if status_code != 200:
            record("error", event=event, reason=row.get("reason"), tallies=tallies,
                   error_detail=str(result.get("error", result))[:500])
            continue

        record("posted", event=event, reason=row.get("reason"), tallies=tallies)
