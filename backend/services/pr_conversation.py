"""PR conversation since a review — the author-disposition feed for follow-ups.

A follow-up review used to see only the parent review's findings. When an
author answers a finding with a rationale instead of a commit, that reply is
the thing the follow-up must weigh. This module gathers everything humans
said on the PR after the parent review — top-level comments, inline review
threads, and review bodies — so begin_review can put it in the prompt.

Three REST calls per follow-up start (issue comments, review comments, reviews),
each paginated. Bots, the app's own account (except as thread roots, which are
the findings being answered), and the app's status comments are dropped.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.services.github_service import run_gh_command
from backend.services.pr_status_comments import STATUS_MARKER

logger = logging.getLogger(__name__)

ROOT_EXCERPT_CHARS = 600
DEFAULT_MAX_CHARS = 12000
_TRUNCATION_NOTICE = "\n\n*(conversation truncated — older items shown first)*"


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    """Parse GitHub ISO-8601 (Z) or a naive server-local timestamp to aware UTC."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naive == server-local (reviews.review_timestamp)
    return dt.astimezone(timezone.utc)


def _ndjson(output: str) -> List[Dict[str, Any]]:
    rows = []
    for line in (output or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _is_bot(login: Optional[str]) -> bool:
    return bool(login) and (login.endswith("[bot]") or login.startswith("app/"))


def _excluded(author: Optional[str], body: Optional[str], exclude_login: Optional[str]) -> bool:
    if not body or not body.strip():
        return True
    if STATUS_MARKER in body:
        return True
    if _is_bot(author):
        return True
    return bool(exclude_login) and author == exclude_login


def fetch_conversation_since(owner: str, repo: str, pr_number: int, since: str,
                             exclude_login: Optional[str] = None) -> List[Dict[str, Any]]:
    """Human conversation on the PR after `since`, oldest first.

    Item kinds:
      comment  {author, created_at, body}
      review   {author, state, created_at, body}
      thread   {path, line, created_at, root: {author, created_at, body}, replies: [...]}
    A thread is included when any non-excluded reply is after `since`; its root
    (usually one of our inline findings) is kept, excerpted, for context.
    Raises on a gh failure — callers decide whether that blocks anything.
    """
    since_dt = _parse_ts(since)
    base = f"repos/{owner}/{repo}"

    def after(ts):
        dt = _parse_ts(ts)
        return dt is not None and (since_dt is None or dt > since_dt)

    items: List[Dict[str, Any]] = []

    issue_rows = _ndjson(run_gh_command([
        "api", f"{base}/issues/{pr_number}/comments", "--paginate",
        "--jq", ".[] | {id, user: .user.login, created_at, body}",
    ]))
    for row in issue_rows:
        if after(row.get("created_at")) and not _excluded(row.get("user"), row.get("body"), exclude_login):
            items.append({"kind": "comment", "author": row.get("user"),
                          "created_at": row.get("created_at"), "body": row["body"]})

    review_rows = _ndjson(run_gh_command([
        "api", f"{base}/pulls/{pr_number}/reviews", "--paginate",
        "--jq", ".[] | {id, user: .user.login, state, submitted_at, body}",
    ]))
    for row in review_rows:
        if after(row.get("submitted_at")) and not _excluded(row.get("user"), row.get("body"), exclude_login):
            items.append({"kind": "review", "author": row.get("user"), "state": row.get("state"),
                          "created_at": row.get("submitted_at"), "body": row["body"]})

    comment_rows = _ndjson(run_gh_command([
        "api", f"{base}/pulls/{pr_number}/comments", "--paginate",
        "--jq", ".[] | {id, in_reply_to_id, path, line, original_line, "
                "user: .user.login, created_at, body}",
    ]))
    by_id = {row.get("id"): row for row in comment_rows}
    threads: Dict[Any, Dict[str, Any]] = {}
    for row in comment_rows:
        root_id = row.get("in_reply_to_id") or row.get("id")
        root = by_id.get(root_id, row)
        thread = threads.setdefault(root_id, {
            "kind": "thread", "path": root.get("path"),
            "line": root.get("line") or root.get("original_line"),
            "created_at": None,
            "root": {"author": root.get("user"), "created_at": root.get("created_at"),
                     "body": _excerpt(root.get("body"))},
            "replies": [],
        })
        if row.get("id") == root_id:
            continue
        if after(row.get("created_at")) and not _excluded(row.get("user"), row.get("body"), exclude_login):
            thread["replies"].append({"author": row.get("user"), "created_at": row.get("created_at"),
                                      "body": row["body"]})
    for thread in threads.values():
        if thread["replies"]:
            thread["created_at"] = max(r["created_at"] for r in thread["replies"])
            items.append(thread)

    items.sort(key=lambda i: _parse_ts(i.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))
    return items


def _excerpt(body: Optional[str]) -> str:
    text = (body or "").strip()
    if len(text) > ROOT_EXCERPT_CHARS:
        return text[:ROOT_EXCERPT_CHARS].rstrip() + " …"
    return text


def _stamp(ts: Optional[str]) -> str:
    dt = _parse_ts(ts)
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "unknown time"


def _quote(body: str) -> str:
    return "\n".join(f"  > {line}" for line in (body or "").strip().splitlines()) or "  > (empty)"


def render_conversation(items: List[Dict[str, Any]], max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Markdown rendering of fetch_conversation_since() output, oldest first."""
    if not items:
        return "(no new comments since the previous review)"
    ordered = sorted(items, key=lambda i: _parse_ts(i.get("created_at"))
                     or datetime.min.replace(tzinfo=timezone.utc))
    blocks = []
    for item in ordered:
        kind = item.get("kind")
        if kind == "comment":
            blocks.append(f"- [{_stamp(item.get('created_at'))}] @{item.get('author')} commented:\n"
                          f"{_quote(item.get('body'))}")
        elif kind == "review":
            blocks.append(f"- [{_stamp(item.get('created_at'))}] @{item.get('author')} submitted a "
                          f"review ({item.get('state') or 'COMMENTED'}):\n{_quote(item.get('body'))}")
        elif kind == "thread":
            root = item.get("root") or {}
            loc = f"{item.get('path')}:{item.get('line')}" if item.get("line") else str(item.get("path"))
            lines = [f"- Thread on `{loc}`",
                     f"  - [{_stamp(root.get('created_at'))}] @{root.get('author')} (original comment):\n"
                     f"{_quote(root.get('body'))}"]
            for reply in item.get("replies") or []:
                lines.append(f"  - [{_stamp(reply.get('created_at'))}] @{reply.get('author')} replied:\n"
                             f"{_quote(reply.get('body'))}")
            blocks.append("\n".join(lines))
    text = "\n\n".join(blocks)
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + _TRUNCATION_NOTICE
    return text
