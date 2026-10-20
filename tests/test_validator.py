"""Validator tests: deliberately broken solutions must be caught."""

import copy

import pytest

from hackhive_ps4.validate import validate

WALL_CROSS_LOOP = [(1, 1.5), (1, 0.05), (7, 0.05), (7, 2.5), (1, 2.5), (1, 1.5)]


@pytest.fixture()
def valid(two_room_artifacts):
    return two_room_artifacts[1]  # final_optimized dict


def mutate(valid, fn):
    broken = copy.deepcopy(valid)
    fn(broken["solution"])
    return broken


def test_valid_solution_passes(valid, two_room_plan):
    v = validate(two_room_plan, valid["solution"], valid["scale_m_per_raw"])
    assert v["all_valid"] is True
    assert v["violations"] == []
    assert all(v["checks"].values())


def test_wall_crossing_detected(valid, two_room_plan):
    def breakit(sol):
        sol["panels"][0]["loop_coords"] = [list(p) for p in WALL_CROSS_LOOP]
        sol["panels"][0]["loop_source_indices"] = sol["panels"][0][
            "loop_source_indices"]
    v = validate(two_room_plan, mutate(valid, breakit)["solution"],
                 valid["scale_m_per_raw"])
    assert v["checks"]["physical_routes"] is False
    assert v["all_valid"] is False
    assert any("wall" in x for x in v["violations"])


def test_unclosed_loop_detected(valid, two_room_plan):
    def breakit(sol):
        sol["panels"][0]["loop_coords"][-1] = [
            sol["panels"][0]["loop_coords"][-1][0] + 0.5,
            sol["panels"][0]["loop_coords"][-1][1] + 0.5,
        ]
    v = validate(two_room_plan, mutate(valid, breakit)["solution"],
                 valid["scale_m_per_raw"])
    assert v["checks"]["closed_loops"] is False
    assert any("not closed" in x for x in v["violations"])


def test_repeated_node_detected(valid, two_room_plan):
    def breakit(sol):
        rooms = list(sol["panels"][0]["device_order"])
        sol["panels"][0]["device_order"] = [rooms[0], rooms[0]]
    v = validate(two_room_plan, mutate(valid, breakit)["solution"],
                 valid["scale_m_per_raw"])
    assert v["checks"]["closed_loops"] is False
    assert any("visitation mismatch" in x for x in v["violations"])


def test_duplicate_assignment_detected(valid, two_room_plan):
    def breakit(sol):
        sol["panels"][0]["assigned_rooms"] = list(
            sol["panels"][0]["assigned_rooms"]) + [
            sol["panels"][0]["assigned_rooms"][0]]
    v = validate(two_room_plan, mutate(valid, breakit)["solution"],
                 valid["scale_m_per_raw"])
    assert v["checks"]["assignment_complete"] is False
    assert any("multiple panels" in x for x in v["violations"])


def test_hub_clearance_violation_detected(valid, two_room_plan):
    def breakit(sol):
        sol["panels"][0]["panel_position"] = [0.35, 0.35]  # 0.35 m from walls
    v = validate(two_room_plan, mutate(valid, breakit)["solution"],
                 valid["scale_m_per_raw"])
    assert v["checks"]["hub_clearance"] is False
    assert any("clearance" in x for x in v["violations"])


def test_diagonal_segment_detected(valid, two_room_plan):
    def breakit(sol):
        loop = sol["panels"][0]["loop_coords"]
        loop[1] = [loop[0][0] + 0.7, loop[0][1] + 0.7]
    v = validate(two_room_plan, mutate(valid, breakit)["solution"],
                 valid["scale_m_per_raw"])
    assert v["checks"]["axis_aligned"] is False
    assert any("diagonal" in x for x in v["violations"])


def test_node_cap_violation_detected():
    """Six rooms forced onto one hub violate the official 5-node cap."""
    from hackhive_ps4.synthetic import make_row_plan
    from hackhive_ps4.validate import validate as _validate

    plan = make_row_plan(6, seed=9)
    rooms = {rid: r for rid, r in
             __import__("hackhive_ps4.geometry", fromlist=["extract_rooms"])
             .extract_rooms(plan).items() if r["eligible"]}
    all_rooms = sorted(rooms)
    device_pts = [rooms[r]["device_point"] for r in all_rooms]
    loop = [[p.x, p.y] for p in device_pts] + [[device_pts[0].x, device_pts[0].y]]
    sol = {
        "mode": "optimized",
        "metrics": {"unroutable_rooms": []},
        "panels": [{
            "panel_room": all_rooms[0],
            "panel_position": [0.7, 1.5],
            "assigned_rooms": all_rooms,
            "device_order": all_rooms,
            "loop_coords": loop,
            "loop_valid": True,
        }],
    }
    v = _validate(plan, sol, 1.0)
    assert v["checks"]["capacity"] is False
    assert any("more than 5 nodes" in x for x in v["violations"])


def test_window_crossing_detected(valid, two_room_plan):
    def breakit(sol):
        # drive one leg along y=0.01 where the synthetic window sits
        sol["panels"][0]["loop_coords"] = [
            [0.5, 1.5], [0.5, 0.01], [2.0, 0.01], [2.0, 1.5], [0.5, 1.5]]
        sol["panels"][0]["device_order"] = sol["panels"][0]["device_order"][:1]
        sol["panels"][0]["assigned_rooms"] = sol["panels"][0][
            "assigned_rooms"][:1]
    v = validate(two_room_plan, mutate(valid, breakit)["solution"],
                 valid["scale_m_per_raw"])
    assert any("window" in x for x in v["violations"])


def test_leaving_building_detected(valid, two_room_plan):
    def breakit(sol):
        sol["panels"][0]["loop_coords"][1] = [
            sol["panels"][0]["loop_coords"][0][0],
            sol["panels"][0]["loop_coords"][0][1] + 5.0]  # outside inner
    v = validate(two_room_plan, mutate(valid, breakit)["solution"],
                 valid["scale_m_per_raw"])
    assert any("leaves the building" in x for x in v["violations"])


def test_transitions_without_portal_detected(two_room_plan):
    """No door between the rooms: any cable into room B is illegal."""
    from hackhive_ps4.synthetic import make_row_plan

    plan = make_row_plan(2, seed=0)
    plan["door"] = __import__("shapely.geometry", fromlist=["box"]).box(
        -0.05, 1.0, 0.05, 1.8)  # decoy on the outer wall, not between rooms
    sol = {
        "mode": "optimized",
        "metrics": {"unroutable_rooms": []},
        "panels": [{
            "panel_room": "room_0",
            "panel_position": [1.5, 1.5],
            "assigned_rooms": ["room_0", "room_1"],
            "device_order": ["room_0", "room_1"],
            "loop_coords": [[1.5, 1.5], [5.5, 1.5], [5.5, 2.2], [1.5, 2.2],
                            [1.5, 1.5]],
            "loop_valid": True,
        }],
    }
    v = validate(plan, sol, 1.0)
    assert v["checks"]["legal_transitions"] is False
    assert v["checks"]["physical_routes"] is False
    assert any("without a portal" in x for x in v["violations"])
