"""Tests for SwimlanesDB pin behavior, pin-aware ordering and Auto-lane retirement."""

import pytest

from backend.database.auto_verdict_arming import AutoVerdictArmingDB
from backend.database.base import Database
from backend.database.swimlanes import SwimlanesDB


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


@pytest.fixture
def swl(db):
    s = SwimlanesDB(db)
    s.ensure_default_lane()
    return s


def _add_card(db, swl, pr_number):
    """Insert a bare merge_queue row and assign it to the default lane.

    Bypasses MergeQueueDB.add_to_queue because that auto-assigns via the global
    singleton DB rather than this test's Database instance.
    """
    with db.connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(MAX(position), 0) + 1 AS p FROM merge_queue")
        pos = cursor.fetchone()["p"]
        cursor.execute(
            "INSERT INTO merge_queue (pr_number, repo, position) VALUES (?, ?, ?)",
            (pr_number, "owner/repo", pos),
        )
        item_id = cursor.lastrowid
    swl.auto_assign_new_card(item_id)
    return item_id


def _lane_order(swl, lane_id):
    """Return queue_item_ids of a lane in board order (pinned-first)."""
    return [
        a["queue_item_id"]
        for a in swl.get_assignments()
        if a["swimlane_id"] == lane_id
    ]


def test_pin_moves_card_to_top_and_survives_reload(db, swl):
    lane = swl.get_default_lane()["id"]
    a = _add_card(db, swl, 1)
    b = _add_card(db, swl, 2)
    c = _add_card(db, swl, 3)

    assert _lane_order(swl, lane) == [a, b, c]

    swl.set_pinned(c, True)

    # Pinned card jumps to the top; reading again (a fresh query) keeps it there.
    assert _lane_order(swl, lane) == [c, a, b]
    assert _lane_order(swl, lane) == [c, a, b]


def test_pin_appends_to_bottom_of_pinned_group(db, swl):
    lane = swl.get_default_lane()["id"]
    a = _add_card(db, swl, 1)
    b = _add_card(db, swl, 2)
    c = _add_card(db, swl, 3)

    swl.set_pinned(a, True)
    swl.set_pinned(c, True)

    # a pinned first, then c (bottom of pinned group), then unpinned b.
    assert _lane_order(swl, lane) == [a, c, b]


def test_unpin_drops_to_top_of_unpinned_group(db, swl):
    lane = swl.get_default_lane()["id"]
    a = _add_card(db, swl, 1)
    b = _add_card(db, swl, 2)
    c = _add_card(db, swl, 3)

    swl.set_pinned(a, True)
    swl.set_pinned(b, True)
    # order: [a, b, c]
    swl.set_pinned(a, False)
    # a is now unpinned and goes to the top of the unpinned group (above c).
    assert _lane_order(swl, lane) == [b, a, c]


def test_auto_assigned_new_card_lands_below_pinned(db, swl):
    lane = swl.get_default_lane()["id"]
    a = _add_card(db, swl, 1)
    swl.set_pinned(a, True)
    b = _add_card(db, swl, 2)
    # b appended at the bottom, still below the pinned a.
    assert _lane_order(swl, lane) == [a, b]


def test_move_card_keeps_unpinned_out_of_pinned_zone(db, swl):
    lane = swl.get_default_lane()["id"]
    a = _add_card(db, swl, 1)
    b = _add_card(db, swl, 2)
    c = _add_card(db, swl, 3)

    swl.set_pinned(a, True)  # order: [a(pinned), b, c]

    # Try to drop unpinned c at position 1 (into the pinned zone).
    swl.move_card(c, lane, 1)

    order = _lane_order(swl, lane)
    # a stays pinned-first; c cannot displace it.
    assert order[0] == a
    assert order == [a, c, b]


def test_move_card_keeps_pinned_inside_pinned_zone(db, swl):
    lane = swl.get_default_lane()["id"]
    a = _add_card(db, swl, 1)
    b = _add_card(db, swl, 2)
    c = _add_card(db, swl, 3)

    swl.set_pinned(a, True)
    swl.set_pinned(b, True)  # order: [a, b, c]; pinned = {a, b}

    # Drop pinned a at the very bottom (position 99) — clamps to bottom of pinned zone.
    swl.move_card(a, lane, 99)

    order = _lane_order(swl, lane)
    # a stays within the pinned group (above unpinned c), now after b.
    assert order == [b, a, c]


def test_move_card_across_lanes_preserves_pin(db, swl):
    src = swl.get_default_lane()["id"]
    dst = swl.create_lane("Reviewing", "warning")["id"]
    a = _add_card(db, swl, 1)
    b = _add_card(db, swl, 2)  # unpinned card already in dst

    swl.move_card(b, dst, 1)
    swl.set_pinned(a, True)
    swl.move_card(a, dst, 99)  # move pinned a into dst, request bottom

    order = _lane_order(swl, dst)
    # a is pinned so it lands in dst's pinned zone (top), above unpinned b.
    assert order == [a, b]
    # a's pin flag persisted.
    pinned = {x["queue_item_id"]: x["is_pinned"] for x in swl.get_assignments()}
    assert pinned[a] == 1


# ----- Auto lane retirement -----


def _legacy_auto_lane(db):
    """Insert the protected lane the way the retired ensure_auto_lane() did."""
    with db.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO swimlanes (name, color, position, is_default, is_protected) "
            "VALUES ('Auto', 'violet', 99, 0, 1)"
        )
        return cursor.lastrowid


def _queue_ids(db):
    with db.connection() as conn:
        return [r["id"] for r in conn.execute("SELECT id FROM merge_queue ORDER BY position").fetchall()]


def test_retire_auto_lane_removes_its_cards_and_the_lane(db, swl):
    auto = _legacy_auto_lane(db)
    a = _add_card(db, swl, 1)
    b = _add_card(db, swl, 2)
    swl.assign_card_to_lane(a, auto)
    with db.connection() as conn:
        conn.execute("INSERT INTO queue_notes (queue_item_id, content) VALUES (?, 'n')", (a,))

    assert swl.retire_auto_lane() == 1

    assert [lane["name"] for lane in swl.list_lanes()] == ["Unassigned"]
    assert _queue_ids(db) == [b]
    assert [x["queue_item_id"] for x in swl.get_assignments()] == [b]
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM queue_notes").fetchone()["n"] == 0
        # The surviving card's position is renumbered from 1.
        assert conn.execute("SELECT position FROM merge_queue").fetchone()["position"] == 1


def test_retire_auto_lane_is_idempotent(db, swl):
    _legacy_auto_lane(db)
    assert swl.retire_auto_lane() == 0
    assert swl.retire_auto_lane() == 0
    assert len(swl.list_lanes()) == 1


def test_retire_auto_lane_without_protected_lane_leaves_cards_alone(db, swl):
    a = _add_card(db, swl, 1)
    other = swl.create_lane("Reviewing", "warning")
    assert swl.retire_auto_lane() == 0
    assert _queue_ids(db) == [a]
    assert {lane["id"] for lane in swl.list_lanes()} == {swl.get_default_lane()["id"], other["id"]}


def test_retire_auto_lane_keeps_arming(db, swl):
    arming = AutoVerdictArmingDB(db)
    arming.set_arming("owner/repo", 1, True, "pb", "comment")
    auto = _legacy_auto_lane(db)
    a = _add_card(db, swl, 1)
    swl.assign_card_to_lane(a, auto)

    swl.retire_auto_lane()

    row = arming.get("owner/repo", 1)
    assert row["auto_verdict_enabled"] == 1
    assert row["auto_verdict_reviewer"] == "pb"


def test_lanes_can_be_renamed_and_deleted_freely(swl):
    lane = swl.create_lane("Auto", "violet")
    assert swl.update_lane(lane["id"], name="Renamed")["name"] == "Renamed"
    swl.delete_lane(lane["id"])
    assert [x["name"] for x in swl.list_lanes()] == ["Unassigned"]


def test_assign_card_to_lane_moves_card_to_bottom(db, swl):
    auto_lane = swl.create_lane("Auto", "violet")
    a = _add_card(db, swl, 1)
    b = _add_card(db, swl, 2)
    swl.assign_card_to_lane(a, auto_lane["id"])
    swl.assign_card_to_lane(b, auto_lane["id"])
    assert _lane_order(swl, auto_lane["id"]) == [a, b]
    assert _lane_order(swl, swl.get_default_lane()["id"]) == []


def test_assign_card_to_lane_is_idempotent(db, swl):
    auto_lane = swl.create_lane("Auto", "violet")
    a = _add_card(db, swl, 1)
    swl.assign_card_to_lane(a, auto_lane["id"])
    swl.assign_card_to_lane(a, auto_lane["id"])
    assert _lane_order(swl, auto_lane["id"]) == [a]
