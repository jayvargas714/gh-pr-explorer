"""Tests for the automation config seed script."""

import json
from pathlib import Path

import pytest

from backend.database.base import Database
from backend.database.reviewers import ReviewersDB
from backend.database.settings import SettingsDB
from backend.services import automation_config
from scripts.seed_automation_config import seed

SEED_FILE = Path(__file__).parent.parent.parent / "scripts" / "automation_seed.json"


@pytest.fixture
def dbs(tmp_path, monkeypatch):
    db = Database(tmp_path / "seed_test.db")
    settings_db = SettingsDB(db)
    reviewers_db = ReviewersDB(db)
    import backend.database as db_pkg
    monkeypatch.setattr(db_pkg, "get_settings_db", lambda: settings_db)
    monkeypatch.setattr(db_pkg, "get_reviewers_db", lambda: reviewers_db)
    return settings_db


def _payload():
    return json.loads(SEED_FILE.read_text())


def test_shipped_seed_file_is_valid_and_inert():
    """The checked-in seed must validate against the builtin registry and must
    never enable dispatching by itself (scope off, no repos)."""
    payload = _payload()
    validated = automation_config.validate_config(payload, ("default", "pb", "ed"))
    assert validated["scope"] == "off"
    assert validated["repoAllowlist"] == []
    rule_names = [r["name"] for r in validated["rules"]]
    assert rule_names == ["PB", "ED"]
    assert validated["rules"][0]["reviewerKey"] == "pb"
    assert validated["rules"][1]["reviewerKey"] == "ed"
    assert any("PB-000-index" in p for p in validated["ignorePatterns"])
    assert any("ED-000-index" in p for p in validated["ignorePatterns"])
    assert validated["defaultRule"]["reviewerKey"] == "default"


def test_seed_applies_ruleset_to_empty_config(dbs):
    assert seed(_payload(), force=False) is True
    stored = automation_config.get_config()
    assert [r["name"] for r in stored["rules"]] == ["PB", "ED"]


def test_seed_refuses_to_overwrite_existing_config(dbs):
    seed(_payload(), force=False)
    modified = _payload()
    modified["scope"] = "all"
    assert seed(modified, force=False) is False
    assert automation_config.get_config()["scope"] == "off"


def test_seed_force_overwrites(dbs):
    seed(_payload(), force=False)
    modified = _payload()
    modified["maxBehindBase"] = 5
    assert seed(modified, force=True) is True
    assert automation_config.get_config()["maxBehindBase"] == 5


def test_seed_rejects_invalid_payload(dbs):
    bad = _payload()
    bad["rules"][0]["reviewerKey"] = "ghost"
    with pytest.raises(ValueError):
        seed(bad, force=False)
