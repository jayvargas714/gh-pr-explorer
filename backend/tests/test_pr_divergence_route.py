"""Live branch-divergence endpoint (PR list badges), with gh mocked."""
import json

import pytest

from backend import create_app


@pytest.fixture
def gh(monkeypatch):
    """Serves reversed-compare (head...base) payloads keyed by head ref."""
    class FakeGh:
        calls = []
        replies = {}

        def __call__(self, args, **kwargs):
            self.calls.append(args)
            head = args[1].split("/compare/")[1].split("...")[0]
            reply = self.replies[head]
            if isinstance(reply, Exception):
                raise reply
            return json.dumps(reply)

    fake = FakeGh()
    fake.calls, fake.replies = [], {}
    import backend.routes.pr_routes as pr_routes
    monkeypatch.setattr(pr_routes, "run_gh_command", fake)
    return fake


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _post(client, prs):
    return client.post("/api/repos/acme/widgets/prs/divergence", json={"prs": prs})


def test_reversed_compare_maps_back_to_base_head_shape(client, gh):
    gh.replies = {
        "feat": {"status": "diverged", "ahead_by": 6, "behind_by": 2,
                 "oldest": "2026-10-01T08:00:00Z"},
        "fresh": {"status": "behind", "ahead_by": 0, "behind_by": 3, "oldest": None},
    }
    resp = _post(client, [{"number": 1, "base": "main", "head": "feat"},
                          {"number": 2, "base": "main", "head": "fresh"}])

    assert resp.status_code == 200
    div = resp.get_json()["divergence"]
    # head...base: its ahead_by is the PR's behind count and vice versa.
    assert div["1"] == {"status": "diverged", "ahead_by": 2, "behind_by": 6,
                        "behind_since": "2026-10-01T08:00:00Z"}
    # head...base "behind" means base has nothing new: the PR is ahead.
    assert div["2"] == {"status": "ahead", "ahead_by": 3, "behind_by": 0, "behind_since": None}
    assert all("compare/" in c[1] and c[1].endswith("?per_page=1") for c in gh.calls)
    assert "repos/acme/widgets/compare/feat...main?per_page=1" in [c[1] for c in gh.calls]


def test_failed_compare_is_omitted(client, gh):
    gh.replies = {"gone": RuntimeError("404")}
    resp = _post(client, [{"number": 9, "base": "main", "head": "gone"}])
    assert resp.get_json()["divergence"] == {}
