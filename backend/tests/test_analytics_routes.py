"""Tests for the /api/repos/<owner>/<repo>/analytics/daily route.

The route never calls GitHub — a rebuild is DB-only, fed by rows the sync
worker already wrote. `no_gh` (autouse) makes any gh CLI call at request time
fail the test outright.
"""

from datetime import datetime, timedelta, timezone

import pytest

import backend.database as database_pkg
import backend.routes.analytics_routes as analytics_routes
from backend.database.base import Database
from backend.database.synced_prs import SyncedPRsDB
from backend.database.synced_commits import SyncedCommitsDB
from backend.database.analytics_daily import AnalyticsDailyDB
from backend.database.reviews import ReviewsDB


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@pytest.fixture
def dbs(tmp_path):
    db = Database(tmp_path / "test.db")
    return SyncedPRsDB(db), SyncedCommitsDB(db), AnalyticsDailyDB(db), ReviewsDB(db)


@pytest.fixture(autouse=True)
def no_gh(monkeypatch):
    """Provably never calls GitHub from this route."""
    from backend.services import github_service

    def _boom(*args, **kwargs):
        raise AssertionError("no gh at request time")

    monkeypatch.setattr(github_service, "run_gh_command", _boom)


@pytest.fixture
def client(dbs, monkeypatch):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    # The route module's own bound names...
    monkeypatch.setattr(analytics_routes, "get_synced_prs_db", lambda: prs_db)
    monkeypatch.setattr(analytics_routes, "get_synced_commits_db", lambda: commits_db)
    monkeypatch.setattr(analytics_routes, "get_analytics_daily_db", lambda: analytics_db)
    # ...and backend.database's module attrs, since analytics_rollup's
    # needs_rebuild/rebuild_repo re-import them from there on every call.
    monkeypatch.setattr(database_pkg, "get_synced_prs_db", lambda: prs_db)
    monkeypatch.setattr(database_pkg, "get_synced_commits_db", lambda: commits_db)
    monkeypatch.setattr(database_pkg, "get_analytics_daily_db", lambda: analytics_db)
    monkeypatch.setattr(database_pkg, "get_reviews_db", lambda: reviews_db)

    monkeypatch.setattr(analytics_routes, "get_pr_sync_config", lambda: {
        "poll_interval_seconds": 60, "commit_branches": ["main"], "enabled": True,
    })
    monkeypatch.setattr(analytics_routes, "get_analytics_config", lambda: {
        "bot_logins": ["some-bot"],
    })

    from backend import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _pr(number, author="alice", author_is_bot=False, state="OPEN", base_ref="main",
        created="2026-09-01T00:00:00Z", merged=None, closed=None,
        additions=5, deletions=1, reviews=None):
    return {
        "number": number, "state": state, "isDraft": False,
        "author": {"login": author, "is_bot": author_is_bot},
        "createdAt": created, "updatedAt": merged or closed or created,
        "closedAt": closed, "mergedAt": merged,
        "baseRefName": base_ref, "additions": additions, "deletions": deletions,
        "reviews": reviews or [],
    }


def _review(login, state, submitted_at):
    return {"author": {"login": login}, "state": state, "submittedAt": submitted_at}


def _seed_repo(prs_db, commits_db, repo="acme/widgets", backfill=True, history=True,
                commit_backfill=True, branch="main"):
    prs_db.register_repo(repo)
    if backfill:
        prs_db.mark_backfill_done(repo)
    if history:
        prs_db.mark_history_done(repo)
    if commit_backfill:
        commits_db.upsert_branch_state(repo, branch, backfill_done=1)


def _person(body, login):
    for p in body["people"]:
        if p["login"] == login:
            return p
    raise AssertionError(f"no person {login} in {[p['login'] for p in body['people']]}")


# -- window resolution ----------------------------------------------------------

def test_default_window_no_from_to(client, dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db)
    prs_db.upsert_pr("acme/widgets", _pr(1, created="2026-09-05T00:00:00Z"))

    resp = client.get("/api/repos/acme/widgets/analytics/daily")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["from"] == "2026-09-05"
    assert body["to"] == _today()


def test_explicit_window_zero_fills_every_day(client, dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db)
    prs_db.upsert_pr("acme/widgets", _pr(1, created="2026-09-01T00:00:00Z"))

    resp = client.get("/api/repos/acme/widgets/analytics/daily?from=2026-09-01&to=2026-09-03")
    body = resp.get_json()
    assert body["days"] == ["2026-09-01", "2026-09-02", "2026-09-03"]
    alice = _person(body, "alice")
    for key, series in alice["series"].items():
        assert len(series) == 3
    assert alice["series"]["prs_created"] == [1, 0, 0]
    for series in body["team"]["series"].values():
        assert len(series) == 3


def test_from_after_to_is_400(client, dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db)
    resp = client.get("/api/repos/acme/widgets/analytics/daily?from=2026-09-05&to=2026-09-01")
    assert resp.status_code == 400


@pytest.mark.parametrize("bad", ["2026/09/01", "09-01-2026", "not-a-date", "2026-13-40"])
def test_bad_date_format_is_400(client, dbs, bad):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db)
    resp = client.get(f"/api/repos/acme/widgets/analytics/daily?from={bad}&to=2026-09-01")
    assert resp.status_code == 400

    resp2 = client.get(f"/api/repos/acme/widgets/analytics/daily?from=2026-09-01&to={bad}")
    assert resp2.status_code == 400


# -- huge ranges (MAX_RANGE_DAYS) ----------------------------------------------------

def test_explicit_range_over_max_is_400(client, dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db)
    resp = client.get("/api/repos/acme/widgets/analytics/daily?from=2010-01-01&to=2026-09-10")
    assert resp.status_code == 400
    body = resp.get_json()
    assert str(analytics_routes.MAX_RANGE_DAYS) in body["error"]


def test_default_window_clamped_to_max_range_on_old_repo(client, dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db)
    prs_db.upsert_pr("acme/widgets", _pr(1, created="2015-01-01T00:00:00Z"))

    resp = client.get("/api/repos/acme/widgets/analytics/daily?to=2026-09-10")
    assert resp.status_code == 200
    body = resp.get_json()
    expected_from = (
        datetime(2026, 9, 10) - timedelta(days=analytics_routes.MAX_RANGE_DAYS - 1)
    ).strftime("%Y-%m-%d")
    assert body["from"] == expected_from
    assert body["to"] == "2026-09-10"
    assert len(body["days"]) == analytics_routes.MAX_RANGE_DAYS


def test_bad_explicit_range_skips_rebuild(client, dbs, monkeypatch):
    """`from > to` (or an over-cap explicit range) must never trigger a rebuild."""
    calls = []
    monkeypatch.setattr(analytics_routes, "rebuild_repo", lambda repo: calls.append(repo))

    resp = client.get("/api/repos/acme/widgets/analytics/daily?from=2026-09-05&to=2026-09-01")
    assert resp.status_code == 400
    assert calls == []

    resp2 = client.get("/api/repos/acme/widgets/analytics/daily?from=2010-01-01&to=2026-09-10")
    assert resp2.status_code == 400
    assert calls == []


def test_rebuild_failure_falls_back_to_existing_rollup(client, dbs, monkeypatch):
    """An unguarded rebuild would 500 the whole request; instead it should log
    and fall through to serving whatever rollup rows already exist."""
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db)
    prs_db.upsert_pr("acme/widgets", _pr(1, author="alice", created="2026-09-01T00:00:00Z"))
    # Build the rollup once so there are existing rows to fall back to.
    client.get("/api/repos/acme/widgets/analytics/daily?from=2026-09-01&to=2026-09-01")

    def _boom(repo):
        raise RuntimeError("boom")

    monkeypatch.setattr(analytics_routes, "needs_rebuild", lambda repo: True)
    monkeypatch.setattr(analytics_routes, "rebuild_repo", _boom)

    resp = client.get("/api/repos/acme/widgets/analytics/daily?from=2026-09-01&to=2026-09-01")
    assert resp.status_code == 200
    body = resp.get_json()
    logins = {p["login"] for p in body["people"]}
    assert logins == {"alice"}


# -- base filtering ---------------------------------------------------------------

def test_base_filter_excludes_other_branch_prs_and_reviews(client, dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db)
    prs_db.upsert_pr("acme/widgets", _pr(
        1, author="alice", base_ref="main", created="2026-09-01T00:00:00Z",
        reviews=[_review("bob", "APPROVED", "2026-09-01T01:00:00Z")],
    ))
    prs_db.upsert_pr("acme/widgets", _pr(
        2, author="carol", base_ref="develop", created="2026-09-01T00:00:00Z",
        reviews=[_review("dave", "APPROVED", "2026-09-01T01:00:00Z")],
    ))

    resp = client.get("/api/repos/acme/widgets/analytics/daily?from=2026-09-01&to=2026-09-01&base=main")
    body = resp.get_json()
    logins = {p["login"] for p in body["people"]}
    assert logins == {"alice", "bob"}
    assert body["base"] == "main"

    resp_all = client.get("/api/repos/acme/widgets/analytics/daily?from=2026-09-01&to=2026-09-01")
    body_all = resp_all.get_json()
    logins_all = {p["login"] for p in body_all["people"]}
    assert logins_all == {"alice", "bob", "carol", "dave"}
    assert body_all["base"] is None


# -- bot exclusion -----------------------------------------------------------------

def test_bots_excluded_from_people_and_team(client, dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db)
    prs_db.upsert_pr("acme/widgets", _pr(1, author="alice", created="2026-09-01T00:00:00Z"))
    prs_db.upsert_pr("acme/widgets", _pr(2, author="some-bot", created="2026-09-01T00:00:00Z"))
    prs_db.upsert_pr("acme/widgets", _pr(3, author="app/github-actions", created="2026-09-01T00:00:00Z"))
    prs_db.upsert_pr("acme/widgets", _pr(4, author="dependabot[bot]", created="2026-09-01T00:00:00Z"))
    prs_db.upsert_pr("acme/widgets", _pr(5, author="flagged-author", author_is_bot=True,
                                          created="2026-09-01T00:00:00Z"))

    resp = client.get("/api/repos/acme/widgets/analytics/daily?from=2026-09-01&to=2026-09-01")
    body = resp.get_json()
    logins = {p["login"] for p in body["people"]}
    assert logins == {"alice"}
    assert body["team"]["totals"]["prs_created"] == 1


# -- derived metrics -----------------------------------------------------------------

def test_merge_rate_fraction_and_none(client, dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db)
    prs_db.upsert_pr("acme/widgets", _pr(
        1, author="alice", state="MERGED",
        created="2026-09-01T00:00:00Z", merged="2026-09-01T06:00:00Z",
    ))
    prs_db.upsert_pr("acme/widgets", _pr(
        2, author="alice", state="CLOSED",
        created="2026-09-01T00:00:00Z", closed="2026-09-01T06:00:00Z",
    ))
    prs_db.upsert_pr("acme/widgets", _pr(3, author="bob", created="2026-09-01T00:00:00Z"))

    resp = client.get("/api/repos/acme/widgets/analytics/daily?from=2026-09-01&to=2026-09-01")
    body = resp.get_json()
    alice = _person(body, "alice")
    assert alice["totals"]["merge_rate"] == pytest.approx(0.5)
    assert alice["totals"]["avg_merge_hours"] == pytest.approx(6.0)

    bob = _person(body, "bob")
    assert bob["totals"]["merge_rate"] is None
    assert bob["totals"]["avg_merge_hours"] is None


def test_avg_review_rounds_value_and_none(client, dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db)
    prs_db.upsert_pr("acme/widgets", _pr(
        1, author="alice", state="MERGED",
        created="2026-09-01T00:00:00Z", merged="2026-09-01T06:00:00Z",
    ))
    reviews_db.save_review(pr_number=1, repo="acme/widgets", status="completed", content_json="{}",
                            review_timestamp=datetime(2026, 9, 1, 1, 0, 0))
    reviews_db.save_review(pr_number=1, repo="acme/widgets", status="completed", content_json="{}",
                            is_followup=True, review_timestamp=datetime(2026, 9, 1, 3, 0, 0))
    # bob's PR is merged but never went through the review pipeline.
    prs_db.upsert_pr("acme/widgets", _pr(
        2, author="bob", state="MERGED",
        created="2026-09-01T00:00:00Z", merged="2026-09-01T06:00:00Z",
    ))

    resp = client.get("/api/repos/acme/widgets/analytics/daily?from=2026-09-01&to=2026-09-01")
    body = resp.get_json()
    alice = _person(body, "alice")
    assert alice["totals"]["avg_review_rounds"] == pytest.approx(2.0)

    bob = _person(body, "bob")
    assert bob["totals"]["avg_review_rounds"] is None

    assert body["team"]["totals"]["avg_review_rounds"] == pytest.approx(2.0)


def test_review_rounds_series_length_matches_days(client, dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db)
    prs_db.upsert_pr("acme/widgets", _pr(
        1, author="alice", state="MERGED",
        created="2026-09-01T00:00:00Z", merged="2026-09-02T00:00:00Z",
    ))
    reviews_db.save_review(pr_number=1, repo="acme/widgets", status="completed", content_json="{}",
                            review_timestamp=datetime(2026, 9, 1, 1, 0, 0))

    resp = client.get("/api/repos/acme/widgets/analytics/daily?from=2026-09-01&to=2026-09-03")
    body = resp.get_json()
    alice = _person(body, "alice")
    assert len(alice["series"]["review_rounds_sum"]) == 3
    assert len(alice["series"]["review_rounds_count"]) == 3
    assert alice["series"]["review_rounds_sum"] == [0, 1, 0]
    assert alice["series"]["review_rounds_count"] == [0, 1, 0]
    for series in body["team"]["series"].values():
        assert len(series) == 3


# -- people ordering & avatar_url -----------------------------------------------------

def test_people_ordering_and_avatar_url(client, dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db)
    # alice: 2 merged (score 2), bob: 1 review (score 1), unknown author: 0
    prs_db.upsert_pr("acme/widgets", _pr(
        1, author="alice", state="MERGED",
        created="2026-09-01T00:00:00Z", merged="2026-09-01T01:00:00Z",
    ))
    prs_db.upsert_pr("acme/widgets", _pr(
        2, author="alice", state="MERGED",
        created="2026-09-01T00:00:00Z", merged="2026-09-01T02:00:00Z",
    ))
    prs_db.upsert_pr("acme/widgets", _pr(
        3, author=None, created="2026-09-01T00:00:00Z",
        reviews=[_review("bob", "COMMENTED", "2026-09-01T03:00:00Z")],
    ))

    resp = client.get("/api/repos/acme/widgets/analytics/daily?from=2026-09-01&to=2026-09-01")
    body = resp.get_json()
    logins = [p["login"] for p in body["people"]]
    assert logins == ["alice", "bob", "unknown"]

    alice = _person(body, "alice")
    assert alice["avatar_url"] == "https://github.com/alice.png"
    unknown = _person(body, "unknown")
    assert "avatar_url" not in unknown


def test_avatar_url_absent_for_login_with_space(client, dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db)
    prs_db.upsert_pr("acme/widgets", _pr(
        1, created="2026-09-01T00:00:00Z",
        reviews=[_review("Jane Doe", "APPROVED", "2026-09-01T01:00:00Z")],
    ))
    resp = client.get("/api/repos/acme/widgets/analytics/daily?from=2026-09-01&to=2026-09-01")
    body = resp.get_json()
    jane = _person(body, "Jane Doe")
    assert "avatar_url" not in jane


# -- base_branches -----------------------------------------------------------------

def test_base_branches_ordered_most_rows_first(client, dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db)
    prs_db.upsert_pr("acme/widgets", _pr(1, base_ref="main", created="2026-09-01T00:00:00Z"))
    prs_db.upsert_pr("acme/widgets", _pr(2, base_ref="main", created="2026-09-02T00:00:00Z"))
    prs_db.upsert_pr("acme/widgets", _pr(3, base_ref="develop", created="2026-09-01T00:00:00Z"))

    resp = client.get("/api/repos/acme/widgets/analytics/daily?from=2026-09-01&to=2026-09-02")
    body = resp.get_json()
    assert body["base_branches"] == ["main", "develop"]


# -- staleness / syncing / coverage --------------------------------------------------

def test_stale_false_when_fresh(client, dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db)
    prs_db.upsert_pr("acme/widgets", _pr(1, created="2026-09-01T00:00:00Z"))
    resp = client.get("/api/repos/acme/widgets/analytics/daily?from=2026-09-01&to=2026-09-01")
    body = resp.get_json()
    assert body["stale"] is False


def test_stale_true_when_meta_built_at_old(client, dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db)
    prs_db.upsert_pr("acme/widgets", _pr(1, created="2026-09-01T00:00:00Z"))
    # First request builds the rollup.
    client.get("/api/repos/acme/widgets/analytics/daily?from=2026-09-01&to=2026-09-01")

    with analytics_db.db.connection() as conn:
        conn.execute(
            "UPDATE analytics_daily_meta SET built_at = ? WHERE repo = ?",
            ("2000-01-01T00:00:00Z", "acme/widgets"),
        )
    # last_synced_at was never set, so needs_rebuild stays False and the
    # stale built_at survives the second request.
    resp = client.get("/api/repos/acme/widgets/analytics/daily?from=2026-09-01&to=2026-09-01")
    body = resp.get_json()
    assert body["stale"] is True


def test_syncing_true_until_everything_done_then_false(client, dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db, backfill=False, history=False, commit_backfill=False)
    resp = client.get("/api/repos/acme/widgets/analytics/daily")
    body = resp.get_json()
    assert body["syncing"] is True

    prs_db.mark_backfill_done("acme/widgets")
    prs_db.mark_history_done("acme/widgets")
    commits_db.upsert_branch_state("acme/widgets", "main", backfill_done=1)
    resp2 = client.get("/api/repos/acme/widgets/analytics/daily")
    body2 = resp2.get_json()
    assert body2["syncing"] is False


def test_syncing_false_when_branch_errored_out(client, dbs):
    """A persistent branch error (e.g. 404 on a non-existent branch) is terminal:
    it must not latch `syncing` true forever once PR history is otherwise done."""
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db, commit_backfill=False)
    commits_db.upsert_branch_state("acme/widgets", "main", backfill_done=0, error="404 Not Found")

    resp = client.get("/api/repos/acme/widgets/analytics/daily")
    body = resp.get_json()
    assert body["syncing"] is False
    assert body["coverage"]["commit_history_done"] is True


def test_syncing_false_when_pr_sync_disabled(client, dbs, monkeypatch):
    """Nothing will ever change when sync is disabled, so syncing must be False
    even if nothing has been backfilled."""
    monkeypatch.setattr(analytics_routes, "get_pr_sync_config", lambda: {
        "poll_interval_seconds": 60, "commit_branches": ["main"], "enabled": False,
    })
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db, backfill=False, history=False, commit_backfill=False)

    resp = client.get("/api/repos/acme/widgets/analytics/daily")
    body = resp.get_json()
    assert body["syncing"] is False


def test_coverage_fields(client, dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db)
    prs_db.upsert_pr("acme/widgets", _pr(
        1, author="alice", state="MERGED",
        created="2026-09-01T00:00:00Z", merged="2026-09-01T06:00:00Z",
        reviews=[_review("bob", "APPROVED", "2026-09-01T01:00:00Z")],
    ))
    commits_db.upsert_commits("acme/widgets", "main", [
        {"sha": "s1", "login": "alice", "committed_at": "2026-09-01T00:00:00Z", "parents": 1},
    ])

    resp = client.get("/api/repos/acme/widgets/analytics/daily?from=2026-09-01&to=2026-09-01")
    body = resp.get_json()
    coverage = body["coverage"]
    assert coverage["earliest_pr_day"] == "2026-09-01"
    assert coverage["earliest_commit_day"] == "2026-09-01"
    assert coverage["pr_count"] == 1
    assert coverage["review_count"] == 1
    assert coverage["commit_count"] == 1
    assert coverage["backfill_done"] is True
    assert coverage["history_done"] is True
    assert coverage["commit_history_done"] is True


# -- repo registration / last_updated ------------------------------------------------

def test_unregistered_repo_gets_registered_and_response_built(client, dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    assert prs_db.get_repo("acme/newrepo") is None

    resp = client.get("/api/repos/acme/newrepo/analytics/daily")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["people"] == []
    assert body["team"]["totals"]["prs_created"] == 0
    assert prs_db.get_repo("acme/newrepo") is not None


def test_last_updated_is_iso_z(client, dbs):
    prs_db, commits_db, analytics_db, reviews_db = dbs
    _seed_repo(prs_db, commits_db)
    prs_db.upsert_pr("acme/widgets", _pr(1, created="2026-09-01T00:00:00Z"))
    resp = client.get("/api/repos/acme/widgets/analytics/daily?from=2026-09-01&to=2026-09-01")
    body = resp.get_json()
    assert body["last_updated"] is not None
    assert body["last_updated"].endswith("Z")
    assert "T" in body["last_updated"]
