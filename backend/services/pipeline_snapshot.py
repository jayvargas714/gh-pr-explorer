"""In-memory snapshot of the automation pipeline, served by GET /api/automation/pipeline.

Rows are built from the database only (automation_dispatches joined with the
synced PR store, review history, arming and merge-queue membership) plus the
in-memory active_reviews registry — never from gh. A daemon thread rebuilds
the snapshot every PIPELINE_REBUILD_SECONDS, or as soon as a writer calls
mark_dirty(); the version counter lets clients poll cheaply.

Imports of backend.database and review_service are deferred inside functions:
the DAO writers call mark_dirty() from the database package, so this module
must import cleanly before either of those is loaded.
"""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

PIPELINE_REBUILD_SECONDS = 10
DIRTY_CHECK_SECONDS = 1

STAGES = ("waiting", "ready", "reviewing", "reviewed", "mediation", "unidentified",
          "skipped", "opted_out", "failed", "closed")

_STATUS_TO_DECISION = {
    "changes_requested": "CHANGES_REQUESTED",
    "approved": "APPROVED",
    "review_required": "REVIEW_REQUIRED",
}


class PipelineSnapshot:
    """Process-wide snapshot: version, timestamps, rows. Thread-safe."""

    def __init__(self):
        self._lock = threading.Lock()
        self._build_lock = threading.Lock()
        self._dirty = threading.Event()
        self.version = 0
        self.generated_at: Optional[str] = None
        self.pr_data_synced_at: Optional[str] = None
        self.rows: List[Dict[str, Any]] = []

    def mark_dirty(self) -> None:
        self._dirty.set()

    def is_dirty(self) -> bool:
        return self._dirty.is_set()

    def rebuild(self) -> None:
        """Build a fresh row set and publish it as a new version."""
        with self._build_lock:
            self._dirty.clear()
            rows = build_rows()
            synced_at = _latest_repo_sync({r["repo"] for r in rows})
            with self._lock:
                self.rows = rows
                self.version += 1
                self.generated_at = _utc_now_iso()
                self.pr_data_synced_at = synced_at

    def payload(self, include_closed: bool, known_version: Optional[int] = None) -> Dict[str, Any]:
        """Current snapshot, building synchronously the first time. When the
        caller already holds `known_version`, answer with the cheap
        {"unchanged": true} form instead of the rows."""
        with self._lock:
            empty = self.version == 0
        if empty:
            self.rebuild()
        with self._lock:
            if known_version is not None and known_version == self.version:
                return {"unchanged": True, "version": self.version}
            rows = self.rows if include_closed else [r for r in self.rows if r["stage"] != "closed"]
            return {
                "version": self.version,
                "generatedAt": self.generated_at,
                "prDataSyncedAt": self.pr_data_synced_at,
                "rows": rows,
            }


snapshot = PipelineSnapshot()


def mark_dirty() -> None:
    """Cheap, thread-safe: ask the loop to rebuild on its next 1 s tick."""
    snapshot.mark_dirty()


def pipeline_snapshot_loop(interval=PIPELINE_REBUILD_SECONDS):
    """Rebuild every `interval` seconds, or sooner when a writer marked the snapshot dirty."""
    logger.info(f"Pipeline snapshot loop started (interval={interval}s)")
    last_build = 0.0
    while True:
        try:
            if snapshot.is_dirty() or time.time() - last_build >= interval:
                snapshot.rebuild()
                last_build = time.time()
        except Exception as e:
            logger.error(f"Pipeline snapshot rebuild failed: {e}")
            last_build = time.time()
        time.sleep(DIRTY_CHECK_SECONDS)


def derive_stage(dispatch_status: str, detail: Optional[str], pr_state: Optional[str],
                 running: bool, last_verdict_outcome: Optional[str] = None) -> str:
    """Collapse dispatch status + detail, PR state, the live registry and the
    last auto-verdict outcome into one Stage. First match wins; see the spec table."""
    if (pr_state or "").upper() in ("MERGED", "CLOSED"):
        return "closed"
    if running:
        return "reviewing"
    if last_verdict_outcome == "mediation":
        # Disputed findings reached the threshold: auto verdict is disarmed and a
        # human settles it. Sticky until the next review's verdict row exists.
        return "mediation"
    if dispatch_status == "failed":
        return "failed"
    if dispatch_status == "unidentified":
        return "unidentified"
    if dispatch_status == "skipped":
        return "opted_out" if detail == "manual opt-out" else "skipped"
    if dispatch_status == "pending":
        return "waiting" if (detail or "").startswith("waiting") else "ready"
    if dispatch_status == "dispatched":
        return "reviewed"
    # Statuses are constrained by VALID_STATUSES; anything else is not actionable.
    return "skipped"


def running_review_pairs(reviews_db) -> Set[Tuple[str, int]]:
    """(repo, pr_number) of every review running right now. Reaps finished
    subprocesses the same way GET /api/reviews does, so a review that just
    exited doesn't linger as running."""
    from backend.extensions import active_reviews, reviews_lock
    from backend.services.review_service import check_review_status

    running: Set[Tuple[str, int]] = set()
    with reviews_lock:
        keys = list(active_reviews.keys())
    for key in keys:
        check_review_status(key, active_reviews, reviews_lock, reviews_db)
        with reviews_lock:
            review = active_reviews.get(key)
        if review and review.get("status") == "running":
            parts = key.split("/")
            if len(parts) >= 3:
                running.add((f"{parts[0]}/{parts[1]}", int(parts[2])))
    return running


def build_rows(dispatch_rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """PipelineRow dicts for the given dispatch rows (default: the whole
    ledger). Database + in-memory registry only — never gh."""
    from backend.database import (
        get_audits_db, get_auto_verdict_arming_db, get_auto_verdicts_db,
        get_automation_dispatches_db, get_queue_db, get_review_requests_db, get_reviews_db,
        get_synced_prs_db,
    )

    if dispatch_rows is None:
        dispatch_rows = get_automation_dispatches_db().list_dispatches(limit=None)
    if not dispatch_rows:
        return []

    pairs = [(d["repo"], d["pr_number"]) for d in dispatch_rows]

    synced: Dict[Tuple[str, int], Dict[str, Any]] = {}
    store = get_synced_prs_db()
    by_repo: Dict[str, List[int]] = {}
    for repo, number in pairs:
        by_repo.setdefault(repo, []).append(number)
    for repo, numbers in by_repo.items():
        # Chunked: SQLite caps bound variables per statement.
        for i in range(0, len(numbers), 800):
            for number, pr in store.get_prs_by_numbers(repo, numbers[i:i + 800]).items():
                synced[(repo, number)] = pr

    reviews_db = get_reviews_db()
    reviews = reviews_db.get_reviews_for_prs(pairs)
    audits = get_audits_db().get_audits_for_prs(pairs)
    verdicts = get_auto_verdicts_db().get_for_prs(pairs)
    arming = get_auto_verdict_arming_db().get_for_prs(pairs)
    requests = get_review_requests_db().get_for_prs(pairs)
    login = _cached_login()
    queue_db = get_queue_db()
    queue = {(q["repo"], q["pr_number"]): q for q in queue_db.get_queue()}
    notes_counts = queue_db.get_notes_counts() if queue else {}
    running = running_review_pairs(reviews_db)

    return [
        _build_row(
            d, synced.get(pair), reviews.get(pair, []), audits.get(pair, []),
            verdicts.get(pair, []), arming.get(pair), queue.get(pair), notes_counts,
            pair in running, requests.get(pair), login,
        )
        for d, pair in zip(dispatch_rows, pairs)
    ]


def _cached_login() -> Optional[str]:
    """The authenticated login for the review-request badge. github_service
    caches it for the process lifetime, so this is one gh call ever — and a
    failure just hides the badge rather than breaking the snapshot."""
    try:
        from backend.services.github_service import get_authenticated_login
        return get_authenticated_login()
    except Exception:
        return None


def build_row_for(repo: str, pr_number: int) -> Optional[Dict[str, Any]]:
    """One PipelineRow built ad hoc, or None when the PR has no dispatch row."""
    from backend.database import get_automation_dispatches_db

    dispatch = get_automation_dispatches_db().get_by_pr(repo, pr_number)
    if dispatch is None:
        return None
    return build_rows([dispatch])[0]


def _build_row(dispatch, pr, pr_reviews, pr_audits, pr_verdicts, arming_row, queue_row,
               notes_counts, is_running, request_row=None, login=None) -> Dict[str, Any]:
    from backend.services.pr_service import get_ci_status, get_current_reviewers, get_review_status
    from backend.services.review_request_service import review_requested_from
    from backend.services.queue_enrichment import (
        _format_auto_verdict, build_rev_log, format_auto_verdict_state,
        format_automation_state, summarize_reviews,
    )

    repo, pr_number = dispatch["repo"], dispatch["pr_number"]
    pr = pr or {}
    pr_state = (pr.get("state") or "").upper() or None

    review_decision = None
    ci_status = None
    status_check_rollup = None
    current_reviewers: List[Dict[str, Any]] = []
    if pr:
        pr_reviews_json = pr.get("reviews")
        effective = get_review_status(pr.get("reviewDecision"), pr_reviews_json)
        review_decision = _STATUS_TO_DECISION.get(effective, pr.get("reviewDecision")) or None
        ci_status = get_ci_status(pr.get("statusCheckRollup"))
        rollup = pr.get("statusCheckRollup")
        if isinstance(rollup, list):
            status_check_rollup = rollup
        elif isinstance(rollup, dict):
            contexts = rollup.get("contexts")
            status_check_rollup = contexts if isinstance(contexts, list) else None
        current_reviewers = get_current_reviewers(pr_reviews_json)

    # Same signal as the board's "new commits" badge, but only when both SHAs
    # are known (synced rows predating headRefOid in the field list carry None).
    head_sha = pr.get("headRefOid") or None
    reviewed_sha = pr_reviews[0].get("head_commit_sha") if pr_reviews else None
    has_new_commits = bool(head_sha and reviewed_sha and head_sha != reviewed_sha)

    rev_log = build_rev_log(pr_reviews, pr_audits, pr_verdicts)
    automation = format_automation_state(dispatch)
    last_verdict = _format_auto_verdict(pr_verdicts[0]) if pr_verdicts else None
    auto_verdict = (
        format_auto_verdict_state(arming_row or {}, last_verdict)
        if arming_row or last_verdict else None
    )

    return {
        "key": f"{repo}#{pr_number}",
        "repo": repo,
        "prNumber": pr_number,
        "title": pr.get("title"),
        "author": (pr.get("author") or {}).get("login"),
        "url": pr.get("url") or f"https://github.com/{repo}/pull/{pr_number}",
        "prState": pr_state,
        "isDraft": bool(pr.get("isDraft")),
        "baseRefName": pr.get("baseRefName"),
        "additions": pr.get("additions"),
        "deletions": pr.get("deletions"),
        "prUpdatedAt": pr.get("updatedAt"),
        "prSyncedAt": pr.get("fetchedAt"),
        "headSha": head_sha,
        "stage": derive_stage(dispatch["status"], dispatch.get("detail"), pr_state, is_running,
                              (last_verdict or {}).get("outcome")),
        "dispatch": {
            "status": dispatch["status"],
            "detail": dispatch.get("detail"),
            "reviewerKey": dispatch.get("reviewer_key"),
            "ruleName": automation["ruleName"],
            "matchedRules": automation["matchedRules"],
            "attempts": dispatch.get("attempts") or 0,
            "createdAt": dispatch.get("created_at"),
            "updatedAt": dispatch.get("updated_at"),
        },
        "automation": automation,
        "autoVerdict": auto_verdict,
        "reviewDecision": review_decision,
        "currentReviewers": current_reviewers,
        "ciStatus": ci_status,
        "statusCheckRollup": status_check_rollup,
        "running": is_running,
        "review": summarize_reviews(pr_reviews),
        "hasNewCommits": has_new_commits,
        "revLog": rev_log,
        "rounds": sum(1 for e in rev_log if e["kind"] == "review"),
        "onBoard": queue_row is not None,
        "queueItemId": queue_row["id"] if queue_row else None,
        "notesCount": notes_counts.get(queue_row["id"], 0) if queue_row else 0,
        "reviewRequest": ({
            "status": request_row["status"],
            "detail": request_row.get("detail"),
            "requestedAt": request_row.get("requested_at"),
            "attempts": request_row.get("attempts") or 0,
        } if request_row else None),
        "reviewRequestedFromMe": review_requested_from(pr, login) if pr else False,
    }


def _latest_repo_sync(repos: Set[str]) -> Optional[str]:
    """When the PR sync worker last finished a cycle for any repo in the
    snapshot — the honest "PR data as of" stamp. A synced_prs row keeps the
    fetched_at from the last time that PR itself changed, so the oldest of
    those reads as stale for a repo that is perfectly in sync."""
    from backend.database import get_synced_prs_db

    stamps = [
        r.get("last_synced_at")
        for r in get_synced_prs_db().list_repos()
        if r.get("repo") in repos and r.get("last_synced_at")
    ]
    if not stamps:
        return None
    latest = max(stamps)  # SQLite CURRENT_TIMESTAMP: "YYYY-MM-DD HH:MM:SS" (UTC)
    latest = latest.replace(" ", "T")
    return latest if latest.endswith("Z") else latest + "Z"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
