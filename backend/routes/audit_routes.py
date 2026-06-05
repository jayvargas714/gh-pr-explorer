"""Audit routes: start, cancel, status, list active, history, detail, check, post-inline."""

import json
import subprocess
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from backend.extensions import logger, active_audits, audits_lock
from backend.database import get_audits_db
from backend.services.audit_service import (
    start_audit_process,
    check_audit_status,
)
from backend.services.audit_schema import audit_json_to_markdown
from backend.services.verdict_service import post_verdict
from backend.routes import error_response

audit_bp = Blueprint("audit", __name__)


def _audit_row_to_summary(row):
    return {
        "id": row["id"],
        "pr_number": row["pr_number"],
        "repo": row["repo"],
        "pr_title": row.get("pr_title"),
        "pr_author": row.get("pr_author"),
        "pr_url": row.get("pr_url"),
        "audit_timestamp": row.get("audit_timestamp"),
        "status": row.get("status"),
        "finding_count": row.get("finding_count", 0),
        "blocking_count": row.get("blocking_count", 0),
        "inline_comments_posted": bool(row.get("inline_comments_posted")),
    }


@audit_bp.route("/api/audits", methods=["GET"])
def get_audits():
    """Active/recent audits with refreshed statuses (drives the spinner)."""
    audits_db = get_audits_db()
    out = []
    with audits_lock:
        keys = list(active_audits.keys())
    for key in keys:
        check_audit_status(key, active_audits, audits_lock, audits_db)
        with audits_lock:
            audit = active_audits.get(key)
            if audit is None:
                continue
            parts = key.split("/")
            out.append({
                "key": key,
                "owner": parts[0] if len(parts) >= 1 else "",
                "repo": parts[1] if len(parts) >= 2 else "",
                "pr_number": int(parts[2]) if len(parts) >= 3 else 0,
                "status": audit["status"],
                "started_at": audit.get("started_at", ""),
                "completed_at": audit.get("completed_at", ""),
                "pr_url": audit.get("pr_url", ""),
                "audit_file": audit.get("audit_file", ""),
                "exit_code": audit.get("exit_code"),
                "error_output": audit.get("error_output", ""),
            })
    return jsonify({"audits": out})


@audit_bp.route("/api/audits", methods=["POST"])
def start_audit():
    """Start a PB↔ED audit for a PR."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        for field in ("number", "url", "owner", "repo"):
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        pr_number = data["number"]
        owner, repo = data["owner"], data["repo"]
        key = f"{owner}/{repo}/{pr_number}"
        logger.info(f"Received audit request for {key}")

        with audits_lock:
            existing = active_audits.get(key)
            if existing and existing["status"] == "running":
                logger.warning(f"Audit already in progress for {key}")
                return jsonify({"error": "Audit already in progress for this PR"}), 409

        process, result = start_audit_process(data["url"], owner, repo, pr_number)
        if process is None:
            return jsonify({"error": result}), 500

        with audits_lock:
            active_audits[key] = {
                "process": process,
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "pr_url": data["url"],
                "audit_file": result,
                "pr_title": data.get("title"),
                "pr_author": data.get("author"),
                "head_ref": data.get("head_ref"),
                "base_ref": data.get("base_ref"),
            }
        return jsonify({
            "message": "Audit started", "key": key, "status": "running",
            "audit_file": result,
        }), 201
    except Exception as e:
        return error_response("Internal server error", 500, f"Error starting audit: {e}")


@audit_bp.route("/api/audits/<owner>/<repo>/<int:pr_number>", methods=["DELETE"])
def cancel_audit(owner, repo, pr_number):
    key = f"{owner}/{repo}/{pr_number}"
    logger.info(f"Cancelling audit {key}")
    with audits_lock:
        if key not in active_audits:
            return jsonify({"error": "Audit not found"}), 404
        audit = active_audits[key]
        process = audit.get("process")
        if process and audit["status"] == "running":
            try:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                audit["status"] = "cancelled"
            except Exception as e:
                return error_response("Failed to terminate audit process", 500,
                                      f"Failed to terminate audit for {key}: {e}")
        del active_audits[key]
    return jsonify({"message": "Audit cancelled", "key": key})


@audit_bp.route("/api/audits/<owner>/<repo>/<int:pr_number>/status", methods=["GET"])
def get_audit_status_endpoint(owner, repo, pr_number):
    key = f"{owner}/{repo}/{pr_number}"
    audit = check_audit_status(key, active_audits, audits_lock, get_audits_db())
    if audit is None:
        return jsonify({"error": "Audit not found"}), 404
    return jsonify({
        "key": key,
        "status": audit["status"],
        "started_at": audit.get("started_at", ""),
        "completed_at": audit.get("completed_at", ""),
        "pr_url": audit.get("pr_url", ""),
        "audit_file": audit.get("audit_file", ""),
        "exit_code": audit.get("exit_code"),
        "error_output": audit.get("error_output", ""),
    })


@audit_bp.route("/api/audit-history", methods=["GET"])
def list_audit_history():
    audits_db = get_audits_db()
    repo = request.args.get("repo")
    author = request.args.get("author")
    pr_number = request.args.get("pr_number", type=int)
    search = request.args.get("search")
    limit = request.args.get("limit", default=50, type=int)
    offset = request.args.get("offset", default=0, type=int)

    if search:
        rows = audits_db.search_audits(search, limit=limit)
        total = len(rows)
    else:
        rows = audits_db.list_audits(repo=repo, author=author, pr_number=pr_number,
                                     limit=limit, offset=offset)
        total = audits_db.count_all()
    return jsonify({
        "audits": [_audit_row_to_summary(r) for r in rows],
        "total": total,
    })


@audit_bp.route("/api/audit-history/<int:audit_id>", methods=["GET"])
def get_audit_detail(audit_id):
    audits_db = get_audits_db()
    row = audits_db.get_audit(audit_id)
    if not row:
        return jsonify({"error": "Audit not found"}), 404
    content_json = None
    content_md = ""
    try:
        content_json = json.loads(row["content_json"]) if row.get("content_json") else None
        if content_json:
            content_md = audit_json_to_markdown(content_json)
    except (json.JSONDecodeError, TypeError):
        pass
    summary = _audit_row_to_summary(row)
    summary["content_json"] = content_json
    summary["content"] = content_md
    summary["head_ref"] = row.get("head_ref")
    summary["base_ref"] = row.get("base_ref")
    summary["audit_file_path"] = row.get("audit_file_path")
    return jsonify({"audit": summary})


@audit_bp.route("/api/audit-history/check/<owner>/<repo>/<int:pr_number>", methods=["GET"])
def check_audit(owner, repo, pr_number):
    audits_db = get_audits_db()
    return jsonify(audits_db.check_pr_audited(f"{owner}/{repo}", pr_number))


def _findings_to_inline_comments(content_json):
    """Map findings with a resolvable file+line to verdict inline_comments entries."""
    comments = []
    for audit in (content_json.get("audits") or []):
        if not isinstance(audit, dict):
            continue
        for f in (audit.get("findings") or []):
            if not isinstance(f, dict):
                continue
            for loc in (f.get("locations") or []):
                file = loc.get("file")
                line = loc.get("line")
                if file and isinstance(line, int) and line >= 1:
                    body_parts = [f"**[{f.get('id', '')}] {f.get('summary', '')}**"]
                    if f.get("severity"):
                        body_parts.append(f"_Severity: {f['severity']}_")
                    if f.get("detail"):
                        body_parts.append(f["detail"])
                    if f.get("recommendation"):
                        body_parts.append(f"**Recommendation:** {f['recommendation']}")
                    comments.append({
                        "path": file,
                        "start_line": line,
                        "end_line": line,
                        "body": "\n\n".join(body_parts),
                        "title": f.get("id", ""),
                    })
                    break  # one inline comment per finding (first mappable location)
    return comments


@audit_bp.route("/api/audits/<int:audit_id>/post-inline-comments", methods=["POST"])
def post_audit_inline_comments(audit_id):
    """Post audit findings with file+line locations as inline PR comments."""
    audits_db = get_audits_db()
    row = audits_db.get_audit(audit_id)
    if not row:
        return jsonify({"error": "Audit not found"}), 404
    if row.get("inline_comments_posted"):
        return jsonify({"error": "Inline comments already posted for this audit"}), 409
    try:
        content_json = json.loads(row["content_json"])
    except (json.JSONDecodeError, TypeError):
        return jsonify({"error": "Audit has no parseable content"}), 400

    comments = _findings_to_inline_comments(content_json)
    if not comments:
        return jsonify({"message": "No findings with mappable file+line locations",
                        "issues_posted": 0, "issues_found": 0}), 200

    repo_parts = (row.get("repo") or "").split("/")
    if len(repo_parts) != 2:
        return jsonify({"error": f"Invalid repo format: {row.get('repo')}"}), 400
    owner, repo_name = repo_parts

    body = f"**PB↔ED Audit** — {len(comments)} finding(s) posted inline."
    result, status_code = post_verdict(
        owner, repo_name, row["pr_number"], "COMMENT", body, inline_comments=comments,
    )
    if status_code == 200 and not result.get("inline_errors"):
        audits_db.update_inline_comments_posted(audit_id, True)
    elif status_code == 200 and result.get("inline_errors"):
        # Some comments failed — leave the flag unset so the user can retry.
        result["partial"] = True
    return jsonify(result), status_code
