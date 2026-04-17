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
    return {
        "id": _stable_id("reviewed", created_at, actor["login"] if actor else "", idx),
        "type": "reviewed",
        "created_at": created_at,
        "actor": actor,
        "state": state,
        "body": raw.get("body") or "",
        "html_url": raw.get("html_url", ""),
    }


def _normalize_commented(raw: Dict[str, Any], idx: int) -> Optional[Dict[str, Any]]:
    actor = _actor_from(raw.get("user") or raw.get("actor"))
    created_at = raw.get("created_at") or ""
    return {
        "id": _stable_id("commented", created_at, actor["login"] if actor else "", idx),
        "type": "commented",
        "created_at": created_at,
        "actor": actor,
        "body": raw.get("body") or "",
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
