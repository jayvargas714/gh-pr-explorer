# Automation — Operator's Guide

A short guide to the Automation tab and the full auto-review pipeline. For the
engineering design, see the "Automation (Full Auto Review Pipeline)" section of
`DESIGN.md`.

## What it does

When automation is on, every **newly arriving** PR in a repo you've allowlisted
is picked up automatically: its changed files decide which reviewer runs, the PR
is added to the merge queue inside a permanent **Auto** swimlane, the review
starts on its own, and (if the matching rule says so) an auto verdict or comment
is posted when the review completes. PRs the rules can't classify are parked in
the Auto lane with a `❓ Unidentified` badge for you to route by hand.

Nothing is hardcoded — reviewers, file patterns, repos, and authors are all
configured in the tab, so the pipeline works for any repo and any reviewer set.

## Quick start

1. Open the **Automation** tab (sixth tab, or the 🤖 header button).
2. **Reviewer Registry** — check the reviewers you need exist. The three
   builtins (default / pb / ed) are seeded; add custom ones with a key, label,
   and Claude agent name.
3. **Reviewer Routing Rules** — add a rule per file family, e.g.:
   - `PB` → patterns `PB-[0-9]*` → PB Reviewer
   - `ED` → patterns `ED-[0-9]*` → ED Reviewer
   - Add ignore patterns for files every such PR touches, e.g.
     `*PB-000-index*` and `*ED-000-index*`.
   - Pick the fallback reviewer on the pinned **Default** row.
   - Per rule, toggle **Auto verdict** and choose **Verdict** (thresholds decide
     approve / changes-requested) or **Comment only**.
4. **Full Automation** — add the repos to the **Repository allowlist**, then set
   the scope: **By author** (only the listed GitHub logins) or **All new PRs**.
5. Click **Save automation config**. Done — the header 🤖 shows `on`.

To stop everything instantly, set the scope back to **Off** and save. It's a
live kill switch; pending PRs stay queued but nothing new is dispatched.

## How routing works

For each new PR the pipeline fetches the changed file list, drops files matching
any ignore pattern, then tests each remaining file against the rules **top to
bottom** (first match wins per file):

| Result | Outcome |
|--------|---------|
| Every file matches the same one rule | That rule's reviewer runs |
| No file matches any rule (or all were ignored) | The default reviewer runs |
| Files span two+ rules, or mix a rule with unmatched files | **Unidentified** — no review; you route it manually |

Patterns are globs (`fnmatch`), matched against the full path **and** the bare
filename, case-sensitively. Note `*` also crosses `/`, so `PB-[0-9]*` matches
`briefs/PB-008-chart-shell.md`.

## What you'll see

- **Auto lane** on the swimlane board — permanent (no delete/rename), tagged
  `🤖 auto`. Every auto-processed PR lands there; you can still drag cards out.
- **Card badges**: `🤖 Auto` (auto-reviewed; tooltip names the rule and
  reviewer), `❓ Unidentified` (tooltip lists the rules the files spanned),
  `🤖 Auto failed` (pipeline gave up; tooltip has the error).
- The board's badge filter has a matching `❓ Unidentified` chip.

**Handling an unidentified PR**: open the card, start the review with the normal
Review button (pick the reviewer yourself), and arm auto-verdict from the card's
🤖 menu if you want the usual follow-up loop. The badge is informational — no
extra bookkeeping needed.

## Auto verdicts

The per-rule toggle only **arms** the PR; what a verdict does is governed by the
**Auto Verdict Criteria** section (moved here from the old header modal): the
global master switch, the critical/major/minor thresholds, auto-approve, and
auto follow-up reviews on new commits. Per-PR threshold overrides still live on
each card's 🤖 menu. If the master switch is off, armed cards evaluate nothing
and never post.

## Rules of engagement (what it will never do)

- **Only PRs first seen after enabling.** Existing open PRs are never swept, and
  a repo's initial backfill never triggers reviews.
- **One auto-dispatch per PR, ever** — survives restarts. Follow-up reviews come
  from the (separate) auto follow-up watcher on armed cards.
- **Draft PRs are skipped**, and marking one ready later does not re-trigger it
  — review it manually.
- **Concurrency is capped** by *Max concurrent auto reviews* (default 2); extra
  PRs wait in line.
- Failures (file fetch, review spawn) retry up to 3 times, then mark the PR
  `Auto failed` for manual handling.

## Troubleshooting

*"My PR wasn't picked up"* — check, in order: scope isn't Off; the repo is in
the allowlist (exact `owner/repo`); for author scope, the PR author's login is
listed; the PR is open and not a draft; and the PR was created **after** you
enabled automation. Also note only repos covered by the background PR sync are
watched (a repo starts syncing once it's been viewed in the app).

*"It routed to the wrong reviewer"* — rules are ordered; the first matching rule
claims each file. Reorder with ↑/↓, and remember patterns are case-sensitive.

*"Where do I see what happened?"* — the card's badges and tooltips carry the
outcome; review attempts themselves appear in the Review Logs tab like any other
review (auto-started runs are marked).
