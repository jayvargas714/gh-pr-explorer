"""Tests for ReviewersDB — the configurable reviewer registry."""

import tempfile
from pathlib import Path

import pytest

from backend.database.base import Database
from backend.database.reviewers import ReviewersDB


@pytest.fixture
def db():
    p = Path(tempfile.mkdtemp()) / "reviewers_test.db"
    return Database(p)


@pytest.fixture
def reviewers_db(db):
    return ReviewersDB(db)


def test_builtins_are_seeded(reviewers_db):
    rows = {r["key"]: r for r in reviewers_db.list_reviewers()}
    assert set(rows) == {"default", "pb", "ed"}
    assert rows["default"]["agent_name"] == "elite-code-reviewer"
    assert rows["pb"]["agent_name"] == "product-brief-reviewer"
    assert rows["ed"]["agent_name"] == "ed-reviewer"
    assert all(r["is_builtin"] for r in rows.values())
    assert rows["pb"]["prompt_context"]  # builtin context strings carried over
    assert rows["default"]["prompt_context"] is None


def test_seeding_is_idempotent(db):
    ReviewersDB(db)
    again = ReviewersDB(db)
    assert len(again.list_reviewers()) == 3


def test_create_and_get_custom_reviewer(reviewers_db):
    reviewers_db.create("rust", "Rust Reviewer", "rust-engineer", "Review the Rust changes.")
    row = reviewers_db.get_by_key("rust")
    assert row["label"] == "Rust Reviewer"
    assert row["agent_name"] == "rust-engineer"
    assert row["prompt_context"] == "Review the Rust changes."
    assert not row["is_builtin"]


def test_create_rejects_duplicate_key(reviewers_db):
    reviewers_db.create("rust", "Rust", "rust-engineer")
    with pytest.raises(ValueError):
        reviewers_db.create("rust", "Rust 2", "other-agent")


def test_create_rejects_invalid_key_slug(reviewers_db):
    with pytest.raises(ValueError):
        reviewers_db.create("Bad Key!", "Bad", "agent")
    with pytest.raises(ValueError):
        reviewers_db.create("", "Empty", "agent")


def test_create_requires_label_and_agent(reviewers_db):
    with pytest.raises(ValueError):
        reviewers_db.create("x", "", "agent")
    with pytest.raises(ValueError):
        reviewers_db.create("x", "Label", "")


def test_update_custom_reviewer(reviewers_db):
    reviewers_db.create("rust", "Rust", "rust-engineer")
    reviewers_db.update("rust", label="Rust Pro", agent_name="rust-pro", prompt_context="ctx")
    row = reviewers_db.get_by_key("rust")
    assert row["label"] == "Rust Pro"
    assert row["agent_name"] == "rust-pro"
    assert row["prompt_context"] == "ctx"


def test_update_builtin_allows_label_and_context_but_not_agent(reviewers_db):
    reviewers_db.update("pb", label="Brief Reviewer", prompt_context="new ctx")
    row = reviewers_db.get_by_key("pb")
    assert row["label"] == "Brief Reviewer"
    assert row["prompt_context"] == "new ctx"
    with pytest.raises(ValueError):
        reviewers_db.update("pb", agent_name="someone-else")


def test_update_unknown_key_raises(reviewers_db):
    with pytest.raises(ValueError):
        reviewers_db.update("nope", label="X")


def test_delete_custom_reviewer(reviewers_db):
    reviewers_db.create("rust", "Rust", "rust-engineer")
    reviewers_db.delete("rust")
    assert reviewers_db.get_by_key("rust") is None


def test_delete_builtin_refused(reviewers_db):
    with pytest.raises(ValueError):
        reviewers_db.delete("default")


def test_delete_unknown_key_raises(reviewers_db):
    with pytest.raises(ValueError):
        reviewers_db.delete("nope")
