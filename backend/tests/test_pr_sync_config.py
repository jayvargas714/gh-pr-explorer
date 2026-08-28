"""Tests for the pr_sync config block."""
import backend.config as config_mod
from backend.config import get_pr_sync_config


def _with_config(monkeypatch, cfg):
    monkeypatch.setattr(config_mod, "_config", cfg)


def test_defaults_when_block_missing(monkeypatch):
    _with_config(monkeypatch, {})
    cfg = get_pr_sync_config()
    assert cfg == {
        "enabled": True,
        "poll_interval_seconds": 120,
        "history_days": 180,
        "max_synced_repos": 10,
        "exclude_repos": [],
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
