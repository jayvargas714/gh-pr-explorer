"""Tests for registry-driven reviewer resolution in review dispatch."""

import tempfile
from pathlib import Path

import pytest

import backend.database as database_pkg
from backend.database.base import Database
from backend.database.reviewers import ReviewersDB
from backend.services import review_service


@pytest.fixture
def reviewers_db(monkeypatch):
    p = Path(tempfile.mkdtemp()) / "registry_dispatch_test.db"
    rdb = ReviewersDB(Database(p))
    monkeypatch.setattr(database_pkg, "get_reviewers_db", lambda: rdb)
    return rdb


@pytest.fixture
def captured_cmd(monkeypatch, tmp_path):
    """Capture the claude CLI command instead of spawning it."""
    captured = {}

    class FakeProcess:
        pid = 12345

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeProcess()

    monkeypatch.setattr(review_service.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(review_service, "get_reviews_dir", lambda: tmp_path)
    return captured


def _prompt(captured):
    return captured["cmd"][captured["cmd"].index("-p") + 1]


def test_valid_reviewer_types_come_from_registry(reviewers_db):
    reviewers_db.create("rust", "Rust", "rust-engineer")
    assert set(review_service.valid_reviewer_types()) == {"default", "pb", "ed", "rust"}


def test_dispatch_resolves_custom_agent_and_context(reviewers_db, captured_cmd):
    reviewers_db.create("rust", "Rust", "rust-engineer", "Focus on unsafe blocks. ")
    process, _, _ = review_service.start_review_process(
        "https://github.com/o/r/pull/1", "o", "r", 1, reviewer_type="rust"
    )
    assert process is not None
    prompt = _prompt(captured_cmd)
    assert "Use the rust-engineer agent." in prompt
    assert "Focus on unsafe blocks. " in prompt


def test_dispatch_builtin_pb_keeps_agent_and_context(reviewers_db, captured_cmd):
    review_service.start_review_process(
        "https://github.com/o/r/pull/1", "o", "r", 1, reviewer_type="pb"
    )
    prompt = _prompt(captured_cmd)
    assert "Use the product-brief-reviewer agent." in prompt
    assert "PB-000 template" in prompt


def test_dispatch_unknown_key_falls_back_to_default(reviewers_db, captured_cmd):
    review_service.start_review_process(
        "https://github.com/o/r/pull/1", "o", "r", 1, reviewer_type="nope"
    )
    prompt = _prompt(captured_cmd)
    assert "Use the elite-code-reviewer agent." in prompt


def test_foreground_instructions_survive_registry_lookup(reviewers_db, captured_cmd):
    review_service.start_review_process(
        "https://github.com/o/r/pull/1", "o", "r", 1, reviewer_type="default"
    )
    assert review_service._FOREGROUND_INSTRUCTIONS in _prompt(captured_cmd)
