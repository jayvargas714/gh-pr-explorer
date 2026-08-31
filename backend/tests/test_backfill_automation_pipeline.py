"""Tests for the one-time automation pipeline backfill script.

The gh listing is stubbed; tests assert on which rows get inserted or revived
in the dispatch ledger.
"""

import pytest

from backend.database.base import Database
from backend.database.automation_dispatches import AutomationDispatchesDB
from scripts import backfill_automation_pipeline as script

REPO = "acme/widgets"


def _cfg(**overrides):
    cfg = {
        "scope": "all", "authors": [], "repoAllowlist": [REPO],
        "maxConcurrentAutoReviews": 2, "requireCiPass": True,
        "maxBehindBase": 10, "maxPipelineSize": 1000,
        "ignorePatterns": [], "rules": [],
        "defaultRule": {"reviewerKey": "default", "autoVerdict": False, "autoVerdictMode": "verdict"},
    }
    cfg.update(overrides)
    return cfg


@pytest.fixture
def dispatches(tmp_path, monkeypatch):
    ddb = AutomationDispatchesDB(Database(tmp_path / "backfill_test.db"))
    import backend.database as db_pkg
    monkeypatch.setattr(db_pkg, "get_automation_dispatches_db", lambda: ddb)
    return ddb


def _stub(monkeypatch, config, open_prs_by_repo):
    from backend.services import automation_config
    monkeypatch.setattr(automation_config, "get_config", lambda: config)
    monkeypatch.setattr(script, "_fetch_open_prs",
                        lambda repo_full: open_prs_by_repo.get(repo_full, []))


def _pr(number, author="alice"):
    return {"number": number, "author": {"login": author}}


def test_backfill_inserts_open_prs_as_pending(dispatches, monkeypatch):
    _stub(monkeypatch, _cfg(), {REPO: [_pr(1), _pr(2)]})

    summary = script.backfill()

    assert dispatches.get_by_pr(REPO, 1)["status"] == "pending"
    assert dispatches.get_by_pr(REPO, 2)["status"] == "pending"
    assert summary["inserted"] == 2
    assert summary["revived"] == 0


def test_backfill_aborts_when_scope_off(dispatches, monkeypatch):
    _stub(monkeypatch, _cfg(scope="off"), {REPO: [_pr(1)]})

    with pytest.raises(RuntimeError):
        script.backfill()
    assert dispatches.get_by_pr(REPO, 1) is None


def test_backfill_filters_authors_when_scoped(dispatches, monkeypatch):
    _stub(monkeypatch, _cfg(scope="authors", authors=["alice"]),
          {REPO: [_pr(1, "alice"), _pr(2, "bob")]})

    summary = script.backfill()

    assert dispatches.get_by_pr(REPO, 1) is not None
    assert dispatches.get_by_pr(REPO, 2) is None
    assert summary["inserted"] == 1


def test_backfill_revives_skipped_and_failed_rows(dispatches, monkeypatch):
    dispatches.record_candidate(REPO, 1)
    dispatches.record_candidate(REPO, 2)
    row1 = dispatches.get_by_pr(REPO, 1)
    row2 = dispatches.get_by_pr(REPO, 2)
    dispatches.set_status(row1["id"], "skipped", detail="conditions not met within 24h")
    dispatches.increment_attempts(row2["id"])
    dispatches.set_status(row2["id"], "failed", detail="metadata fetch failed")
    _stub(monkeypatch, _cfg(), {REPO: [_pr(1), _pr(2)]})

    summary = script.backfill()

    for n in (1, 2):
        row = dispatches.get_by_pr(REPO, n)
        assert row["status"] == "pending"
        assert row["attempts"] == 0
        assert "revived" in row["detail"]
    assert summary["revived"] == 2
    assert summary["inserted"] == 0


def test_backfill_leaves_active_and_terminal_dispatch_rows_alone(dispatches, monkeypatch):
    dispatches.record_candidate(REPO, 1)  # already pending
    dispatches.record_candidate(REPO, 2)
    dispatches.record_candidate(REPO, 3)
    dispatches.set_status(dispatches.get_by_pr(REPO, 2)["id"], "dispatched", reviewer_key="pb")
    dispatches.set_status(dispatches.get_by_pr(REPO, 3)["id"], "unidentified")
    _stub(monkeypatch, _cfg(), {REPO: [_pr(1), _pr(2), _pr(3)]})

    summary = script.backfill()

    assert dispatches.get_by_pr(REPO, 1)["status"] == "pending"
    assert dispatches.get_by_pr(REPO, 2)["status"] == "dispatched"
    assert dispatches.get_by_pr(REPO, 3)["status"] == "unidentified"
    assert summary["inserted"] == 0
    assert summary["revived"] == 0
    assert summary["unchanged"] == 3


def test_backfill_never_revives_manual_optouts(dispatches, monkeypatch):
    """A PR the operator explicitly removed stays out until re-enrolled by hand."""
    dispatches.record_candidate(REPO, 1)
    row = dispatches.get_by_pr(REPO, 1)
    dispatches.set_status(row["id"], "skipped", detail="manual opt-out")
    _stub(monkeypatch, _cfg(), {REPO: [_pr(1)]})

    summary = script.backfill()

    updated = dispatches.get_by_pr(REPO, 1)
    assert updated["status"] == "skipped"
    assert updated["detail"] == "manual opt-out"
    assert summary["revived"] == 0
    assert summary["unchanged"] == 1


def test_backfill_respects_pipeline_cap(dispatches, monkeypatch):
    dispatches.record_candidate(REPO, 90)  # existing pending row occupies the cap
    _stub(monkeypatch, _cfg(maxPipelineSize=2), {REPO: [_pr(1), _pr(2), _pr(3)]})

    summary = script.backfill()

    assert summary["inserted"] == 1
    assert summary["capped"] == 2
    assert dispatches.count_pending() == 2
