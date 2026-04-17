"""Tests for timeline_service event normalization."""
import json
from pathlib import Path

import pytest

from backend.services.timeline_service import normalize_timeline_events


FIXTURE = Path(__file__).parent / "fixtures" / "timeline_raw.json"


@pytest.fixture
def raw_events():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def pr_info():
    return {
        "created_at": "2026-04-10T14:00:00Z",
        "user": {"login": "jvargas", "avatar_url": "https://example.com/j.png"},
    }


def test_prepends_synthesized_opened_event(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    assert events[0]["type"] == "opened"
    assert events[0]["created_at"] == "2026-04-10T14:00:00Z"
    assert events[0]["actor"]["login"] == "jvargas"


def test_sorts_ascending_by_created_at(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    timestamps = [e["created_at"] for e in events]
    assert timestamps == sorted(timestamps)


def test_committed_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    commit = next(e for e in events if e["type"] == "committed")
    assert commit["sha"] == "abc1234567890abcdef1234567890abcdef1234"
    assert commit["short_sha"] == "abc1234"
    assert commit["message"] == "Add caching layer\n\nDetails..."
    assert commit["actor"]["login"] == "J Vargas"
    assert commit["created_at"] == "2026-04-10T14:30:00Z"


def test_reviewed_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    review = next(e for e in events if e["type"] == "reviewed")
    assert review["state"] == "CHANGES_REQUESTED"
    assert review["body"] == "Please fix the race condition."
    assert review["actor"]["login"] == "alice"
    assert review["html_url"].endswith("pullrequestreview-999")


def test_commented_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    comment = next(e for e in events if e["type"] == "commented")
    assert comment["body"] == "Looks good to me."
    assert comment["actor"]["login"] == "bob"
    assert comment["html_url"].endswith("issuecomment-1000")


def test_review_requested_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    rr = next(e for e in events if e["type"] == "review_requested")
    assert rr["requested_reviewer"]["login"] == "charlie"
    assert rr["actor"]["login"] == "jvargas"


def test_ready_for_review_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    rfr = next(e for e in events if e["type"] == "ready_for_review")
    assert rfr["actor"]["login"] == "jvargas"


def test_convert_to_draft_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    ctd = next(e for e in events if e["type"] == "convert_to_draft")
    assert ctd["actor"]["login"] == "jvargas"


def test_closed_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    closed = next(e for e in events if e["type"] == "closed")
    assert closed["actor"]["login"] == "bob"


def test_reopened_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    reopened = next(e for e in events if e["type"] == "reopened")
    assert reopened["actor"]["login"] == "jvargas"


def test_merged_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    merged = next(e for e in events if e["type"] == "merged")
    assert merged["sha"] == "merged1234567890abcdef1234567890abcdef12"
    assert merged["actor"]["login"] == "jvargas"


def test_force_pushed_event_shape(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    fp = next(e for e in events if e["type"] == "head_ref_force_pushed")
    assert fp["actor"]["login"] == "jvargas"


def test_all_events_have_required_fields(raw_events, pr_info):
    events = normalize_timeline_events(raw_events, pr_info)
    for e in events:
        assert "id" in e and e["id"]
        assert "type" in e
        assert "created_at" in e
