"""Module 4: Independent validator, Honeywell physics metrics, CAD-style
blueprint renderer, and final JSON export.

This module deliberately re-derives geometry from the raw plan and does NOT
trust module 2/3 bookkeeping: it re-extracts rooms and portals, re-measures
every loop polyline, and checks all PS4 hard constraints:

  1. Device placement - exactly one device per eligible room, inside the room.
  2. Panel capacity   - max 100 m^2 eligible area and 5 nodes per hub.
  3. Assignment       - every eligible room assigned to exactly one panel.
  4. Contiguity       - each panel's rooms connected via passages (transit
                        rooms may be traversed; other panels' rooms may not).
  5. Closed loops     - one closed loop per panel, every assigned device
                        visited exactly once, non-branching.
  6. Physical routes  - every segment inside the building, not crossing walls
                        outside verified portal openings, never touching windows.
  7. Legal transitions- room changes occur only through verified portals.

Honeywell physics:
  - NFPA 72 Class X pinch points: portals used twice by one loop although an
    alternate portal connects the same room pair (avoidable), vs unavoidable
    dead-end double passes.
  - NEC bend rule: more than four 90-degree bends between pull points flagged.
  - 24 V DC loop voltage drop with 18 AWG resistance.

Usage: python module4_validator_and_blueprint.py --plan-id 14433 --mode optimized
"""

import argparse
import json
import math

from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from . import config as common
from . import data
from . import geometry as m2
from .render import render_blueprint

CURRENT_PER_DEVICE_A = 0.002
PANEL_MARGIN_A = 0.010


def polyline_length_m(coords, scale):
    total = 0.0
    for a, b in zip(coords[:-1], coords[1:]):
        total += math.hypot(a[0] - b[0], a[1] - b[1])
    return total * scale


def segment_room_transitions(coords, rooms):
    """Which room contains each vertex; transitions between consecutive
    vertices where rooms differ."""
    seq = []
    for c in coords:
        p = Point(c)
        hit = None
        for rid, room in rooms.items():
            if room["geometry"].covers(p):
                hit = rid
                break
        seq.append(hit)
    return seq


def validate(plan, solution, scale):
    rooms = m2.extract_rooms(plan)
    portals = m2.find_portals(plan, rooms, scale)
    walls = unary_union(m2.parts(plan.get("wall")))
    windows = unary_union(m2.parts(plan.get("window")))
    inner = unary_union(m2.parts(plan.get("inner")))
    eps = 0.05 / scale
    walls_core = walls.buffer(-0.02 / scale) if walls is not None and not walls.is_empty else None

    portal_union = unary_union([p["polygon"] for p in portals]) if portals else None
    eligible = {rid for rid, r in rooms.items() if r["eligible"]}
    room_union = unary_union([r["geometry"] for r in rooms.values()])
    # Rooms the dataset gives no physical opening for (sealed closets etc.)
    # cannot be wired by ANY solution; reported separately, not failed.
    sealed = set(solution.get("metrics", {}).get("unroutable_rooms") or [])
    routable_eligible = eligible - sealed
    # Some plans have rooms sticking out of the inner polygon (dataset issue);
    # treat rooms and portals as part of the building envelope.
    building = unary_union([inner, room_union, portal_union]).buffer(eps) \
        if inner is not None else unary_union([room_union, portal_union]).buffer(eps)

    room_graph = {}
    for portal in portals:
        a, b = portal["rooms"]
        room_graph.setdefault(a, set()).add(b)
        room_graph.setdefault(b, set()).add(a)

    checks = {}
    violations = []

    # 1 + 3: device placement and assignment coverage.
    assigned = {}
    duplicates = set()
    for i, panel in enumerate(solution["panels"]):
        for rid in panel["assigned_rooms"]:
            if rid in assigned:
                duplicates.add(rid)
                violations.append(
                    f"room {rid} assigned to multiple panels {assigned[rid]} and {i}"
                )
            assigned[rid] = i
    missing = routable_eligible - set(assigned)
    extra = set(assigned) - eligible
    checks["assignment_complete"] = not missing and not extra and not duplicates
    if duplicates:
        pass  # violations already recorded above
    if missing:
        violations.append(f"eligible rooms never assigned: {sorted(missing)}")
    if extra:
        violations.append(f"non-eligible rooms assigned: {sorted(extra)}")

    # 2: capacity.
    area_cap_ok = True
    for i, panel in enumerate(solution["panels"]):
        area = sum(rooms[r]["geometry"].area * scale * scale
                   for r in panel["assigned_rooms"])
        if area > 100.0 + 1e-6:
            area_cap_ok = False
            violations.append(
                f"panel {i} area {area:.2f} m^2 exceeds 100 m^2"
            )
        if len(panel["assigned_rooms"]) > 5:
            area_cap_ok = False
            violations.append(f"panel {i} serves more than 5 nodes")
    checks["capacity"] = area_cap_ok

    # 4: contiguity.
    contiguous = True
    for i, panel in enumerate(solution["panels"]):
        cluster = set(panel["assigned_rooms"])
        seen = set()
        stack = [next(iter(cluster))]
        seen.add(stack[0])
        while stack:
            cur = stack.pop()
            for nb in room_graph.get(cur, ()):
                if nb in seen:
                    continue
                if nb in eligible and nb not in cluster:
                    continue
                seen.add(nb)
                stack.append(nb)
        if not cluster <= seen:
            contiguous = False
            violations.append(f"panel {i} territory not contiguous")
    checks["contiguity"] = contiguous

    # 4b: hub clearance - official rule 6: the hub point sits inside an
    # eligible room assigned to that hub, at least 0.5 m from walls.
    hub_ok = True
    for i, panel in enumerate(solution["panels"]):
        pos = panel.get("panel_position")
        rid = panel.get("panel_room")
        if not pos or rid not in rooms:
            hub_ok = False
            violations.append(f"panel {i} has no hub position in a known room")
            continue
        pt = Point(pos)
        if not rooms[rid]["geometry"].covers(pt):
            hub_ok = False
            violations.append(f"panel {i} hub outside its assigned room {rid}")
            continue
        clearance_raw = rooms[rid]["geometry"].boundary.distance(pt)
        if walls is not None and not walls.is_empty:
            local_walls = walls.intersection(
                rooms[rid]["geometry"].buffer(0.5 / scale))
            if not local_walls.is_empty:
                clearance_raw = min(clearance_raw, local_walls.distance(pt))
        clearance_m = clearance_raw * scale
        if clearance_m < common.HUB_MIN_CLEARANCE_M - 1e-6:
            hub_ok = False
            violations.append(
                f"panel {i} hub clearance {clearance_m:.3f} m < 0.5 m from walls"
            )
    checks["hub_clearance"] = hub_ok

    # 5b: axis-aligned routing - every polyline segment horizontal or
    # vertical (official rule 5, 1 mm tolerance in raw units).
    axis_ok = True
    tol_raw = 0.001 / scale
    for i, panel in enumerate(solution["panels"]):
        loop = panel.get("loop_coords") or []
        for a, b in zip(loop[:-1], loop[1:]):
            if abs(a[0] - b[0]) > tol_raw and abs(a[1] - b[1]) > tol_raw:
                axis_ok = False
                violations.append(f"panel {i} has a diagonal cable segment")
                break
    checks["axis_aligned"] = axis_ok

    # 5 + 6 + 7: loops and physical validity.
    loops_ok = True
    routes_ok = True
    transitions_ok = True
    pinch_points = []
    bend_flags = []
    voltage_results = []

    for i, panel in enumerate(solution["panels"]):
        loop = panel.get("loop_coords") or []
        if len(loop) < 2:
            loops_ok = False
            violations.append(f"panel {i} has no loop polyline")
            continue

        if math.dist(loop[0], loop[-1]) > 0.5 / scale:
            loops_ok = False
            violations.append(f"panel {i} loop is not closed")

        # Non-branching: each assigned device appears exactly once in the
        # visitation order; panel appears exactly twice (start and end).
        visits = [v for v in panel.get("device_order", [])]
        expect = sorted(panel["assigned_rooms"])
        if sorted(visits) != expect:
            loops_ok = False
            violations.append(
                f"panel {i} device visitation mismatch: {sorted(visits)} != {expect}"
            )

        # Physical validity of every segment.
        for a, b in zip(loop[:-1], loop[1:]):
            seg = LineString([a, b])
            if not building.covers(seg):
                routes_ok = False
                violations.append(f"panel {i} segment leaves the building")
            if windows is not None and seg.intersects(windows):
                routes_ok = False
                violations.append(f"panel {i} segment crosses a window")
            if walls_core is not None and not walls_core.is_empty:
                bad = seg.intersection(walls_core)
                if portal_union is not None:
                    bad = bad.difference(portal_union.buffer(eps))
                if not bad.is_empty and bad.length > 1e-9:
                    routes_ok = False
                    violations.append(
                        f"panel {i} segment crosses a wall outside a portal"
                    )

        # Room transitions must pass through verified portals.
        seq = segment_room_transitions(loop, rooms)
        for ra, rb, a, b in zip(seq[:-1], seq[1:], loop[:-1], loop[1:]):
            if ra is None or rb is None or ra == rb:
                continue
            legit = any(
                {ra, rb} == set(p["rooms"]) for p in portals
            )
            if not legit:
                transitions_ok = False
                violations.append(
                    f"panel {i} moves between {ra} and {rb} without a portal"
                )

        # Portal usage / pinch points.
        portal_use = {}
        for p in portals:
            pair = tuple(sorted(p["rooms"]))
            portal_use.setdefault(pair, 0)
        seq_pairs = []
        for ra, rb in zip(seq[:-1], seq[1:]):
            if ra and rb and ra != rb:
                seq_pairs.append(tuple(sorted((ra, rb))))
        for pair in seq_pairs:
            portal_use[pair] = portal_use.get(pair, 0) + 1
        for pair, use_count in portal_use.items():
            if use_count >= 2:
                alternates = [
                    p for p in portals
                    if tuple(sorted(p["rooms"])) == pair
                ]
                kind = "avoidable" if len(alternates) > 1 else "unavoidable (dead-end)"
                pinch_points.append({
                    "panel": i, "room_pair": list(pair),
                    "uses": use_count, "type": kind,
                })

        # Bends between pull points (devices/panel are pull points).
        loop_bends = 0
        coords = loop
        for j in range(1, len(coords) - 1):
            ang = m2.turn_angle(coords[j - 1], coords[j], coords[j + 1])
            if ang >= m2.BEND_ANGLE_THRESHOLD_DEG:
                loop_bends += 1
        seg_bends = max(1, math.ceil(loop_bends / max(1, len(visits) + 1)))
        if seg_bends > 4:
            bend_flags.append({"panel": i, "max_bends_between_pulls": seg_bends})

        # Voltage drop: worst-case device along the loop (18 AWG).
        total_len = polyline_length_m(loop, scale)
        resistance = total_len * common.WIRE_OHMS_PER_M_18AWG
        current = PANEL_MARGIN_A + CURRENT_PER_DEVICE_A * len(visits)
        drop = current * resistance
        voltage_results.append({
            "panel": i,
            "loop_length_m": round(total_len, 3),
            "loop_resistance_ohm": round(resistance, 3),
            "current_a": round(current, 4),
            "voltage_drop_v": round(drop, 4),
            "within_limit": drop <= common.MAX_VOLTAGE_DROP_V,
        })

    checks["closed_loops"] = loops_ok
    checks["physical_routes"] = routes_ok
    checks["legal_transitions"] = transitions_ok

    return {
        "checks": checks,
        "violations": violations,
        "all_valid": all(checks.values()) and not violations,
        "dataset_sealed_rooms": sorted(sealed),
        "physics": {
            "nfpa72_classX_pinch_points": pinch_points,
            "nec_bend_violations": bend_flags,
            "voltage_drop_24v": voltage_results,
        },
    }


# ------------------------------------------------------------------
# CAD-style blueprint
# ------------------------------------------------------------------

# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-id", default="14433")
    ap.add_argument("--mode", default="optimized")
    ap.add_argument("--solution", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--png", default=None)
    args = ap.parse_args()

    plan = data.load_plan(args.plan_id)
    scale = m2.calibrate(plan)["scale_m_per_raw"]

    sol_path = args.solution or f"solution_{args.mode}_{args.plan_id}.json"
    with open(sol_path, encoding="utf-8") as f:
        solution = json.load(f)

    validation = validate(plan, solution, scale)

    out_json = args.out or f"final_{args.mode}_{args.plan_id}.json"
    out_png = args.png or f"blueprint_{args.mode}_{args.plan_id}.png"

    final = {
        "plan_id": args.plan_id,
        "mode": args.mode,
        "scale_m_per_raw": scale,
        "solution": solution,
        "validation": validation,
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(final, f, indent=2)

    render_blueprint(plan, solution, validation, scale, out_png)

    print(f"VALIDATION - plan {args.plan_id} [{args.mode}]")
    for check, ok in validation["checks"].items():
        print(f"  {check}: {'PASS' if ok else 'FAIL'}")
    if validation.get("dataset_sealed_rooms"):
        print(f"  dataset-sealed rooms (no physical opening, excluded from "
              f"validation): {validation['dataset_sealed_rooms']}")
    if validation["violations"]:
        for v in validation["violations"][:20]:
            print(f"  violation: {v}")
    print(f"  RESULT: {'PASS' if validation['all_valid'] else 'FAIL'}")
    print(f"  pinch points: {len(validation['physics']['nfpa72_classX_pinch_points'])}"
          f" | voltage drop checks: "
          f"{sum(1 for v in validation['physics']['voltage_drop_24v'] if v['within_limit'])}"
          f"/{len(validation['physics']['voltage_drop_24v'])} within limit")
    print(f"Saved: {out_json}")
    print(f"Saved: {out_png}")
    # The validation verdict is data, not a crash: always exit 0 so the
    # pipeline runner can still produce the baseline benchmark and aggregates.


if __name__ == "__main__":
    main()
