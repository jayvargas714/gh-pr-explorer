"""Claude CLI subprocess management for PB↔ED audits: start, cancel, poll, save."""

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from backend.config import get_reviews_dir
from backend.services.audit_schema import (
    AUDIT_SCHEMA_VERSION,
    validate_audit_json,
    compute_audit_tallies,
)

logger = logging.getLogger(__name__)

# Compact schema instructions embedded in the audit prompt.
_AUDIT_SCHEMA_INSTRUCTIONS = (
    "The JSON must have these top-level keys: "
    '"schema_version" (set to "1.0.0"), "format" (set to "audit"), '
    '"audit_type" (set to "pb_ed"), '
    '"metadata" (object with pr_number, repository, pr_url, pr_title, head_ref, base_ref, '
    "parent_pb {id, title, status}, eds (array of {id, title}), auditor, date, scope), "
    '"executive_summary" (markdown string), '
    '"audits" (array of {key, name, verdict, tally, findings}), '
    '"verified_clean" (markdown), "supplementary_notes" (markdown), '
    '"action_map" (array of {priority, finding_ids, nature}). '
    "Each finding MUST have: id (e.g. 'CE-1'), severity (uppercase token such as "
    "CONTRADICTION, SCOPE-VIOLATION, INCONSISTENCY, UN-ANCHORED, UNDER-COVERAGE, INFO), "
    "summary (one-line), and optionally blocking (boolean), rule_id, rule_authority, "
    "concept, lens, detail, recommendation, and locations (array of "
    "{file, line, ref, quote}). For locations, file MUST be a repo-relative path and "
    "line an integer so the finding can be posted as an inline PR comment; ref is the "
    "human display reference like 'ED-010 §10:389'. "
)


def save_audit_to_db(key, audit, status, audits_db):
    """Save a completed/failed audit to the database (reads the .json output file)."""
    try:
        parts = key.split("/")
        if len(parts) < 3:
            return
        owner, repo, pr_number = parts[0], parts[1], int(parts[2])
        full_repo = f"{owner}/{repo}"

        audit_json_data = None
        audit_file = audit.get("audit_file")

        if status == "completed" and audit_file:
            json_path = Path(audit_file).with_suffix(".json")
            if json_path.exists():
                try:
                    parsed = json.loads(json_path.read_text(encoding="utf-8"))
                    valid, errs = validate_audit_json(parsed)
                    if valid:
                        audit_json_data = parsed
                        logger.info(f"Loaded validated audit JSON from {json_path}")
                    else:
                        logger.warning(f"Audit JSON at {json_path} failed validation: {errs[:3]}")
                        audit_json_data = parsed  # keep it; still renderable
                except Exception as e:
                    logger.warning(f"Could not read/parse audit JSON {json_path}: {e}")

        if audit_json_data is None:
            audit_json_data = {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "format": "audit",
                "audit_type": "pb_ed",
                "error": True,
                "metadata": {"pr_number": pr_number, "repository": full_repo},
                "audits": [],
            }

        tallies = compute_audit_tallies(audit_json_data)
        content_json_str = json.dumps(audit_json_data, ensure_ascii=False)

        meta = audit_json_data.get("metadata", {})
        pr_title = audit.get("pr_title") or meta.get("pr_title") or f"PR #{pr_number} Audit"
        pr_author = audit.get("pr_author")
        pr_url = audit.get("pr_url") or meta.get("pr_url", "")
        head_ref = audit.get("head_ref") or meta.get("head_ref")
        base_ref = audit.get("base_ref") or meta.get("base_ref")

        audits_db.add_audit(
            pr_number=pr_number,
            repo=full_repo,
            pr_title=pr_title,
            pr_author=pr_author,
            pr_url=pr_url,
            head_ref=head_ref,
            base_ref=base_ref,
            status=status,
            content_json=content_json_str,
            finding_count=tallies["finding_count"],
            blocking_count=tallies["blocking_count"],
            audit_file_path=audit_file,
        )
        logger.info(f"Saved audit to database for {key}")
    except Exception as e:
        logger.error(f"Failed to save audit to database for {key}: {e}")


def check_audit_status(key, active_audits, audits_lock, audits_db):
    """Poll the subprocess for a running audit and persist on completion."""
    with audits_lock:
        if key not in active_audits:
            return None
        audit = active_audits[key]
        process = audit.get("process")
        if process and audit["status"] == "running":
            exit_code = process.poll()
            if exit_code is not None:
                try:
                    stdout, stderr = process.communicate(timeout=1)
                    if stderr:
                        audit["error_output"] = stderr.strip()[-2000:]
                except subprocess.TimeoutExpired:
                    pass
                except Exception as e:
                    logger.error(f"Error reading audit process output for {key}: {e}")

                status = "completed" if exit_code == 0 else "failed"
                audit["status"] = status
                audit["exit_code"] = exit_code
                audit["completed_at"] = datetime.now(timezone.utc).isoformat()
                if exit_code == 0:
                    logger.info(f"Audit completed successfully: {key}")
                else:
                    logger.error(f"Audit failed: {key} (exit {exit_code})")
                save_audit_to_db(key, audit, status, audits_db)
        return audit


def start_audit_process(pr_url, owner, repo, pr_number):
    """Start a Claude CLI audit process (invokes the /pb-ed-audit skill) in the background.

    Returns: (process, audit_file_path_or_error)
    """
    reviews_dir = get_reviews_dir()
    reviews_dir.mkdir(parents=True, exist_ok=True)

    repo_safe = repo.replace("/", "-")
    audit_file = reviews_dir / f"{owner}-{repo_safe}-pr-{pr_number}-audit.md"
    json_file = str(audit_file.with_suffix(".json"))

    prompt = (
        f"Run a PB↔ED audit on PR #{pr_number} at {pr_url}. "
        f"Use the /pb-ed-audit skill to audit the Engineering Design (ED) documents touched "
        f"in this PR against their parent Product Brief (PB) for parity, and against each "
        f"other for cross-ED consistency. "
        f"Write the human-readable audit report to {audit_file}. "
        f"ALSO write a structured JSON version to {json_file} following this schema: "
        f"{_AUDIT_SCHEMA_INSTRUCTIONS}"
    )

    cmd = [
        "claude",
        "-p", prompt,
        # Skill required: the /pb-ed-audit skill invokes sub-skills/subagents at runtime
        "--allowedTools", (
            "Bash(git status*),Bash(git log*),Bash(git show*),"
            "Bash(git diff*),Bash(git blame*),Bash(git branch*),"
            "Bash(gh pr view*),Bash(gh pr diff*),Bash(gh pr checks*),"
            "Bash(gh api*),Read,Glob,Grep,Write,Task,Skill"
        ),
        "--dangerously-skip-permissions",
    ]

    logger.info(f"Starting PB↔ED audit for PR #{pr_number} ({owner}/{repo})")
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        logger.info(f"Audit process started with PID {process.pid} for {owner}/{repo}/#{pr_number}")
        return process, str(audit_file)
    except FileNotFoundError:
        msg = "Claude CLI not found. Please ensure 'claude' is installed and in PATH."
        logger.error(f"Failed to start audit: {msg}")
        return None, msg
    except Exception as e:
        logger.error(f"Failed to start audit process: {e}")
        return None, str(e)
