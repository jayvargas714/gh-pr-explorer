"""Claude CLI subprocess management: start, cancel, poll, save to DB."""

import json
import logging
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.config import get_review_retry_settings, get_reviews_dir
from backend.services.github_service import fetch_pr_head_sha, fetch_pr_state
from backend.services.review_started_service import post_review_started_comment
from backend.services.review_event_log import (
    new_run_id,
    record_completed,
    record_failed,
    record_gave_up,
    record_retry_scheduled,
    record_started,
    REASON_NO_OUTPUT,
    REASON_NONZERO_EXIT,
    REASON_SPAWN_FAILED,
)
from backend.services.review_schema import (
    extract_markdown_summary,
    markdown_to_json,
    validate_review_json,
    json_to_markdown,
    SCHEMA_VERSION,
)

logger = logging.getLogger(__name__)

# Compact schema instructions embedded in the review prompt
_SCHEMA_INSTRUCTIONS = (
    "The JSON must have these top-level keys: "
    '"schema_version" (set to "1.0.0"), '
    '"metadata" (object with pr_number, repository, pr_url, pr_title, author, branch {head, base}, '
    "review_date, review_type, files_changed, additions, deletions), "
    '"summary" (string), '
    '"sections" (array of objects with type=critical|major|minor, display_name, and issues array), '
    '"highlights" (array of strings), '
    '"recommendations" (array of {priority: must_fix|high|medium|low, text}), '
    '"score" (object with overall 0-10, optional breakdown array of {category, score, comment}, optional summary). '
    "Each issue MUST have: title (string), location (object with file, start_line, end_line), "
    "problem (string), and optionally principle (string — the engineering principle violated, "
    "e.g. 'DRY / Single Source of Truth (violates DRY)'), fix (string), and code_snippet (string). "
)

# The wrapper CLI must not hand the review off to a background agent. In
# `claude -p`, a text-only turn ends the run, which kills any still-running
# background subagent before it writes its output files — producing a silent
# success with no review on disk. Requiring a foreground dispatch keeps the
# wrapper alive until the files exist.
_FOREGROUND_INSTRUCTIONS = (
    "Run the reviewer agent in the FOREGROUND and wait for it to return. Do NOT "
    "dispatch it as a background or async agent, and do not end your turn while it "
    "is still running — ending your turn early kills the agent before it can write "
    "anything. Confirm both output files exist on disk before you finish. "
)


def review_produced_output(review_file):
    """True when a review run actually wrote something we can ingest.

    The Claude CLI can exit 0 having written neither file — most often because
    it delegated to a background agent and ended its turn, killing the agent
    mid-review. Such a run is a failure however clean its exit code looks.
    """
    if not review_file:
        return False
    review_path = Path(review_file)
    return review_path.exists() or review_path.with_suffix(".json").exists()


# How far back to look for a follow-up's parent. A PR accumulates a handful of
# reviews, so this only needs to outrun a plausible run of consecutive failures.
PREVIOUS_REVIEW_SEARCH_LIMIT = 20


def _is_error_stub(content_json):
    """True when a stored review holds no findings to follow up on.

    save_review_to_db() writes an {"error": true} stub when a review produced no
    output. Handing that to a follow-up asks the reviewer to track resolution
    against an empty issue list. Content that simply is not JSON is left alone —
    start_review_process() passes it through verbatim, which predates this check.
    """
    if not content_json:
        return True
    try:
        return bool(json.loads(content_json).get("error"))
    except (json.JSONDecodeError, TypeError, AttributeError):
        return False


def _find_usable_previous_review(reviews_db, full_repo, pr_number):
    """Most recent review for a PR that carries real findings.

    Walks back past failure stubs rather than falling back to a fresh review: the
    PR's earlier findings are still the right thing to track resolution against,
    and discarding them would waste the follow-up's whole point.
    """
    candidates = reviews_db.list_reviews(
        repo=full_repo, pr_number=pr_number, limit=PREVIOUS_REVIEW_SEARCH_LIMIT
    )
    for candidate in candidates:
        if not _is_error_stub(candidate.get("content_json")):
            return candidate
    return None


def _event_target_for(key, review):
    """(run_id, repo, pr_number) for the event recorders.

    Returns None when the key is unparseable or the review predates run_id
    tracking, in which case the event is simply not recorded — the log must
    never be the reason a review stops progressing.
    """
    parts = key.split("/")
    if len(parts) < 3 or not review.get("run_id"):
        return None
    try:
        return review["run_id"], f"{parts[0]}/{parts[1]}", int(parts[2])
    except ValueError:
        return None


def _review_score(review_id, reviews_db):
    """Best-effort score lookup for the event log; never raises."""
    if not review_id or reviews_db is None:
        return None
    try:
        row = reviews_db.get_review(review_id)
        return row.get("score") if row else None
    except Exception:
        return None


def save_review_to_db(key, review, status, reviews_db):
    """Save a completed/failed review to the database.

    Reads both .md and .json files. If .json exists and validates, uses it directly.
    Otherwise falls back to parsing the .md file via markdown_to_json().

    Returns the new review id, or None if the review could not be saved.
    """
    try:
        parts = key.split("/")
        if len(parts) >= 3:
            owner = parts[0]
            repo = parts[1]
            pr_number = int(parts[2])
            full_repo = f"{owner}/{repo}"

            review_json_data = None
            review_file = review.get("review_file")

            if status == "completed" and review_file:
                review_path = Path(review_file)
                json_path = review_path.with_suffix(".json")

                # Try reading the .json file first (agent writes both .md and .json)
                if json_path.exists():
                    try:
                        raw = json_path.read_text(encoding="utf-8")
                        parsed = json.loads(raw)
                        valid, errs = validate_review_json(parsed)
                        if valid:
                            review_json_data = parsed
                            logger.info(f"Loaded validated JSON review from {json_path}")
                        else:
                            logger.warning(f"JSON review at {json_path} failed validation: {errs[:3]}")
                    except Exception as e:
                        logger.warning(f"Could not read/parse JSON review file {json_path}: {e}")

                # Fallback: read the .md file and convert to JSON
                if review_json_data is None and review_path.exists():
                    try:
                        md_content = review_path.read_text(encoding="utf-8")
                        metadata = {
                            "pr_number": pr_number,
                            "repo": full_repo,
                            "pr_url": review.get("pr_url", ""),
                            "pr_title": review.get("pr_title"),
                            "pr_author": review.get("pr_author"),
                            "is_followup": review.get("is_followup", False),
                            "parent_review_id": review.get("parent_review_id"),
                        }
                        review_json_data = markdown_to_json(md_content, metadata)
                        logger.info(f"Converted markdown review to JSON for {key}")
                    except Exception as e:
                        logger.warning(f"Could not read/convert review file {review_file}: {e}")

                # Override JSON summary with verbatim markdown summary when both
                # files exist. The agent produces the two files independently
                # and often reworks the JSON summary; the markdown is canonical.
                if review_json_data is not None and review_path.exists():
                    try:
                        md_content = review_path.read_text(encoding="utf-8")
                        md_summary = extract_markdown_summary(md_content)
                        if md_summary:
                            review_json_data["summary"] = md_summary
                    except Exception as e:
                        logger.warning(f"Could not extract markdown summary for {key}: {e}")

            # Build content_json string
            if review_json_data is None:
                # Distinguishable stub for failed/empty reviews
                review_json_data = {
                    "schema_version": SCHEMA_VERSION,
                    "error": True,
                    "metadata": {"pr_number": pr_number, "repository": full_repo},
                    "summary": "",
                    "sections": [],
                    "highlights": [],
                    "recommendations": [],
                    "score": {"overall": 0},
                }

            content_json_str = json.dumps(review_json_data, ensure_ascii=False)

            pr_url = review.get("pr_url", "")
            pr_title = review.get("pr_title")
            pr_author = review.get("pr_author")
            is_followup = review.get("is_followup", False)
            parent_review_id = review.get("parent_review_id")
            reviewer_agent = review.get("reviewer_type", "default")

            if not pr_title:
                pr_title = review_json_data.get("metadata", {}).get("pr_title")
            if not pr_title:
                pr_title = f"PR #{pr_number} Review"

            # The head SHA is critical for the "new commits since review" badge
            # in the merge queue and swimlane views. fetch_pr_head_sha already
            # retries transient errors via run_gh_command, but if it still comes
            # back empty (because gh succeeded but returned no SHA, or a rare
            # double failure), retry with a short delay before giving up — a
            # review without a SHA permanently loses its follow-up signal.
            head_commit_sha = fetch_pr_head_sha(owner, repo, pr_number)
            if not head_commit_sha:
                for delay in (2, 5):
                    time.sleep(delay)
                    head_commit_sha = fetch_pr_head_sha(owner, repo, pr_number)
                    if head_commit_sha:
                        break
                if not head_commit_sha:
                    logger.warning(
                        f"Could not capture head SHA for {key} after retries — the "
                        f"'new commits' badge will not work until the PR is re-reviewed."
                    )
            pr_state_at_review = fetch_pr_state(owner, repo, pr_number)

            review_id = reviews_db.save_review(
                pr_number=pr_number,
                repo=full_repo,
                pr_title=pr_title,
                pr_author=pr_author,
                pr_url=pr_url,
                status=status,
                review_file_path=review_file,
                content_json=content_json_str,
                is_followup=is_followup,
                parent_review_id=parent_review_id,
                head_commit_sha=head_commit_sha,
                pr_state_at_review=pr_state_at_review,
                reviewer_agent=reviewer_agent,
                auto_started=review.get("auto_started", False)
            )
            logger.info(f"Saved review to database for {key}")
            return review_id
    except Exception as e:
        logger.error(f"Failed to save review to database for {key}: {e}")
    return None


def check_review_status(key, active_reviews, reviews_lock, reviews_db):
    """Check and update the status of a review process.

    A run that exits non-zero, or exits 0 without writing its review files, is
    retried up to the configured attempt limit before being recorded as failed.
    The reported status stays "running" across retries so callers see one
    continuous review rather than a burst of failures.
    """
    with reviews_lock:
        if key not in active_reviews:
            return None
        review = active_reviews[key]
        if review["status"] != "running":
            return review

        def finalize(succeeded):
            status = "completed" if succeeded else "failed"
            review["status"] = status
            review["completed_at"] = datetime.now(timezone.utc).isoformat()
            review_id = save_review_to_db(key, review, status, reviews_db)

            target = _event_target_for(key, review)
            if target and succeeded:
                run_id, full_repo, pr_number = target
                record_completed(
                    run_id, full_repo, pr_number,
                    attempt=review.get("attempt", 1),
                    review_id=review_id,
                    score=_review_score(review_id, reviews_db),
                    review_file=review.get("review_file"),
                )

            if review_id and status == "completed":
                _spawn_auto_verdict(key, review_id)

        # Waiting out the backoff before the next attempt. Spawning here rather
        # than sleeping keeps the poll cheap and the lock short.
        if review.get("retry_at") is not None:
            if time.monotonic() >= review["retry_at"]:
                if not _respawn_review(key, review):
                    finalize(False)
            return review

        process = review.get("process")
        if process is None:
            return review
        exit_code = process.poll()
        if exit_code is None:
            return review

        try:
            stdout, stderr = process.communicate(timeout=1)
            if stderr:
                review["error_output"] = stderr.strip()[-2000:]
            if stdout:
                review["stdout"] = stdout.strip()[-500:]
        except subprocess.TimeoutExpired:
            pass
        except Exception as e:
            logger.error(f"Error reading process output for {key}: {e}")

        review["exit_code"] = exit_code
        produced_output = review_produced_output(review.get("review_file"))

        if exit_code != 0:
            error_msg = review.get("error_output", "Unknown error")
            logger.error(f"Review failed: {key} (exit code: {exit_code})\nError: {error_msg}")
            failure_reason = REASON_NONZERO_EXIT
            failure_detail = error_msg[:500]
        elif not produced_output:
            # Exit 0 with nothing on disk: the CLI reported success but wrote no
            # review. Recording this as "completed" would store a 0-score stub
            # that reads like a real verdict, so treat it as a failed attempt.
            logger.error(
                f"Review process for {key} exited 0 without writing "
                f"{review.get('review_file')} — treating as a failed attempt"
            )
            failure_reason = REASON_NO_OUTPUT
            failure_detail = f"exited 0 without writing {review.get('review_file')}"
        else:
            logger.info(f"Review completed successfully: {key}")
            failure_reason = None
            failure_detail = None

        if failure_reason:
            target = _event_target_for(key, review)
            if target:
                run_id, full_repo, pr_number = target
                record_failed(
                    run_id, full_repo, pr_number,
                    attempt=review.get("attempt", 1),
                    max_attempts=review.get("max_attempts"),
                    reason=failure_reason,
                    exit_code=exit_code,
                    detail=failure_detail,
                    review_file=review.get("review_file"),
                )

        if exit_code == 0 and produced_output:
            finalize(True)
        elif not _schedule_review_retry(key, review):
            finalize(False)

        return review


def _schedule_review_retry(key, review):
    """Arm a delayed retry for a failed attempt.

    Returns:
        bool: True if another attempt was armed, False if the limit is reached
        and the caller should record the review as failed.
    """
    max_attempts, retry_delay = get_review_retry_settings()
    attempt = review.get("attempt", 1)

    if attempt >= max_attempts:
        logger.error(f"Review for {key} failed after {attempt} attempt(s) — giving up")
        target = _event_target_for(key, review)
        if target:
            run_id, full_repo, pr_number = target
            record_gave_up(run_id, full_repo, pr_number,
                           attempt=attempt, max_attempts=max_attempts)
        return False

    if not review.get("spawn"):
        logger.error(f"Cannot retry review for {key}: no spawn arguments recorded")
        return False

    review["retry_at"] = time.monotonic() + retry_delay
    review["process"] = None
    logger.warning(
        f"Review attempt {attempt}/{max_attempts} failed for {key} — "
        f"retrying in {retry_delay:g}s"
    )

    target = _event_target_for(key, review)
    if target:
        run_id, full_repo, pr_number = target
        record_retry_scheduled(run_id, full_repo, pr_number,
                               attempt=attempt, max_attempts=max_attempts,
                               delay_seconds=retry_delay)
    return True


def _respawn_review(key, review):
    """Start the next review attempt.

    Returns:
        bool: True if a new process is running, False if the spawn itself
        failed (a missing or unusable CLI, which a further retry cannot fix).
    """
    review["retry_at"] = None
    review["attempt"] = review.get("attempt", 1) + 1

    process, result, _ = start_review_process(**review["spawn"])
    if process is None:
        logger.error(f"Could not start retry attempt {review['attempt']} for {key}: {result}")
        target = _event_target_for(key, review)
        if target:
            run_id, full_repo, pr_number = target
            record_failed(run_id, full_repo, pr_number,
                          attempt=review["attempt"],
                          max_attempts=review.get("max_attempts"),
                          reason=REASON_SPAWN_FAILED,
                          detail=str(result)[:500])
        return False

    review["process"] = process
    review["review_file"] = result
    review["exit_code"] = None
    review["error_output"] = ""
    logger.info(
        f"Started retry attempt {review['attempt']} for {key} (PID {process.pid})"
    )

    target = _event_target_for(key, review)
    if target:
        run_id, full_repo, pr_number = target
        spawn = review.get("spawn") or {}
        record_started(
            run_id, full_repo, pr_number,
            attempt=review["attempt"],
            max_attempts=review.get("max_attempts"),
            reviewer_agent=spawn.get("reviewer_type", "default"),
            is_followup=spawn.get("is_followup", False),
            auto_started=review.get("auto_started", False),
            review_file=result,
            pid=getattr(process, "pid", None),
        )
    return True


def _spawn_auto_verdict(key, review_id):
    """Evaluate auto verdicts for a just-completed review, off the polling thread.

    The verdict path makes several gh subprocess calls, so it must not run while
    reviews_lock is held or it would stall every review poll for seconds. The
    running -> terminal transition happens once per review, so this spawns once;
    AutoVerdictsDB.claim() guards against any other path racing it.
    """
    parts = key.split("/")
    if len(parts) < 3:
        return
    full_repo = f"{parts[0]}/{parts[1]}"
    try:
        pr_number = int(parts[2])
    except ValueError:
        return

    def run():
        try:
            from backend.services.auto_verdict_service import maybe_post_auto_verdict
            maybe_post_auto_verdict(full_repo, pr_number, review_id)
        except Exception as e:
            logger.error(f"Auto verdict evaluation failed for {key}: {e}")

    threading.Thread(target=run, daemon=True).start()


VALID_REVIEWER_TYPES = ("default", "pb", "ed")


def begin_review(owner, repo, pr_number, pr_url, reviews_db,
                 is_followup=False, previous_review_id=None,
                 pr_title=None, pr_author=None, reviewer_type="default",
                 auto_started=False):
    """Start a review and register it in active_reviews.

    Shared by the POST /api/reviews route and the auto follow-up review
    watcher so both paths keep identical semantics (previous-review lookup,
    fallback to a normal review, duplicate-run rejection).

    Returns:
        tuple: (payload dict, status) where status is 201 on success,
        409 if a review is already running for this PR, 500 on spawn failure.
    """
    from backend.extensions import active_reviews, reviews_lock

    key = f"{owner}/{repo}/{pr_number}"

    with reviews_lock:
        if key in active_reviews:
            existing = active_reviews[key]
            if existing["status"] == "running":
                logger.warning(f"Review already in progress for {key}")
                return {"error": "Review already in progress for this PR"}, 409

    previous_review_content = None
    parent_id = None
    if is_followup:
        full_repo = f"{owner}/{repo}"
        prev_review = None

        if previous_review_id:
            candidate = reviews_db.get_review(previous_review_id)
            if candidate and _is_error_stub(candidate.get("content_json")):
                logger.warning(
                    f"Previous review {previous_review_id} for {full_repo}#{pr_number} has no "
                    f"findings (failed review) — looking further back for a usable one"
                )
            else:
                prev_review = candidate

        if prev_review is None:
            prev_review = _find_usable_previous_review(reviews_db, full_repo, pr_number)

        if prev_review:
            previous_review_content = prev_review.get("content_json")
            parent_id = prev_review.get("id")

        if not previous_review_content:
            logger.warning(f"No previous review found for follow-up, proceeding as normal review")
            is_followup = False

    process, result, is_followup = start_review_process(
        pr_url, owner, repo, pr_number,
        is_followup=is_followup,
        previous_review_content=previous_review_content,
        reviewer_type=reviewer_type,
    )

    if process is None:
        logger.error(f"Failed to start review for {key}: {result}")
        return {"error": result}, 500

    # Recorded verbatim so a retry reproduces the same run. is_followup comes
    # from start_review_process, which downgrades it when no previous review
    # was usable — retries must not silently re-promote the review.
    spawn_args = {
        "pr_url": pr_url,
        "owner": owner,
        "repo": repo,
        "pr_number": pr_number,
        "is_followup": is_followup,
        "previous_review_content": previous_review_content,
        "reviewer_type": reviewer_type,
    }

    run_id = new_run_id()
    max_attempts, _ = get_review_retry_settings()

    with reviews_lock:
        active_reviews[key] = {
            "process": process,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "pr_url": pr_url,
            "review_file": result,
            "is_followup": is_followup,
            "parent_review_id": parent_id,
            "pr_title": pr_title,
            "pr_author": pr_author,
            "reviewer_type": reviewer_type,
            "auto_started": auto_started,
            "spawn": spawn_args,
            "attempt": 1,
            "retry_at": None,
            "run_id": run_id,
            "max_attempts": max_attempts
        }

    record_started(
        run_id, f"{owner}/{repo}", pr_number,
        attempt=1,
        max_attempts=max_attempts,
        reviewer_agent=reviewer_type,
        is_followup=is_followup,
        auto_started=auto_started,
        review_file=result,
        pid=getattr(process, "pid", None),
    )

    post_review_started_comment(
        owner, repo, pr_number,
        is_followup=is_followup,
        reviewer_type=reviewer_type,
        auto_started=auto_started,
    )

    return {
        "message": "Review started",
        "key": key,
        "status": "running",
        "review_file": result,
        "is_followup": is_followup
    }, 201


def start_review_process(pr_url, owner, repo, pr_number, is_followup=False, previous_review_content=None, reviewer_type="default"):
    """Start a Claude CLI review process in the background.

    Args:
        previous_review_content: For follow-ups, the JSON string of the previous review's content_json.
        reviewer_type: Which reviewer agent to use. One of:
            - "default": elite-code-reviewer (general code review)
            - "pb": product-brief-reviewer (PB-000 product brief review)
            - "ed": ed-reviewer (ED-000 engineering design review)

    Returns:
        tuple: (process, review_file_path_or_error, is_followup)
    """
    if reviewer_type not in VALID_REVIEWER_TYPES:
        reviewer_type = "default"

    reviews_dir = get_reviews_dir()
    reviews_dir.mkdir(parents=True, exist_ok=True)

    repo_safe = repo.replace("/", "-")
    suffix = "-followup" if is_followup else ""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S") if is_followup else ""
    if is_followup:
        review_file = reviews_dir / f"{owner}-{repo_safe}-pr-{pr_number}{suffix}-{timestamp}.md"
    else:
        review_file = reviews_dir / f"{owner}-{repo_safe}-pr-{pr_number}.md"

    json_file = str(review_file).replace(".md", ".json")

    if reviewer_type == "pb":
        agent_name = "product-brief-reviewer"
    elif reviewer_type == "ed":
        agent_name = "ed-reviewer"
    else:
        agent_name = "elite-code-reviewer"

    if reviewer_type == "pb":
        pb_context = (
            "This PR adds or modifies a product brief (a PB-NNN-*.md file under briefs/). "
            "Identify the brief file(s) touched in the PR diff and review them against the PB-000 template "
            "and the rules embedded in the product-brief-reviewer agent. Quote evidence verbatim and keep "
            "all fixes in user-observable, product-level language. "
        )
    elif reviewer_type == "ed":
        pb_context = (
            "This PR adds or modifies an engineering design (an ED-NNN-*.md file under docs/designs/). "
            "Identify the ED file(s) touched in the PR diff and review them against the ED-000 template "
            "and the rules embedded in the ed-reviewer agent. Apply both lenses: SDLC conformance "
            "(SPEC-AUTH-*, SPEC-REVIEW-*, SAFE-*) and the code-review lens for technical soundness. "
            "Quote evidence verbatim from the ED and cite rule IDs where they apply. "
        )
    else:
        pb_context = ""

    if is_followup and previous_review_content:
        # Convert raw JSON to readable markdown for the prompt
        previous_review_markdown = previous_review_content
        try:
            parsed_prev = json.loads(previous_review_content)
            previous_review_markdown = json_to_markdown(parsed_prev)
        except (json.JSONDecodeError, TypeError, Exception):
            pass  # Fall back to raw string if conversion fails

        prompt = (
            f"Review PR #{pr_number} at {pr_url}. "
            f"{pb_context}"
            f"This is a FOLLOW-UP review. Previous review:\n\n"
            f"---PREVIOUS REVIEW---\n{previous_review_markdown[:8000]}\n---END PREVIOUS REVIEW---\n\n"
            f"Focus on: changes since last review, whether previous issues were addressed. "
            f"Include a 'followup' section with a 'resolution_status' array tracking each previous issue. "
            f"Each entry MUST be an object with exactly these fields: "
            f'"issue" (string — the human-readable title of the previous issue, copy it verbatim from the previous review), '
            f'"status" (one of: resolved, partially_addressed, not_addressed, wont_fix), '
            f'"notes" (string — brief explanation of what changed or why). '
            f'Do NOT use "title", "details", or "id" as alternative field names. '
            f"Use the {agent_name} agent. "
            f"{_FOREGROUND_INSTRUCTIONS}"
            f"Write the review to {review_file}. "
            f"ALSO write a structured JSON version to {json_file} following this schema: "
            f"{_SCHEMA_INSTRUCTIONS} "
            f"IMPORTANT: Include a final score from 0-10 in both formats."
        )
    else:
        prompt = (
            f"Review PR #{pr_number} at {pr_url}. "
            f"{pb_context}"
            f"Use the {agent_name} agent. "
            f"{_FOREGROUND_INSTRUCTIONS}"
            f"Write the review to {review_file}. "
            f"ALSO write a structured JSON version to {json_file} following this schema: "
            f"{_SCHEMA_INSTRUCTIONS} "
            f"IMPORTANT: Include a final score from 0-10 in both formats."
        )

    # --dangerously-skip-permissions is required for non-interactive subprocess execution.
    # This app is single-user/local-only; the flag does not expose a network attack surface.
    # allowedTools is restricted to read-only git/gh commands + file tools.
    cmd = [
        "claude",
        "-p", prompt,
        # Pin the model so reviews stay reproducible if the CLI default changes.
        "--model", "claude-opus-5",
        "--allowedTools", (
            "Bash(git status*),Bash(git log*),Bash(git show*),"
            "Bash(git diff*),Bash(git blame*),Bash(git branch*),"
            "Bash(gh pr view*),Bash(gh pr diff*),Bash(gh pr checks*),"
            "Bash(gh api*),Read,Glob,Grep,Write,Task"
        ),
        "--dangerously-skip-permissions"
    ]

    review_type = "follow-up " if is_followup else ""
    logger.info(f"Starting {review_type}review for PR #{pr_number} ({owner}/{repo}) using {agent_name}")
    logger.debug(f"Review command: {' '.join(cmd)}")

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        logger.info(f"Review process started with PID {process.pid} for {owner}/{repo}/#{pr_number}")
        return process, str(review_file), is_followup
    except FileNotFoundError:
        error_msg = "Claude CLI not found. Please ensure 'claude' is installed and in PATH."
        logger.error(f"Failed to start review: {error_msg}")
        return None, error_msg, is_followup
    except Exception as e:
        logger.error(f"Failed to start review process: {e}")
        return None, str(e), is_followup
