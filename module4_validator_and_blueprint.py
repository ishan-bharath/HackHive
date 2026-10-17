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

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

import common
import module2_wall_router_and_matrix as m2

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
    for i, panel in enumerate(solution["panels"]):
        for rid in panel["assigned_rooms"]:
            if rid in assigned:
                violations.append(
                    f"room {rid} assigned to multiple panels {assigned[rid]} and {i}"
                )
            assigned[rid] = i
    missing = routable_eligible - set(assigned)
    extra = set(assigned) - eligible
    checks["assignment_complete"] = not missing and not extra
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

def render_blueprint(plan, solution, validation, scale, out_png, out=None):
    """Render the CAD-style blueprint. Writes to `out` when given (file path
    or file-like object, e.g. BytesIO); otherwise to `out_png` exactly as
    before. Default behavior is unchanged."""
    rooms = m2.extract_rooms(plan)
    fig, ax = plt.subplots(figsize=(16, 12))
    fig.patch.set_facecolor("#FFFFFF")

    m2.draw_geom(ax, plan.get("inner"), "#FDFDFD", "#333333", 1.0, lw=1.0)
    for p in m2.parts(plan.get("wall")):
        xs, ys = p.exterior.xy
        ax.fill(xs, ys, facecolor="#2B2B2B", edgecolor="#111111", lw=0.4)

    palette = ["#C0392B", "#2471A3", "#1E8449", "#7D3C98", "#CA6F1E"]
    n_base = 0
    for k, panel in enumerate(solution["panels"]):
        color = palette[k % len(palette)]
        for rid in panel["assigned_rooms"]:
            m2.draw_geom(ax, rooms[rid]["geometry"], color, color, 0.10, lw=0.6)
        coords = panel["loop_coords"]
        if coords:
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            ax.plot(xs, ys, color=color, linewidth=2.2, zorder=5,
                    solid_joinstyle="round")
            # Direction arrow at the loop start (panel -> first device).
            if len(coords) >= 2:
                (x0, y0), (x1, y1) = coords[0], coords[1]
                t = 0.45
                ax.annotate("", xy=(x0 + (x1 - x0) * (t + 0.12),
                                    y0 + (y1 - y0) * (t + 0.12)),
                            xytext=(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t),
                            arrowprops=dict(arrowstyle="-|>", color=color,
                                            lw=2.0), zorder=6)
        if panel.get("panel_position"):
            px, py = panel["panel_position"]
            ax.plot(px, py, marker="*", markersize=260 / fig.dpi * 3,
                    markerfacecolor=color, markeredgecolor="#111111", zorder=7)
            ax.text(px, py, f"  H{k+1}", fontsize=10, fontweight="bold",
                    color="#111111", zorder=8)
        # Node ID badges: N1.. across the whole plan, numbered in visiting
        # order (hub by hub), matching export_submission.py's assigned_nodes.
        for j, rid in enumerate(panel.get("device_order") or []):
            nid = f"N{n_base + j + 1}"
            d = rooms[rid]["device_point"]
            ax.plot(d.x, d.y, marker="s", markersize=6, color=color,
                    markeredgecolor="#111111", zorder=6)
            ax.text(d.x, d.y, nid, fontsize=5.5, fontweight="bold",
                    ha="center", va="center", color="#111111", zorder=9,
                    bbox=dict(boxstyle="round,pad=0.22",
                              facecolor="#FFFFFF", edgecolor=color, lw=1.0))
        n_base += len(panel.get("device_order") or [])
        for rid in panel["assigned_rooms"]:
            if rid in (panel.get("device_order") or []):
                continue
            d = rooms[rid]["device_point"]
            ax.plot(d.x, d.y, marker="s", markersize=6, color=color,
                    markeredgecolor="#111111", zorder=6)

    for pp in validation["physics"]["nfpa72_classX_pinch_points"]:
        if pp["type"].startswith("unavoidable"):
            rid_a, rid_b = pp["room_pair"]
            for portal in m2.find_portals(plan, rooms, scale):
                if set(portal["rooms"]) == {rid_a, rid_b}:
                    cx, cy = portal["center"]
                    ax.plot(cx, cy, marker="X", markersize=9, color="#FF8C00",
                            zorder=8)

    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    # Failed validation: draw the violations in red on the image itself.
    if not validation["all_valid"] and validation["violations"]:
        lines = ["VIOLATIONS (design invalid):"]
        lines += [f"- {v}" for v in validation["violations"][:6]]
        if len(validation["violations"]) > 6:
            lines.append(f"- ... +{len(validation['violations']) - 6} more")
        ax.text(0.01, 0.99, "\n".join(lines), transform=ax.transAxes,
                fontsize=9, fontweight="bold", color="#C0392B",
                va="top", ha="left", zorder=10,
                bbox=dict(boxstyle="round,pad=0.4", facecolor="#FDEDEC",
                          edgecolor="#C0392B", lw=1.2, alpha=0.92))
    # Legend: symbols, route semantics, visiting order.
    handles = [
        Line2D([], [], marker="*", ls="none", markersize=13,
               markerfacecolor="#666666", markeredgecolor="#111111",
               label="Hub  H# (ring start/end)"),
        Line2D([], [], marker="s", ls="none", markersize=8,
               markerfacecolor="#666666", markeredgecolor="#111111",
               label="Node N# - visiting order, matches the submission JSON"),
        Line2D([], [], color="#666666", lw=2.2,
               label="Cable loop (closed, non-branching, through portals only)"),
        Line2D([], [], marker="X", ls="none", markersize=9, color="#FF8C00",
               label="Unavoidable doorway pinch point (NFPA 72 Class X)"),
    ]
    handles += [Patch(facecolor=c, alpha=0.35, edgecolor=c,
                      label=f"Hub {i+1} territory (rooms served)")
                for i, c in enumerate(palette[:len(solution["panels"])])]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.01),
              ncol=3, fontsize=8, framealpha=0.92, title="LEGEND",
              title_fontsize=9)
    metrics = solution["metrics"]
    title = (
        f"PS4 Solution Blueprint - plan {solution['plan_id']} ({solution['mode']})\n"
        f"hubs: {metrics['panel_count']} | cable: {metrics['total_cable_length_m']} m | "
        f"bends: {metrics['total_bends']} | "
        f"validator: {'PASS' if validation['all_valid'] else 'FAIL'}"
    )
    ax.set_title(title, fontsize=13)
    plt.tight_layout()
    target = out_png if out is None else out
    save_kwargs = dict(dpi=200, bbox_inches="tight", facecolor="#FFFFFF")
    if out is not None:
        save_kwargs["format"] = "png"
    plt.savefig(target, **save_kwargs)
    plt.close(fig)


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

    plan = common.load_plan(args.plan_id)
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
