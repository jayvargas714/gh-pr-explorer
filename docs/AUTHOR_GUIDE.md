# Automated Reviews — PR Author's Guide

This guide is for people who **open pull requests** in a repo where GitHub PR
Explorer is running. You never open the app. Everything you see and everything
you do happens on GitHub: comments on your PR, review verdicts, inline comments,
and the **Re-request review** button.

For the people who run the tool, see `AUTOMATION.md`.

---

## The short version

1. Open a PR. If the repo is enrolled, a 🤖 comment says your PR is queued.
2. The review starts once your PR is **not a draft**, **CI is green**, it
   **targets `main`**, and it is **not far behind** `main`.
3. You get a normal GitHub review: **Approve**, **Request Changes**, or
   **Comment**, with findings in the body and often as inline comments.
4. To get another look: **push commits**, or **reply to the findings** and click
   **Re-request review** on the bot's account.
5. Findings you push back on with a good reason are **withdrawn**. Findings you
   agree to do later are **deferred**. Findings where you and the reviewer
   disagree are **disputed** and go to a human once there are enough of them.

---

## 1. What happens when you open a PR

If your repo is enrolled and your PR is in scope, a comment appears within a
minute or two:

> 🤖 **PR enrolled for automated review**
> GitHub PR Explorer has queued this PR for automatic code review. The review
> starts once all gates pass (not a draft, CI green, branch close enough to
> base, review slot free).

Nothing else happens until the gates clear. If a gate is blocking, the comment
is replaced with **🤖 Automated review waiting** and names the gate:

| Waiting on | What to do |
|---|---|
| `PR is a draft` | Mark the PR ready for review. |
| `CI pending` / `CI failure` | Wait for CI, or fix it. PRs with no CI checks pass this gate. |
| `base branch is X, not main` | Retarget the PR to `main`. Stacked PRs pick up automatically once the parent merges and GitHub retargets them. |
| `N commits behind base (max 10)` | Rebase or merge `main` into your branch. |
| `concurrency budget full` | Nothing. Other reviews are running; yours starts when a slot frees. |

The pipeline re-checks about once a minute. Your PR waits as long as it stays
open; there is no timeout unless your team has configured one (in which case you
would see **🤖 Automated review window expired** with instructions).

**There is only ever one 🤖 status comment on your PR.** Each new status replaces
the previous one, so the latest 🤖 comment is always the current state. Posted
review verdicts are never deleted or edited.

### Why did nothing happen?

The pipeline only picks up PRs that match the team's configuration. Common
reasons for silence:

- The repo is not enrolled.
- The team restricted automation to specific authors and you are not listed.
- The PR is a draft (drafts are recorded but not announced until ready).
- The PR touched files that match more than one routing rule. You would see
  **🤖 Automated review needs manual routing**; an operator has to pick the
  reviewer.

If you want a review anyway, **request a review from the bot's account** on
GitHub (see section 4). A direct request bypasses the author restriction.

---

## 2. What a review looks like

When the review starts you see:

> 🤖 **Code review in progress**
> A review has been started for this PR by GitHub PR Explorer.
> - Reviewer: `ed`
> - Commit: `3f2a9c1d`
> - Started: 2026-09-04 15:02 UTC

The `Reviewer` line names which specialist ran: `default` for code, `pb` for
Product Briefs, `ed` for Engineering Designs, or a custom reviewer your team
has configured. It is chosen from the files you changed.

Reviews take a few minutes to an hour. If something goes wrong mid-run you will
see **attempt failed — retry scheduled**; nothing is needed from you. After the
last failed attempt you see **Code review failed — giving up**, and pushing a
new commit triggers a fresh attempt.

### The posted review

The result is a standard GitHub review on your PR. The body has these parts,
separated by horizontal rules, and only the parts that apply:

- **Summary.** A few sentences on the change. It never contains a verdict of its
  own; the verdict is the review state.
- **Critical Issues**, **Major Concerns**, **Minor Issues.** Each finding has a
  title, the file and line, the **Problem**, and a suggested **Fix**.
- **Disputed** and **Deferred.** Only in follow-up reviews. Findings you pushed
  back on or agreed to do later, with your rationale attached. See section 5.
- **Dispositions.** Only in follow-up reviews. One line per finding from the
  previous round saying what happened to it: `resolved`,
  `partially_addressed`, `not_addressed`, `wont_fix`, `withdrawn`, `disputed`,
  or `deferred`.

There is no score in the posted body and no closing recommendations block.

### Inline comments

Critical and major findings are often posted as **inline comments** on the
exact lines, each formatted as:

> **Title of the finding**
> **Problem:** what is wrong
> **Fix:** what to do instead

When inline comments are used, the review body starts with a small table
listing every inline finding with its severity, title, and location, so the
review acts as an index into the diff.

**Reply on the inline thread** when you respond to a finding. That is the
easiest way for the next round to connect your reply to the right finding.

---

## 3. How the verdict is decided

The reviewer agent never decides the verdict. It reports findings; the tool
applies your team's thresholds.

| Result | When |
|---|---|
| **Request Changes** | Findings exceed the thresholds. Default: any critical or any major finding. |
| **Approve** | Findings are within thresholds **and** the team has enabled auto-approve. |
| **Comment** | Findings within thresholds but auto-approve is off; comment-only mode is configured for this kind of PR; the PR is authored by the bot's own account; or the PR is in mediation (section 6). |

If your review passes but auto-approve is off, you see:

> 🤖 **Review complete — approval needs manual action**

A human has to post the approval. This is by design: on most teams every
approval is a person's decision.

Minor findings never block by default (the threshold is 99). Disputed and
deferred findings never count toward any threshold.

If GitHub's API quota is exhausted when the verdict is ready, you see
**verdict delayed by GitHub rate limit**. The verdict posts itself when the
quota resets, retrying for up to 24 hours.

---

## 4. Getting another review

There are two triggers. Use whichever fits.

### Push commits

- **If a review is running**, it is stopped and restarted against your new head.
  The new "Code review in progress" comment carries a note saying it was
  restarted after new commits. Findings against stale code are never posted.
- **If a review has already been posted** and your team enabled automatic
  follow-ups for this PR, a follow-up review starts on its own within about a
  minute. Otherwise nothing happens until you re-request.

### Re-request review

Click the **↻ Re-request review** button next to the bot's account in the
Reviewers sidebar (or request it fresh if it is not there yet). Within a sync
cycle you see one of:

| Comment | Meaning |
|---|---|
| **Review requested — PR enrolled for automated review** | The PR was not in the pipeline. It is now, and the first review starts once the gates pass. |
| **Review requested — follow-up queued** | The PR was already reviewed. A follow-up runs under the same gates. |
| **Review requested — needs manual routing** | The reviewer could not be chosen from the files. An operator will route it. |

A review request works even if the PR had been opted out of automation, and
even if the author restriction would otherwise exclude you. It does **not**
bypass the gates: a draft or red CI still waits.

**When to re-request instead of pushing.** Re-request when you have answered
findings **in the conversation** rather than with code: you explained why a
finding does not apply, or agreed to handle it in a named follow-up. The
follow-up review reads those replies. Pushing alone does not tell the reviewer
to read your replies.

**Known gap.** If the bot posted a review but GitHub did not clear its request
(rare), a plain re-request is not detected. Remove the bot from Reviewers, wait
a minute, and request it again.

---

## 5. Responding to findings

A follow-up review is **not** a fresh review. It looks at three things only:

1. The diff since the previous review.
2. The previous review's findings, and whether each was addressed.
3. **Your replies** in the PR conversation since the previous review.

Unchanged text is not re-reviewed, so a follow-up cannot surface new findings in
code you did not touch. This is what lets review rounds converge.

### What the reviewer reads

Everything a human wrote on the PR after the previous review was posted:

- PR conversation comments
- Replies on inline review threads (the whole thread is included for context)
- Bodies of reviews submitted by people

Bots, the tool's own 🤖 status comments, and the bot account's own reviews are
excluded. Comments made before the previous review are not re-read.

### How your reply is classified

Each reply that addresses a finding is treated as your **disposition** of it:

| You say | Reviewer accepts? | Result |
|---|---|---|
| "Fixed in `abc1234`" (or the diff shows it) | — | **resolved** / **partially_addressed** |
| "This does not apply because …" | Yes | **withdrawn**. Gone from the review, listed under Dispositions. |
| "This does not apply because …" | No | **disputed**. Moved to the Disputed section with your rationale attached and the reviewer's reason for holding it. It is not re-argued in later rounds. |
| "Will do in #1234" / "tracked for M3" | — | **deferred**. Moved to the Deferred section with the target you named. |
| "Won't fix" with no reason | — | **wont_fix**. Still counts against the threshold. |
| Nothing | — | **not_addressed**. Still counts. |

Once a finding is in Disputed or Deferred it stays there **verbatim** in every
later round unless you say something new about it. The reviewer will never
silently drop a finding you disputed.

### Writing replies that land

- **Reply on the inline thread** for the finding, or quote the finding's title
  exactly. Dispositions are matched by title.
- **One finding, one reply.** A single comment covering five findings is
  harder to attribute than five short replies.
- **Give the reason, not just the position.** "Not applicable" is a dispute
  with no rationale. "Not applicable: this path is unreachable because X
  validates Y at line 40" can be withdrawn.
- **Name the follow-up target** when deferring: an issue number, a PR, or a
  milestone. A deferral with no target may not be recognized as one.
- Then **push or re-request**. Replies alone do not start a round.

---

## 6. Disputed findings and mediation

Disputed and deferred findings keep their original severity but **do not count**
toward the approve / request-changes decision. A PR with two disputed criticals
and nothing else outstanding can pass the thresholds.

There is a ceiling. When the number of disputed **critical or major** findings
reaches the team's threshold (default **3**), automation stops for the PR:

> 🤖 **Auto verdict stopped — human mediation needed**
> 3 critical/major findings are disputed (threshold 3): the author declined them
> with a rationale the reviewer does not accept. The review was posted as a
> comment instead of a verdict, and auto verdict is now disarmed for this PR so
> no further automatic rounds run.

What this means for you:

- The review body is still posted, as a **Comment**, so the Disputed list is on
  the PR for everyone to read.
- No further automatic verdicts are posted on this PR until a person re-arms it.
- The disputes are settled by a human (on Scala teams, the Area Lead at live
  review). After that, the operator re-arms the PR and normal rounds resume.

Comment-only mode never mediates, because it never posts a verdict to begin
with.

---

## 7. Every 🤖 comment you might see

| Heading | Meaning | Your move |
|---|---|---|
| PR enrolled for automated review | Queued; waiting for gates. | None. |
| Automated review waiting | A gate is blocking; the reason is listed. | Clear the gate if it is yours (draft, CI, base, behind). |
| Automated review window expired | Waited past the team's timeout and left the pipeline. | Ask for a manual review, or re-request from the bot. |
| Automated review needs manual routing | Files span several routing rules. | None; an operator routes it. |
| Automated review dispatch failed | The pipeline could not start the review. | None; an operator will look. Re-request later if you like. |
| Code review in progress | A review is running on the named commit. | Avoid pushing if you want this run to finish; a push restarts it. |
| Code review attempt failed — retry scheduled | Transient failure; retry is automatic. | None. |
| Code review failed — giving up | All attempts failed. | Push a commit to trigger a fresh attempt, or ask an operator. |
| Code review stopped — new commits | Your push stopped a running review and the automatic restart failed. | Re-request review or ask an operator. |
| Code review interrupted — requeued | The service restarted mid-review; it will re-run. | None. |
| Review complete — approval needs manual action | Passed thresholds; auto-approve is off. | Wait for a human approval. |
| Review complete — verdict delayed by GitHub rate limit | Verdict decided; posting is deferred. | None; it posts itself. |
| Review verdict could not be posted | Posting failed for good. | An operator posts it by hand. |
| Automatic verdict skipped | Review completed but no verdict was appropriate; reason given. | Read the reason. |
| Auto verdict stopped — human mediation needed | Disputed threshold reached. | See section 6. |
| Review requested — PR enrolled / follow-up queued / needs manual routing | Your re-request was received. | None. |

---

## 8. What the bot will never do

- **Approve your own PRs.** GitHub forbids self-approval, so PRs authored by
  the bot's account get their findings as a Comment.
- **Approve anything unless the team enabled auto-approve.** Otherwise a
  passing review ends in "approval needs manual action".
- **Merge, push, edit, or rebase your branch.** It reads your PR in a throwaway
  checkout of its own. Your working copy and the shared checkouts are never
  touched.
- **Review a draft.** Drafts wait until marked ready.
- **Post findings against code you have since replaced.** A running review is
  stopped and restarted when you push.
- **Leave more than one status comment standing**, or delete a posted review.
- **Drop a finding you disputed without saying so.** Disputed findings stay
  listed with your rationale until a human settles them.
- **Argue a dispute twice.** Once a finding is Disputed, later rounds carry it
  forward verbatim unless you add something new.

---

## 9. Quick FAQ

**How long does a review take?** Usually a few minutes; up to an hour for large
design documents. Runs are killed after 60 minutes and retried.

**I pushed and nothing happened.** Automatic follow-ups on push are enabled per
PR by your team. If they are not enabled for yours, click Re-request review.

**Can I turn it off for my PR?** Ask an operator to opt the PR out. Note that
re-requesting a review from the bot re-enrolls it.

**The finding is wrong.** Reply on the thread with why, then re-request. If the
reviewer accepts the reason the finding is withdrawn; if not it becomes
Disputed, stops counting toward the verdict, and a human settles it.

**Why did the same finding come back after I fixed it?** Check the Dispositions
section: it will say `partially_addressed` or `not_addressed` with the
reviewer's reasoning. If you believe it is fully fixed, say so on the thread and
re-request.

**Who is the bot?** The GitHub account your team uses to run GitHub PR
Explorer. Its reviews and comments appear under that login, and that is the
account to request a review from.
