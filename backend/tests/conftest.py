"""Pytest config — adds project root to sys.path so 'backend.' imports work."""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture(autouse=True)
def isolate_review_event_log(monkeypatch, tmp_path):
    """Keep review event recorders off the application database.

    check_review_status() and begin_review() record lifecycle events through the
    real recorders, which resolve the process-wide ReviewEventsDB singleton — the
    app's own pr_explorer.db. Without this guard, any test that drives a review
    lifecycle writes fake events (owner/repo#42) into the developer's live
    Review Logs tab. Tests that assert on events override this with their own DB.
    """
    from backend.database.base import Database
    from backend.database.review_events import ReviewEventsDB
    from backend.services import review_event_log

    db_path = Path(tempfile.mkdtemp(dir=tmp_path)) / "review_events_isolated.db"
    isolated = ReviewEventsDB(Database(db_path))
    monkeypatch.setattr(review_event_log, "get_review_events_db", lambda: isolated)
    return isolated


@pytest.fixture(autouse=True)
def isolate_pr_status_comments(monkeypatch):
    """Keep PR status comments off the real gh CLI.

    Status comments are posted from many lifecycle paths (begin_review, retry
    scheduling, watchers, the dispatch worker), so a test driving any of them
    would otherwise shell out to gh and comment on a real PR. Tests that assert
    on comment calls monkeypatch the specific post_* function they care about;
    this is the suite-wide safety net for everything else.
    """
    from backend.services import pr_status_comments

    calls = []
    monkeypatch.setattr(
        pr_status_comments, "run_gh_command",
        lambda args, **kwargs: (calls.append(args), "")[1],
    )
    return calls


@pytest.fixture(autouse=True)
def isolate_pr_conversation(monkeypatch):
    """Keep the follow-up conversation fetch off the real gh CLI.

    begin_review gathers the PR conversation for every follow-up (three REST
    calls), so any test that starts a follow-up would otherwise shell out to
    gh. Tests that care about the conversation monkeypatch
    review_service.fetch_conversation_since themselves; this is the default.
    """
    from backend.services import review_service

    monkeypatch.setattr(review_service, "fetch_conversation_since", lambda *a, **kw: [])
