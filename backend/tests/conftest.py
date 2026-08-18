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
