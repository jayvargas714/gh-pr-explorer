#!/usr/bin/env python3
"""One-time backfill: enroll existing open PRs into the automation pipeline.

Candidate detection normally fires only for PRs that appear *after* automation
is enabled, so PRs that were already open never enter the pipeline on their
own. This script enrolls them: for every allowlisted repo it lists the open
PRs (drafts included — the dispatch worker holds them until they're marked
ready) and records each as a pending dispatch candidate. Rows that earlier
ended `skipped` or `failed` (e.g. evicted by the old dispatch timeout) are
revived to pending; rows that are pending, dispatched, or unidentified are
left untouched, so the dispatch-at-most-once guarantee holds.

Respects the automation config: aborts when scope is "off", filters by author
when scope is "authors", and refuses new enrollments past maxPipelineSize.

Usage:
    python scripts/backfill_automation_pipeline.py
"""

import sys
from pathlib import Path

# Add project root to path so we can import backend modules
sys.path.insert(0, str(Path(__file__).parent.parent))


def _fetch_open_prs(repo_full):
    """Open PRs (number + author) for one repo, via gh."""
    from backend.services.github_service import parse_json_output, run_gh_command

    output = run_gh_command([
        "pr", "list", "-R", repo_full, "--state", "open",
        "--limit", "1000", "--json", "number,author",
    ])
    return parse_json_output(output) or []


def backfill():
    """Enroll open PRs from allowlisted repos. Returns a summary dict.

    Raises:
        RuntimeError: when automation is off or no repos are allowlisted —
        enrolling candidates that nothing will ever process is a mistake.
    """
    from backend.database import get_automation_dispatches_db
    from backend.services.automation_config import get_config

    config = get_config()
    if config["scope"] == "off":
        raise RuntimeError("Automation scope is 'off' — enable automation in the "
                           "Automation tab before backfilling.")
    if not config["repoAllowlist"]:
        raise RuntimeError("The repo allowlist is empty — nothing to backfill.")

    dispatches = get_automation_dispatches_db()
    cap = config.get("maxPipelineSize", 1000)
    headroom = cap - dispatches.count_pending()

    summary = {"inserted": 0, "revived": 0, "unchanged": 0, "filtered": 0, "capped": 0}
    for repo_full in config["repoAllowlist"]:
        for pr in _fetch_open_prs(repo_full):
            number = pr.get("number")
            if number is None:
                continue
            author = (pr.get("author") or {}).get("login")
            if config["scope"] == "authors" and author not in config["authors"]:
                summary["filtered"] += 1
                continue

            existing = dispatches.get_by_pr(repo_full, number)
            if existing is None:
                if headroom <= 0:
                    summary["capped"] += 1
                    continue
                dispatches.record_candidate(repo_full, number)
                headroom -= 1
                summary["inserted"] += 1
            elif existing["status"] in ("skipped", "failed"):
                if headroom <= 0:
                    summary["capped"] += 1
                    continue
                dispatches.requeue(existing["id"], detail="revived by backfill")
                headroom -= 1
                summary["revived"] += 1
            else:
                summary["unchanged"] += 1
    return summary


def main():
    try:
        summary = backfill()
    except RuntimeError as e:
        print(f"Backfill aborted: {e}", file=sys.stderr)
        return 1

    print(f"Backfill complete: {summary['inserted']} enrolled, "
          f"{summary['revived']} revived, {summary['unchanged']} already in the pipeline, "
          f"{summary['filtered']} outside the author scope, "
          f"{summary['capped']} refused at maxPipelineSize.")
    if summary["capped"]:
        print("Raise maxPipelineSize in the Automation tab and re-run to enroll the rest.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
