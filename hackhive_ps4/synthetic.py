"""Synthetic rectilinear floor plans for tests and CI smoke runs.

Builds small axis-aligned plans (no dataset needed) that exercise the full
pipeline: calibration, portal verification, routing, partitioning, ring
sequencing, validation. Rooms are laid out in a row; consecutive rooms are
separated by a wall strip pierced by exactly one door.
"""

import random

import networkx as nx
from shapely.geometry import box
from shapely.ops import unary_union

from .data import json_to_plan

WALL_HALF = 0.1   # wall strips are 0.2 raw units thick
DOOR_HALF_W = 0.1  # door is 0.2 wide in x (pierces the wall strip)
DOOR_LEN = 0.8     # door length along the wall (y)


def make_row_plan(n_rooms=2, seed=0, room_h=3.0, widths=None):
    """Row plan: n_rooms rooms side by side, one door between each pair.

    Scale is 1 raw unit = 1 m by construction (area == inner.area).
    Returns the plan dict (networkx graph + shapely geometries).
    """
    rng = random.Random(seed)
    if widths is None:
        widths = [rng.uniform(3.0, 5.0) for _ in range(n_rooms)]
    room_h = float(room_h)

    xs = [0.0]
    for w in widths:
        xs.append(xs[-1] + w)
    total_w = xs[-1]

    inner = box(0.0, 0.0, total_w, room_h)

    # Wall strips: outer boundary + one strip per interior boundary.
    strips = [
        box(0.0, 0.0, total_w, WALL_HALF),
        box(0.0, room_h - WALL_HALF, total_w, room_h),
        box(0.0, 0.0, WALL_HALF, room_h),
        box(total_w - WALL_HALF, 0.0, total_w, room_h),
    ]
    boundaries = xs[1:-1]
    for bx in boundaries:
        strips.append(box(bx - WALL_HALF, 0.0, bx + WALL_HALF, room_h))
    walls = unary_union(strips)

    # Doors: one per interior boundary, at a seeded y offset.
    doors = []
    for bx in boundaries:
        y0 = rng.uniform(0.5, room_h - 0.5 - DOOR_LEN)
        doors.append(box(bx - DOOR_HALF_W, y0, bx + DOOR_HALF_W, y0 + DOOR_LEN))
    door_geom = unary_union(doors) if len(doors) > 1 else doors[0]

    # Rooms: exact tiles between boundaries.
    types = ["living", "bedroom", "kitchen", "storage"]
    graph = nx.Graph()
    rooms = []
    for i in range(n_rooms):
        rid = f"room_{i}"
        poly = box(xs[i], 0.0, xs[i + 1], room_h)
        graph.add_node(rid, type=types[i % len(types)], geometry=poly)
        rooms.append(poly)
        if i > 0:
            graph.add_edge(f"room_{i - 1}", rid, type="via_door")

    plan = {
        "id": f"synthetic_{n_rooms}_{seed}",
        "area": inner.area,  # scale = sqrt(inner.area / area) = 1.0 m per unit
        "wall_depth": 2 * WALL_HALF,
        "inner": inner,
        "wall": walls,
        "door": door_geom,
        "window": box(0.0, -0.001, 1.0, 0.02),  # on the outer bottom wall
        "frontdoor": box(-0.001, room_h - 1.0, 0.02, room_h),
        "graph": graph,
    }
    return plan


def make_row_plan_jsonable(n_rooms=2, seed=0):
    """JSON-serializable variant (round-trips through data.json_to_plan)."""
    from .data import plan_to_jsonable

    return plan_to_jsonable(make_row_plan(n_rooms, seed))


def run_full(plan):
    """Run the full pipeline in-process on a plan dict.

    Returns (matrix, final_optimized, final_baseline) dicts (validation
    included), mirroring what the CLI pipeline writes to disk."""
    from .matrices import build_report
    from .optimize import baseline_solution, optimized_solution
    from .validate import validate

    plan_id = str(plan.get("id", "synthetic"))
    report = build_report(plan, plan_id)
    scale = report["calibration"]["scale_m_per_raw"]
    base = baseline_solution(plan, report, scale)
    opt = optimized_solution(plan, report, scale)
    final_opt = {
        "plan_id": plan_id, "mode": "optimized",
        "scale_m_per_raw": scale,
        "solution": opt, "validation": validate(plan, opt, scale),
    }
    final_base = {
        "plan_id": plan_id, "mode": "baseline",
        "scale_m_per_raw": scale,
        "solution": base, "validation": validate(plan, base, scale),
    }
    return report, final_opt, final_base


def plan_from_json(d):
    """Rehydrate a plan dict from its JSON-serializable form."""
    return json_to_plan(d)
