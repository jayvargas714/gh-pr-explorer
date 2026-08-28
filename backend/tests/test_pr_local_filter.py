"""Filter-parity tests: local engine matches gh qualifier semantics."""
from backend.filters.pr_filter_builder import PRFilterParams
from backend.services.pr_local_filter import (
    filter_prs_locally, needs_github_search, sort_prs_locally, states_for,
)


def _pr(number, **over):
    pr = {
        "number": number, "title": f"Title {number}", "body": "",
        "state": "OPEN", "isDraft": False,
        "author": {"login": "alice"},
        "assignees": [], "labels": [], "reviewRequests": [], "reviews": [],
        "createdAt": "2026-08-01T00:00:00Z", "updatedAt": "2026-08-02T00:00:00Z",
        "closedAt": None, "mergedAt": None,
        "baseRefName": "main", "headRefName": f"feat-{number}",
        "milestone": None,
    }
    pr.update(over)
    return pr


def test_needs_github_search_flags():
    assert not needs_github_search(PRFilterParams())
    assert needs_github_search(PRFilterParams(mentions="bob"))
    assert needs_github_search(PRFilterParams(involves="bob"))
    assert needs_github_search(PRFilterParams(commenter="bob"))
    assert needs_github_search(PRFilterParams(reactions=">5"))
    assert needs_github_search(PRFilterParams(interactions=">5"))
    assert needs_github_search(PRFilterParams(comments=">2"))
    assert needs_github_search(PRFilterParams(linked="true"))
    assert needs_github_search(PRFilterParams(team_review_requested="acme/core"))
    assert needs_github_search(PRFilterParams(search="x", search_in="comments"))
    assert not needs_github_search(PRFilterParams(search="x", search_in="title"))
    assert needs_github_search(PRFilterParams(sort_by="comments"))
    assert not needs_github_search(PRFilterParams(sort_by="updated"))


def test_states_for():
    assert states_for(PRFilterParams(state="open")) == {"OPEN"}
    assert states_for(PRFilterParams(state="merged")) == {"MERGED"}
    assert states_for(PRFilterParams(state="closed")) == {"CLOSED"}
    assert states_for(PRFilterParams(state="all")) is None


def test_author_and_exclude_author():
    prs = [_pr(1), _pr(2, author={"login": "Bob"})]
    assert [p["number"] for p in filter_prs_locally(prs, PRFilterParams(author="bob"))] == [2]
    assert [p["number"] for p in filter_prs_locally(prs, PRFilterParams(exclude_author="bob"))] == [1]


def test_assignee_and_no_assignee():
    prs = [_pr(1, assignees=[{"login": "carol"}]), _pr(2)]
    assert [p["number"] for p in filter_prs_locally(prs, PRFilterParams(assignee="carol"))] == [1]
    assert [p["number"] for p in filter_prs_locally(prs, PRFilterParams(no_assignee="true"))] == [2]


def test_labels_are_ANDed_and_exclusions():
    prs = [
        _pr(1, labels=[{"name": "bug"}, {"name": "ui"}]),
        _pr(2, labels=[{"name": "bug"}]),
        _pr(3, labels=[]),
    ]
    assert [p["number"] for p in filter_prs_locally(prs, PRFilterParams(labels="bug,ui"))] == [1]
    assert [p["number"] for p in filter_prs_locally(prs, PRFilterParams(exclude_labels="ui"))] == [2, 3]
    assert [p["number"] for p in filter_prs_locally(prs, PRFilterParams(no_label="true"))] == [3]


def test_branch_filters():
    prs = [_pr(1, baseRefName="develop"), _pr(2)]
    assert [p["number"] for p in filter_prs_locally(prs, PRFilterParams(base="develop"))] == [1]
    assert [p["number"] for p in filter_prs_locally(prs, PRFilterParams(head="feat-2"))] == [2]


def test_reviewed_by_and_review_requested():
    prs = [
        _pr(1, reviews=[{"author": {"login": "dave"}, "state": "APPROVED"}]),
        _pr(2, reviewRequests=[{"login": "erin"}]),
    ]
    assert [p["number"] for p in filter_prs_locally(prs, PRFilterParams(reviewed_by="dave"))] == [1]
    assert [p["number"] for p in filter_prs_locally(prs, PRFilterParams(review_requested="erin"))] == [2]


def test_date_ranges_inclusive():
    prs = [_pr(1, createdAt="2026-08-01T00:00:00Z"), _pr(2, createdAt="2026-08-15T00:00:00Z")]
    got = filter_prs_locally(prs, PRFilterParams(created_after="2026-08-10", created_before="2026-08-20"))
    assert [p["number"] for p in got] == [2]


def test_milestone_and_none():
    prs = [_pr(1, milestone={"title": "v1.0"}), _pr(2)]
    assert [p["number"] for p in filter_prs_locally(prs, PRFilterParams(milestone="v1.0"))] == [1]
    assert [p["number"] for p in filter_prs_locally(prs, PRFilterParams(milestone="none"))] == [2]
    assert [p["number"] for p in filter_prs_locally(prs, PRFilterParams(exclude_milestone="v1.0"))] == [2]


def test_text_search_title_body():
    prs = [_pr(1, title="Fix login bug"), _pr(2, body="login mentioned here")]
    both = filter_prs_locally(prs, PRFilterParams(search="login"))
    assert [p["number"] for p in both] == [1, 2]
    title_only = filter_prs_locally(prs, PRFilterParams(search="login", search_in="title"))
    assert [p["number"] for p in title_only] == [1]


def test_sort_created_and_updated():
    prs = [
        _pr(1, createdAt="2026-08-01T00:00:00Z", updatedAt="2026-08-20T00:00:00Z"),
        _pr(2, createdAt="2026-08-10T00:00:00Z", updatedAt="2026-08-05T00:00:00Z"),
    ]
    assert [p["number"] for p in sort_prs_locally(prs, PRFilterParams())] == [2, 1]  # default: created desc
    p = PRFilterParams(sort_by="updated", sort_direction="asc")
    assert [p2["number"] for p2 in sort_prs_locally(prs, p)] == [2, 1]
    p = PRFilterParams(sort_by="created", sort_direction="asc")
    assert [p2["number"] for p2 in sort_prs_locally(prs, p)] == [1, 2]
