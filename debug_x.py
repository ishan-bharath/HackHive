import json, math, os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compute_cost as cc

pid = sys.argv[1] if len(sys.argv) > 1 else "2372"
sub = json.load(open(f"submissions/{pid}.json", encoding="utf-8"))
hub_pts = [(h["location"]["x"], h["location"]["y"]) for h in sub["hubs"]]
all_segs = []
node_pts = list(hub_pts)
for hi, h in enumerate(sub["hubs"]):
    for li, leg in enumerate(h["route_segments"]):
        poly = leg["polyline"]
        node_pts.append((poly[-1][0], poly[-1][1]))
        for k, seg in enumerate(cc.segments_of_leg(leg)):
            all_segs.append((hi, li, k, seg))


def legname(hi, li):
    h = sub["hubs"][hi]
    s = h["route_segments"][li]
    return h["hub_id"] + ":" + s["from"] + "->" + s["to"]


shown = 0
for i in range(len(all_segs)):
    hi, li, ki, si = all_segs[i]
    for j in range(i + 1, len(all_segs)):
        hj, lj, kj, sj = all_segs[j]
        if hi == hj and li == lj and abs(ki - kj) == 1:
            continue
        ka, kb = cc.line_key(si), cc.line_key(sj)
        if ka == kb:
            continue
        pt = cc.perpendicular_crossing(si, sj)
        if pt is None:
            continue
        if any(math.dist(pt, q) <= cc.TOL for q in node_pts):
            continue
        print("X at (%.3f, %.3f)  %s seg%d x %s seg%d"
              % (pt[0], pt[1], legname(hi, li), ki, legname(hj, lj), kj))
        shown += 1
print("total genuine X points:", shown)