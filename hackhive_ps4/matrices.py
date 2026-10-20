"""APSP D/B matrix build (former module2 main + shortest_paths, and the
in-process build_report formerly duplicated in app.py).

build_report(plan, plan_id) is the canonical programmatic Tier-1 entry:
it computes verified portals, the axis-aligned routing graph and the D/B
distance/bend matrices, returning the matrix report dict. main() is the CLI
wrapper writing matrix_<id>.json + the verification PNG.
"""

import argparse
import json

import numpy as np
import networkx as nx

from . import data
from . import geometry as m2
from .geometry import (build_global_graph, calibrate, count_bends,
                       extract_rooms, find_portals)
from .render import render


def shortest_paths(global_graph, sources):
    """Dijkstra from each source; returns dict src -> (dist, paths)."""
    result = {}
    for src in sources:
        dist, paths = nx.single_source_dijkstra(global_graph, src, weight="weight")
        result[src] = (dist, paths)
    return result


def build_report(plan, plan_id):
    cal = m2.calibrate(plan)
    scale = cal["scale_m_per_raw"]
    rooms = m2.extract_rooms(plan)
    eligible_ids = [rid for rid, r in rooms.items() if r["eligible"]]

    portals = m2.find_portals(plan, rooms, scale)
    global_graph, rooms_graph_data, portals = m2.build_global_graph(
        plan, rooms, portals, scale)

    unroutable_rooms = []
    if global_graph.number_of_nodes() > 0 and eligible_ids:
        dev_nodes_all = [(("dev", rid), rid) for rid in eligible_ids]
        anchor = max(
            (nd for nd, _ in dev_nodes_all if nd in global_graph),
            key=lambda nd: len(nx.node_connected_component(global_graph, nd)),
            default=None,
        )
        if anchor is not None:
            reachable = nx.node_connected_component(global_graph, anchor)
            unroutable_rooms = [
                rid for nd, rid in dev_nodes_all if nd not in reachable
            ]

    devices = [(("dev", rid), rooms[rid]["device_point"]) for rid in eligible_ids]
    cand_nodes = []
    for rid in eligible_ids:
        for k in range(len(rooms_graph_data[rid]["candidates"])):
            cand_nodes.append((f"cand_{k}", rid))
    cands = []
    for rid in eligible_ids:
        cands.extend(rooms_graph_data[rid]["candidates"])

    sources = [n for n, _ in devices] + cand_nodes
    sources = list(dict.fromkeys(sources))
    sp = shortest_paths(global_graph, sources)

    order = sources
    n = len(order)
    D = np.full((n, n), np.inf)
    B = np.full((n, n), -1, dtype=int)
    paths = {}
    for i, src in enumerate(order):
        dist, spaths = sp[src]
        for j, dst in enumerate(order):
            if dst in dist:
                D[i, j] = dist[dst]
                coords = [global_graph.nodes[nd]["pos"] for nd in spaths[dst]]
                B[i, j] = m2.count_bends(coords)
                paths[f"{i}_{j}"] = [
                    [round(c[0], 3), round(c[1], 3)] for c in coords
                ]

    unreachable = [
        order[j] for j in range(n)
        if not np.isfinite(D[0, j]) and j != 0
    ]
    node_pos = {str(nd): global_graph.nodes[nd]["pos"] for nd in global_graph.nodes}

    return {
        "plan_id": str(plan_id),
        "module": "module2_wall_router_and_matrix",
        "status": "TIER1_MATRIX_COMPLETE",
        "calibration": cal,
        "rooms": {
            rid: {
                "type": r["type"],
                "eligible": r["eligible"],
                "device_point": [r["device_point"].x, r["device_point"].y],
            }
            for rid, r in rooms.items()
        },
        "portals": [
            {
                "id": p["id"],
                "rooms": list(p["rooms"]),
                "edge_type": p["edge_type"],
                "width_m": round(p["width_m"], 3),
                "center": [round(p["center"][0], 3), round(p["center"][1], 3)],
            }
            for p in portals
        ],
        "devices": {nd[1]: list(nd) for nd, _ in devices},
        "panel_candidates": [
            {"room": rid, "pos": [round(x, 3), round(y, 3)]}
            for rid, (x, y) in cands
        ],
        "source_order": [list(s) for s in order],
        "D_m": [[round(v, 3) if np.isfinite(v) else None for v in row]
                for row in D],
        "B_bends": [[int(v) if v >= 0 else None for v in row] for row in B],
        "paths": paths,
        "node_pos": {k: [round(v[0], 3), round(v[1], 3)]
                     for k, v in node_pos.items()},
        "unreachable_from_first_device": [list(u) for u in unreachable],
        "unroutable_rooms": unroutable_rooms,
        "notes": [
            "D and B computed with length-first Dijkstra; bend count measured on the chosen path.",
            "Portal pins offset +/-8cm for dead-end loop separation.",
            "All edge segments validated against room interiors and buffered walls.",
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-id", default="14433")
    ap.add_argument("--out", default=None)
    ap.add_argument("--png", default=None)
    args = ap.parse_args()

    plan = data.load_plan(args.plan_id)
    cal = calibrate(plan)
    scale = cal["scale_m_per_raw"]

    print(f"Plan {args.plan_id} | official scale {scale:.4f} m/raw-unit "
          f"({cal['method']}) | door-width sanity check: median door "
          f"{cal['median_door_width_m'] and round(cal['median_door_width_m'], 3)} m "
          f"(area-implied {cal['area_implied_door_width_m'] and round(cal['area_implied_door_width_m'], 3)} m)")

    rooms = extract_rooms(plan)
    eligible_ids = [rid for rid, r in rooms.items() if r["eligible"]]
    print(f"Rooms: {len(rooms)} total, {len(eligible_ids)} eligible")

    portals = find_portals(plan, rooms, scale)
    print(f"Verified portals: {len(portals)}")

    global_graph, rooms_graph_data, portals = build_global_graph(plan, rooms, portals, scale)
    print(f"Global routing graph: {global_graph.number_of_nodes()} nodes, "
          f"{global_graph.number_of_edges()} edges")

    # Reachability check for eligible rooms.
    eligible_ids = [rid for rid, r in rooms.items() if r["eligible"]]
    unroutable_rooms = []
    if global_graph.number_of_nodes() > 0 and eligible_ids:
        comps = list(nx.connected_components(global_graph))
        print(f"Connected components: {len(comps)}")
        dev_nodes_all = [(("dev", rid), rid) for rid in eligible_ids]
        anchor = max(
            (nd for nd, _ in dev_nodes_all if nd in global_graph),
            key=lambda nd: len(nx.node_connected_component(global_graph, nd)),
            default=None,
        )
        if anchor is not None:
            reachable = nx.node_connected_component(global_graph, anchor)
            unroutable_rooms = [
                rid for nd, rid in dev_nodes_all if nd not in reachable
            ]
            if unroutable_rooms:
                print(f"WARNING: dataset-sealed rooms (no verified portal): {unroutable_rooms}")

    # Sources: devices + panel candidates.
    devices = [(("dev", rid), rooms[rid]["device_point"]) for rid in eligible_ids]
    cands = []
    for rid in eligible_ids:
        cands.extend(rooms_graph_data[rid]["candidates"])

    cand_nodes = []
    for rid in eligible_ids:
        for k in range(len(rooms_graph_data[rid]["candidates"])):
            cand_nodes.append((f"cand_{k}", rid))

    sources = [n for n, _ in devices] + cand_nodes
    sources = list(dict.fromkeys(sources))
    print(f"APSP sources: {len(devices)} devices + {len(cand_nodes)} panel candidates")

    sp = shortest_paths(global_graph, sources)

    # Matrices over sources (devices first, then candidates).
    order = sources
    n = len(order)
    D = np.full((n, n), np.inf)
    B = np.full((n, n), -1, dtype=int)
    paths = {}
    for i, src in enumerate(order):
        dist, spaths = sp[src]
        for j, dst in enumerate(order):
            if dst in dist:
                D[i, j] = dist[dst]
                coords = [global_graph.nodes[nd]["pos"] for nd in spaths[dst]]
                B[i, j] = count_bends(coords)
                paths[f"{i}_{j}"] = [
                    [round(c[0], 3), round(c[1], 3)] for c in coords
                ]

    # Connectivity report.
    unreachable = [
        order[j] for j in range(n)
        if not np.isfinite(D[0, j]) and j != 0
    ]

    # Sample routes for visual verification.
    sample_routes = []
    dev_nodes = [n for n, _ in devices]
    for k in range(1, len(dev_nodes)):
        if dev_nodes[k] in sp[dev_nodes[0]][1]:
            coords = [global_graph.nodes[nd]["pos"] for nd in sp[dev_nodes[0]][1][dev_nodes[k]]]
            sample_routes.append((coords, f"{dev_nodes[0][1]} -> {dev_nodes[k][1]}"))

    out_json = args.out or f"matrix_{args.plan_id}.json"
    out_png = args.png or f"module2_routes_{args.plan_id}.png"

    node_pos = {str(nd): global_graph.nodes[nd]["pos"] for nd in global_graph.nodes}

    report = {
        "plan_id": args.plan_id,
        "module": "module2_wall_router_and_matrix",
        "status": "TIER1_MATRIX_COMPLETE",
        "calibration": cal,
        "rooms": {
            rid: {
                "type": r["type"],
                "eligible": r["eligible"],
                "device_point": [r["device_point"].x, r["device_point"].y],
            }
            for rid, r in rooms.items()
        },
        "portals": [
            {
                "id": p["id"],
                "rooms": list(p["rooms"]),
                "edge_type": p["edge_type"],
                "width_m": round(p["width_m"], 3),
                "center": [round(p["center"][0], 3), round(p["center"][1], 3)],
            }
            for p in portals
        ],
        "devices": {n[1]: list(n) for n, _ in devices},
        "panel_candidates": [
            {"room": rid, "pos": [round(x, 3), round(y, 3)]} for rid, (x, y) in cands
        ],
        "source_order": [list(s) for s in order],
        "D_m": [[round(v, 3) if np.isfinite(v) else None for v in row] for row in D],
        "B_bends": [[int(v) if v >= 0 else None for v in row] for row in B],
        "paths": paths,
        "node_pos": {str(k): [round(v[0], 3), round(v[1], 3)] for k, v in node_pos.items()},
        "unreachable_from_first_device": [list(u) for u in unreachable],
        "unroutable_rooms": unroutable_rooms,
        "notes": [
            "D and B computed with length-first Dijkstra; bend count measured on the chosen path.",
            "Portal pins offset +/-8cm for dead-end loop separation.",
            "All edge segments validated against room interiors and buffered walls.",
        ],
    }

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    render(plan, rooms, portals, rooms_graph_data, global_graph, sample_routes, out_png)

    print(f"Saved: {out_json}")
    print(f"Saved: {out_png}")
    if unreachable:
        print(f"WARNING: {len(unreachable)} sources unreachable from device 0: {unreachable}")
    else:
        print("All sources mutually reachable.")
