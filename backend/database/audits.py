"""AuditsDB - Database operations for PB↔ED audits (JSON-primary storage)."""

import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)


class AuditsDB:
    """Database operations for PB↔ED audits.

    Audits are stored with content_json as the primary content column.
    There is no score; finding_count / blocking_count drive the UI chip.
    """

    def __init__(self, db):
        self.db = db

    def add_audit(
        self,
        pr_number: int,
        repo: str,
        pr_title: Optional[str] = None,
        pr_author: Optional[str] = None,
        pr_url: Optional[str] = None,
        head_ref: Optional[str] = None,
        base_ref: Optional[str] = None,
        audit_type: str = "pb_ed",
        status: str = "completed",
        content_json: Optional[str] = None,
        finding_count: int = 0,
        blocking_count: int = 0,
        audit_file_path: Optional[str] = None,
        audit_timestamp: Optional[datetime] = None,
    ) -> int:
        """Insert an audit. Returns the new audit ID."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            if content_json is None:
                content_json = "{}"
            timestamp = audit_timestamp or datetime.now()
            cursor.execute("""
                INSERT INTO audits (
                    pr_number, repo, pr_title, pr_author, pr_url,
                    head_ref, base_ref, audit_type, status, content_json,
                    finding_count, blocking_count, audit_file_path, audit_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pr_number, repo, pr_title, pr_author, pr_url,
                head_ref, base_ref, audit_type, status, content_json,
                finding_count, blocking_count, audit_file_path, timestamp,
            ))
            audit_id = cursor.lastrowid
            logger.info(f"Saved audit {audit_id} for PR #{pr_number} in {repo}")
            return audit_id

    def update_inline_comments_posted(self, audit_id: int, posted: bool = True):
        """Update the inline_comments_posted flag for an audit."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE audits SET inline_comments_posted = ? WHERE id = ?",
                (posted, audit_id),
            )
            logger.info(f"Updated inline_comments_posted for audit {audit_id} to {posted}")

    def get_audit(self, audit_id: int) -> Optional[Dict[str, Any]]:
        """Return a single audit row by ID, or None if not found."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM audits WHERE id = ?", (audit_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_audits_for_pr(self, repo: str, pr_number: int) -> List[Dict[str, Any]]:
        """Return all audits for a PR ordered by most recent first."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM audits WHERE repo = ? AND pr_number = ?
                ORDER BY audit_timestamp DESC, id DESC
            """, (repo, pr_number))
            return [dict(r) for r in cursor.fetchall()]

    def get_audits_for_prs(
        self, repo_pr_pairs: List[Tuple[str, int]]
    ) -> Dict[Tuple[str, int], List[Dict[str, Any]]]:
        """Batch lookup: every audit per (repo, pr_number), newest first.
        Never-audited pairs are absent from the result."""
        result: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
        if not repo_pr_pairs:
            return result
        with self.db.connection() as conn:
            cursor = conn.cursor()
            # Chunked: each pair costs two SQL variables and SQLite caps them.
            for i in range(0, len(repo_pr_pairs), 400):
                chunk = repo_pr_pairs[i:i + 400]
                placeholders = " OR ".join(["(repo = ? AND pr_number = ?)"] * len(chunk))
                params = [v for pair in chunk for v in pair]
                cursor.execute(
                    f"SELECT * FROM audits WHERE {placeholders} "
                    "ORDER BY audit_timestamp DESC, id DESC",
                    params,
                )
                for row in cursor.fetchall():
                    result.setdefault((row["repo"], row["pr_number"]), []).append(dict(row))
        return result

    def get_latest_audit_for_pr(self, repo: str, pr_number: int) -> Optional[Dict[str, Any]]:
        """Return the most recent audit for a PR, or None if none exist."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM audits WHERE repo = ? AND pr_number = ?
                ORDER BY audit_timestamp DESC, id DESC LIMIT 1
            """, (repo, pr_number))
            row = cursor.fetchone()
            return dict(row) if row else None

    def check_pr_audited(self, repo: str, pr_number: int) -> Dict[str, Any]:
        """Return audit status dict indicating whether a PR has been audited."""
        audits = self.get_audits_for_pr(repo, pr_number)
        if not audits:
            return {"audited": False, "audit_count": 0, "latest_audit": None}
        latest = audits[0]
        return {
            "audited": True,
            "audit_count": len(audits),
            "latest_audit": {
                "id": latest["id"],
                "audit_timestamp": latest["audit_timestamp"],
                "finding_count": latest["finding_count"],
                "blocking_count": latest["blocking_count"],
            },
        }

    def list_audits(
        self,
        repo: Optional[str] = None,
        author: Optional[str] = None,
        pr_number: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Return audits with optional filters, ordered by most recent first."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            conditions, params = [], []
            if repo:
                conditions.append("repo = ?"); params.append(repo)
            if author:
                conditions.append("pr_author = ?"); params.append(author)
            if pr_number:
                conditions.append("pr_number = ?"); params.append(pr_number)
            if status:
                conditions.append("status = ?"); params.append(status)
            where = "WHERE " + " AND ".join(conditions) if conditions else ""
            params.extend([limit, offset])
            cursor.execute(
                f"SELECT * FROM audits {where} ORDER BY audit_timestamp DESC LIMIT ? OFFSET ?",
                params,
            )
            return [dict(r) for r in cursor.fetchall()]

    def count_all(self) -> int:
        """Return the total number of audits in the database."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as total FROM audits")
            return cursor.fetchone()["total"]

    def search_audits(self, search_text: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search audits by PR title or content_json substring."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            pattern = f"%{search_text}%"
            cursor.execute("""
                SELECT * FROM audits
                WHERE pr_title LIKE ? OR content_json LIKE ?
                ORDER BY audit_timestamp DESC LIMIT ?
            """, (pattern, pattern, limit))
            return [dict(r) for r in cursor.fetchall()]
