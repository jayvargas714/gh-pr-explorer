"""Tests for the pr_sync and analytics config blocks."""
import backend.config as config_mod
from backend.config import get_analytics_config, get_pr_sync_config


def _with_config(monkeypatch, cfg):
    monkeypatch.setattr(config_mod, "_config", cfg)


def test_defaults_when_block_missing(monkeypatch):
    _with_config(monkeypatch, {})
    cfg = get_pr_sync_config()
    assert cfg == {
        "enabled": True,
        "poll_interval_seconds": 120,
        "history_days": 180,
        "retain_days": 0,
        "max_synced_repos": 10,
        "exclude_repos": [],
        "history_backfill_budget": 60,
        "history_chunk_days": 30,
        "min_graphql_remaining": 1500,
        "commit_branches": ["main"],
        "commit_pages_per_cycle": 40,
        "behind_per_cycle": 40,
    }


def test_overrides_merge_with_defaults(monkeypatch):
    _with_config(monkeypatch, {"pr_sync": {"history_days": 30, "enabled": False}})
    cfg = get_pr_sync_config()
    assert cfg["history_days"] == 30
    assert cfg["enabled"] is False
    assert cfg["poll_interval_seconds"] == 120


def test_malformed_values_fall_back(monkeypatch):
    _with_config(monkeypatch, {"pr_sync": {
        "poll_interval_seconds": "soon", "history_days": -5,
        "max_synced_repos": 0, "exclude_repos": "nope",
    }})
    cfg = get_pr_sync_config()
    assert cfg["poll_interval_seconds"] == 120
    assert cfg["history_days"] == 180      # non-positive is malformed -> default
    assert cfg["max_synced_repos"] == 1    # clamped to >= 1
    assert cfg["exclude_repos"] == []


def test_retain_days_minimum_zero(monkeypatch):
    _with_config(monkeypatch, {"pr_sync": {"retain_days": 0}})
    assert get_pr_sync_config()["retain_days"] == 0

    _with_config(monkeypatch, {"pr_sync": {"retain_days": 45}})
    assert get_pr_sync_config()["retain_days"] == 45

    _with_config(monkeypatch, {"pr_sync": {"retain_days": -1}})
    assert get_pr_sync_config()["retain_days"] == 0  # malformed -> default

    _with_config(monkeypatch, {"pr_sync": {"retain_days": "nope"}})
    assert get_pr_sync_config()["retain_days"] == 0  # malformed -> default


def test_history_backfill_budget_minimum_one(monkeypatch):
    _with_config(monkeypatch, {"pr_sync": {"history_backfill_budget": 0}})
    assert get_pr_sync_config()["history_backfill_budget"] == 60  # malformed -> default

    _with_config(monkeypatch, {"pr_sync": {"history_backfill_budget": 5}})
    assert get_pr_sync_config()["history_backfill_budget"] == 5

    _with_config(monkeypatch, {"pr_sync": {"history_backfill_budget": "many"}})
    assert get_pr_sync_config()["history_backfill_budget"] == 60


def test_history_chunk_days_clamped(monkeypatch):
    _with_config(monkeypatch, {"pr_sync": {"history_chunk_days": 0}})
    assert get_pr_sync_config()["history_chunk_days"] == 1

    _with_config(monkeypatch, {"pr_sync": {"history_chunk_days": 500}})
    assert get_pr_sync_config()["history_chunk_days"] == 90

    _with_config(monkeypatch, {"pr_sync": {"history_chunk_days": 15}})
    assert get_pr_sync_config()["history_chunk_days"] == 15

    _with_config(monkeypatch, {"pr_sync": {"history_chunk_days": "many"}})
    assert get_pr_sync_config()["history_chunk_days"] == 30


def test_min_graphql_remaining_minimum_zero(monkeypatch):
    _with_config(monkeypatch, {"pr_sync": {"min_graphql_remaining": 0}})
    assert get_pr_sync_config()["min_graphql_remaining"] == 0

    _with_config(monkeypatch, {"pr_sync": {"min_graphql_remaining": -5}})
    assert get_pr_sync_config()["min_graphql_remaining"] == 1500  # malformed -> default

    _with_config(monkeypatch, {"pr_sync": {"min_graphql_remaining": "lots"}})
    assert get_pr_sync_config()["min_graphql_remaining"] == 1500


def test_commit_pages_per_cycle_minimum_one(monkeypatch):
    _with_config(monkeypatch, {"pr_sync": {"commit_pages_per_cycle": 0}})
    assert get_pr_sync_config()["commit_pages_per_cycle"] == 40  # malformed -> default

    _with_config(monkeypatch, {"pr_sync": {"commit_pages_per_cycle": 10}})
    assert get_pr_sync_config()["commit_pages_per_cycle"] == 10

    _with_config(monkeypatch, {"pr_sync": {"commit_pages_per_cycle": "many"}})
    assert get_pr_sync_config()["commit_pages_per_cycle"] == 40


def test_commit_branches_sanitize(monkeypatch):
    _with_config(monkeypatch, {"pr_sync": {"commit_branches": ["main", "develop"]}})
    assert get_pr_sync_config()["commit_branches"] == ["main", "develop"]

    _with_config(monkeypatch, {"pr_sync": {"commit_branches": []}})
    assert get_pr_sync_config()["commit_branches"] == []  # empty allowed, disables commit sync

    _with_config(monkeypatch, {"pr_sync": {"commit_branches": "main"}})
    assert get_pr_sync_config()["commit_branches"] == ["main"]  # non-list -> default

    _with_config(monkeypatch, {"pr_sync": {"commit_branches": ["main", "", 5, None]}})
    assert get_pr_sync_config()["commit_branches"] == ["main"]  # drop non-strings/empty


def test_get_analytics_config_defaults(monkeypatch):
    _with_config(monkeypatch, {})
    cfg = get_analytics_config()
    assert cfg == {
        "bot_logins": [
            "github-actions", "coderabbitai", "greptile-apps", "cursor", "claude",
            "copilot-pull-request-reviewer", "dependabot", "scalazack",
        ],
    }


def test_get_analytics_config_override_and_lowercasing(monkeypatch):
    _with_config(monkeypatch, {"analytics": {"bot_logins": ["Some-Bot", "OTHER"]}})
    cfg = get_analytics_config()
    assert cfg["bot_logins"] == ["some-bot", "other"]


def test_get_analytics_config_malformed_falls_back(monkeypatch):
    _with_config(monkeypatch, {"analytics": {"bot_logins": "not-a-list"}})
    cfg = get_analytics_config()
    assert cfg["bot_logins"][0] == "github-actions"

    _with_config(monkeypatch, {"analytics": {"bot_logins": ["ok", 5]}})
    cfg = get_analytics_config()
    assert cfg["bot_logins"][0] == "github-actions"


def test_behind_per_cycle_minimum_one(monkeypatch):
    _with_config(monkeypatch, {"pr_sync": {"behind_per_cycle": 0}})
    assert get_pr_sync_config()["behind_per_cycle"] == 40  # malformed -> default

    _with_config(monkeypatch, {"pr_sync": {"behind_per_cycle": 5}})
    assert get_pr_sync_config()["behind_per_cycle"] == 5

    _with_config(monkeypatch, {"pr_sync": {"behind_per_cycle": "lots"}})
    assert get_pr_sync_config()["behind_per_cycle"] == 40
