"""Portal verification tests on synthetic plans."""

from shapely.geometry import box

from hackhive_ps4.geometry import find_portals, extract_rooms, calibrate
from hackhive_ps4.synthetic import make_row_plan, run_full


def test_two_rooms_one_verified_door():
    plan = make_row_plan(2, seed=0)
    rooms = extract_rooms(plan)
    scale = calibrate(plan)["scale_m_per_raw"]
    portals = find_portals(plan, rooms, scale)
    assert len(portals) == 1
    p = portals[0]
    assert p["kind"] == "door"
    assert set(p["rooms"]) == {"room_0", "room_1"}
    assert p["width_m"] >= 0.6


def test_no_door_between_rooms_no_portal():
    """A decoy door on the outer wall must NOT connect the two rooms."""
    plan = make_row_plan(2, seed=0)
    plan["door"] = box(-0.05, 1.0, 0.05, 1.8)
    rooms = extract_rooms(plan)
    scale = calibrate(plan)["scale_m_per_raw"]
    portals = find_portals(plan, rooms, scale)
    assert portals == []


def test_sealed_room_excluded_reported():
    """Dataset-sealed design: no physical opening -> excluded, not failed."""
    plan = make_row_plan(2, seed=0)
    plan["door"] = box(-0.05, 1.0, 0.05, 1.8)
    report, fo, fb = run_full(plan)
    # exactly one room is sealed (the one not reachable from the anchor)
    sealed = set(report["unroutable_rooms"])
    assert len(sealed) == 1
    assert fo["solution"]["metrics"]["unroutable_rooms"] == report["unroutable_rooms"]
    assert fo["validation"]["all_valid"] is True
    assigned = set()
    for panel in fo["solution"]["panels"]:
        assigned.update(panel["assigned_rooms"])
    eligible = {rid for rid, r in extract_rooms(plan).items() if r["eligible"]}
    assert assigned == eligible - sealed


def test_row_plan_portals_match_boundaries():
    plan = make_row_plan(4, seed=2)
    rooms = extract_rooms(plan)
    scale = calibrate(plan)["scale_m_per_raw"]
    portals = find_portals(plan, rooms, scale)
    assert len(portals) == 3
    pairs = {tuple(sorted(p["rooms"])) for p in portals}
    assert pairs == {("room_0", "room_1"), ("room_1", "room_2"),
                     ("room_2", "room_3")}
