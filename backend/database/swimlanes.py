"""SwimlanesDB - Database operations for swimlane board (Kanban view of merge queue)."""

import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


VALID_COLORS = {"success", "warning", "error", "info", "primary", "accent", "violet", "slate"}
DEFAULT_LANE_NAME = "Unassigned"
DEFAULT_LANE_COLOR = "info"


class SwimlanesDB:
    """Database operations for swimlanes and per-card lane assignments."""

    def __init__(self, db):
        self.db = db

    # ----- Lanes -----

    def list_lanes(self) -> List[Dict[str, Any]]:
        """Return all lanes ordered by position."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM swimlanes ORDER BY position ASC")
            return [dict(row) for row in cursor.fetchall()]

    def get_lane(self, lane_id: int) -> Optional[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM swimlanes WHERE id = ?", (lane_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_default_lane(self) -> Optional[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM swimlanes WHERE is_default = 1 ORDER BY position ASC LIMIT 1"
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def ensure_default_lane(self) -> Dict[str, Any]:
        """On startup: guarantee at least one lane exists and exactly one is the default."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) AS n FROM swimlanes")
            if cursor.fetchone()["n"] == 0:
                cursor.execute(
                    "INSERT INTO swimlanes (name, color, position, is_default) VALUES (?, ?, ?, 1)",
                    (DEFAULT_LANE_NAME, DEFAULT_LANE_COLOR, 1),
                )
                logger.info("Seeded default swimlane '%s'", DEFAULT_LANE_NAME)
            else:
                cursor.execute("SELECT COUNT(*) AS n FROM swimlanes WHERE is_default = 1")
                if cursor.fetchone()["n"] == 0:
                    cursor.execute(
                        "UPDATE swimlanes SET is_default = 1 "
                        "WHERE id = (SELECT id FROM swimlanes ORDER BY position ASC LIMIT 1)"
                    )

            cursor.execute(
                "SELECT * FROM swimlanes WHERE is_default = 1 ORDER BY position ASC LIMIT 1"
            )
            return dict(cursor.fetchone())

    def create_lane(self, name: str, color: str) -> Dict[str, Any]:
        if color not in VALID_COLORS:
            raise ValueError(f"Invalid color '{color}'. Must be one of: {sorted(VALID_COLORS)}")
        name = (name or "").strip()
        if not name:
            raise ValueError("Lane name is required")

        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COALESCE(MAX(position), 0) + 1 AS next_pos FROM swimlanes")
            next_pos = cursor.fetchone()["next_pos"]
            cursor.execute(
                "INSERT INTO swimlanes (name, color, position, is_default) VALUES (?, ?, ?, 0)",
                (name, color, next_pos),
            )
            new_id = cursor.lastrowid
            cursor.execute("SELECT * FROM swimlanes WHERE id = ?", (new_id,))
            return dict(cursor.fetchone())

    def update_lane(
        self, lane_id: int, name: Optional[str] = None, color: Optional[str] = None
    ) -> Dict[str, Any]:
        if color is not None and color not in VALID_COLORS:
            raise ValueError(f"Invalid color '{color}'. Must be one of: {sorted(VALID_COLORS)}")
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("Lane name cannot be empty")

        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM swimlanes WHERE id = ?", (lane_id,))
            if not cursor.fetchone():
                raise ValueError("Lane not found")

            sets, params = [], []
            if name is not None:
                sets.append("name = ?")
                params.append(name)
            if color is not None:
                sets.append("color = ?")
                params.append(color)
            if sets:
                params.append(lane_id)
                cursor.execute(f"UPDATE swimlanes SET {', '.join(sets)} WHERE id = ?", params)

            cursor.execute("SELECT * FROM swimlanes WHERE id = ?", (lane_id,))
            return dict(cursor.fetchone())

    def delete_lane(self, lane_id: int) -> Dict[str, Any]:
        """Delete a lane; orphaned cards are re-homed to the default lane.

        If the deleted lane is the default, the leftmost remaining lane becomes the new default.
        Refuses to delete the last remaining lane.
        """
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM swimlanes WHERE id = ?", (lane_id,))
            target = cursor.fetchone()
            if not target:
                raise ValueError("Lane not found")

            cursor.execute("SELECT COUNT(*) AS n FROM swimlanes")
            if cursor.fetchone()["n"] <= 1:
                raise ValueError("Cannot delete the last remaining lane")

            was_default = bool(target["is_default"])

            # ON DELETE SET NULL handles assignments; we re-home them after.
            cursor.execute("DELETE FROM swimlanes WHERE id = ?", (lane_id,))
            self._reorder_lane_positions(cursor)

            if was_default:
                cursor.execute(
                    "UPDATE swimlanes SET is_default = 1 "
                    "WHERE id = (SELECT id FROM swimlanes ORDER BY position ASC LIMIT 1)"
                )

            cursor.execute(
                "SELECT * FROM swimlanes WHERE is_default = 1 ORDER BY position ASC LIMIT 1"
            )
            default_lane = dict(cursor.fetchone())

            # Re-home orphaned assignments (swimlane_id became NULL) to the new default.
            cursor.execute(
                "SELECT id FROM swimlane_assignments WHERE swimlane_id IS NULL ORDER BY id ASC"
            )
            orphan_ids = [r["id"] for r in cursor.fetchall()]
            if orphan_ids:
                cursor.execute(
                    "SELECT COALESCE(MAX(position_in_lane), 0) AS max_pos "
                    "FROM swimlane_assignments WHERE swimlane_id = ?",
                    (default_lane["id"],),
                )
                start = cursor.fetchone()["max_pos"]
                for offset, aid in enumerate(orphan_ids, start=1):
                    cursor.execute(
                        "UPDATE swimlane_assignments "
                        "SET swimlane_id = ?, position_in_lane = ? WHERE id = ?",
                        (default_lane["id"], start + offset, aid),
                    )

            return default_lane

    def reorder_lanes(self, order: List[int]) -> List[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            for pos, lane_id in enumerate(order, start=1):
                cursor.execute("UPDATE swimlanes SET position = ? WHERE id = ?", (pos, lane_id))
        return self.list_lanes()

    def set_default_lane(self, lane_id: int) -> Dict[str, Any]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM swimlanes WHERE id = ?", (lane_id,))
            if not cursor.fetchone():
                raise ValueError("Lane not found")
            cursor.execute("UPDATE swimlanes SET is_default = 0")
            cursor.execute("UPDATE swimlanes SET is_default = 1 WHERE id = ?", (lane_id,))
            cursor.execute("SELECT * FROM swimlanes WHERE id = ?", (lane_id,))
            return dict(cursor.fetchone())

    def _reorder_lane_positions(self, cursor):
        cursor.execute(
            "UPDATE swimlanes SET position = ("
            "  SELECT COUNT(*) FROM swimlanes s2 WHERE s2.position <= swimlanes.position"
            ")"
        )

    # ----- Card assignments -----

    def auto_assign_new_card(self, queue_item_id: int) -> None:
        """Place a freshly-added merge queue item into the default lane at the bottom.

        Idempotent: if the card already has an assignment, leaves it alone.
        """
        default_lane = self.ensure_default_lane()
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM swimlane_assignments WHERE queue_item_id = ?", (queue_item_id,)
            )
            if cursor.fetchone():
                return

            cursor.execute(
                "SELECT COALESCE(MAX(position_in_lane), 0) + 1 AS next_pos "
                "FROM swimlane_assignments WHERE swimlane_id = ?",
                (default_lane["id"],),
            )
            next_pos = cursor.fetchone()["next_pos"]
            cursor.execute(
                "INSERT INTO swimlane_assignments (queue_item_id, swimlane_id, position_in_lane) "
                "VALUES (?, ?, ?)",
                (queue_item_id, default_lane["id"], next_pos),
            )

    def reconcile_assignments(self) -> None:
        """Ensure every merge_queue row has an assignment row.

        Useful for bootstrapping when the swimlane feature is first enabled on an existing DB.
        """
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT mq.id FROM merge_queue mq "
                "LEFT JOIN swimlane_assignments sa ON sa.queue_item_id = mq.id "
                "WHERE sa.id IS NULL"
            )
            missing = [r["id"] for r in cursor.fetchall()]
        for qid in missing:
            self.auto_assign_new_card(qid)
        if missing:
            logger.info("Reconciled %d missing swimlane assignments", len(missing))

    def get_assignments(self) -> List[Dict[str, Any]]:
        """Return all assignments (queue_item_id, swimlane_id, position_in_lane)."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM swimlane_assignments "
                "ORDER BY swimlane_id ASC, position_in_lane ASC"
            )
            return [dict(row) for row in cursor.fetchall()]

    def move_card(
        self, queue_item_id: int, to_lane_id: int, to_position: int
    ) -> Dict[str, Any]:
        """Move a card to (to_lane_id, to_position). Compacts source and destination lanes.

        `to_position` is 1-based. Out-of-range values clamp to the lane's bounds.
        """
        with self.db.connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM swimlanes WHERE id = ?", (to_lane_id,))
            if not cursor.fetchone():
                raise ValueError("Target lane not found")

            cursor.execute(
                "SELECT * FROM swimlane_assignments WHERE queue_item_id = ?", (queue_item_id,)
            )
            current = cursor.fetchone()
            if not current:
                raise ValueError("Card not assigned to any lane (is it in the merge queue?)")

            from_lane_id = current["swimlane_id"]

            # Remove from source lane (set position to a sentinel out of the way)
            cursor.execute(
                "UPDATE swimlane_assignments "
                "SET swimlane_id = NULL, position_in_lane = -1 WHERE queue_item_id = ?",
                (queue_item_id,),
            )

            # Compact source lane positions (skip if source was NULL, e.g. orphaned)
            if from_lane_id is not None:
                self._compact_lane(cursor, from_lane_id)

            # Insert into destination at requested position
            cursor.execute(
                "SELECT COUNT(*) AS n FROM swimlane_assignments WHERE swimlane_id = ?",
                (to_lane_id,),
            )
            dest_count = cursor.fetchone()["n"]
            target_pos = max(1, min(to_position, dest_count + 1))

            cursor.execute(
                "UPDATE swimlane_assignments "
                "SET position_in_lane = position_in_lane + 1 "
                "WHERE swimlane_id = ? AND position_in_lane >= ?",
                (to_lane_id, target_pos),
            )

            cursor.execute(
                "UPDATE swimlane_assignments "
                "SET swimlane_id = ?, position_in_lane = ? WHERE queue_item_id = ?",
                (to_lane_id, target_pos, queue_item_id),
            )

            cursor.execute(
                "SELECT * FROM swimlane_assignments WHERE queue_item_id = ?", (queue_item_id,)
            )
            return dict(cursor.fetchone())

    def _compact_lane(self, cursor, lane_id: int) -> None:
        cursor.execute(
            "UPDATE swimlane_assignments SET position_in_lane = ("
            "  SELECT COUNT(*) FROM swimlane_assignments s2 "
            "  WHERE s2.swimlane_id = swimlane_assignments.swimlane_id "
            "    AND s2.position_in_lane <= swimlane_assignments.position_in_lane"
            ") WHERE swimlane_id = ?",
            (lane_id,),
        )
