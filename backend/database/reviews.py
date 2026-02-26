"""ReviewsDB - Database operations for code reviews."""

import re
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class ReviewsDB:
    """Database operations for code reviews."""

    def __init__(self, db):
        self.db = db

    def save_review(
        self,
        pr_number: int,
        repo: str,
        pr_title: Optional[str] = None,
        pr_author: Optional[str] = None,
        pr_url: Optional[str] = None,
        status: str = "completed",
        review_file_path: Optional[str] = None,
        score: Optional[float] = None,
        content: Optional[str] = None,
        is_followup: bool = False,
        parent_review_id: Optional[int] = None,
        review_timestamp: Optional[datetime] = None,
        head_commit_sha: Optional[str] = None,
        pr_state_at_review: Optional[str] = None
    ) -> int:
        """Save a review to the database. Returns the review ID."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            if score is None and content:
                score = self._extract_score(content)

            timestamp = review_timestamp or datetime.now()

            cursor.execute("""
                INSERT INTO reviews (
                    pr_number, repo, pr_title, pr_author, pr_url,
                    status, review_file_path, score, content,
                    is_followup, parent_review_id, review_timestamp,
                    head_commit_sha, pr_state_at_review
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pr_number, repo, pr_title, pr_author, pr_url,
                status, review_file_path, score, content,
                is_followup, parent_review_id, timestamp,
                head_commit_sha, pr_state_at_review
            ))

            review_id = cursor.lastrowid
            logger.info(f"Saved review {review_id} for PR #{pr_number} in {repo}")
            return review_id

    def update_review(
        self,
        review_id: int,
        status: Optional[str] = None,
        score: Optional[float] = None,
        content: Optional[str] = None
    ):
        """Update an existing review."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            updates = []
            params = []

            if status is not None:
                updates.append("status = ?")
                params.append(status)

            if content is not None:
                updates.append("content = ?")
                params.append(content)
                if score is None:
                    score = self._extract_score(content)

            if score is not None:
                updates.append("score = ?")
                params.append(score)

            if not updates:
                return

            params.append(review_id)
            query = f"UPDATE reviews SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, params)
            logger.info(f"Updated review {review_id}")

    def update_inline_comments_posted(self, review_id: int, posted: bool = True):
        """Update the inline_comments_posted flag for a review."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE reviews SET inline_comments_posted = ? WHERE id = ?",
                (posted, review_id)
            )
            logger.info(f"Updated inline_comments_posted for review {review_id} to {posted}")

    def update_section_posted(
        self, review_id: int, section: str, posted: bool = True,
        posted_count: int = 0, found_count: int = 0
    ):
        """Update the posted flag and counts for a specific review section.

        Args:
            review_id: The review ID.
            section: One of 'critical', 'major', or 'minor'.
            posted: Whether the section has been posted.
            posted_count: Number of issues successfully posted.
            found_count: Number of issues found/parsed.
        """
        column_map = {
            "critical": "inline_comments_posted",
            "major": "major_concerns_posted",
            "minor": "minor_issues_posted",
        }
        column = column_map.get(section)
        if not column:
            raise ValueError(f"Unknown section: {section}")

        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE reviews SET {column} = ?, "
                f"{section}_posted_count = ?, {section}_found_count = ? "
                f"WHERE id = ?",
                (posted, posted_count, found_count, review_id)
            )
            logger.info(f"Updated {column} for review {review_id}: {posted_count}/{found_count} posted")

    def _extract_score(self, content: str) -> Optional[float]:
        """Extract score from review content."""
        if not content:
            return None

        patterns = [
            r'(?:#*\s*)?(?:\*\*)?(?:\w+\s+)?(?:Score|Rating)\s*[:\s]*(\d+(?:\.\d{1,2})?)\s*/?\s*10',
            r'(\d+(?:\.\d{1,2})?)\s*/\s*10\s*(?:score|rating)',
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                score = float(match.group(1))
                if 0 <= score <= 10:
                    return score

        return None

    def get_review(self, review_id: int) -> Optional[Dict[str, Any]]:
        """Get a single review by ID."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM reviews WHERE id = ?", (review_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_reviews_for_pr(self, repo: str, pr_number: int) -> List[Dict[str, Any]]:
        """Get all reviews for a specific PR (review chain)."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM reviews
                WHERE repo = ? AND pr_number = ?
                ORDER BY review_timestamp DESC
            """, (repo, pr_number))
            return [dict(row) for row in cursor.fetchall()]

    def get_latest_review_for_pr(self, repo: str, pr_number: int) -> Optional[Dict[str, Any]]:
        """Get the most recent review for a PR."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM reviews
                WHERE repo = ? AND pr_number = ?
                ORDER BY review_timestamp DESC
                LIMIT 1
            """, (repo, pr_number))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_reviews(
        self,
        repo: Optional[str] = None,
        author: Optional[str] = None,
        pr_number: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List reviews with optional filtering."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            conditions = []
            params = []

            if repo:
                conditions.append("repo = ?")
                params.append(repo)
            if author:
                conditions.append("pr_author = ?")
                params.append(author)
            if pr_number:
                conditions.append("pr_number = ?")
                params.append(pr_number)
            if status:
                conditions.append("status = ?")
                params.append(status)

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            query = f"""
                SELECT * FROM reviews
                {where_clause}
                ORDER BY review_timestamp DESC
                LIMIT ? OFFSET ?
            """
            params.extend([limit, offset])

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_review_stats(self) -> Dict[str, Any]:
        """Get review statistics."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) as total FROM reviews")
            total = cursor.fetchone()["total"]

            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM reviews GROUP BY status
            """)
            by_status = {row["status"]: row["count"] for row in cursor.fetchall()}

            cursor.execute("""
                SELECT repo, COUNT(*) as count
                FROM reviews GROUP BY repo
                ORDER BY count DESC LIMIT 10
            """)
            by_repo = {row["repo"]: row["count"] for row in cursor.fetchall()}

            cursor.execute("""
                SELECT AVG(score) as avg_score
                FROM reviews WHERE score IS NOT NULL
            """)
            avg_score = cursor.fetchone()["avg_score"]

            cursor.execute("SELECT COUNT(*) as count FROM reviews WHERE is_followup = 1")
            followup_count = cursor.fetchone()["count"]

            return {
                "total": total,
                "by_status": by_status,
                "by_repo": by_repo,
                "average_score": round(avg_score, 1) if avg_score else None,
                "followup_count": followup_count
            }

    def count_all(self) -> int:
        """Return the total number of reviews in the database."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as total FROM reviews")
            return cursor.fetchone()["total"]

    def search_reviews(self, search_text: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search reviews by title or content."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            search_pattern = f"%{search_text}%"
            cursor.execute("""
                SELECT * FROM reviews
                WHERE pr_title LIKE ? OR content LIKE ?
                ORDER BY review_timestamp DESC
                LIMIT ?
            """, (search_pattern, search_pattern, limit))
            return [dict(row) for row in cursor.fetchall()]
