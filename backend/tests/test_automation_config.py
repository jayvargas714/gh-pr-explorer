"""Tests for the automation config module (defaults, validation, persistence)."""

import tempfile
from pathlib import Path

import pytest

from backend.services import automation_config
from backend.database.base import Database
from backend.database.settings import SettingsDB

KEYS = ("default", "pb", "ed")


@pytest.fixture
def settings_db(monkeypatch):
    p = Path(tempfile.mkdtemp()) / "automation_config_test.db"
    sdb = SettingsDB(Database(p))
    import backend.database as db_pkg
    monkeypatch.setattr(db_pkg, "get_settings_db", lambda: sdb)
    return sdb


def _valid_config(**overrides):
    config = {
        "scope": "authors",
        "authors": ["alice"],
        "repoAllowlist": ["owner/repo"],
        "maxConcurrentAutoReviews": 2,
        "ignorePatterns": ["*PB-000-index*"],
        "defaultRule": {"reviewerKey": "default", "autoVerdict": False, "autoVerdictMode": "verdict"},
        "rules": [
            {"name": "PB", "patterns": ["PB-[0-9]*"], "reviewerKey": "pb",
             "autoVerdict": True, "autoVerdictMode": "comment"},
        ],
    }
    config.update(overrides)
    return config


def test_defaults_are_all_off():
    config = automation_config.get_config()
    assert config["scope"] == "off"
    assert config["authors"] == []
    assert config["repoAllowlist"] == []
    assert config["rules"] == []
    assert config["defaultRule"]["reviewerKey"] == "default"


def test_validate_accepts_a_full_config():
    validated = automation_config.validate_config(_valid_config(), KEYS)
    assert validated["scope"] == "authors"
    assert validated["rules"][0]["reviewerKey"] == "pb"


def test_validate_rejects_bad_scope():
    with pytest.raises(ValueError):
        automation_config.validate_config(_valid_config(scope="everything"), KEYS)


def test_validate_rejects_unknown_reviewer_key():
    bad = _valid_config()
    bad["rules"][0]["reviewerKey"] = "nope"
    with pytest.raises(ValueError):
        automation_config.validate_config(bad, KEYS)
    bad2 = _valid_config(defaultRule={"reviewerKey": "nope", "autoVerdict": False, "autoVerdictMode": "verdict"})
    with pytest.raises(ValueError):
        automation_config.validate_config(bad2, KEYS)


def test_validate_rejects_bad_mode_and_empty_rule_fields():
    bad = _valid_config()
    bad["rules"][0]["autoVerdictMode"] = "shout"
    with pytest.raises(ValueError):
        automation_config.validate_config(bad, KEYS)
    bad = _valid_config()
    bad["rules"][0]["name"] = ""
    with pytest.raises(ValueError):
        automation_config.validate_config(bad, KEYS)
    bad = _valid_config()
    bad["rules"][0]["patterns"] = []
    with pytest.raises(ValueError):
        automation_config.validate_config(bad, KEYS)


def test_validate_rejects_bad_concurrency():
    with pytest.raises(ValueError):
        automation_config.validate_config(_valid_config(maxConcurrentAutoReviews=0), KEYS)
    with pytest.raises(ValueError):
        automation_config.validate_config(_valid_config(maxConcurrentAutoReviews="lots"), KEYS)


def test_validate_normalizes_string_lists():
    config = _valid_config(authors=["alice", "", "  bob "], repoAllowlist=["o/r", " "])
    validated = automation_config.validate_config(config, KEYS)
    assert validated["authors"] == ["alice", "bob"]
    assert validated["repoAllowlist"] == ["o/r"]


def test_save_and_reload_roundtrip(settings_db):
    automation_config.save_config(_valid_config(), KEYS)
    loaded = automation_config.get_config()
    assert loaded["scope"] == "authors"
    assert loaded["rules"][0]["name"] == "PB"
    assert loaded["maxConcurrentAutoReviews"] == 2


def test_get_config_ignores_unknown_stored_keys(settings_db):
    settings_db.set_setting(automation_config.SETTINGS_KEY, {"scope": "all", "bogus": 1})
    loaded = automation_config.get_config()
    assert loaded["scope"] == "all"
    assert "bogus" not in loaded
