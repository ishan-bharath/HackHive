"""Export final_optimized_<plan_id>.json to the organisers' submission schema
(slide 8 of docs/"Cable Ring Challenge - Problem Statement4.pptx").

Output (submissions/<plan_id>.json by default):
{
  "plan_id": "...", "units": "m",
  "hubs": [
    {
      "hub_id": "H1", "room_id": "...",
      "location": {"x": m, "y": m},
      "assigned_rooms": [...],
      "assigned_nodes": ["N1", ...],        # visiting order
      "closed_sequence": ["H1", "N1", ..., "H1"],
      "route_segments": [
        {"from": "H1", "to": "N1", "length_m": ..., "polyline": [[x, y], ...]},
        ... one segment per ring leg, return leg included ...
      ],
      "ring_length_m": ...
    }, ...
  ],
  "reported_metrics": {"hub_count": H, "total_length_m": ...}
}

Leg splitting: the final JSON stores the full stitched loop polyline
(loop_coords, raw units) plus loop_source_indices into the matrix report's
source_order. Pull-point positions (hub + nodes) come from the matrix
node_pos; the polyline is cut exactly at those points, in visiting order.

CLI:
  python export_submission.py --plan-id 14433 [--out submissions/14433.json]
  python export_submission.py --all [--limit 25]
"""

import argparse
import glob
import json
import math
import os
import re

TOL_RAW = 0.02      # leg-boundary match tolerance (raw units, > rounding gap)
TOL_M = 0.001       # 1 mm reporting tolerance


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def pull_points(panel, matrix):
    """Ordered pull-point positions (raw): hub, N1..Nn, hub again."""
    src = matrix["source_order"]
    node_pos = matrix["node_pos"]
    pts = []
    hub_key = str(tuple(src[panel["loop_source_indices"][0]]))
    pts.append(node_pos[hub_key])
    for rid in panel["device_order"]:
        pts.append(node_pos[str(("dev", rid))])
    pts.append(node_pos[hub_key])
    return pts


def split_legs(loop_coords, pulls):
    """Cut the stitched loop polyline at the pull points, in order.
    Returns a list of leg polylines (raw units), shared endpoints included."""
    legs = []
    cur = [loop_coords[0]]
    li = 1          # next loop vertex index
    for target in pulls[1:]:
        # Advance until we hit the target pull point.
        while li < len(loop_coords):
            p = loop_coords[li]
            cur.append(p)
            li += 1
            if math.dist(p, target) <= TOL_RAW:
                break
        legs.append(cur)
        cur = [cur[-1]]
    if math.dist(legs[-1][-1], pulls[0]) > TOL_RAW:
        raise ValueError("loop does not close at the hub position")
    return legs


def leg_length_m(polyline, scale):
    return sum(math.dist(a, b) for a, b in zip(polyline[:-1], polyline[1:])) * scale


def export(plan_id, final, matrix):
    scale = final["scale_m_per_raw"]
    labels = []

    def next_label():
        labels.append(f"N{len(labels) + 1}")
        return labels[-1]

    hubs = []
    for k, panel in enumerate(final["solution"]["panels"]):
        hub_id = f"H{k + 1}"
        node_ids = [next_label() for _ in panel["device_order"]]
        pulls = pull_points(panel, matrix)
        loop = [[c[0], c[1]] for c in panel["loop_coords"]]
        if math.dist(loop[0], pulls[0]) > TOL_RAW:
            # loop_coords are rounded to 2 decimals; re-anchor at the hub.
            loop[0] = pulls[0]
        legs = split_legs(loop, pulls)
        seq_labels = [hub_id] + node_ids + [hub_id]

        route_segments = []
        for (u, v), leg in zip(zip(seq_labels[:-1], seq_labels[1:]), legs):
            leg_m = [[round(x * scale, 3), round(y * scale, 3)] for x, y in leg]
            route_segments.append({
                "from": u,
                "to": v,
                "length_m": round(leg_length_m(leg, scale), 3),
                "polyline": leg_m,
            })
        ring_len = round(sum(s["length_m"] for s in route_segments), 3)
        hubs.append({
            "hub_id": hub_id,
            "room_id": panel["panel_room"],
            "location": {
                "x": round(pulls[0][0] * scale, 3),
                "y": round(pulls[0][1] * scale, 3),
            },
            "assigned_rooms": list(panel["assigned_rooms"]),
            "assigned_nodes": node_ids,
            "closed_sequence": seq_labels,
            "route_segments": route_segments,
            "ring_length_m": ring_len,
        })

    return {
        "plan_id": str(plan_id),
        "units": "m",
        "hubs": hubs,
        "reported_metrics": {
            "hub_count": len(hubs),
            "total_length_m": round(sum(h["ring_length_m"] for h in hubs), 3),
        },
    }


def verify(sub):
    """Parse-back verification: schema, closed sequences, leg chaining,
    metre-plausible coordinates. Raises AssertionError on any problem."""
    assert sub["units"] == "m"
    assert isinstance(sub["plan_id"], str) and sub["plan_id"]
    assert sub["reported_metrics"]["hub_count"] == len(sub["hubs"])
    all_labels = set()
    for h in sub["hubs"]:
        for key in ("hub_id", "room_id", "location", "assigned_rooms",
                    "assigned_nodes", "closed_sequence", "route_segments",
                    "ring_length_m"):
            assert key in h, f"hub missing {key}"
        seq = h["closed_sequence"]
        assert seq[0] == seq[-1] == h["hub_id"], "sequence not closed at hub"
        assert seq[1:-1] == h["assigned_nodes"], "sequence != assigned_nodes"
        assert len(set(seq[1:-1])) == len(seq) - 2, "repeated node in sequence"
        all_labels.update(seq)
        # Leg chaining + closure.
        segs = h["route_segments"]
        assert segs[0]["from"] == h["hub_id"] and segs[-1]["to"] == h["hub_id"]
        assert {s["from"] for s in segs[1:]} == {s["to"] for s in segs[:-1]}
        for s in segs:
            assert len(s["polyline"]) >= 2
            for x, y in s["polyline"]:
                assert abs(x) < 2000 and abs(y) < 2000, \
                    f"coordinate not metre-plausible: {x}, {y}"
        for a, b in zip(segs[:-1], segs[1:]):
            assert max(abs(a["polyline"][-1][0] - b["polyline"][0][0]),
                       abs(a["polyline"][-1][1] - b["polyline"][0][1])) <= TOL_M + 1e-9, \
                "leg endpoints do not chain"
        start = segs[0]["polyline"][0]
        end = segs[-1]["polyline"][-1]
        assert max(abs(start[0] - end[0]), abs(start[1] - end[1])) <= TOL_M + 1e-9, \
            "ring does not return to its hub location"
        assert abs(start[0] - h["location"]["x"]) <= TOL_M + 1e-9 and \
            abs(start[1] - h["location"]["y"]) <= TOL_M + 1e-9, \
            "ring does not start at the hub location"
        ring_sum = round(sum(s["length_m"] for s in segs), 3)
        assert abs(ring_sum - h["ring_length_m"]) <= 2 * TOL_M, \
            "ring_length_m != sum of legs"
    assert len(all_labels) == sum(
        len(h["assigned_nodes"]) + 1 for h in sub["hubs"]), "duplicate node/hub IDs"
    return True


def main():
    ap = argparse.ArgumentParser(description="export organisers' submission JSON")
    ap.add_argument("--plan-id", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    os.makedirs("submissions", exist_ok=True)
    if args.all:
        finals = sorted(glob.glob("final_optimized_*.json"),
                        key=lambda p: int(re.search(r"(\d+)\.json", p).group(1)))
        if args.limit:
            finals = finals[:args.limit]
        plan_ids = [re.search(r"final_optimized_(\d+)\.json", p).group(1)
                    for p in finals]
    elif args.plan_id:
        plan_ids = [args.plan_id]
    else:
        ap.error("give --plan-id or --all")

    for plan_id in plan_ids:
        final = load_json(f"final_optimized_{plan_id}.json")
        matrix = load_json(f"matrix_{plan_id}.json")
        sub = export(plan_id, final, matrix)
        verify(sub)
        out = args.out or f"submissions/{plan_id}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(sub, f, indent=2)
        print(f"exported {out}: {sub['reported_metrics']['hub_count']} hubs, "
              f"{sub['reported_metrics']['total_length_m']} m [verified]")


if __name__ == "__main__":
    main()