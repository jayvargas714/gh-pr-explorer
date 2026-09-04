"""Tests for pr_conversation — gathering the PR conversation since a review so
follow-ups can process author dispositions."""

import json

import pytest

from backend.services import pr_conversation as conv
from backend.services.pr_status_comments import STATUS_MARKER

OWNER, REPO, PR = "acme", "widgets", 7
ME = "jayvargas714"
SINCE = "2026-09-01 12:00:00"  # reviews.review_timestamp shape (naive, server-local)


def _ndjson(rows):
    return "\n".join(json.dumps(r) for r in rows)


@pytest.fixture
def gh(monkeypatch):
    """Fake run_gh_command keyed on the REST path segment."""
    data = {"issues": [], "pulls_comments": [], "reviews": []}
    calls = []

    def fake(args, **kwargs):
        calls.append(args)
        path = args[1]
        if path.endswith("/comments") and "/issues/" in path:
            return _ndjson(data["issues"])
        if path.endswith("/comments") and "/pulls/" in path:
            return _ndjson(data["pulls_comments"])
        if path.endswith("/reviews"):
            return _ndjson(data["reviews"])
        raise AssertionError(f"unexpected gh call: {args}")

    monkeypatch.setattr(conv, "run_gh_command", fake)
    data["calls"] = calls
    return data


def _issue(author, created, body, id=1):
    return {"id": id, "user": author, "created_at": created, "body": body}


def _rc(id, author, created, body, path="src/a.py", line=42, reply_to=None):
    return {"id": id, "in_reply_to_id": reply_to, "path": path, "line": line,
            "original_line": line, "user": author, "created_at": created, "body": body}


def _review(author, submitted, body, state="COMMENTED", id=9):
    return {"id": id, "user": author, "state": state, "submitted_at": submitted, "body": body}


def test_issue_comments_after_since_are_kept_in_order(gh):
    gh["issues"] = [
        _issue("alice", "2026-09-02T10:00:00Z", "Second", id=2),
        _issue("alice", "2026-09-01T13:00:00Z", "First", id=1),
        _issue("alice", "2026-08-30T00:00:00Z", "Too old", id=0),
    ]
    items = conv.fetch_conversation_since(OWNER, REPO, PR, SINCE, exclude_login=ME)
    assert [i["body"] for i in items] == ["First", "Second"]
    assert all(i["kind"] == "comment" for i in items)


def test_own_comments_bots_and_status_comments_are_dropped(gh):
    gh["issues"] = [
        _issue(ME, "2026-09-02T10:00:00Z", "my own note", id=1),
        _issue("coderabbitai[bot]", "2026-09-02T10:01:00Z", "bot noise", id=2),
        _issue("alice", "2026-09-02T10:02:00Z", f"🤖 status\n{STATUS_MARKER}", id=3),
        _issue("alice", "2026-09-02T10:03:00Z", "real disposition", id=4),
    ]
    items = conv.fetch_conversation_since(OWNER, REPO, PR, SINCE, exclude_login=ME)
    assert [i["body"] for i in items] == ["real disposition"]


def test_review_bodies_from_others_are_kept(gh):
    gh["reviews"] = [
        _review(ME, "2026-09-02T09:00:00Z", "our verdict", state="CHANGES_REQUESTED", id=1),
        _review("alice", "2026-09-02T11:00:00Z", "", id=2),                # empty body
        _review("alice", "2026-09-02T12:00:00Z", "I disagree with #2", id=3),
    ]
    items = conv.fetch_conversation_since(OWNER, REPO, PR, SINCE, exclude_login=ME)
    assert len(items) == 1
    assert items[0]["kind"] == "review"
    assert items[0]["state"] == "COMMENTED"
    assert items[0]["body"] == "I disagree with #2"


def test_threads_group_replies_under_root_and_keep_our_root_for_context(gh):
    gh["pulls_comments"] = [
        _rc(10, ME, "2026-08-31T00:00:00Z", "**Null check missing**\n**Problem:** ..."),
        _rc(11, "alice", "2026-09-02T10:00:00Z", "This is guarded upstream", reply_to=10),
        _rc(12, ME, "2026-09-02T10:30:00Z", "our own reply", reply_to=10),
        _rc(20, ME, "2026-08-31T00:00:00Z", "Old finding, no replies", path="src/b.py", line=7),
        _rc(30, "bob", "2026-08-30T00:00:00Z", "pre-review chatter", path="src/c.py", line=1),
    ]
    items = conv.fetch_conversation_since(OWNER, REPO, PR, SINCE, exclude_login=ME)
    assert len(items) == 1
    thread = items[0]
    assert thread["kind"] == "thread"
    assert thread["path"] == "src/a.py" and thread["line"] == 42
    assert thread["root"]["author"] == ME
    assert thread["root"]["body"].startswith("**Null check missing**")
    assert [r["author"] for r in thread["replies"]] == ["alice"]


def test_thread_root_is_truncated(gh):
    gh["pulls_comments"] = [
        _rc(10, ME, "2026-08-31T00:00:00Z", "x" * 2000),
        _rc(11, "alice", "2026-09-02T10:00:00Z", "reply", reply_to=10),
    ]
    items = conv.fetch_conversation_since(OWNER, REPO, PR, SINCE, exclude_login=ME)
    assert len(items[0]["root"]["body"]) < 700


def test_one_paginated_call_per_endpoint(gh):
    conv.fetch_conversation_since(OWNER, REPO, PR, SINCE, exclude_login=ME)
    assert len(gh["calls"]) == 3
    assert all("--paginate" in c for c in gh["calls"])


def test_endpoint_failure_raises(gh, monkeypatch):
    def boom(args, **kwargs):
        raise RuntimeError("gh exploded")
    monkeypatch.setattr(conv, "run_gh_command", boom)
    with pytest.raises(RuntimeError):
        conv.fetch_conversation_since(OWNER, REPO, PR, SINCE, exclude_login=ME)


# ----- rendering (pure) -----

def test_render_is_chronological_across_kinds():
    items = [
        {"kind": "review", "author": "alice", "state": "COMMENTED",
         "created_at": "2026-09-02T12:00:00Z", "body": "review body"},
        {"kind": "comment", "author": "alice", "created_at": "2026-09-02T10:00:00Z",
         "body": "comment body"},
        {"kind": "thread", "path": "src/a.py", "line": 42, "created_at": "2026-09-02T11:00:00Z",
         "root": {"author": ME, "created_at": "2026-08-31T00:00:00Z", "body": "finding"},
         "replies": [{"author": "alice", "created_at": "2026-09-02T11:00:00Z", "body": "pushback"}]},
    ]
    text = conv.render_conversation(items)
    assert text.index("comment body") < text.index("pushback") < text.index("review body")
    assert "src/a.py:42" in text
    assert "@alice" in text and f"@{ME}" in text
    assert "COMMENTED" in text


def test_render_empty_says_so():
    assert "no new comments" in conv.render_conversation([]).lower()


def test_render_truncates_with_notice():
    items = [{"kind": "comment", "author": "alice", "created_at": f"2026-09-02T10:{i:02d}:00Z",
              "body": "y" * 500} for i in range(60)]
    text = conv.render_conversation(items, max_chars=3000)
    assert len(text) <= 3000 + 200
    assert "truncated" in text.lower()
