"""PR filter parameter parsing and gh CLI arg construction."""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class PRFilterParams:
    """Parsed PR filter parameters from request args."""
    state: str = "open"
    author: Optional[str] = None
    assignee: Optional[str] = None
    labels: Optional[str] = None
    base: Optional[str] = None
    head: Optional[str] = None
    draft: Optional[str] = None
    review: Optional[str] = None
    reviewed_by: Optional[str] = None
    review_requested: Optional[str] = None
    status: Optional[str] = None
    involves: Optional[str] = None
    mentions: Optional[str] = None
    commenter: Optional[str] = None
    linked: Optional[str] = None
    comments: Optional[str] = None
    created_after: Optional[str] = None
    created_before: Optional[str] = None
    updated_after: Optional[str] = None
    updated_before: Optional[str] = None
    merged_after: Optional[str] = None
    merged_before: Optional[str] = None
    closed_after: Optional[str] = None
    closed_before: Optional[str] = None
    milestone: Optional[str] = None
    no_assignee: Optional[str] = None
    no_label: Optional[str] = None
    search_in: Optional[str] = None
    search: Optional[str] = None
    reactions: Optional[str] = None
    interactions: Optional[str] = None
    team_review_requested: Optional[str] = None
    exclude_labels: Optional[str] = None
    exclude_author: Optional[str] = None
    exclude_milestone: Optional[str] = None
    sort_by: Optional[str] = None
    sort_direction: str = "desc"
    limit: int = 30

    @classmethod
    def from_request_args(cls, args, default_per_page=30):
        """Parse from Flask request.args."""
        return cls(
            state=args.get("state", "open"),
            author=args.get("author"),
            assignee=args.get("assignee"),
            labels=args.get("labels"),
            base=args.get("base"),
            head=args.get("head"),
            draft=args.get("draft"),
            review=args.get("review"),
            reviewed_by=args.get("reviewedBy"),
            review_requested=args.get("reviewRequested"),
            status=args.get("status"),
            involves=args.get("involves"),
            mentions=args.get("mentions"),
            commenter=args.get("commenter"),
            linked=args.get("linked"),
            comments=args.get("comments"),
            created_after=args.get("createdAfter"),
            created_before=args.get("createdBefore"),
            updated_after=args.get("updatedAfter"),
            updated_before=args.get("updatedBefore"),
            merged_after=args.get("mergedAfter"),
            merged_before=args.get("mergedBefore"),
            closed_after=args.get("closedAfter"),
            closed_before=args.get("closedBefore"),
            milestone=args.get("milestone"),
            no_assignee=args.get("noAssignee"),
            no_label=args.get("noLabel"),
            search_in=args.get("searchIn", ""),
            search=args.get("search", ""),
            reactions=args.get("reactions"),
            interactions=args.get("interactions"),
            team_review_requested=args.get("teamReviewRequested"),
            exclude_labels=args.get("excludeLabels"),
            exclude_author=args.get("excludeAuthor"),
            exclude_milestone=args.get("excludeMilestone"),
            sort_by=args.get("sortBy"),
            sort_direction=args.get("sortDirection", "desc"),
            limit=min(args.get("limit", default_per_page, type=int), 100),
        )


class PRFilterBuilder:
    """Translates PRFilterParams to gh CLI args list."""

    def __init__(self, owner: str, repo: str, params: PRFilterParams):
        self.owner = owner
        self.repo = repo
        self.params = params

    def build(self) -> List[str]:
        """Build the full gh pr list command args."""
        args = ["pr", "list", "-R", f"{self.owner}/{self.repo}"]
        search_parts = []

        self._add_state(args)
        self._add_basic_filters(args)
        self._add_draft_qualifier(search_parts)
        self._add_review_qualifiers(search_parts)
        self._add_people_qualifiers(search_parts)
        self._add_date_qualifiers(search_parts)
        self._add_misc_qualifiers(search_parts)
        self._add_search_text(search_parts)
        self._add_advanced_qualifiers(search_parts)
        self._add_sort(search_parts)

        if search_parts:
            args.extend(["--search", " ".join(search_parts)])

        args.extend(["--limit", str(self.params.limit)])

        args.extend([
            "--json",
            "number,title,author,state,isDraft,createdAt,updatedAt,closedAt,"
            "mergedAt,url,body,headRefName,baseRefName,labels,assignees,"
            "reviewRequests,reviewDecision,mergeable,additions,deletions,changedFiles,"
            "milestone,statusCheckRollup"
        ])

        return args

    def _add_state(self, args):
        p = self.params
        if p.state == "all":
            args.extend(["--state", "all"])
        elif p.state == "merged":
            args.extend(["--state", "merged"])
        elif p.state == "closed":
            args.extend(["--state", "closed"])
        else:
            args.extend(["--state", "open"])

    def _add_basic_filters(self, args):
        p = self.params
        if p.author:
            args.extend(["--author", p.author])
        if p.assignee:
            args.extend(["--assignee", p.assignee])
        if p.labels:
            for lbl in p.labels.split(","):
                lbl = lbl.strip()
                if lbl:
                    args.extend(["--label", lbl])
        if p.base:
            args.extend(["--base", p.base])
        if p.head:
            args.extend(["--head", p.head])

    def _add_draft_qualifier(self, search_parts):
        p = self.params
        if p.draft == "true":
            search_parts.append("draft:true")
        elif p.draft == "false":
            search_parts.append("draft:false")

    def _add_review_qualifiers(self, search_parts):
        p = self.params
        if p.review:
            values = [r.strip() for r in p.review.split(",") if r.strip()]
            if len(values) == 1:
                search_parts.append(f"review:{values[0]}")
            elif len(values) > 1:
                parts = [f"review:{r}" for r in values]
                search_parts.append(f"({' OR '.join(parts)})")
        if p.reviewed_by:
            search_parts.append(f"reviewed-by:{p.reviewed_by}")
        if p.review_requested:
            search_parts.append(f"review-requested:{p.review_requested}")
        # Note: CI status filtering (params.status) is handled via Python post-filter
        # in pr_routes.py because gh search doesn't support the status: qualifier
        # for CI check results.

    def _add_people_qualifiers(self, search_parts):
        p = self.params
        if p.involves:
            search_parts.append(f"involves:{p.involves}")
        if p.mentions:
            search_parts.append(f"mentions:{p.mentions}")
        if p.commenter:
            search_parts.append(f"commenter:{p.commenter}")
        if p.linked == "true":
            search_parts.append("linked:issue")
        elif p.linked == "false":
            search_parts.append("-linked:issue")

    def _add_date_qualifiers(self, search_parts):
        p = self.params
        date_filters = [
            (p.created_after, "created:>="),
            (p.created_before, "created:<="),
            (p.updated_after, "updated:>="),
            (p.updated_before, "updated:<="),
            (p.merged_after, "merged:>="),
            (p.merged_before, "merged:<="),
            (p.closed_after, "closed:>="),
            (p.closed_before, "closed:<="),
        ]
        for value, prefix in date_filters:
            if value:
                search_parts.append(f"{prefix}{value}")

    def _add_misc_qualifiers(self, search_parts):
        p = self.params
        if p.comments:
            search_parts.append(f"comments:{p.comments}")
        if p.milestone:
            if p.milestone == "none":
                search_parts.append("no:milestone")
            else:
                search_parts.append(f'milestone:"{p.milestone}"')
        if p.no_assignee == "true":
            search_parts.append("no:assignee")
        if p.no_label == "true":
            search_parts.append("no:label")

    def _add_search_text(self, search_parts):
        p = self.params
        if p.search:
            if p.search_in:
                for f in p.search_in.split(","):
                    f = f.strip()
                    if f in ["title", "body", "comments"]:
                        search_parts.append(f"{p.search} in:{f}")
            else:
                search_parts.append(p.search)

    def _add_advanced_qualifiers(self, search_parts):
        p = self.params
        if p.reactions:
            search_parts.append(f"reactions:{p.reactions}")
        if p.interactions:
            search_parts.append(f"interactions:{p.interactions}")
        if p.team_review_requested:
            search_parts.append(f"team-review-requested:{p.team_review_requested}")
        if p.exclude_labels:
            for lbl in p.exclude_labels.split(","):
                lbl = lbl.strip()
                if lbl:
                    search_parts.append(f'-label:"{lbl}"')
        if p.exclude_author:
            search_parts.append(f"-author:{p.exclude_author}")
        if p.exclude_milestone:
            search_parts.append(f'-milestone:"{p.exclude_milestone}"')

    def _add_sort(self, search_parts):
        p = self.params
        if p.sort_by:
            sort_map = {
                "created": "created",
                "updated": "updated",
                "comments": "comments",
                "reactions": "reactions",
                "interactions": "interactions"
            }
            if p.sort_by in sort_map:
                search_parts.append(f"sort:{sort_map[p.sort_by]}-{p.sort_direction}")
