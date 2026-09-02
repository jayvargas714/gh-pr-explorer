"""Claude CLI subprocess management: start, cancel, poll, save to DB."""

import json
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.config import (
    get_review_resource_limits,
    get_review_retry_settings,
    get_review_timeout_seconds,
    get_review_workspace_config,
    get_reviews_dir,
)
from backend.services.github_service import fetch_pr_head_sha, fetch_pr_state
from backend.services.pr_status_comments import (
    delete_status_comments,
    post_review_gave_up_comment,
    post_review_retry_scheduled_comment,
    post_review_started_comment,
)
from backend.services.review_event_log import (
    new_run_id,
    record_cancelled,
    record_completed,
    record_failed,
    record_gave_up,
    record_retry_scheduled,
    record_started,
    REASON_CANCELLED,
    REASON_NO_OUTPUT,
    REASON_NONZERO_EXIT,
    REASON_SPAWN_FAILED,
    REASON_TIMEOUT,
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


def _workspace_instructions(owner, repo, pr_number, head_sha):
    """The mandatory code-access recipe embedded in every review prompt.

    Reviewers used to improvise their own snapshot of the repo under review;
    one improvisation — a blobless partial clone from a local checkout — spawned
    ~1,700 git processes and OOM'd the machine (Aug 31 incident). This pins the
    one proven-safe pattern: a throwaway shallow fetch from GitHub over HTTPS,
    in a per-PR workspace the app cleans up afterwards.
    """
    ws = _workspace_dir(owner, repo, pr_number)
    fetch_cfg = get_review_workspace_config()
    clone_url = f"https://github.com/{owner}/{repo}.git"
    if head_sha:
        head = head_sha
        resolve = ""
    else:
        head = "<head-sha>"
        resolve = (
            "First resolve the PR's head SHA with `gh pr view --json headRefOid` "
            "and substitute it for <head-sha> below. "
        )
    return (
        f"CODE ACCESS (mandatory): examine the PR's code ONLY in the throwaway "
        f"workspace {ws}, created exactly like this: {resolve}"
        f"`rm -rf {ws} && mkdir -p {ws} && cd {ws} && git init -q repo && cd repo && "
        f"git remote add origin {clone_url} && "
        f"timeout {fetch_cfg['fetch_timeout_seconds']} git fetch -q "
        f"--depth={fetch_cfg['fetch_depth']} --no-tags origin {head} && "
        f"git checkout -q -f {head}`. "
        f"If you need other commits (the base branch head, a previously reviewed "
        f"SHA), add them to that same fetch command. "
        f"HARD LIMITS — a violation of these previously took down this machine: "
        f"run git ONLY inside {ws}; NEVER run git clone or git fetch against a "
        f"local filesystem path or any existing checkout on this machine — fetch "
        f"only from {clone_url}; NEVER use --filter, --reference, --shared, "
        f"--mirror, or --recurse-submodules; NEVER run a git command in the "
        f"background — foreground only, wrapped in `timeout` as shown; do not "
        f"create worktrees or branches in any repo outside {ws}. "
        f"When the review files are written, delete the workspace: rm -rf {ws}. "
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


def _workspace_dir(owner, repo, pr_number):
    """The throwaway git workspace for a PR's review runs.

    Deterministic per PR (one review per PR runs at a time, so no collisions):
    the prompt, the terminal-state cleanup, and the sweeper all derive the same
    path without plumbing it through spawn arguments.
    """
    root = get_review_workspace_config()["root"]
    return root / f"{owner}-{repo.replace('/', '-')}-pr-{pr_number}"


def _cleanup_workspace_for_key(key):
    """Best-effort removal of a finished review's workspace."""
    parts = key.split("/")
    if len(parts) != 3:
        return
    try:
        ws = _workspace_dir(parts[0], parts[1], parts[2])
        if ws.is_dir():
            shutil.rmtree(ws, ignore_errors=True)
            logger.info(f"Removed review workspace {ws}")
    except Exception:
        logger.warning(f"Could not remove review workspace for {key}")


def sweep_stale_workspaces():
    """Delete review workspaces whose last activity predates the sweep window.

    Terminal-state cleanup already removes a run's workspace; this catches dirs
    left behind by a crash or kill -9. Never raises.
    """
    try:
        ws_config = get_review_workspace_config()
        root = ws_config["root"]
        if not root.is_dir():
            return
        cutoff = time.time() - ws_config["sweep_after_hours"] * 3600

        from backend.extensions import active_reviews, reviews_lock
        with reviews_lock:
            running_keys = [k for k, e in active_reviews.items()
                            if e.get("status") == "running"]
        in_use = set()
        for k in running_keys:
            parts = k.split("/")
            if len(parts) == 3:
                in_use.add(f"{parts[0]}-{parts[1]}-pr-{parts[2]}")

        for child in root.iterdir():
            if not child.is_dir() or child.name in in_use:
                continue
            try:
                if child.stat().st_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True)
                    logger.info(f"Swept stale review workspace {child}")
            except OSError:
                continue
    except Exception:
        logger.exception("Review workspace sweep failed")


def _kill_process_group(process):
    """SIGTERM, then SIGKILL, the review's whole process group.

    Reviews spawn with start_new_session=True, so the CLI leads its own group
    and every descendant (git included) dies with it. The Aug 31 OOM storm
    survived every cancel precisely because only the CLI PID was signalled —
    its orphaned git children ground on for ten more hours.

    Raises nothing for an already-dead group; propagates unexpected errors so
    callers can report a process that would not die.
    """
    try:
        pgid = os.getpgid(process.pid)
    except (ProcessLookupError, PermissionError, OSError):
        pgid = None

    def _signal(sig):
        if pgid is not None and pgid == process.pid:
            os.killpg(pgid, sig)
        elif sig == signal.SIGTERM:
            process.terminate()
        else:
            process.kill()

    try:
        _signal(signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _signal(signal.SIGKILL)
            process.wait(timeout=2)
    except ProcessLookupError:
        pass


def count_running_reviews():
    """Number of reviews currently running, auto-started and manual alike."""
    from backend.extensions import active_reviews, reviews_lock

    with reviews_lock:
        return sum(1 for entry in active_reviews.values()
                   if entry.get("status") == "running")


# Cached result of the one-time systemd-run --user probe. Reset only by a
# process restart, which is exactly when the environment could have changed.
_SYSTEMD_RUN_STATE = {"checked": False, "available": False}


def _resource_limit_prefix():
    """systemd-run prefix that boxes a review into a resource-capped scope.

    MemoryMax kills a runaway review instead of the machine; TasksMax is the
    hard stop against process fan-out (the Aug 31 incident was ~1,700 git
    processes from a single run). Returns [] when limits are disabled or
    systemd-run --user is unusable here — the review still runs, uncapped.
    """
    memory_max, tasks_max = get_review_resource_limits()
    props = []
    if memory_max:
        props += ["-p", f"MemoryMax={memory_max}", "-p", "MemorySwapMax=0"]
    if tasks_max:
        props += ["-p", f"TasksMax={tasks_max}"]
    if not props:
        return []

    if not _SYSTEMD_RUN_STATE["checked"]:
        _SYSTEMD_RUN_STATE["checked"] = True
        try:
            probe = subprocess.run(
                ["systemd-run", "--user", "--scope", "-q", "true"],
                capture_output=True, timeout=10,
            )
            _SYSTEMD_RUN_STATE["available"] = probe.returncode == 0
        except Exception:
            _SYSTEMD_RUN_STATE["available"] = False
        if not _SYSTEMD_RUN_STATE["available"]:
            logger.warning(
                "systemd-run --user is not usable here — review resource limits "
                "(MemoryMax/TasksMax) will NOT be enforced"
            )

    if not _SYSTEMD_RUN_STATE["available"]:
        return []
    return ["systemd-run", "--user", "--scope", "-q"] + props


def _run_log_path(review_file):
    """Where a run's CLI stdout/stderr goes (all attempts append to one file)."""
    if not review_file:
        return None
    review_path = Path(review_file)
    return review_path.parent / "logs" / (review_path.stem + ".log")


def _read_log_tail(review_file, max_bytes=2000):
    """Last chunk of a run's CLI output, for error reporting. Never raises."""
    log_path = _run_log_path(review_file)
    if not log_path:
        return ""
    try:
        with open(log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            return f.read().decode("utf-8", errors="replace").strip()
    except OSError:
        return ""


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
    # Status comments make gh calls, which must not run under reviews_lock
    # (they would stall every review poll for seconds) — the locked body queues
    # them as (fn, args, kwargs) and they post here after the lock is released.
    pending_comments = []
    try:
        return _check_review_status_locked(
            key, active_reviews, reviews_lock, reviews_db, pending_comments
        )
    finally:
        for fn, args, kwargs in pending_comments:
            try:
                fn(*args, **kwargs)
            except Exception as e:
                logger.warning(f"Status comment for {key} failed: {e}")


def _check_review_status_locked(key, active_reviews, reviews_lock, reviews_db,
                                pending_comments):
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
            _cleanup_workspace_for_key(key)
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
                if not _respawn_review(key, review, pending_comments):
                    finalize(False)
            return review

        process = review.get("process")
        if process is None:
            return review
        exit_code = process.poll()
        if exit_code is None:
            deadline = review.get("deadline")
            if not deadline or time.monotonic() < deadline:
                return review
            # The attempt ran past the wall-clock limit. Kill the whole process
            # group — a wedged run's git children must die with the CLI — and
            # hand the failure to the normal retry policy.
            logger.error(
                f"Review for {key} exceeded its time limit — killing process "
                f"group (PID {process.pid})"
            )
            try:
                _kill_process_group(process)
            except Exception as e:
                logger.error(f"Could not kill timed-out review for {key}: {e}")
                return review
            review["exit_code"] = None
            review["last_failure"] = (
                REASON_TIMEOUT,
                f"killed after exceeding {get_review_timeout_seconds():g}s",
            )
            target = _event_target_for(key, review)
            if target:
                run_id, full_repo, pr_number = target
                record_failed(
                    run_id, full_repo, pr_number,
                    attempt=review.get("attempt", 1),
                    max_attempts=review.get("max_attempts"),
                    reason=REASON_TIMEOUT,
                    detail=f"killed after exceeding {get_review_timeout_seconds():g}s",
                    review_file=review.get("review_file"),
                )
            if not _schedule_review_retry(key, review, pending_comments):
                finalize(False)
            return review

        review["exit_code"] = exit_code
        produced_output = review_produced_output(review.get("review_file"))

        if exit_code != 0:
            error_msg = (_read_log_tail(review.get("review_file"))
                         or review.get("error_output") or "Unknown error")
            review["error_output"] = error_msg
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
            review["last_failure"] = (failure_reason, failure_detail)
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
        elif not _schedule_review_retry(key, review, pending_comments):
            finalize(False)

        return review


def _comment_target_for(key):
    """(owner, repo, pr_number) from an active_reviews key, or None."""
    parts = key.split("/")
    if len(parts) < 3:
        return None
    try:
        return parts[0], parts[1], int(parts[2])
    except ValueError:
        return None


def _schedule_review_retry(key, review, pending_comments):
    """Arm a delayed retry for a failed attempt.

    Returns:
        bool: True if another attempt was armed, False if the limit is reached
        and the caller should record the review as failed.
    """
    max_attempts, retry_delay = get_review_retry_settings()
    attempt = review.get("attempt", 1)
    failure_reason, failure_detail = review.get("last_failure") or ("unknown", None)
    target = _comment_target_for(key)

    if attempt >= max_attempts:
        logger.error(f"Review for {key} failed after {attempt} attempt(s) — giving up")
        event_target = _event_target_for(key, review)
        if event_target:
            run_id, full_repo, pr_number = event_target
            record_gave_up(run_id, full_repo, pr_number,
                           attempt=attempt, max_attempts=max_attempts)
        if target:
            pending_comments.append((post_review_gave_up_comment, target, {
                "reviewer_type": review.get("reviewer_type", "default"),
                "attempt": attempt, "max_attempts": max_attempts,
                "reason": failure_reason, "detail": failure_detail,
            }))
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

    event_target = _event_target_for(key, review)
    if event_target:
        run_id, full_repo, pr_number = event_target
        record_retry_scheduled(run_id, full_repo, pr_number,
                               attempt=attempt, max_attempts=max_attempts,
                               delay_seconds=retry_delay)
    if target:
        pending_comments.append((post_review_retry_scheduled_comment, target, {
            "reviewer_type": review.get("reviewer_type", "default"),
            "attempt": attempt, "max_attempts": max_attempts,
            "delay_seconds": retry_delay,
            "reason": failure_reason, "detail": failure_detail,
        }))
    return True


def _respawn_review(key, review, pending_comments):
    """Start the next review attempt.

    Returns:
        bool: True if a new process is running, False if the spawn itself
        failed (a missing or unusable CLI, which a further retry cannot fix).
    """
    review["retry_at"] = None
    review["attempt"] = review.get("attempt", 1) + 1
    target = _comment_target_for(key)

    process, result, _ = start_review_process(**review["spawn"])
    if process is None:
        logger.error(f"Could not start retry attempt {review['attempt']} for {key}: {result}")
        event_target = _event_target_for(key, review)
        if event_target:
            run_id, full_repo, pr_number = event_target
            record_failed(run_id, full_repo, pr_number,
                          attempt=review["attempt"],
                          max_attempts=review.get("max_attempts"),
                          reason=REASON_SPAWN_FAILED,
                          detail=str(result)[:500])
        if target:
            pending_comments.append((post_review_gave_up_comment, target, {
                "reviewer_type": review.get("reviewer_type", "default"),
                "attempt": review["attempt"],
                "max_attempts": review.get("max_attempts"),
                "reason": REASON_SPAWN_FAILED, "detail": str(result)[:500],
                "spawn_failed": True,
            }))
        return False

    review["process"] = process
    review["review_file"] = result
    review["exit_code"] = None
    review["error_output"] = ""
    timeout = get_review_timeout_seconds()
    review["deadline"] = (time.monotonic() + timeout) if timeout else None
    logger.info(
        f"Started retry attempt {review['attempt']} for {key} (PID {process.pid})"
    )

    event_target = _event_target_for(key, review)
    spawn = review.get("spawn") or {}
    if event_target:
        run_id, full_repo, pr_number = event_target
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
    if target:
        pending_comments.append((post_review_started_comment, target, {
            "is_followup": spawn.get("is_followup", False),
            "reviewer_type": spawn.get("reviewer_type", "default"),
            "auto_started": review.get("auto_started", False),
            "attempt": review["attempt"],
            "max_attempts": review.get("max_attempts"),
            "head_sha": spawn.get("head_sha"),
        }))
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


# Fallback if the registry is unreadable; the live list comes from valid_reviewer_types().
VALID_REVIEWER_TYPES = ("default", "pb", "ed")


def cancel_active_review(key, *, reason=REASON_CANCELLED, detail=None,
                         require_running=False):
    """Terminate a review's subprocess and remove it from active_reviews.

    Shared by the DELETE route (user cancel) and the stale-review watcher
    (automatic cancel when new commits invalidate a running attempt).

    Args:
        require_running: only cancel entries whose status is "running" — the
            watcher must not delete a finished entry it raced.

    Returns:
        str: "cancelled" on success, "not_found" if no entry exists,
        "not_running" if require_running and the entry already finished,
        "error" if the process would not terminate (entry kept).
    """
    from backend.extensions import active_reviews, reviews_lock

    with reviews_lock:
        if key not in active_reviews:
            return "not_found"
        review = active_reviews[key]
        if require_running and review.get("status") != "running":
            return "not_running"

        process = review.get("process")
        if process and review.get("status") == "running":
            try:
                logger.info(f"Terminating review process group (PID {process.pid}) for {key}")
                _kill_process_group(process)
                review["status"] = "cancelled"
            except Exception as e:
                logger.error(f"Failed to terminate review process for {key}: {e}")
                return "error"

        if review.get("run_id"):
            owner, repo, pr_number = key.split("/")
            record_cancelled(
                review["run_id"], f"{owner}/{repo}", int(pr_number),
                attempt=review.get("attempt", 1),
                reason=reason,
                detail=detail,
            )

        del active_reviews[key]

    _cleanup_workspace_for_key(key)
    if reason == REASON_CANCELLED:
        # A deliberate user cancel is silent, but the "review in progress"
        # status comment must not outlive the review it announces.
        target = _comment_target_for(key)
        if target:
            delete_status_comments(*target)
    logger.info(f"Review cancelled and removed: {key}")
    return "cancelled"


def valid_reviewer_types():
    """Reviewer keys from the registry (falls back to the builtin tuple)."""
    try:
        from backend.database import get_reviewers_db
        return tuple(r["key"] for r in get_reviewers_db().list_reviewers())
    except Exception:
        logger.exception("Failed to read reviewer registry; using builtin reviewer types")
        return VALID_REVIEWER_TYPES


def _resolve_reviewer(reviewer_type):
    """Resolve a reviewer key to its registry row, falling back to 'default'."""
    try:
        from backend.database import get_reviewers_db
        registry = get_reviewers_db()
        row = registry.get_by_key(reviewer_type)
        if row is None:
            logger.warning(f"Unknown reviewer type '{reviewer_type}', falling back to default")
            row = registry.get_by_key("default")
        if row is not None:
            return row
    except Exception:
        logger.exception("Failed to resolve reviewer from registry; using builtin default")
    return {"key": "default", "agent_name": "elite-code-reviewer", "prompt_context": None}


def begin_review(owner, repo, pr_number, pr_url, reviews_db,
                 is_followup=False, previous_review_id=None,
                 pr_title=None, pr_author=None, reviewer_type="default",
                 auto_started=False, bypass_budget=False, comment_note=None):
    """Start a review and register it in active_reviews.

    Shared by the POST /api/reviews route and the auto follow-up review
    watcher so both paths keep identical semantics (previous-review lookup,
    fallback to a normal review, duplicate-run rejection).

    Every auto-started spawn is gated by the maxConcurrentAutoReviews budget
    here, whichever path asked for it — before this gate only the dispatch
    worker checked, and the watchers piled reviews past the limit (8 running
    with a budget of 7 the night of the Aug 31 OOM). Manual reviews are always
    admitted but count toward the running total. bypass_budget is for the
    stale-review watcher's cancel-and-replace, which never raises concurrency.

    Returns:
        tuple: (payload dict, status) where status is 201 on success,
        409 if a review is already running for this PR, 429 if the concurrency
        budget is full (payload carries "over_budget": True), 500 on spawn
        failure.
    """
    from backend.extensions import active_reviews, reviews_lock

    key = f"{owner}/{repo}/{pr_number}"

    with reviews_lock:
        if key in active_reviews:
            existing = active_reviews[key]
            if existing["status"] == "running":
                logger.warning(f"Review already in progress for {key}")
                return {"error": "Review already in progress for this PR"}, 409

    if auto_started and not bypass_budget:
        from backend.services.automation_config import get_config as get_automation_config
        limit = get_automation_config()["maxConcurrentAutoReviews"]
        running = count_running_reviews()
        if running >= limit:
            logger.info(
                f"Auto review for {key} deferred: {running} review(s) running "
                f">= budget {limit}"
            )
            return {
                "error": f"Concurrency budget full ({running}/{limit} reviews running)",
                "over_budget": True,
            }, 429

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

    # Snapshot the head SHA before spawning: the stale-review watcher compares
    # this baseline against the live head to stop and restart a review that new
    # commits invalidated. Fetching before the spawn keeps the baseline
    # conservative — a commit racing the spawn triggers a restart rather than
    # slipping through. No SHA means no baseline: that run isn't stale-watched.
    head_sha_at_start = fetch_pr_head_sha(owner, repo, pr_number) or None

    process, result, is_followup = start_review_process(
        pr_url, owner, repo, pr_number,
        is_followup=is_followup,
        previous_review_content=previous_review_content,
        reviewer_type=reviewer_type,
        head_sha=head_sha_at_start,
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
        "head_sha": head_sha_at_start,
    }

    run_id = new_run_id()
    max_attempts, _ = get_review_retry_settings()
    timeout = get_review_timeout_seconds()

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
            "head_sha_at_start": head_sha_at_start,
            "spawn": spawn_args,
            "attempt": 1,
            "retry_at": None,
            "run_id": run_id,
            "max_attempts": max_attempts,
            "deadline": (time.monotonic() + timeout) if timeout else None,
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
        attempt=1,
        max_attempts=max_attempts,
        head_sha=head_sha_at_start,
        note=comment_note,
    )

    return {
        "message": "Review started",
        "key": key,
        "status": "running",
        "review_file": result,
        "is_followup": is_followup
    }, 201


def start_review_process(pr_url, owner, repo, pr_number, is_followup=False, previous_review_content=None, reviewer_type="default", head_sha=None):
    """Start a Claude CLI review process in the background.

    Args:
        previous_review_content: For follow-ups, the JSON string of the previous review's content_json.
        reviewer_type: Reviewer registry key (see backend/database/reviewers.py).
            Unknown keys fall back to "default".
        head_sha: The PR head SHA the review should examine, when the caller
            knows it; baked into the workspace recipe so the reviewer need not
            resolve it.

    Returns:
        tuple: (process, review_file_path_or_error, is_followup)
    """
    reviewer = _resolve_reviewer(reviewer_type)

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

    agent_name = reviewer["agent_name"]
    pb_context = reviewer["prompt_context"] or ""
    workspace_instructions = _workspace_instructions(owner, repo, pr_number, head_sha)

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
            f"{workspace_instructions}"
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
            f"{workspace_instructions}"
            f"Write the review to {review_file}. "
            f"ALSO write a structured JSON version to {json_file} following this schema: "
            f"{_SCHEMA_INSTRUCTIONS} "
            f"IMPORTANT: Include a final score from 0-10 in both formats."
        )

    # --dangerously-skip-permissions is required for non-interactive subprocess
    # execution — which also means the allowedTools list below is advisory, not
    # enforced. The enforced guardrails are the systemd scope's MemoryMax/
    # TasksMax, the wall-clock timeout, and process-group kill semantics
    # (start_new_session) so no descendant outlives a cancel.
    cmd = _resource_limit_prefix() + [
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

    # A stale workspace from a crashed earlier run must not leak into this one.
    try:
        workspace = _workspace_dir(owner, repo, pr_number)
        if workspace.is_dir():
            shutil.rmtree(workspace, ignore_errors=True)
    except Exception:
        logger.warning(f"Could not pre-clean review workspace for {owner}/{repo}#{pr_number}")

    # CLI output goes to a per-run log file, not a pipe: nothing drains a pipe
    # while the run is in flight, so a chatty CLI would fill the 64KB buffer and
    # wedge forever — permanently "running", never retried, never timed out.
    log_handle = None
    try:
        log_path = _run_log_path(review_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(log_path, "a")
    except OSError as e:
        logger.warning(f"Could not open review log file for {owner}/{repo}#{pr_number}: {e}")

    try:
        process = subprocess.Popen(
            cmd,
            stdout=log_handle if log_handle else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if log_handle else subprocess.DEVNULL,
            text=True,
            # Own process group: cancels and timeouts kill the CLI *and* every
            # descendant. The Aug 31 git storm outlived its review because the
            # CLI shared our group and only its own PID was ever signalled.
            start_new_session=True,
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
    finally:
        # The child holds its own copy of the fd; keeping ours open would leak
        # one fd per review for the life of the app.
        if log_handle:
            log_handle.close()
