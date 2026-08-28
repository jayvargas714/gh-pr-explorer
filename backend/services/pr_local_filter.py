"""Local (DB-served) evaluation of PR list filters with gh-qualifier semantics.

The route's shared post-filter block still owns draft/review/CI filtering —
this module covers everything else that gh qualifiers used to do, so the DB
path returns the same rows a live `gh pr list` query would.
"""

_GITHUB_ONLY_SORTS = {"comments", "reactions", "interactions"}


def needs_github_search(params) -> bool:
    """True when the request uses data GitHub computes that we don't store."""
    if any([params.involves, params.mentions, params.commenter,
            params.reactions, params.interactions, params.comments,
            params.linked, params.team_review_requested]):
        return True
    if params.search and params.search_in and "comments" in params.search_in:
        return True
    if params.sort_by in _GITHUB_ONLY_SORTS:
        return True
    return False


def states_for(params):
    """Map the state param to synced_prs state values (None = all)."""
    return {
        "open": {"OPEN"},
        "closed": {"CLOSED"},
        "merged": {"MERGED"},
    }.get(params.state)  # "all" -> None


def _login(entity) -> str:
    return ((entity or {}).get("login") or "").lower()


def _label_names(pr):
    return {(lbl.get("name") or "").lower() for lbl in pr.get("labels") or []}


def _date_ok(value, after, before) -> bool:
    """Inclusive ISO-string comparison; missing value fails any bound."""
    if after or before:
        if not value:
            return False
        day = value[:10]
        if after and day < after[:10]:
            return False
        if before and day > before[:10]:
            return False
    return True


def _matches(pr, p) -> bool:
    if p.author and _login(pr.get("author")) != p.author.lower():
        return False
    if p.exclude_author and _login(pr.get("author")) == p.exclude_author.lower():
        return False

    assignee_logins = {_login(a) for a in pr.get("assignees") or []}
    if p.assignee and p.assignee.lower() not in assignee_logins:
        return False
    if p.no_assignee == "true" and assignee_logins:
        return False

    labels = _label_names(pr)
    if p.labels:
        wanted = {l.strip().lower() for l in p.labels.split(",") if l.strip()}
        if not wanted.issubset(labels):
            return False
    if p.exclude_labels:
        banned = {l.strip().lower() for l in p.exclude_labels.split(",") if l.strip()}
        if banned & labels:
            return False
    if p.no_label == "true" and labels:
        return False

    if p.base and pr.get("baseRefName") != p.base:
        return False
    if p.head and pr.get("headRefName") != p.head:
        return False

    if p.reviewed_by:
        reviewers = {_login(r.get("author")) for r in pr.get("reviews") or []}
        if p.reviewed_by.lower() not in reviewers:
            return False
    if p.review_requested:
        requested = {_login(r) for r in pr.get("reviewRequests") or []}
        if p.review_requested.lower() not in requested:
            return False

    for value, after, before in (
        (pr.get("createdAt"), p.created_after, p.created_before),
        (pr.get("updatedAt"), p.updated_after, p.updated_before),
        (pr.get("mergedAt"), p.merged_after, p.merged_before),
        (pr.get("closedAt"), p.closed_after, p.closed_before),
    ):
        if not _date_ok(value, after, before):
            return False

    milestone_title = (pr.get("milestone") or {}).get("title")
    if p.milestone:
        if p.milestone == "none":
            if milestone_title:
                return False
        elif milestone_title != p.milestone:
            return False
    if p.exclude_milestone and milestone_title == p.exclude_milestone:
        return False

    if p.search:
        needle = p.search.lower()
        fields = [f.strip() for f in (p.search_in or "").split(",") if f.strip()] or ["title", "body"]
        haystacks = []
        if "title" in fields:
            haystacks.append((pr.get("title") or "").lower())
        if "body" in fields:
            haystacks.append((pr.get("body") or "").lower())
        if not any(needle in h for h in haystacks):
            return False

    return True


def filter_prs_locally(prs, params):
    return [pr for pr in prs if _matches(pr, params)]


def sort_prs_locally(prs, params):
    field = {"updated": "updatedAt"}.get(params.sort_by, "createdAt")
    reverse = params.sort_direction != "asc" if params.sort_by else True
    return sorted(prs, key=lambda pr: pr.get(field) or "", reverse=reverse)
