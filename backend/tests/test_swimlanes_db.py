"""Tests for SwimlanesDB pin behavior and pin-aware ordering."""

import pytest

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
