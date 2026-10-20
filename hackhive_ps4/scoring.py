"""compute_cost.py - official PS4 ranking metric from submitted polylines.

J = L + 5*X + O + 0.5*B   (slide 6/7 of docs/"Cable Ring Challenge - Problem
Statement4.pptx"; the checker recomputes every metric from the polylines).

  L  cable length: sum of every leg polyline of every ring, return legs
     included (metres).
  X  crossings (5 each): points where two cables meet away from a node or
     hub, inside one ring or between rings; counted once per point. Collinear
     overlaps are NOT crossings (they are O).
  O  overlap (1 per m): length where two legs run along the same line. A
     stretch covered by k legs counts (k-1) times its length. Parallel runs
     on DIFFERENT lines count 0 (our +/-8 cm door offsets make door retraces
     parallel-distinct, so they add nothing).
  B  bends (0.5 each): direction changes along each closed ring, vertices at
     nodes and the hub included; every turn is 90 deg, a reversal counts
     once. Threshold >= 45 deg, 1 mm tolerance throughout.

CLI:
  python compute_cost.py                       # all submissions/*.json
  python compute_cost.py --submission submissions/14433.json
Output: per-plan table + submissions/cost_summary.json.
"""

import argparse
import glob
import json
import math
import os

TOL = 0.001  # 1 mm: points closer than this are the same point, lines within
             # 1 mm of each other are the same line (slide 7).

EXCLUDED = {
    "1448": (
        "officially unsolvable under the mandated scale (living_0 = "
        "107.26 m2 > 100 m2 hub cap; rooms cannot be split across hubs per "
        "rule 1) - matches the organisers' out-of-benchmark guarantee. "
        "Final artifacts kept as evidence."
    ),
}


# ------------------------------------------------------------------
# Geometry helpers (axis-aligned segments in metres)
# ------------------------------------------------------------------

def segments_of_leg(leg):
    poly = leg["polyline"]
    segs = []
    for a, b in zip(poly[:-1], poly[1:]):
        if math.dist(a, b) > TOL:  # drop zero-length slivers
            segs.append((tuple(a), tuple(b)))
    return segs


def line_key(seg):  # -> tuple[str, int] | None
    (x1, y1), (x2, y2) = seg
    if abs(y1 - y2) <= TOL:
        return ("h", round(y1 / TOL))
    if abs(x1 - x2) <= TOL:
        return ("v", round(x1 / TOL))
    return None  # diagonal - invalid input, flagged by the axis gate


def merge_intervals(intervals: list) -> list:
    """Union of [s, e] intervals (same line)."""
    if not intervals:
        return []
    intervals = sorted(intervals)
    out = [list(intervals[0])]
    for s, e in intervals[1:]:
        if s <= out[-1][1] + TOL:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def overlap_on_line(intervals: list) -> float:
    """O contribution for one line: sweep with coverage depth k; a stretch
    covered by k legs counts (k-1) times its length."""
    events = []
    for s, e in intervals:
        events.append((s, 1))
        events.append((e, -1))
    events.sort()
    total = 0.0
    depth = 0
    for i in range(len(events) - 1):
        depth += events[i][1]
        width = events[i + 1][0] - events[i][0]
        if depth >= 2 and width > TOL:
            total += (depth - 1) * width
    return total


def perpendicular_crossing(seg_a, seg_b):  # -> tuple | None
    """Intersection point of a horizontal and a vertical segment, if any."""
    (ax1, ay1), (ax2, ay2) = seg_a
    (bx1, by1), (bx2, by2) = seg_b
    a_horiz = abs(ay1 - ay2) <= TOL
    b_horiz = abs(by1 - by2) <= TOL
    if a_horiz == b_horiz:
        return None
    h, v = (seg_a, seg_b) if a_horiz else (seg_b, seg_a)
    (hx1, hy1), (hx2, hy2) = h
    (vx1, vy1), (vx2, vy2) = v
    x_lo, x_hi = min(hx1, hx2) - TOL, max(hx1, hx2) + TOL
    y_lo, y_hi = min(vy1, vy2) - TOL, max(vy1, vy2) + TOL
    vx = (vx1 + vx2) / 2.0
    hy = (hy1 + hy2) / 2.0
    if x_lo <= vx <= x_hi and y_lo <= hy <= y_hi:
        return (vx, hy)
    return None


def direction_change(a, b, c) -> float:
    """Degrees of direction change at vertex b; reversal (180) counts as one
    bend, collinear continuation counts 0."""
    v1 = (b[0] - a[0], b[1] - a[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 < TOL or n2 < TOL:
        return 0.0
    dot = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


# ------------------------------------------------------------------
# Metric computation for one submission
# ------------------------------------------------------------------

def compute_metrics(sub: dict) -> dict:
    hub_pts = []
    for h in sub["hubs"]:
        hub_pts.append((h["location"]["x"], h["location"]["y"]))

    # Segments tagged with (hub_idx, leg_idx, seg_idx); node/hub points are
    # the chaining endpoints of legs (hub location + every node).
    all_segs = []      # (hub, leg, k, seg)
    node_pts = list(hub_pts)
    for hi, h in enumerate(sub["hubs"]):
        for li, leg in enumerate(h["route_segments"]):
            poly = leg["polyline"]
            if li == 0:
                node_pts.append((poly[0][0], poly[0][1]))
            node_pts.append((poly[-1][0], poly[-1][1]))
            for k, seg in enumerate(segments_of_leg(leg)):
                all_segs.append((hi, li, k, seg))

    # ---- L ----
    L = sum(math.dist(a, b) for _, _, _, (a, b) in all_segs)

    # ---- O ----
    # Intervals per (line, leg): a leg covering a stretch counts once, so
    # union its own collinear segments first.
    per_line: dict = {}
    for hi, h in enumerate(sub["hubs"]):
        for li, leg in enumerate(h["route_segments"]):
            by_line: dict = {}
            for seg in segments_of_leg(leg):
                key = line_key(seg)
                if key is None:
                    raise ValueError(f"diagonal segment in {sub['plan_id']}")
                (x1, y1), (x2, y2) = seg
                s, e = sorted((x1, x2)) if key[0] == "h" else sorted((y1, y2))
                by_line.setdefault(key, []).append((s, e))
            for key, ivs in by_line.items():
                for iv in merge_intervals(ivs):
                    per_line.setdefault(key, []).append(iv)
    O = sum((overlap_on_line(ivs) for ivs in per_line.values()), 0.0)

    # ---- X ----
    def is_node(pt):
        return any(math.dist(pt, q) <= TOL for q in node_pts)

    raw_points = []
    for i in range(len(all_segs)):
        hi, li, ki, si = all_segs[i]
        for j in range(i + 1, len(all_segs)):
            hj, lj, kj, sj = all_segs[j]
            if hi == hj and li == lj and abs(ki - kj) == 1:
                continue  # adjacent segments of one leg share a bend vertex
            ka, kb = line_key(si), line_key(sj)
            if ka == kb:
                continue  # same line -> overlap, not a crossing
            pt = perpendicular_crossing(si, sj)
            if pt is None or is_node(pt):
                continue
            raw_points.append(pt)
    # Distinct points: cluster within the 1 mm tolerance.
    pts: list = []
    for p in sorted(raw_points):
        if not any(math.dist(p, q) <= TOL for q in pts):
            pts.append(p)
    X = len(pts)

    # ---- B ----
    # Direction changes along each closed ring, hub vertex included.
    B = 0
    for h in sub["hubs"]:
        ring: list = []
        for li, leg in enumerate(h["route_segments"]):
            poly = leg["polyline"]
            chunk = poly if li == 0 else poly[1:]
            for p in chunk:
                pt = (p[0], p[1])
                if ring and math.dist(pt, ring[-1]) <= TOL:
                    continue  # 1 mm tolerance: same point
                ring.append(pt)
        if len(ring) > 2 and math.dist(ring[0], ring[-1]) <= TOL:
            ring.pop()  # closed ring: drop the duplicated hub vertex
        n = len(ring)
        for i in range(n):
            a, b, c = ring[i - 1], ring[i], ring[(i + 1) % n]
            if direction_change(a, b, c) >= 45.0:
                B += 1

    J = L + 5.0 * X + O + 0.5 * B
    return {
        "hubs": len(sub["hubs"]),
        "L": round(L, 3),
        "X": X,
        "O": round(O, 3),
        "B": B,
        "J": round(J, 3),
    }


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="official cost J from submissions")
    ap.add_argument("--submission", default=None)
    args = ap.parse_args()

    if args.submission:
        files = [args.submission]
    else:
        files = sorted(
            (f for f in glob.glob("submissions/*.json")
             if not f.endswith("cost_summary.json")),
            key=lambda p: int(os.path.basename(p).split(".")[0])
            if os.path.basename(p).split(".")[0].isdigit() else 0)

    rows = []
    excluded = []
    for f in files:
        plan_id = os.path.splitext(os.path.basename(f))[0]
        with open(f, encoding="utf-8") as fh:
            sub = json.load(fh)
        if not sub.get("hubs"):
            excluded.append({"plan_id": plan_id, "reason": "no hubs"})
            continue
        m = compute_metrics(sub)
        rows.append({"plan_id": plan_id, **m})
        print(f"{plan_id:>8}  H={m['hubs']}  L={m['L']:>8.3f}  X={m['X']}  "
              f"O={m['O']:.3f}  B={m['B']:>3}  J={m['J']:>8.3f}")

    if rows:
        js = sorted(r["J"] for r in rows)
        n = len(js)
        median = js[n // 2] if n % 2 else (js[n // 2 - 1] + js[n // 2]) / 2
        stats = {
            "plans": n,
            "total_J": round(sum(js), 3),
            "mean_J": round(sum(js) / n, 3),
            "median_J": round(median, 3),
            "min_J": js[0],
            "max_J": js[-1],
            "total_L": round(sum(r["L"] for r in rows), 3),
            "total_X": sum(r["X"] for r in rows),
            "total_O": round(sum(r["O"] for r in rows), 3),
            "total_B": sum(r["B"] for r in rows),
        }
        print("\nSTATS over", n, "plans:", json.dumps(stats))

    out = {
        "metric": "J = L + 5X + O + 0.5B (official PS4 slide 6/7, 1 mm tolerance)",
        "tolerance_m": TOL,
        "plans": rows,
        "stats": stats if rows else {},
        "excluded": [
            {"plan_id": "1448",
             "reason": ("officially unsolvable under the mandated scale "
                        "(living_0 = 107.26 m2 > 100 m2 hub cap; rooms cannot "
                        "be split across hubs per rule 1) - matches the "
                        "organisers' out-of-benchmark guarantee. Final "
                        "artifacts kept as evidence.")}
        ],
    }
    with open("submissions/cost_summary.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print("Saved: submissions/cost_summary.json")


if __name__ == "__main__":
    main()
