"""PR timeline service: fetch, normalize, and cache GitHub issue timeline events."""

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.services.github_service import (
    run_gh_command,
    parse_json_output,
    fetch_pr_state,
)

logger = logging.getLogger(__name__)

# Events we surface to the UI. Anything else from GitHub is dropped.
_SUPPORTED_EVENT_TYPES = {
    "committed",
    "commented",
    "reviewed",
    "review_requested",
    "ready_for_review",
    "convert_to_draft",
    "closed",
    "reopened",
    "merged",
    "head_ref_force_pushed",
}

_OPEN_TTL_MINUTES = 5

# Tracks which (repo, pr_number) keys have an in-flight background refresh.
_refresh_lock = threading.Lock()
_refreshing: set = set()


def _actor_from(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """Extract a normalized actor dict from a GitHub user object."""
    if not raw:
        return None
    return {
        "login": raw.get("login") or raw.get("name") or "",
        "avatar_url": raw.get("avatar_url", ""),
    }


def _stable_id(event_type: str, created_at: str, actor_login: str, idx: int) -> str:
    return f"{event_type}-{created_at}-{actor_login}-{idx}"


def _normalize_committed(raw: Dict[str, Any], idx: int) -> Optional[Dict[str, Any]]:
    author = raw.get("author") or {}
    sha = raw.get("sha") or ""
    created_at = author.get("date") or ""
    actor = _actor_from({"login": author.get("name", ""), "avatar_url": ""})
    return {
        "id": _stable_id("committed", created_at, actor["login"] if actor else "", idx),
        "type": "committed",
        "created_at": created_at,
        "actor": actor,
        "sha": sha,
        "short_sha": sha[:7],
        "message": raw.get("message", ""),
    }


def _normalize_reviewed(raw: Dict[str, Any], idx: int) -> Optional[Dict[str, Any]]:
    actor = _actor_from(raw.get("user"))
    created_at = raw.get("submitted_at") or raw.get("created_at") or ""
    state = (raw.get("state") or "").upper()
    body = raw.get("body") or ""
    # Drop COMMENTED reviews with no body — these are just inline-comment containers
    # (the actual code comments live on a separate endpoint) and add noise to the timeline.
    if state == "COMMENTED" and not body.strip():
        return None
    return {
        "id": _stable_id("reviewed", created_at, actor["login"] if actor else "", idx),
        "type": "reviewed",
        "created_at": created_at,
        "actor": actor,
        "state": state,
        "body": body,
        "html_url": raw.get("html_url", ""),
    }


def _normalize_commented(raw: Dict[str, Any], idx: int) -> Optional[Dict[str, Any]]:
    actor = _actor_from(raw.get("user") or raw.get("actor"))
    created_at = raw.get("created_at") or ""
    body = raw.get("body") or ""
    if not body.strip():
        return None
    return {
        "id": _stable_id("commented", created_at, actor["login"] if actor else "", idx),
        "type": "commented",
        "created_at": created_at,
        "actor": actor,
        "body": body,
        "html_url": raw.get("html_url", ""),
    }


def _normalize_review_requested(raw: Dict[str, Any], idx: int) -> Optional[Dict[str, Any]]:
    actor = _actor_from(raw.get("actor"))
    created_at = raw.get("created_at") or ""
    reviewer = _actor_from(raw.get("requested_reviewer"))
    return {
        "id": _stable_id("review_requested", created_at, actor["login"] if actor else "", idx),
        "type": "review_requested",
        "created_at": created_at,
        "actor": actor,
        "requested_reviewer": reviewer,
    }


def _normalize_merged(raw: Dict[str, Any], idx: int) -> Optional[Dict[str, Any]]:
    actor = _actor_from(raw.get("actor"))
    created_at = raw.get("created_at") or ""
    return {
        "id": _stable_id("merged", created_at, actor["login"] if actor else "", idx),
        "type": "merged",
        "created_at": created_at,
        "actor": actor,
        "sha": raw.get("commit_id") or "",
    }


def _normalize_force_pushed(raw: Dict[str, Any], idx: int) -> Optional[Dict[str, Any]]:
    actor = _actor_from(raw.get("actor"))
    created_at = raw.get("created_at") or ""
    return {
        "id": _stable_id("head_ref_force_pushed", created_at, actor["login"] if actor else "", idx),
        "type": "head_ref_force_pushed",
        "created_at": created_at,
        "actor": actor,
        "before": raw.get("before_commit_oid") or "",
        "after": raw.get("after_commit_oid") or "",
    }


def _normalize_simple_state_change(raw: Dict[str, Any], event_type: str, idx: int) -> Optional[Dict[str, Any]]:
    """Shared shape for ready_for_review, convert_to_draft, closed, reopened."""
    actor = _actor_from(raw.get("actor"))
    created_at = raw.get("created_at") or ""
    return {
        "id": _stable_id(event_type, created_at, actor["login"] if actor else "", idx),
        "type": event_type,
        "created_at": created_at,
        "actor": actor,
    }


_NORMALIZERS = {
    "committed": _normalize_committed,
    "reviewed": _normalize_reviewed,
    "commented": _normalize_commented,
    "review_requested": _normalize_review_requested,
    "merged": _normalize_merged,
    "head_ref_force_pushed": _normalize_force_pushed,
}


def normalize_timeline_events(
    raw_events: List[Dict[str, Any]],
    pr_info: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Normalize raw GitHub timeline events into unified TimelineEvent dicts.

    pr_info must contain:
        - created_at: ISO 8601 PR creation timestamp
        - user: {login, avatar_url} of PR author

    Returns a list of events sorted ascending by created_at, with an 'opened'
    event synthesized from pr_info prepended.
    """
    result: List[Dict[str, Any]] = []

    for idx, raw in enumerate(raw_events or []):
        event_type = raw.get("event")
        if event_type not in _SUPPORTED_EVENT_TYPES:
            continue
        if event_type in _NORMALIZERS:
            normalized = _NORMALIZERS[event_type](raw, idx)
        else:
            normalized = _normalize_simple_state_change(raw, event_type, idx)
        if normalized and normalized.get("created_at"):
            result.append(normalized)

    # Synthesize the 'opened' event from pr_info.
    opened_actor = _actor_from(pr_info.get("user"))
    opened_created_at = pr_info.get("created_at") or ""
    if opened_created_at:
        result.append({
            "id": _stable_id("opened", opened_created_at, opened_actor["login"] if opened_actor else "", -1),
            "type": "opened",
            "created_at": opened_created_at,
            "actor": opened_actor,
        })

    result.sort(key=lambda e: e["created_at"])
    return result


def fetch_pr_timeline_from_api(owner: str, repo: str, pr_number: int) -> List[Dict[str, Any]]:
    """Fetch and normalize the full issue timeline for a PR.

    Also fetches PR metadata (createdAt, user) to synthesize the 'opened' event.
    """
    try:
        raw_output = run_gh_command([
            "api",
            f"repos/{owner}/{repo}/issues/{pr_number}/timeline",
            "--paginate",
        ])
    except RuntimeError as e:
        logger.warning(f"Failed to fetch timeline for {owner}/{repo}#{pr_number}: {e}")
        raise

    raw_events = parse_json_output(raw_output) or []

    # Fetch minimal PR metadata for the synthesized opened event.
    try:
        pr_output = run_gh_command([
            "api",
            f"repos/{owner}/{repo}/pulls/{pr_number}",
            "--jq",
            '{created_at: .created_at, user: {login: .user.login, avatar_url: .user.avatar_url}}',
        ])
        pr_info = parse_json_output(pr_output) or {}
    except RuntimeError as e:
        logger.warning(f"Failed to fetch PR info for {owner}/{repo}#{pr_number}: {e}")
        pr_info = {}

    return normalize_timeline_events(raw_events, pr_info)


def _now_iso_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _strip_empty_body_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter out empty-body noise from already-cached timelines."""
    cleaned: List[Dict[str, Any]] = []
    for e in events or []:
        etype = e.get("type")
        body = (e.get("body") or "").strip()
        if etype == "commented" and not body:
            continue
        if etype == "reviewed" and (e.get("state") or "").upper() == "COMMENTED" and not body:
            continue
        cleaned.append(e)
    return cleaned


def _ttl_for_state(pr_state: Optional[str]) -> Optional[int]:
    """Return the TTL (in minutes) for a given PR state.

    Closed/Merged PRs are immutable — ttl of None means 'never stale'.
    Open PRs use 5-minute TTL.
    """
    if pr_state in ("CLOSED", "MERGED"):
        return None
    return _OPEN_TTL_MINUTES


def _background_refresh(owner: str, repo: str, pr_number: int, cache_db) -> None:
    """Worker function: refetch from the API and update the cache."""
    key = (repo, pr_number)
    try:
        current_state = fetch_pr_state(owner, repo, pr_number) or "OPEN"
        events = fetch_pr_timeline_from_api(owner, repo, pr_number)
        cache_db.save_cache(f"{owner}/{repo}", pr_number, current_state, events)
        logger.info(f"Background timeline refresh complete for {owner}/{repo}#{pr_number}")
    except Exception as e:
        logger.warning(
            f"Background timeline refresh failed for {owner}/{repo}#{pr_number}: {e}"
        )
    finally:
        with _refresh_lock:
            _refreshing.discard(key)


def get_timeline(
    owner: str,
    repo: str,
    pr_number: int,
    cache_db,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Cache-aware entry point for the timeline endpoint.

    Returns a dict matching the response schema:
        {
            "events": [...],
            "pr_state": "OPEN" | "CLOSED" | "MERGED",
            "last_updated": "...Z",
            "cached": bool,
            "stale": bool,
            "refreshing": bool,
        }
    """
    repo_key = f"{owner}/{repo}"
    key = (repo, pr_number)
    cached = cache_db.get_cached(repo_key, pr_number)

    if cached and not force_refresh:
        ttl = _ttl_for_state(cached["pr_state"])
        is_stale = cache_db.is_stale(repo_key, pr_number, ttl)

        if not is_stale:
            return {
                "events": _strip_empty_body_events(cached["data"]),
                "pr_state": cached["pr_state"],
                "last_updated": cached["updated_at"],
                "cached": True,
                "stale": False,
                "refreshing": False,
            }

        # Stale: return immediately, trigger background refresh.
        with _refresh_lock:
            already_refreshing = key in _refreshing
            if not already_refreshing:
                _refreshing.add(key)
        if not already_refreshing:
            t = threading.Thread(
                target=_background_refresh,
                args=(owner, repo, pr_number, cache_db),
                daemon=True,
            )
            t.start()

        return {
            "events": _strip_empty_body_events(cached["data"]),
            "pr_state": cached["pr_state"],
            "last_updated": cached["updated_at"],
            "cached": True,
            "stale": True,
            "refreshing": True,
        }

    # Cache miss or force refresh: fetch synchronously.
    current_state = fetch_pr_state(owner, repo, pr_number) or "OPEN"
    events = fetch_pr_timeline_from_api(owner, repo, pr_number)
    cache_db.save_cache(repo_key, pr_number, current_state, events)

    return {
        "events": events,
        "pr_state": current_state,
        "last_updated": _now_iso_z(),
        "cached": False,
        "stale": False,
        "refreshing": False,
    }
