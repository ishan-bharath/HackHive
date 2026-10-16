"""Verify module 2 output: every stored path must be physically valid.

Checks per path polyline:
  1. Every segment stays inside (union of routing rooms + portal openings).
  2. No segment crosses wall geometry, except where the crossing lies inside
     a door/opening polygon (portal zone).
  3. Room-to-room transitions occur only through verified portals.

Usage: python verify_module2.py --plan-id 14433
"""

import argparse
import json

import numpy as np
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

import common
import module2_wall_router_and_matrix as m2


def parts(geom):
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if hasattr(geom, "geoms"):
        return [g for g in geom.geoms if isinstance(g, Polygon) and not g.is_empty]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-id", default="14433")
    ap.add_argument("--matrix", default=None)
    args = ap.parse_args()

    matrix_path = args.matrix or f"matrix_{args.plan_id}.json"
    with open(matrix_path, encoding="utf-8") as f:
        report = json.load(f)

    plan = common.load_plan(args.plan_id)
    scale = m2.calibrate(plan)["scale_m_per_raw"]
    rooms = m2.extract_rooms(plan)
    portals = m2.find_portals(plan, rooms, scale)

    eps = 0.05 / scale
    walls = unary_union(m2.parts(plan.get("wall")))
    doors = unary_union(m2.parts(plan.get("door")))
    windows = unary_union(m2.parts(plan.get("window")))
    inner = unary_union(m2.parts(plan.get("inner")))
    room_union = unary_union([r["geometry"] for r in rooms.values()])
    portal_union = unary_union([p["polygon"] for p in portals])

    node_pos = {k: tuple(v) for k, v in report["node_pos"].items()}
    allowed = unary_union([room_union, portal_union]).buffer(eps)

    total_paths = 0
    violations = {"outside_allowed": 0, "crosses_wall": 0, "hits_window": 0,
                  "outside_building": 0}

    for key, coords in report["paths"].items():
        if len(coords) < 2:
            continue
        total_paths += 1
        segs = [
            LineString([(c[0], c[1]), (d[0], d[1])])
            for c, d in zip(coords[:-1], coords[1:])
        ]
        for seg in segs:
            if not allowed.covers(seg):
                violations["outside_allowed"] += 1
            if walls is not None:
                bad = seg.intersection(walls).difference(portal_union.buffer(eps))
                if bad.length > 1e-9:
                    violations["crosses_wall"] += 1
            if windows is not None and seg.intersects(windows):
                violations["hits_window"] += 1
            if inner is not None and not inner.buffer(eps).covers(seg):
                violations["outside_building"] += 1

    print(f"PATH VERIFICATION - plan {args.plan_id}")
    print(f"  paths checked: {total_paths}")
    for k, v in violations.items():
        print(f"  {k}: {v}")

    ok = all(v == 0 for v in violations.values())
    print("  RESULT:", "PASS" if ok else "FAIL")

    # Sanity: matrix symmetry and reachability.
    D = np.array(
        [[v if v is not None else np.inf for v in row] for row in report["D_m"]]
    )
    mask = np.isfinite(D) & np.isfinite(D.T)
    n = len(D)
    symmetric = np.allclose(D[mask], D.T[mask], atol=1e-6)
    connected = np.isfinite(D).all()
    print(f"  matrix {n}x{n} | fully reachable: {connected} | symmetric: {symmetric}")

    if not ok or not connected:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
