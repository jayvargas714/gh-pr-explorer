"""Tests for the post-incident review hardening (Aug 31 OOM).

Covers the concurrency budget gate in begin_review, the per-attempt wall-clock
timeout, process-group kill semantics, the workspace recipe in the prompt, the
resource-limit prefix, the stale-workspace sweeper, and the dispatch-window
expiry. Only the process-group test spawns real processes (two sleeps).
"""

import json
import os
import signal
import subprocess
import time

import pytest

from backend.extensions import active_reviews, reviews_lock
from backend.services import review_service
from backend.services.automation_dispatch_worker import _dispatch_window_expired

OWNER = "owner"
REPO = "repo"
PR = 42
KEY = f"{OWNER}/{REPO}/{PR}"
PR_URL = f"https://github.com/{OWNER}/{REPO}/pull/{PR}"


@pytest.fixture(autouse=True)
def clean_active_reviews():
    with reviews_lock:
        active_reviews.clear()
    yield
    with reviews_lock:
        active_reviews.clear()


def register_running(key, **overrides):
    entry = {"process": None, "status": "running", "auto_started": False}
    entry.update(overrides)
    with reviews_lock:
        active_reviews[key] = entry
    return entry


# --- concurrency budget gate in begin_review ---------------------------------

@pytest.fixture
def budget(monkeypatch):
    """Pin the automation budget and stub everything begin_review touches."""
    monkeypatch.setattr(
        "backend.services.automation_config.get_config",
        lambda: {"maxConcurrentAutoReviews": 2},
    )
    monkeypatch.setattr(review_service, "fetch_pr_head_sha", lambda *a, **kw: "abc123")
    monkeypatch.setattr(
        review_service, "start_review_process",
        lambda *a, **kw: (object(), "/tmp/review.md", kw.get("is_followup", False)),
    )
    monkeypatch.setattr(review_service, "post_review_started_comment", lambda *a, **kw: None)
    monkeypatch.setattr(review_service, "record_started", lambda *a, **kw: None)


def test_auto_review_over_budget_returns_429(budget):
    register_running("o/r/1")
    register_running("o/r/2", auto_started=True)

    payload, status = review_service.begin_review(
        OWNER, REPO, PR, PR_URL, reviews_db=None, auto_started=True,
    )
    assert status == 429
    assert payload["over_budget"] is True
    with reviews_lock:
        assert KEY not in active_reviews  # refused with no side effects


def test_manual_reviews_count_toward_budget_but_are_admitted(budget):
    """Two manual runs fill the budget for auto spawns; a third manual still starts."""
    register_running("o/r/1")
    register_running("o/r/2")

    payload, status = review_service.begin_review(
        OWNER, REPO, PR, PR_URL, reviews_db=None, auto_started=False,
    )
    assert status == 201


def test_bypass_budget_admits_a_replacement(budget):
    register_running("o/r/1", auto_started=True)
    register_running("o/r/2", auto_started=True)

    payload, status = review_service.begin_review(
        OWNER, REPO, PR, PR_URL, reviews_db=None,
        auto_started=True, bypass_budget=True,
    )
    assert status == 201


def test_auto_review_under_budget_starts(budget):
    register_running("o/r/1")

    payload, status = review_service.begin_review(
        OWNER, REPO, PR, PR_URL, reviews_db=None, auto_started=True,
    )
    assert status == 201


# --- wall-clock timeout -------------------------------------------------------

class HungProcess:
    """A Popen stand-in that never exits."""

    def __init__(self, pid=1234):
        self.pid = pid

    def poll(self):
        return None


def register_hung(deadline, **overrides):
    entry = {
        "process": HungProcess(),
        "status": "running",
        "started_at": "now",
        "pr_url": PR_URL,
        "review_file": "/tmp/review.md",
        "is_followup": False,
        "attempt": 1,
        "retry_at": None,
        "run_id": "run-test",
        "max_attempts": 3,
        "deadline": deadline,
        "spawn": {"pr_url": PR_URL, "owner": OWNER, "repo": REPO, "pr_number": PR,
                  "is_followup": False, "previous_review_content": None,
                  "reviewer_type": "default"},
    }
    entry.update(overrides)
    with reviews_lock:
        active_reviews[KEY] = entry
    return entry


@pytest.fixture
def timeout_harness(monkeypatch):
    killed = []
    recorded = []
    monkeypatch.setattr(review_service, "_kill_process_group",
                        lambda process: killed.append(process.pid))
    monkeypatch.setattr(review_service, "record_failed",
                        lambda *a, **kw: recorded.append(kw))
    monkeypatch.setattr(review_service, "record_retry_scheduled", lambda *a, **kw: None)
    monkeypatch.setattr(review_service, "record_gave_up", lambda *a, **kw: None)
    monkeypatch.setattr(review_service, "save_review_to_db", lambda *a, **kw: None)
    monkeypatch.setattr(review_service, "_spawn_auto_verdict", lambda *a, **kw: None)
    return killed, recorded


def test_running_review_past_deadline_is_killed_and_retried(monkeypatch, timeout_harness):
    killed, recorded = timeout_harness
    monkeypatch.setattr(review_service, "get_review_retry_settings", lambda: (3, 0))
    register_hung(deadline=time.monotonic() - 1)

    review = review_service.check_review_status(KEY, active_reviews, reviews_lock, reviews_db=None)

    assert killed == [1234]
    assert len(recorded) == 1
    assert recorded[0]["reason"] == "timeout"
    assert review["retry_at"] is not None       # retry armed
    assert review["status"] == "running"        # one continuous review to callers


def test_timeout_on_last_attempt_finalizes_as_failed(monkeypatch, timeout_harness):
    killed, recorded = timeout_harness
    monkeypatch.setattr(review_service, "get_review_retry_settings", lambda: (1, 0))
    register_hung(deadline=time.monotonic() - 1)

    review = review_service.check_review_status(KEY, active_reviews, reviews_lock, reviews_db=None)

    assert killed == [1234]
    assert review["status"] == "failed"


def test_running_review_before_deadline_is_left_alone(timeout_harness):
    killed, _ = timeout_harness
    register_hung(deadline=time.monotonic() + 3600)

    review = review_service.check_review_status(KEY, active_reviews, reviews_lock, reviews_db=None)

    assert killed == []
    assert review["status"] == "running"


def test_no_deadline_means_no_timeout(timeout_harness):
    killed, _ = timeout_harness
    register_hung(deadline=None)

    review = review_service.check_review_status(KEY, active_reviews, reviews_lock, reviews_db=None)

    assert killed == []
    assert review["status"] == "running"


# --- process-group kill semantics ---------------------------------------------

def test_kill_process_group_kills_descendants():
    """The whole tree dies, including a child the leader backgrounded — the
    exact shape (CLI -> sh -> git) that outlived every kill in the incident."""
    process = subprocess.Popen(
        ["bash", "-c", "sleep 300 & exec sleep 300"],
        start_new_session=True,
    )
    pgid = os.getpgid(process.pid)

    review_service._kill_process_group(process)

    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            break  # every member is gone
        time.sleep(0.1)
    else:
        os.killpg(pgid, signal.SIGKILL)
        pytest.fail("process group survived _kill_process_group")


# --- workspace recipe in the prompt --------------------------------------------

@pytest.fixture
def spawn_env(monkeypatch, tmp_path):
    """Run the real start_review_process with a captured Popen."""
    calls = {}

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            calls["cmd"] = cmd
            calls["kwargs"] = kwargs
            self.pid = 4321

    monkeypatch.setattr(review_service.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(review_service, "_resolve_reviewer",
                        lambda rt: {"key": rt, "agent_name": "elite-code-reviewer",
                                    "prompt_context": None})
    monkeypatch.setattr(review_service, "get_reviews_dir", lambda: tmp_path / "reviews")
    monkeypatch.setattr(
        review_service, "get_review_workspace_config",
        lambda: {"root": tmp_path / "ws", "fetch_depth": 50,
                 "fetch_timeout_seconds": 600, "sweep_after_hours": 24},
    )
    monkeypatch.setitem(review_service._SYSTEMD_RUN_STATE, "checked", True)
    monkeypatch.setitem(review_service._SYSTEMD_RUN_STATE, "available", True)
    monkeypatch.setattr(review_service, "get_review_resource_limits", lambda: ("12G", 256))
    return calls


def _prompt_of(calls):
    cmd = calls["cmd"]
    i = cmd.index("claude")  # the systemd-run prefix also uses "-p"
    assert cmd[i + 1] == "-p"
    return cmd[i + 2]


def test_prompt_prescribes_the_safe_workspace_recipe(spawn_env, tmp_path):
    process, review_file, _ = review_service.start_review_process(
        PR_URL, OWNER, REPO, PR, head_sha="abc123def",
    )

    prompt = _prompt_of(spawn_env)
    ws = str(tmp_path / "ws" / f"{OWNER}-{REPO}-pr-{PR}")
    assert ws in prompt
    assert f"https://github.com/{OWNER}/{REPO}.git" in prompt
    assert "git fetch -q --depth=50 --no-tags origin abc123def" in prompt
    assert "timeout 600 git fetch" in prompt
    assert "NEVER run git clone or git fetch against a local filesystem path" in prompt
    assert "NEVER use --filter" in prompt
    assert f"rm -rf {ws}" in prompt


def test_prompt_without_head_sha_asks_the_reviewer_to_resolve_it(spawn_env):
    review_service.start_review_process(PR_URL, OWNER, REPO, PR)
    prompt = _prompt_of(spawn_env)
    assert "gh pr view --json headRefOid" in prompt
    assert "<head-sha>" in prompt


def test_spawn_uses_its_own_process_group_and_a_log_file(spawn_env, tmp_path):
    review_service.start_review_process(PR_URL, OWNER, REPO, PR, head_sha="abc")
    kwargs = spawn_env["kwargs"]
    assert kwargs["start_new_session"] is True
    assert kwargs["stdout"] is not subprocess.PIPE
    assert kwargs["stderr"] is not subprocess.PIPE
    assert (tmp_path / "reviews" / "logs").is_dir()


def test_resource_limit_prefix_wraps_the_cli(spawn_env):
    review_service.start_review_process(PR_URL, OWNER, REPO, PR, head_sha="abc")
    cmd = spawn_env["cmd"]
    assert cmd[0] == "systemd-run"
    assert "-p" in cmd and "MemoryMax=12G" in cmd and "TasksMax=256" in cmd
    assert "claude" in cmd


def test_no_prefix_when_systemd_run_is_unavailable(spawn_env, monkeypatch):
    monkeypatch.setitem(review_service._SYSTEMD_RUN_STATE, "available", False)
    review_service.start_review_process(PR_URL, OWNER, REPO, PR, head_sha="abc")
    assert spawn_env["cmd"][0] == "claude"


def test_stale_workspace_is_precleaned_before_spawn(spawn_env, tmp_path):
    ws = tmp_path / "ws" / f"{OWNER}-{REPO}-pr-{PR}"
    ws.mkdir(parents=True)
    (ws / "leftover.txt").write_text("stale")

    review_service.start_review_process(PR_URL, OWNER, REPO, PR, head_sha="abc")

    assert not ws.exists()


# --- stale-workspace sweeper ----------------------------------------------------

def test_sweeper_removes_only_old_unused_workspaces(monkeypatch, tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setattr(
        review_service, "get_review_workspace_config",
        lambda: {"root": root, "fetch_depth": 50,
                 "fetch_timeout_seconds": 600, "sweep_after_hours": 24},
    )
    old = root / "o-r-pr-1"
    fresh = root / "o-r-pr-2"
    in_use = root / f"{OWNER}-{REPO}-pr-{PR}"
    for d in (old, fresh, in_use):
        d.mkdir()
    stale_time = time.time() - 48 * 3600
    os.utime(old, (stale_time, stale_time))
    os.utime(in_use, (stale_time, stale_time))
    register_running(KEY)  # in_use belongs to this running review

    review_service.sweep_stale_workspaces()

    assert not old.exists()
    assert fresh.exists()
    assert in_use.exists()


# --- dispatch window expiry ------------------------------------------------------

def test_dispatch_window_expiry():
    fresh = {"enrolled_at": "2026-09-01 00:00:00"}
    assert _dispatch_window_expired(fresh, {"dispatchTimeoutHours": 0}) is False

    old = {"enrolled_at": "2020-01-01 00:00:00"}
    assert _dispatch_window_expired(old, {"dispatchTimeoutHours": 72}) is True

    never_enrolled = {"enrolled_at": None}
    assert _dispatch_window_expired(never_enrolled, {"dispatchTimeoutHours": 72}) is False


# --- follow-up prompt: conversation + dispositions ------------------------------

PREV_CONTENT = json.dumps({
    "schema_version": "1.0.0", "metadata": {"pr_number": PR, "repository": f"{OWNER}/{REPO}"},
    "summary": "Prior summary.", "score": {"overall": 5},
    "sections": [{"type": "critical", "display_name": "Critical Issues", "issues": [
        {"title": "Null check missing", "location": {"file": "a.py", "start_line": 1, "end_line": 2},
         "problem": "p", "fix": "f"}]}],
})


def test_followup_prompt_carries_conversation_and_disposition_rules(spawn_env):
    review_service.start_review_process(
        PR_URL, OWNER, REPO, PR, is_followup=True, previous_review_content=PREV_CONTENT,
        head_sha="abc123", conversation="- @alice replied: guarded upstream",
    )
    prompt = _prompt_of(spawn_env)
    assert "---PR CONVERSATION SINCE PREVIOUS REVIEW---" in prompt
    assert "@alice replied: guarded upstream" in prompt
    assert "---END PR CONVERSATION---" in prompt
    assert "DISPOSITION" in prompt
    for status in ("resolved", "partially_addressed", "not_addressed", "wont_fix", "withdrawn", "disputed"):
        assert status in prompt
    assert "never silently drop" in prompt.lower()
    assert "No new commits since the previous review" not in prompt


def test_followup_prompt_flags_unchanged_head(spawn_env):
    review_service.start_review_process(
        PR_URL, OWNER, REPO, PR, is_followup=True, previous_review_content=PREV_CONTENT,
        head_sha="abc123", conversation="x", head_unchanged=True,
    )
    assert "No new commits since the previous review" in _prompt_of(spawn_env)


def test_followup_prompt_without_conversation_says_unavailable(spawn_env):
    review_service.start_review_process(
        PR_URL, OWNER, REPO, PR, is_followup=True, previous_review_content=PREV_CONTENT,
        head_sha="abc123", conversation=None,
    )
    prompt = _prompt_of(spawn_env)
    assert "---PR CONVERSATION SINCE PREVIOUS REVIEW---" in prompt
    assert "conversation unavailable" in prompt.lower()


def test_initial_prompt_has_no_conversation_block(spawn_env):
    review_service.start_review_process(PR_URL, OWNER, REPO, PR, head_sha="abc123")
    assert "PR CONVERSATION" not in _prompt_of(spawn_env)


@pytest.fixture
def followup_env(budget, monkeypatch, tmp_path):
    """begin_review with a real reviews DB holding one parent review, and a
    captured start_review_process."""
    from backend.database.base import Database
    from backend.database.reviews import ReviewsDB
    reviews_db = ReviewsDB(Database(tmp_path / "followup.db"))
    parent_id = reviews_db.save_review(
        pr_number=PR, repo=f"{OWNER}/{REPO}", status="completed", pr_url=PR_URL,
        pr_title="t", pr_author="alice", content_json=PREV_CONTENT, head_commit_sha="old",
    )
    captured = {}
    monkeypatch.setattr(
        review_service, "start_review_process",
        lambda *a, **kw: (captured.update(kw) or object(), "/tmp/review.md", kw.get("is_followup", False)),
    )
    monkeypatch.setattr(review_service, "get_authenticated_login", lambda: "me")
    monkeypatch.setattr(review_service, "fetch_pr_state", lambda *a, **kw: "OPEN")
    return {"reviews_db": reviews_db, "parent_id": parent_id, "captured": captured}


def test_begin_review_fetches_conversation_since_parent(followup_env, monkeypatch):
    calls = []

    def fake_fetch(owner, repo, pr_number, since, exclude_login=None):
        calls.append({"since": since, "exclude_login": exclude_login})
        return [{"kind": "comment", "author": "alice", "created_at": "2026-09-02T10:00:00Z",
                 "body": "guarded upstream"}]
    monkeypatch.setattr(review_service, "fetch_conversation_since", fake_fetch)

    payload, status = review_service.begin_review(
        OWNER, REPO, PR, PR_URL, followup_env["reviews_db"], is_followup=True, head_unchanged=True,
    )

    assert status == 201, payload
    parent = followup_env["reviews_db"].get_review(followup_env["parent_id"])
    assert calls == [{"since": parent["review_timestamp"], "exclude_login": "me"}]
    kw = followup_env["captured"]
    assert kw["is_followup"] is True
    assert "guarded upstream" in kw["conversation"]
    assert kw["head_unchanged"] is True
    spawn = active_reviews[KEY]["spawn"]
    assert spawn["conversation"] == kw["conversation"]
    assert spawn["head_unchanged"] is True


def test_begin_review_survives_conversation_fetch_failure(followup_env, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("gh exploded")
    monkeypatch.setattr(review_service, "fetch_conversation_since", boom)

    payload, status = review_service.begin_review(
        OWNER, REPO, PR, PR_URL, followup_env["reviews_db"], is_followup=True,
    )

    assert status == 201, payload
    assert followup_env["captured"]["conversation"] is None


def test_initial_review_does_not_fetch_conversation(followup_env, monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("must not fetch for an initial review")
    monkeypatch.setattr(review_service, "fetch_conversation_since", boom)
    payload, status = review_service.begin_review(OWNER, REPO, PR, PR_URL, followup_env["reviews_db"])
    assert status == 201, payload
