"""MergeQueueDB - Database operations for merge queue."""

import sqlite3
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class MergeQueueDB:
    """Database operations for merge queue."""

    def __init__(self, db):
        self.db = db

    def _get_connection(self) -> sqlite3.Connection:
        return self.db._get_connection()

    def get_queue(self) -> List[Dict[str, Any]]:
        """Get all items in the merge queue, ordered by position."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM merge_queue ORDER BY position ASC")
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def add_to_queue(
        self,
        pr_number: int,
        repo: str,
        pr_title: Optional[str] = None,
        pr_author: Optional[str] = None,
        pr_url: Optional[str] = None,
        additions: int = 0,
        deletions: int = 0,
        pr_state: Optional[str] = None
    ) -> Dict[str, Any]:
        """Add a PR to the merge queue. Returns the added queue item."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT id FROM merge_queue WHERE pr_number = ? AND repo = ?",
                (pr_number, repo)
            )
            if cursor.fetchone():
                raise ValueError("PR already in queue")

            cursor.execute("SELECT COALESCE(MAX(position), 0) + 1 as next_pos FROM merge_queue")
            next_position = cursor.fetchone()["next_pos"]

            state_updated_at = datetime.now() if pr_state else None

            cursor.execute("""
                INSERT INTO merge_queue (
                    pr_number, repo, pr_title, pr_author, pr_url,
                    additions, deletions, position, pr_state, state_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pr_number, repo, pr_title, pr_author, pr_url,
                additions, deletions, next_position, pr_state, state_updated_at
            ))

            conn.commit()

            cursor.execute(
                "SELECT * FROM merge_queue WHERE pr_number = ? AND repo = ?",
                (pr_number, repo)
            )
            return dict(cursor.fetchone())
        finally:
            conn.close()

    def update_pr_state(self, pr_number: int, repo: str, pr_state: str):
        """Update the PR state for a queue item."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE merge_queue
                SET pr_state = ?, state_updated_at = ?
                WHERE pr_number = ? AND repo = ?
            """, (pr_state, datetime.now(), pr_number, repo))
            conn.commit()
        finally:
            conn.close()

    def remove_from_queue(self, pr_number: int, repo: Optional[str] = None) -> bool:
        """Remove a PR from the merge queue. Returns True if removed."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            if repo:
                cursor.execute(
                    "DELETE FROM merge_queue WHERE pr_number = ? AND repo = ?",
                    (pr_number, repo)
                )
            else:
                cursor.execute(
                    "DELETE FROM merge_queue WHERE pr_number = ?",
                    (pr_number,)
                )

            deleted = cursor.rowcount > 0

            if deleted:
                self._reorder_positions(cursor)
                conn.commit()

            return deleted
        finally:
            conn.close()

    def _reorder_positions(self, cursor: sqlite3.Cursor):
        """Reorder position values to be sequential starting from 1."""
        cursor.execute("""
            UPDATE merge_queue
            SET position = (
                SELECT COUNT(*)
                FROM merge_queue AS mq2
                WHERE mq2.position <= merge_queue.position
            )
        """)

    def reorder_queue(self, order: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Reorder the merge queue based on provided order."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            for position, item in enumerate(order, start=1):
                cursor.execute("""
                    UPDATE merge_queue
                    SET position = ?
                    WHERE pr_number = ? AND repo = ?
                """, (position, item["number"], item["repo"]))

            conn.commit()
            return self.get_queue()
        finally:
            conn.close()

    def clear_queue(self):
        """Remove all items from the merge queue."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM merge_queue")
            conn.commit()
        finally:
            conn.close()

    def is_in_queue(self, pr_number: int, repo: str) -> bool:
        """Check if a PR is in the merge queue."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM merge_queue WHERE pr_number = ? AND repo = ?",
                (pr_number, repo)
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def get_queue_item_id(self, pr_number: int, repo: str) -> Optional[int]:
        """Get the queue item ID for a PR."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM merge_queue WHERE pr_number = ? AND repo = ?",
                (pr_number, repo)
            )
            row = cursor.fetchone()
            return row["id"] if row else None
        finally:
            conn.close()

    def add_note(self, queue_item_id: int, content: str) -> Dict[str, Any]:
        """Add a note to a queue item."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            cursor.execute("SELECT id FROM merge_queue WHERE id = ?", (queue_item_id,))
            if not cursor.fetchone():
                raise ValueError("Queue item not found")

            cursor.execute("""
                INSERT INTO queue_notes (queue_item_id, content)
                VALUES (?, ?)
            """, (queue_item_id, content))

            conn.commit()
            note_id = cursor.lastrowid

            cursor.execute("SELECT * FROM queue_notes WHERE id = ?", (note_id,))
            return dict(cursor.fetchone())
        finally:
            conn.close()

    def get_notes(self, queue_item_id: int) -> List[Dict[str, Any]]:
        """Get all notes for a queue item."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM queue_notes
                WHERE queue_item_id = ?
                ORDER BY created_at DESC
            """, (queue_item_id,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def delete_note(self, note_id: int) -> bool:
        """Delete a note. Returns True if deleted."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM queue_notes WHERE id = ?", (note_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_notes_count(self, queue_item_id: int) -> int:
        """Get the count of notes for a queue item."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as count FROM queue_notes WHERE queue_item_id = ?",
                (queue_item_id,)
            )
            return cursor.fetchone()["count"]
        finally:
            conn.close()
