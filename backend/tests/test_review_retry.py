"""Tests for review failure detection and the retry loop.

Nothing here spawns a Claude CLI process: start_review_process is stubbed and
the "process" objects are fakes whose poll() returns a scripted exit code.
"""

import pytest

from backend.config import (
    DEFAULT_REVIEW_MAX_ATTEMPTS,
    REVIEW_MAX_ATTEMPTS_CAP,
    get_review_retry_settings,
)
from backend.extensions import active_reviews, reviews_lock
from backend.services import review_service

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


class FakeProcess:
    """A Popen stand-in with a scripted exit code."""

    def __init__(self, exit_code=0, pid=1234):
        self._exit_code = exit_code
        self.pid = pid

    def poll(self):
        return self._exit_code

    def communicate(self, timeout=None):
        return ("", "")


@pytest.fixture
def saved(monkeypatch):
    """Capture save_review_to_db calls instead of writing to the database."""
    calls = []

    def fake_save(key, review, status, reviews_db):
        calls.append({"key": key, "status": status, "review_file": review.get("review_file")})
        return len(calls)

    monkeypatch.setattr(review_service, "save_review_to_db", fake_save)
    monkeypatch.setattr(review_service, "_spawn_auto_verdict", lambda key, review_id: None)
    return calls


def set_retry_policy(monkeypatch, max_attempts, delay=0):
    monkeypatch.setattr(
        review_service, "get_review_retry_settings", lambda: (max_attempts, delay)
    )


def register(review_file, process, **overrides):
    entry = {
        "process": process,
        "status": "running",
        "started_at": "now",
        "pr_url": PR_URL,
        "review_file": str(review_file),
        "is_followup": False,
        "attempt": 1,
        "retry_at": None,
        "run_id": "run-test",
        "max_attempts": 3,
        "spawn": {
            "pr_url": PR_URL,
            "owner": OWNER,
            "repo": REPO,
            "pr_number": PR,
            "is_followup": False,
            "previous_review_content": None,
            "reviewer_type": "default",
        },
    }
    entry.update(overrides)
    with reviews_lock:
        active_reviews[KEY] = entry
    return entry


def poll():
    return review_service.check_review_status(KEY, active_reviews, reviews_lock, reviews_db=None)


# --- review_produced_output -------------------------------------------------

def test_output_detected_from_markdown_only(tmp_path):
    md = tmp_path / "review.md"
    md.write_text("# Review")
    assert review_service.review_produced_output(str(md)) is True


def test_output_detected_from_json_only(tmp_path):
    md = tmp_path / "review.md"
    (tmp_path / "review.json").write_text("{}")
    assert review_service.review_produced_output(str(md)) is True


def test_no_output_when_neither_file_written(tmp_path):
    assert review_service.review_produced_output(str(tmp_path / "review.md")) is False


def test_no_output_for_missing_path():
    assert review_service.review_produced_output(None) is False
    assert review_service.review_produced_output("") is False


# --- failure detection ------------------------------------------------------

def test_exit_zero_with_output_completes(monkeypatch, saved, tmp_path):
    set_retry_policy(monkeypatch, max_attempts=3)
    md = tmp_path / "review.md"
    md.write_text("# Review")
    register(md, FakeProcess(exit_code=0))

    review = poll()

    assert review["status"] == "completed"
    assert [c["status"] for c in saved] == ["completed"]


def test_exit_zero_without_output_is_retried_not_completed(monkeypatch, saved, tmp_path):
    """The silent-failure case: a clean exit that wrote no review."""
    set_retry_policy(monkeypatch, max_attempts=3)
    spawned = []
    monkeypatch.setattr(
        review_service, "start_review_process",
        lambda **kwargs: (spawned.append(kwargs) or FakeProcess(exit_code=0, pid=999),
                          str(tmp_path / "retry.md"), kwargs["is_followup"]),
    )
    register(tmp_path / "review.md", FakeProcess(exit_code=0))

    review = poll()

    # Failed attempt: still reported as running, nothing saved yet.
    assert review["status"] == "running"
    assert review["retry_at"] is not None
    assert saved == []

    # Backoff elapsed (delay 0) -> next poll starts attempt 2.
    review = poll()

    assert review["status"] == "running"
    assert review["attempt"] == 2
    assert review["review_file"] == str(tmp_path / "retry.md")
    assert len(spawned) == 1
    assert saved == []


def test_nonzero_exit_is_retried(monkeypatch, saved, tmp_path):
    set_retry_policy(monkeypatch, max_attempts=2)
    monkeypatch.setattr(
        review_service, "start_review_process",
        lambda **kwargs: (FakeProcess(exit_code=0), str(tmp_path / "retry.md"), False),
    )
    register(tmp_path / "review.md", FakeProcess(exit_code=1))

    assert poll()["retry_at"] is not None
    assert saved == []


# --- attempt limit ----------------------------------------------------------

def test_gives_up_and_saves_failed_after_limit(monkeypatch, saved, tmp_path):
    set_retry_policy(monkeypatch, max_attempts=3)
    attempts = []

    def fake_spawn(**kwargs):
        attempts.append(kwargs)
        return FakeProcess(exit_code=1), str(tmp_path / "review.md"), False

    monkeypatch.setattr(review_service, "start_review_process", fake_spawn)
    register(tmp_path / "review.md", FakeProcess(exit_code=1))

    # attempt 1 fails -> arm retry; respawn -> attempt 2 fails -> arm retry;
    # respawn -> attempt 3 fails -> limit reached.
    for _ in range(6):
        review = poll()
        if review["status"] != "running":
            break

    assert review["status"] == "failed"
    assert review["attempt"] == 3
    assert len(attempts) == 2, "two retries after the initial attempt"
    assert [c["status"] for c in saved] == ["failed"]


def test_single_attempt_policy_disables_retry(monkeypatch, saved, tmp_path):
    set_retry_policy(monkeypatch, max_attempts=1)
    register(tmp_path / "review.md", FakeProcess(exit_code=1))

    review = poll()

    assert review["status"] == "failed"
    assert [c["status"] for c in saved] == ["failed"]


def test_retry_stops_when_spawn_fails(monkeypatch, saved, tmp_path):
    """A CLI that cannot be started at all is a hard failure, not a retry loop."""
    set_retry_policy(monkeypatch, max_attempts=5)
    monkeypatch.setattr(
        review_service, "start_review_process",
        lambda **kwargs: (None, "Claude CLI not found.", False),
    )
    register(tmp_path / "review.md", FakeProcess(exit_code=1))

    poll()               # attempt 1 failed -> retry armed
    review = poll()      # respawn fails -> finalize

    assert review["status"] == "failed"
    assert [c["status"] for c in saved] == ["failed"]


def test_retry_without_spawn_args_finalizes(monkeypatch, saved, tmp_path):
    set_retry_policy(monkeypatch, max_attempts=5)
    register(tmp_path / "review.md", FakeProcess(exit_code=1), spawn=None)

    review = poll()

    assert review["status"] == "failed"
    assert [c["status"] for c in saved] == ["failed"]


def test_retry_preserves_followup_spawn_arguments(monkeypatch, saved, tmp_path):
    set_retry_policy(monkeypatch, max_attempts=2)
    spawned = []
    monkeypatch.setattr(
        review_service, "start_review_process",
        lambda **kwargs: (spawned.append(kwargs) or FakeProcess(exit_code=0),
                          str(tmp_path / "retry.md"), kwargs["is_followup"]),
    )
    md = tmp_path / "review.md"
    entry = register(md, FakeProcess(exit_code=1))
    entry["spawn"]["is_followup"] = True
    entry["spawn"]["previous_review_content"] = '{"score": {"overall": 8}}'

    poll()
    poll()

    assert len(spawned) == 1
    assert spawned[0]["is_followup"] is True
    assert spawned[0]["previous_review_content"] == '{"score": {"overall": 8}}'
    assert spawned[0]["reviewer_type"] == "default"


# --- backoff ----------------------------------------------------------------

def test_respawn_waits_for_backoff(monkeypatch, saved, tmp_path):
    set_retry_policy(monkeypatch, max_attempts=3, delay=300)
    spawned = []
    monkeypatch.setattr(
        review_service, "start_review_process",
        lambda **kwargs: (spawned.append(kwargs) or FakeProcess(exit_code=0),
                          str(tmp_path / "retry.md"), False),
    )
    register(tmp_path / "review.md", FakeProcess(exit_code=1))

    poll()
    review = poll()

    assert spawned == [], "must not respawn before the backoff elapses"
    assert review["attempt"] == 1
    assert review["status"] == "running"


# --- terminal states are not re-processed -----------------------------------

@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_terminal_review_is_left_alone(monkeypatch, saved, tmp_path, status):
    set_retry_policy(monkeypatch, max_attempts=3)
    register(tmp_path / "review.md", FakeProcess(exit_code=1), status=status)

    assert poll()["status"] == status
    assert saved == []


# --- config -----------------------------------------------------------------

def test_retry_settings_defaults(monkeypatch):
    monkeypatch.setattr("backend.config.get_config", lambda: {})
    assert get_review_retry_settings() == (DEFAULT_REVIEW_MAX_ATTEMPTS, 30.0)


def test_retry_settings_read_from_config(monkeypatch):
    monkeypatch.setattr(
        "backend.config.get_config",
        lambda: {"review_max_attempts": 5, "review_retry_delay_seconds": 10},
    )
    assert get_review_retry_settings() == (5, 10.0)


def test_retry_settings_clamped_to_cap(monkeypatch):
    monkeypatch.setattr("backend.config.get_config", lambda: {"review_max_attempts": 99})
    assert get_review_retry_settings()[0] == REVIEW_MAX_ATTEMPTS_CAP


def test_retry_settings_reject_below_one(monkeypatch):
    monkeypatch.setattr("backend.config.get_config", lambda: {"review_max_attempts": 0})
    assert get_review_retry_settings()[0] == 1


def test_retry_settings_fall_back_on_garbage(monkeypatch):
    monkeypatch.setattr(
        "backend.config.get_config",
        lambda: {"review_max_attempts": "five", "review_retry_delay_seconds": "soon"},
    )
    assert get_review_retry_settings() == (DEFAULT_REVIEW_MAX_ATTEMPTS, 30.0)


def test_negative_delay_floored_to_zero(monkeypatch):
    monkeypatch.setattr("backend.config.get_config", lambda: {"review_retry_delay_seconds": -5})
    assert get_review_retry_settings()[1] == 0.0


# --- event log integration ---------------------------------------------------

def test_retry_lifecycle_emits_the_full_event_sequence(monkeypatch, saved, tmp_path):
    """One review that fails once then succeeds must read as one run."""
    set_retry_policy(monkeypatch, max_attempts=3)

    recorded = []
    for name in ("record_started", "record_completed", "record_failed",
                 "record_retry_scheduled", "record_gave_up"):
        monkeypatch.setattr(
            review_service, name,
            lambda *a, _n=name, **kw: recorded.append((_n, a, kw)),
        )

    retry_file = tmp_path / "retry.md"

    def fake_spawn(**kwargs):
        retry_file.write_text("# Review")
        return FakeProcess(exit_code=0, pid=555), str(retry_file), False

    monkeypatch.setattr(review_service, "start_review_process", fake_spawn)
    register(tmp_path / "review.md", FakeProcess(exit_code=0), run_id="run-xyz")

    poll()   # attempt 1: exit 0, no output -> failed + retry armed
    poll()   # backoff elapsed -> attempt 2 spawns
    poll()   # attempt 2: exit 0 with output -> completed

    assert [name for name, _, _ in recorded] == [
        "record_failed", "record_retry_scheduled", "record_started", "record_completed",
    ]

    failed_kwargs = recorded[0][2]
    assert failed_kwargs["reason"] == "no_output"
    assert failed_kwargs["attempt"] == 1

    started_kwargs = recorded[2][2]
    assert started_kwargs["attempt"] == 2
    assert started_kwargs["pid"] == 555

    # Every event belongs to the same run.
    assert {args[0] for _, args, _ in recorded} == {"run-xyz"}
    # ...and names the same repo and PR.
    assert {args[1:] for _, args, _ in recorded} == {(f"{OWNER}/{REPO}", PR)}


def test_gave_up_is_recorded_once_at_the_limit(monkeypatch, saved, tmp_path):
    set_retry_policy(monkeypatch, max_attempts=1)

    recorded = []
    monkeypatch.setattr(review_service, "record_gave_up",
                        lambda *a, **kw: recorded.append(kw))
    monkeypatch.setattr(review_service, "record_failed", lambda *a, **kw: None)

    register(tmp_path / "review.md", FakeProcess(exit_code=1), run_id="run-1")
    poll()

    assert len(recorded) == 1
    assert recorded[0]["attempt"] == 1
    assert recorded[0]["max_attempts"] == 1


def test_nonzero_exit_records_reason_and_stderr(monkeypatch, saved, tmp_path):
    set_retry_policy(monkeypatch, max_attempts=1)

    recorded = []
    monkeypatch.setattr(review_service, "record_failed",
                        lambda *a, **kw: recorded.append(kw))
    monkeypatch.setattr(review_service, "record_gave_up", lambda *a, **kw: None)

    register(tmp_path / "review.md", FakeProcess(exit_code=1), run_id="run-1",
             error_output="API Error: 529 Overloaded")
    poll()

    assert len(recorded) == 1
    assert recorded[0]["reason"] == "nonzero_exit"
    assert recorded[0]["exit_code"] == 1
    assert "529" in recorded[0]["detail"]


def test_spawn_failure_records_spawn_failed(monkeypatch, saved, tmp_path):
    set_retry_policy(monkeypatch, max_attempts=5)
    monkeypatch.setattr(
        review_service, "start_review_process",
        lambda **kwargs: (None, "Claude CLI not found.", False),
    )

    reasons = []
    monkeypatch.setattr(review_service, "record_failed",
                        lambda *a, **kw: reasons.append(kw["reason"]))
    monkeypatch.setattr(review_service, "record_retry_scheduled", lambda *a, **kw: None)

    register(tmp_path / "review.md", FakeProcess(exit_code=1), run_id="run-1")
    poll()      # attempt 1 failed -> retry armed
    poll()      # respawn fails -> finalize

    assert "spawn_failed" in reasons


def test_events_are_skipped_when_no_run_id_is_recorded(monkeypatch, saved, tmp_path):
    """Entries registered before this feature existed must not crash the poller."""
    set_retry_policy(monkeypatch, max_attempts=1)

    recorded = []
    monkeypatch.setattr(review_service, "record_failed",
                        lambda *a, **kw: recorded.append(kw))
    monkeypatch.setattr(review_service, "record_gave_up",
                        lambda *a, **kw: recorded.append(kw))

    register(tmp_path / "review.md", FakeProcess(exit_code=1), run_id=None)
    review = poll()

    assert review["status"] == "failed"
    assert recorded == []
