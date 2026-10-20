"""Official cost metric tests (hackhive_ps4.scoring, J = L + 5X + O + 0.5B)."""

import pytest

from hackhive_ps4.scoring import (compute_metrics, direction_change,
                                  line_key, merge_intervals,
                                  overlap_on_line, perpendicular_crossing,
                                  segments_of_leg)


def make_sub(legs):
    """Single-hub submission at (0,0) from ordered leg polylines."""
    return {
        "plan_id": "t", "units": "m",
        "hubs": [{
            "hub_id": "H1", "room_id": "r",
            "location": {"x": legs[0][0][0], "y": legs[0][0][1]},
            "assigned_rooms": [], "assigned_nodes": [],
            "closed_sequence": [],
            "route_segments": [
                {"from": "A", "to": "B", "length_m": 0.0, "polyline": leg}
                for leg in legs],
            "ring_length_m": 0.0,
        }],
        "reported_metrics": {"hub_count": 1, "total_length_m": 0.0},
    }


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def test_line_key():
    assert line_key(((0, 1), (5, 1))) == ("h", 1000)
    assert line_key(((2, 0), (2, 7))) == ("v", 2000)
    assert line_key(((0, 0), (1, 1))) is None  # diagonal -> invalid


def test_segments_of_leg_drops_slivers():
    segs = segments_of_leg({"polyline": [(0, 0), (0, 0), (3, 0), (3, 0), (3, 2)]})
    assert segs == [((0.0, 0.0), (3.0, 0.0)), ((3.0, 0.0), (3.0, 2.0))]


def test_merge_intervals():
    assert merge_intervals([]) == []
    assert merge_intervals([(0, 2), (2, 4)]) == [[0, 4]]      # touching
    assert merge_intervals([(0, 3), (2, 4)]) == [[0, 4]]      # overlapping
    assert merge_intervals([(0, 1), (3, 4), (1.5, 2)]) == [[0, 1], [1.5, 2], [3, 4]]


def test_overlap_on_line_depth():
    assert overlap_on_line([(0, 4), (0, 4)]) == pytest.approx(4.0)   # k=2
    assert overlap_on_line([(0, 4), (0, 4), (0, 4)]) == pytest.approx(8.0)  # k=3
    assert overlap_on_line([(0, 2), (2, 4)]) == pytest.approx(0.0)   # touching
    assert overlap_on_line([(0, 1), (5, 6)]) == pytest.approx(0.0)   # disjoint
    assert overlap_on_line([(0, 4), (2, 3)]) == pytest.approx(1.0)   # nested


def test_perpendicular_crossing():
    assert perpendicular_crossing(((0, 0), (10, 0)), ((5, -4), (5, 6))) == (5.0, 0.0)
    assert perpendicular_crossing(((0, 0), (4, 0)), ((5, -4), (5, 6))) is None
    assert perpendicular_crossing(((0, 0), (10, 0)), ((0, 1), (10, 1))) is None
    assert perpendicular_crossing(((0, 0), (10, 0)), ((0, 0), (0, 5))) == (0.0, 0.0)


def test_direction_change():
    assert direction_change((0, 0), (1, 0), (2, 0)) == pytest.approx(0.0)
    assert direction_change((0, 0), (1, 0), (1, 1)) == pytest.approx(90.0)
    assert direction_change((0, 0), (1, 0), (0, 0)) == pytest.approx(180.0)


# ------------------------------------------------------------------
# metric end-to-end on hand-built rings
# ------------------------------------------------------------------

def test_l_only_square_ring():
    # H(0,0) -> square ring back to H. L=8, B=4, X=0, O=0 -> J=10.
    m = compute_metrics(make_sub([[(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)]]))
    assert m["L"] == pytest.approx(8.0)
    assert m["B"] == 4
    assert m["X"] == 0
    assert m["O"] == pytest.approx(0.0)
    assert m["J"] == pytest.approx(8.0 + 0.5 * 4)


def test_perpendicular_crossing_counts_once():
    # leg1 runs y=0 x in [0,10]; leg2 dives and crosses it at (5,0) away
    # from any node -> exactly one crossing.
    m = compute_metrics(make_sub([
        [(0, 0), (10, 0)],
        [(10, 0), (10, -4), (5, -4), (5, 6), (0, 6), (0, 0)],
    ]))
    assert m["X"] == 1
    assert m["O"] == pytest.approx(0.0)
    assert m["L"] == pytest.approx(40.0)
    assert m["B"] == 6
    assert m["J"] == pytest.approx(40.0 + 5.0 + 0.5 * 6)


def test_same_line_retrace_counts_overlap_not_crossing():
    # Pure out-and-back on the same line: O = 4 (k=2 x 4 m), X = 0,
    # two 180-degree reversals (hub + node) -> B = 2.
    m = compute_metrics(make_sub([[(0, 0), (4, 0)], [(4, 0), (0, 0)]]))
    assert m["O"] == pytest.approx(4.0)
    assert m["X"] == 0
    assert m["B"] == 2
    assert m["J"] == pytest.approx(8.0 + 4.0 + 1.0)


def test_parallel_offset_retrace_is_free():
    # Door-offset retrace: the return runs on a parallel line 0.16 m away
    # -> O = 0, X = 0 (the two junctions are node/hub points).
    m = compute_metrics(make_sub([
        [(0, 0), (4, 0)],
        [(4, 0), (4, 0.16), (0.16, 0.16), (0, 0.16), (0, 0)],
    ]))
    assert m["O"] == pytest.approx(0.0)
    assert m["X"] == 0
    assert m["L"] == pytest.approx(8.32)
    assert m["J"] == pytest.approx(8.32 + 0.5 * 4)


def test_two_hubs_cross_rings_count():
    # Two hubs whose rings cross once away from nodes/hubs.
    sub = {
        "plan_id": "t", "units": "m",
        "hubs": [
            {"hub_id": "H1", "room_id": "r", "location": {"x": 0, "y": 0},
             "assigned_rooms": [], "assigned_nodes": [], "closed_sequence": [],
             "route_segments": [
                 {"from": "H1", "to": "H1", "length_m": 0.0,
                  "polyline": [(0, 0), (10, 0), (10, 1), (0, 1), (0, 0)]}],
             "ring_length_m": 0.0},
            {"hub_id": "H2", "room_id": "r", "location": {"x": 2, "y": -5},
             "assigned_rooms": [], "assigned_nodes": [], "closed_sequence": [],
             "route_segments": [
                 {"from": "H2", "to": "H2", "length_m": 0.0,
                  "polyline": [(2, -5), (2, 5), (2.5, 5), (2.5, -5), (2, -5)]}],
             "ring_length_m": 0.0},
        ],
        "reported_metrics": {"hub_count": 2, "total_length_m": 0.0},
    }
    m = compute_metrics(sub)
    # H2 spans y in [-5, 5] across both of H1's horizontals (y=0, y=1),
    # with two verticals (x=2, x=2.5): 4 clean between-ring crossings.
    assert m["X"] == 4
    assert m["J"] == pytest.approx(m["L"] + 5.0 * 4 + m["O"] + 0.5 * m["B"])


def test_diagonal_polyline_raises():
    with pytest.raises(ValueError, match="diagonal"):
        compute_metrics(make_sub([[(0, 0), (1, 1), (2, 1), (0, 0)]]))
