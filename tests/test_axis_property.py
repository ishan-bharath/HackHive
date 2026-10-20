"""Property test: generated plans always produce axis-aligned valid rings."""

import pytest

from helpers import assert_axis_aligned
from hackhive_ps4.synthetic import make_row_plan, run_full


@pytest.mark.parametrize("n_rooms,seed", [(2, 0), (2, 7), (3, 1), (4, 2),
                                          (5, 3), (5, 11)])
def test_generated_plans_are_valid_and_axis_aligned(n_rooms, seed):
    plan = make_row_plan(n_rooms, seed=seed)
    report, fo, fb = run_full(plan)
    assert fo["validation"]["all_valid"] is True, fo["validation"]["violations"]
    assert fb["validation"]["all_valid"] is True, fb["validation"]["violations"]
    assert_axis_aligned(fo)
    assert_axis_aligned(fb)
    # every submitted polyline axis-aligned too (metres)
    from hackhive_ps4.export import export
    sub = export(str(plan["id"]), fo, report)
    for h in sub["hubs"]:
        for seg in h["route_segments"]:
            assert_axis_aligned({"solution": {"panels": [{"loop_coords":
                                                          seg["polyline"]}]}},
                                tol=1e-6)


def test_node_cap_never_exceeded(two_room_artifacts):
    for panel in two_room_artifacts[1]["solution"]["panels"]:
        assert len(panel["assigned_rooms"]) <= 5
    for panel in two_room_artifacts[2]["solution"]["panels"]:
        assert len(panel["assigned_rooms"]) <= 5
