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


def test_defaults_are_all_off(settings_db):
    config = automation_config.get_config()
    assert config["scope"] == "off"
    assert config["authors"] == []
    assert config["repoAllowlist"] == []
    assert config["rules"] == []
    assert config["defaultRule"]["reviewerKey"] == "default"
    assert config["requireCiPass"] is True
    assert config["maxBehindBase"] == 10
    assert config["maxStaleHours"] is None  # None = time gate off
    assert config["maxPipelineSize"] == 1000
    assert config["dispatchTimeoutHours"] == 0  # 0 = rows wait forever
    assert config["requireBaseBranch"] == "main"


def test_validate_dispatch_condition_fields():
    validated = automation_config.validate_config(
        _valid_config(requireCiPass=False, maxBehindBase=0, maxPipelineSize=500), KEYS)
    assert validated["requireCiPass"] is False
    assert validated["maxBehindBase"] == 0
    assert validated["maxPipelineSize"] == 500


def test_validate_behind_gates_accept_none_as_off():
    validated = automation_config.validate_config(
        _valid_config(maxBehindBase=None, maxStaleHours=None), KEYS)
    assert validated["maxBehindBase"] is None
    assert validated["maxStaleHours"] is None

    validated = automation_config.validate_config(
        _valid_config(maxBehindBase=10, maxStaleHours=24), KEYS)
    assert validated["maxBehindBase"] == 10
    assert validated["maxStaleHours"] == 24


def test_validate_stale_hours_defaults_off_when_omitted():
    assert automation_config.validate_config(_valid_config(), KEYS)["maxStaleHours"] is None


def test_validate_rejects_bad_dispatch_condition_values():
    with pytest.raises(ValueError):
        automation_config.validate_config(_valid_config(maxBehindBase=-1), KEYS)
    with pytest.raises(ValueError):
        automation_config.validate_config(_valid_config(maxBehindBase="ten"), KEYS)
    with pytest.raises(ValueError):
        automation_config.validate_config(_valid_config(maxStaleHours=-1), KEYS)
    with pytest.raises(ValueError):
        automation_config.validate_config(_valid_config(maxStaleHours="day"), KEYS)
    with pytest.raises(ValueError):
        automation_config.validate_config(_valid_config(maxPipelineSize=0), KEYS)
    with pytest.raises(ValueError):
        automation_config.validate_config(_valid_config(maxPipelineSize="many"), KEYS)


def test_validate_require_base_branch():
    validated = automation_config.validate_config(
        _valid_config(requireBaseBranch=" release/v2 "), KEYS)
    assert validated["requireBaseBranch"] == "release/v2"
    # Empty and None both mean "any base"
    assert automation_config.validate_config(
        _valid_config(requireBaseBranch=""), KEYS)["requireBaseBranch"] == ""
    assert automation_config.validate_config(
        _valid_config(requireBaseBranch=None), KEYS)["requireBaseBranch"] == ""
    with pytest.raises(ValueError):
        automation_config.validate_config(_valid_config(requireBaseBranch=["main"]), KEYS)


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


# --- routeUnidentifiedToDefault ---

def test_route_unidentified_to_default_defaults_off(settings_db):
    assert automation_config.get_config()["routeUnidentifiedToDefault"] is False


def test_validate_route_unidentified_to_default_is_boolean():
    assert automation_config.validate_config(
        _valid_config(routeUnidentifiedToDefault=True), KEYS)["routeUnidentifiedToDefault"] is True
    assert automation_config.validate_config(
        _valid_config(routeUnidentifiedToDefault=0), KEYS)["routeUnidentifiedToDefault"] is False
    # Legacy payloads without the key keep the flag off.
    assert automation_config.validate_config(
        _valid_config(), KEYS)["routeUnidentifiedToDefault"] is False


@pytest.fixture
def dispatches_db(settings_db, monkeypatch):
    from backend.database.automation_dispatches import AutomationDispatchesDB
    ddb = AutomationDispatchesDB(settings_db.db)
    import backend.database as db_pkg
    monkeypatch.setattr(db_pkg, "get_automation_dispatches_db", lambda: ddb)
    return ddb


def _seed_rows(ddb):
    from backend.database.synced_prs import SyncedPRsDB
    synced = SyncedPRsDB(ddb.db)
    synced.register_repo("o/r")
    for n, state in ((1, "OPEN"), (2, "OPEN"), (3, "OPEN"), (4, "MERGED")):
        synced.upsert_pr("o/r", {
            "number": n, "title": f"PR {n}", "state": state, "isDraft": False,
            "author": {"login": "alice"}, "url": f"https://github.com/o/r/pull/{n}",
            "additions": 1, "deletions": 1, "baseRefName": "main", "headRefName": f"f-{n}",
            "createdAt": "2026-09-01T00:00:00Z", "updatedAt": "2026-09-01T00:00:00Z",
            "closedAt": None, "mergedAt": None,
        })
        ddb.record_candidate("o/r", n)
    unidentified = "files span multiple rules or mix rule and unmatched files"
    ddb.set_status(ddb.get_by_pr("o/r", 1)["id"], "unidentified", detail=unidentified)
    ddb.set_status(ddb.get_by_pr("o/r", 2)["id"], "unidentified", detail=unidentified)
    ddb.set_status(ddb.get_by_pr("o/r", 3)["id"], "dispatched", reviewer_key="pb")
    ddb.set_status(ddb.get_by_pr("o/r", 4)["id"], "unidentified", detail=unidentified)


def test_enabling_route_unidentified_requeues_unidentified_rows(settings_db, dispatches_db):
    automation_config.save_config(_valid_config(routeUnidentifiedToDefault=False), KEYS)
    _seed_rows(dispatches_db)

    automation_config.save_config(_valid_config(routeUnidentifiedToDefault=True), KEYS)

    for n in (1, 2):
        row = dispatches_db.get_by_pr("o/r", n)
        assert row["status"] == "pending"
        assert row["attempts"] == 0
        assert "default reviewer" in row["detail"]
    # Rows the worker already acted on are untouched.
    assert dispatches_db.get_by_pr("o/r", 3)["status"] == "dispatched"
    # An unidentified row whose PR has since merged has nothing to review.
    assert dispatches_db.get_by_pr("o/r", 4)["status"] == "unidentified"


def test_enabling_from_legacy_config_without_key_requeues(settings_db, dispatches_db):
    # A blob saved before the key existed reads as off, so turning it on is a flip.
    legacy = automation_config.validate_config(_valid_config(), KEYS)
    legacy.pop("routeUnidentifiedToDefault")
    settings_db.set_setting(automation_config.SETTINGS_KEY, legacy)
    _seed_rows(dispatches_db)

    automation_config.save_config(_valid_config(routeUnidentifiedToDefault=True), KEYS)

    assert dispatches_db.get_by_pr("o/r", 1)["status"] == "pending"


def test_saving_with_flag_already_on_does_not_requeue(settings_db, dispatches_db):
    automation_config.save_config(_valid_config(routeUnidentifiedToDefault=True), KEYS)
    _seed_rows(dispatches_db)

    automation_config.save_config(_valid_config(routeUnidentifiedToDefault=True), KEYS)

    assert dispatches_db.get_by_pr("o/r", 1)["status"] == "unidentified"


def test_disabling_flag_does_not_touch_rows(settings_db, dispatches_db):
    automation_config.save_config(_valid_config(routeUnidentifiedToDefault=True), KEYS)
    _seed_rows(dispatches_db)

    automation_config.save_config(_valid_config(routeUnidentifiedToDefault=False), KEYS)

    assert dispatches_db.get_by_pr("o/r", 1)["status"] == "unidentified"
