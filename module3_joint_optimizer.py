"""Module 3: Joint optimizer for panel placement, room assignment, and
closed-loop cable routing.

Consumes the module 2 matrix report. Two modes:

  baseline   - naive panel-first: greedy geometric clustering, panel at the
               device room closest to the cluster centroid, loop ordered by
               nearest-neighbour on straight-line device distances.
  optimized  - contiguous BFS region-growing partition + local boundary swaps,
               per-cluster TSP (nearest neighbour + 2-opt) on true indoor
               distances D, then Loop-First/Panel-Snap: the panel snaps to the
               candidate position whose insertion into the best tour edge adds
               the least cable.

Hard constraints enforced: panel capacity (100 m^2, 20 devices), contiguous
territories (on the verified portal room graph), every eligible room assigned
to exactly one panel, one closed loop per panel visiting each device exactly
once. Both modes are measured with the SAME true indoor routed lengths, so the
comparison isolates decision quality, not measurement differences.

Output: solution JSON + quick-look PNG.
"""

import argparse
import itertools
import json
import math
import time

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import common
import module2_wall_router_and_matrix as m2

PANEL_AREA_CAP_M2 = 100.0
PANEL_DEVICE_CAP = 20

TSP_IMPROVE_PASSES = 60

MAX_SPLIT_COST_EVALS = 160


# ------------------------------------------------------------------
# Load matrix + derived structures
# ------------------------------------------------------------------

def load_matrix(plan_id, matrix_path=None):
    path = matrix_path or f"matrix_{plan_id}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def derive_structures(plan, report, scale):
    rooms = m2.extract_rooms(plan)
    portals = m2.find_portals(plan, rooms, scale)

    room_graph = {}
    for portal in portals:
        a, b = portal["rooms"]
        room_graph.setdefault(a, set()).add(b)
        room_graph.setdefault(b, set()).add(a)

    areas_m2 = {
        rid: rooms[rid]["geometry"].area * scale * scale for rid in rooms
    }
    unroutable = set(report.get("unroutable_rooms") or [])
    eligible = [
        rid for rid, r in rooms.items()
        if r["eligible"] and rid not in unroutable
    ]
    return rooms, portals, room_graph, areas_m2, eligible, unroutable


def build_index_and_matrices(report):
    index = {tuple(s): i for i, s in enumerate(report["source_order"])}
    D = np.array(
        [[v if v is not None else np.inf for v in row] for row in report["D_m"]]
    )
    B = np.array(
        [[v if v is not None else 0 for v in row] for row in report["B_bends"]]
    )
    return index, D, B


def min_panels(areas_m2, eligible, room_graph):
    total_area = sum(areas_m2[rid] for rid in eligible)
    n_devices = len(eligible)
    n_comp = len(_eligible_components(eligible, room_graph))
    k_area = math.ceil(total_area / PANEL_AREA_CAP_M2) if total_area > 0 else 1
    k_dev = math.ceil(n_devices / PANEL_DEVICE_CAP) if n_devices else 1
    return max(k_area, k_dev, n_comp, 1), total_area, n_comp


def _eligible_components(eligible, room_graph):
    remaining = set(eligible)
    comps = []
    while remaining:
        seed = next(iter(remaining))
        comp = set()
        stack = [seed]
        while stack:
            cur = stack.pop()
            if cur in comp:
                continue
            comp.add(cur)
            for nb in room_graph.get(cur, ()):
                if nb in eligible and nb not in comp:
                    stack.append(nb)
        remaining -= comp
        comps.append(comp)
    return comps


def cluster_connected_strict(cluster, room_graph, eligible=None):
    """Territory contiguity: cluster rooms must be mutually reachable through
    valid indoor passages. Transit (non-eligible) rooms may be traversed, but
    rooms assigned to other panels (eligible, not in cluster) may not."""
    if not cluster:
        return True
    eligible = set(eligible) if eligible is not None else set(cluster)
    cluster = set(cluster)
    seen = set()
    stack = [next(iter(cluster))]
    seen.add(stack[0])
    while stack:
        cur = stack.pop()
        for nb in room_graph.get(cur, ()):
            if nb in seen:
                continue
            if nb in eligible and nb not in cluster:
                continue  # belongs to another panel's territory
            seen.add(nb)
            stack.append(nb)
    return cluster <= seen


# ------------------------------------------------------------------
# TSP on the D matrix
# ------------------------------------------------------------------

def nn_tour_indexed(dev_idx, D):
    """Nearest-neighbour tour over D-matrix indices."""
    unvisited = set(dev_idx)
    start = dev_idx[0]
    tour = [start]
    unvisited.remove(start)
    while unvisited:
        last = tour[-1]
        nxt = min(unvisited, key=lambda j: D[last, j])
        tour.append(nxt)
        unvisited.remove(nxt)
    return tour


def two_opt(tour, D):
    best = list(tour)
    improved = True
    passes = 0
    while improved and passes < TSP_IMPROVE_PASSES:
        improved = False
        passes += 1
        n = len(best)
        for i in range(n - 1):
            for j in range(i + 1, n):
                new = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                if loop_len_idx(new, D) + 1e-9 < loop_len_idx(best, D):
                    best = new
                    improved = True
    return best


def loop_len_idx(tour, D):
    total = 0.0
    n = len(tour)
    for i in range(n):
        a, b = tour[i], tour[(i + 1) % n]
        if not np.isfinite(D[a, b]):
            return math.inf
        total += D[a, b]
    return total


def solve_loop(cluster, index, D):
    """Optimal-ish device order (TSP indices) and its closed length."""
    dev_idx = [index[("dev", rid)] for rid in sorted(cluster)]
    if not dev_idx:
        return [], 0.0
    if len(dev_idx) == 1:
        return dev_idx, 0.0
    tour = nn_tour_indexed(dev_idx, D)
    tour = two_opt(tour, D)
    return tour, loop_len_idx(tour, D)


def best_panel_for_tour(cluster, report, index, D):
    """Loop-first panel snap: candidate whose insertion into the best tour
    edge adds the least cable."""
    tour, _ = solve_loop(cluster, index, D)
    if not tour:
        return None, 0.0, []

    best_si, best_cost = None, math.inf
    n = len(tour)
    for si, src in enumerate(report["source_order"]):
        if not str(src[0]).startswith("cand") or src[-1] not in cluster:
            continue
        if n == 1:
            cost = float(D[si, tour[0]] * 2.0)
        else:
            det = math.inf
            for i in range(n):
                a, b = tour[i], tour[(i + 1) % n]
                det = min(det, D[si, a] + D[si, b] - D[a, b])
            cost = float(det + loop_len_idx(tour, D))
        if cost < best_cost:
            best_cost, best_si = cost, si

    if best_si is None:
        return None, math.inf, []

    # Rebuild the loop with the panel inserted at its best edge.
    if n == 1:
        loop = [best_si, tour[0], best_si]
    else:
        best_det, best_i = math.inf, 0
        for i in range(n):
            a, b = tour[i], tour[(i + 1) % n]
            det = D[best_si, a] + D[best_si, b] - D[a, b]
            if det < best_det:
                best_det, best_i = det, i
        ordered = tour[best_i + 1:] + tour[:best_i + 1]
        loop = [best_si] + ordered + [best_si]
    return best_si, best_cost, loop


# ------------------------------------------------------------------
# Partitioning
# ------------------------------------------------------------------

def find_partition(areas_m2, eligible, room_graph, loop_cost_fn):
    """Try k = k_min, k_min+1 ... (more panels can make a contiguous
    capacity-feasible split possible). A candidate is only accepted when it
    is contiguous AND every cluster fits the panel area cap; Selection order: fewest panels that satisfy the constraints (k ascending),
    then least total loop cable among partitions with that panel count. If no capacity-feasible contiguous partition exists (e.g. a single
    oversized component that cannot be split), the best contiguous partition
    is returned with the violation flagged.
    Returns (clusters, k_used, k_min, capacity_relaxed)."""
    k_min, total_area, n_comp = min_panels(areas_m2, eligible, room_graph)
    attempts = list(range(k_min, k_min + 4)) + list(range(k_min - 1, 0, -1)) + [1]
    tried = set()
    feasible = []
    contiguous_over = None
    for k in attempts:
        if k in tried or k < 1:
            continue
        tried.add(k)
        clusters = grow_partition(areas_m2, eligible, room_graph, k,
                                  cost_fn=loop_cost_fn)
        if clusters is None or len(clusters) != k:
            continue
        if not all(cluster_connected_strict(c, room_graph, eligible) for c in clusters):
            continue
        if all(sum(areas_m2[r] for r in c) <= PANEL_AREA_CAP_M2 + 1e-9
               for c in clusters):
            feasible.append((sum(loop_cost_fn(c) for c in clusters), k, clusters))
        elif contiguous_over is None:
            contiguous_over = clusters
    if feasible:
        _, k, clusters = min(feasible, key=lambda t: (t[1], round(t[0], 6)))
        return clusters, k, k_min, k < k_min
    if contiguous_over is not None:
        return contiguous_over, len(contiguous_over), k_min, True
    return [set(eligible)], 1, k_min, True


def grow_partition(areas_m2, eligible, room_graph, k, cost_fn=None):
    """Contiguous region-growing into k clusters; returns None when k-way
    splitting is impossible without disconnecting a territory. When cost_fn
    is given, the split point minimises total cable instead of taking the
    first feasible configuration."""
    if cost_fn is None:
        cost_fn = lambda c: 0.0  # noqa: E731
    comps = _eligible_components(eligible, room_graph)
    comps.sort(key=lambda c: sum(areas_m2[r] for r in c), reverse=True)
    clusters = [set(c) for c in comps]
    if len(clusters) > k:
        return None

    while len(clusters) < k:
        big = max(range(len(clusters)),
                  key=lambda i: sum(areas_m2[r] for r in clusters[i]))
        comp = clusters[big]
        if len(comp) < 2:
            return None
        # Try splitting: seed at a room, grow one room at a time (BFS). Every
        # configuration where both sides are contiguous and fit the panel
        # capacity is a candidate; take the cheapest (bounded number of cost
        # evaluations). If none fits both caps, fall back to the first split
        # where at least the smaller side fits - the oversized side may be
        # split again when more clusters are needed.
        comp_area = sum(areas_m2[r] for r in comp)
        placed = False
        cands = []
        relaxed = None
        evals = 0
        for seed in sorted(comp, key=lambda r: -areas_m2[r]):
            grown = {seed}
            frontier = [(seed, nb) for nb in room_graph.get(seed, ()) if nb in comp]
            frontier.sort(key=lambda sn: areas_m2[sn[1]])
            while True:
                rest = comp - grown
                grown_area = sum(areas_m2[r] for r in grown)
                rest_area = comp_area - grown_area
                if rest and \
                        cluster_connected_strict(grown, room_graph, eligible) and \
                        cluster_connected_strict(rest, room_graph, eligible):
                    if grown_area <= PANEL_AREA_CAP_M2 + 1e-9 and \
                            rest_area <= PANEL_AREA_CAP_M2 + 1e-9:
                        if evals < MAX_SPLIT_COST_EVALS:
                            cands.append((cost_fn(grown) + cost_fn(rest),
                                          set(grown), set(rest)))
                            evals += 1
                        else:
                            cands.append((math.inf, set(grown), set(rest)))
                    elif relaxed is None and (
                            grown_area <= PANEL_AREA_CAP_M2 + 1e-9 or
                            rest_area <= PANEL_AREA_CAP_M2 + 1e-9):
                        relaxed = (set(grown), set(rest))
                if not frontier:
                    break
                _, nb = frontier.pop(0)
                if nb in grown:
                    continue
                grown.add(nb)
                for nb2 in room_graph.get(nb, ()):
                    if nb2 in comp and nb2 not in grown:
                        frontier.append((nb, nb2))
                frontier.sort(key=lambda sn: areas_m2[sn[1]])
        if cands:
            _, g, r = min(cands, key=lambda t: t[0])
            clusters[big] = g
            clusters.append(r)
            placed = True
        elif relaxed is not None:
            clusters[big] = relaxed[0]
            clusters.append(relaxed[1])
            placed = True
        if not placed:
            return None

    while len(clusters) > k:
        best = None
        for i, j in itertools.combinations(range(len(clusters)), 2):
            merged = clusters[i] | clusters[j]
            if cluster_connected_strict(merged, room_graph, eligible):
                c = sum(areas_m2[r] for r in merged)
                if best is None or c < best[0]:
                    best = (c, i, j)
        if best is None:
            i, j = 0, 1
            best = (0.0, 0, 1)
        _, i, j = best
        clusters[i] |= clusters[j]
        clusters.pop(j)

    # Pull neighbouring rooms into smaller clusters while capacity allows.
    # A move is only accepted when it transfers area from a larger to a
    # smaller cluster, which guarantees termination.
    changed = True
    moves = 0
    while changed and moves < 100:
        changed = False
        for ci in range(len(clusters)):
            cluster = clusters[ci]
            if sum(areas_m2[r] for r in cluster) > PANEL_AREA_CAP_M2 + 1e-9:
                continue
            for rid in list(cluster):
                for nb in room_graph.get(rid, ()):
                    if nb not in eligible:
                        continue
                    oj = next((oj for oj, oc in enumerate(clusters) if nb in oc), None)
                    if oj is None or oj == ci:
                        continue
                    new_c = cluster | {nb}
                    new_o = clusters[oj] - {nb}
                    if not new_o:
                        continue
                    if sum(areas_m2[r] for r in new_c) > PANEL_AREA_CAP_M2 + 1e-9:
                        continue
                    if len(new_c) > PANEL_DEVICE_CAP:
                        continue
                    if sum(areas_m2[r] for r in clusters[oj]) <= sum(
                            areas_m2[r] for r in clusters[ci]):
                        continue
                    if cluster_connected_strict(new_c, room_graph, eligible) and \
                       cluster_connected_strict(new_o, room_graph, eligible):
                        clusters[ci] = new_c
                        clusters[oj] = new_o
                        changed = True
                        moves += 1
                        break
                if changed:
                    break
            if changed:
                break
    return [c for c in clusters if c]


def boundary_swap_improve(clusters, areas_m2, eligible, room_graph, loop_cost_fn):
    improved = True
    rounds = 0
    while improved and rounds < 30:
        improved = False
        rounds += 1
        for ci in range(len(clusters)):
            for rid in sorted(list(clusters[ci])):
                if rid not in eligible:
                    continue
                for cj in range(len(clusters)):
                    if cj == ci:
                        continue
                    new_c = clusters[ci] - {rid}
                    new_t = clusters[cj] | {rid}
                    if not new_c:
                        continue
                    if not cluster_connected_strict(new_c, room_graph, eligible):
                        continue
                    if not cluster_connected_strict(new_t, room_graph, eligible):
                        continue
                    if sum(areas_m2[r] for r in new_t) > PANEL_AREA_CAP_M2 + 1e-9:
                        continue
                    if len(new_t) > PANEL_DEVICE_CAP:
                        continue
                    delta = (loop_cost_fn(new_t) + loop_cost_fn(new_c)
                             - loop_cost_fn(clusters[ci]) - loop_cost_fn(clusters[cj]))
                    if delta < -1e-9:
                        clusters[ci] = new_c
                        clusters[cj] = new_t
                        improved = True
                        break
                if improved:
                    break
            if improved:
                break
    return clusters


# ------------------------------------------------------------------
# Solution assembly
# ------------------------------------------------------------------

def build_panel_record(panel_si, loop, report, D, B, cluster, areas_m2):
    coords, length, bends = [], 0.0, 0
    ok = True
    for u, v in zip(loop[:-1], loop[1:]):
        key = f"{u}_{v}"
        seg = report["paths"].get(key)
        if seg is None:
            ok = False
            break
        coords.extend(seg if not coords else seg[1:])
        length += D[u, v]
    if not ok:
        length, bends = math.inf, -1
    else:
        # Count bends on the STITCHED loop polyline with the same rule as the
        # M4 validator's NEC check (turn >= 45 deg at interior vertices).
        # Summing per-segment B[u, v] misses the turn at every segment
        # junction (each device/panel node), under-reporting ~1 bend per node.
        loop_coords = [[round(x, 2), round(y, 2)] for x, y in coords]
        bends = m2.count_bends(loop_coords)

    src = report["source_order"][panel_si]
    pos = report["node_pos"].get(str(tuple(src)))
    panel_room = src[-1]

    return {
        "panel_room": panel_room,
        "panel_position": pos,
        "assigned_rooms": sorted(cluster),
        "assigned_area_m2": round(sum(areas_m2[r] for r in cluster), 2),
        "device_order": [report["source_order"][i][-1] for i in loop[1:-1]],
        "loop_source_indices": loop,
        "loop_length_m": round(length, 3) if math.isfinite(length) else None,
        "loop_bends": int(bends) if bends >= 0 else None,
        "loop_coords": [[round(x, 2), round(y, 2)] for x, y in coords]
        if bends < 0 else loop_coords,
        "loop_valid": ok,
    }


def summarize(solution):
    m = solution["metrics"]
    m["panel_count"] = len(solution["panels"])
    m["devices_total"] = sum(len(p["assigned_rooms"]) for p in solution["panels"])
    lens = [p["loop_length_m"] for p in solution["panels"]]
    m["total_cable_length_m"] = (
        round(sum(lens), 3) if all(l is not None for l in lens) else None
    )
    m["total_bends"] = sum(p["loop_bends"] or 0 for p in solution["panels"])
    m["all_loops_routed"] = all(p["loop_valid"] for p in solution["panels"])
    return solution


# ------------------------------------------------------------------
# Baseline mode (naive panel-first)
# ------------------------------------------------------------------

def baseline_solution(plan, report, scale):
    rooms, portals, room_graph, areas_m2, eligible, unroutable = derive_structures(
        plan, report, scale
    )
    index, D, B = build_index_and_matrices(report)

    # Candidate lookup: per room, candidate source indices + positions.
    cand_by_room = {}
    for si, src in enumerate(report["source_order"]):
        if str(src[0]).startswith("cand"):
            cand_by_room.setdefault(src[-1], []).append(
                (si, report["node_pos"][str(tuple(src))])
            )

    # Greedy geometric clustering: seed at largest room, grow by centroid
    # distance, connectivity + capacity enforced.
    centroids = {rid: rooms[rid]["geometry"].representative_point() for rid in rooms}
    unassigned = set(eligible)
    clusters = []
    while unassigned:
        seed = max(unassigned, key=lambda r: areas_m2[r])
        cluster = {seed}
        unassigned.discard(seed)
        frontier = [seed]
        while frontier:
            cur = frontier.pop(0)
            nbrs = sorted(
                (nb for nb in room_graph.get(cur, ()) if nb in unassigned),
                key=lambda nb: centroids[nb].distance(centroids[seed]),
            )
            for nb in nbrs:
                if sum(areas_m2[r] for r in cluster) + areas_m2[nb] <= PANEL_AREA_CAP_M2 \
                        and len(cluster) < PANEL_DEVICE_CAP:
                    cluster.add(nb)
                    unassigned.discard(nb)
                    frontier.append(nb)
            if sum(areas_m2[r] for r in cluster) > PANEL_AREA_CAP_M2:
                break
        clusters.append(cluster)
        # Distribute leftovers into clusters they can join contiguously.
        for rid in sorted(unassigned, key=lambda r: -areas_m2[r]):
            options = [
                cluster for cluster in clusters
                if sum(areas_m2[r] for r in cluster) + areas_m2[rid] <= PANEL_AREA_CAP_M2 + 1e-9
                and len(cluster) < PANEL_DEVICE_CAP
                and cluster_connected_strict(cluster | {rid}, room_graph, eligible)
            ]
            if options:
                target = min(options, key=lambda c: math.hypot(
                    sum(centroids[r].x for r in c) / len(c) - centroids[rid].x,
                    sum(centroids[r].y for r in c) / len(c) - centroids[rid].y))
                target.add(rid)
                unassigned.discard(rid)
        if unassigned:
            # Last resort: attach a leftover only when the merge stays
            # contiguous AND within capacity; otherwise give the room its own
            # panel (a trivial one-device loop is still valid PS4 output).
            for rid in sorted(unassigned, key=lambda r: -areas_m2[r]):
                options = [
                    cluster for cluster in clusters
                    if sum(areas_m2[r] for r in cluster) + areas_m2[rid] <= PANEL_AREA_CAP_M2 + 1e-9
                    and len(cluster) < PANEL_DEVICE_CAP
                    and cluster_connected_strict(cluster | {rid}, room_graph, eligible)
                ]
                if options:
                    target = min(options, key=lambda c: math.hypot(
                        sum(centroids[r].x for r in c) / len(c) - centroids[rid].x,
                        sum(centroids[r].y for r in c) / len(c) - centroids[rid].y))
                    target.add(rid)
                else:
                    clusters.append({rid})
                unassigned.discard(rid)
            unassigned.clear()

    panels = []
    for cluster in clusters:
        # Panel first: nearest wall candidate to the cluster centroid.
        cx = sum(centroids[r].x for r in cluster) / len(cluster)
        cy = sum(centroids[r].y for r in cluster) / len(cluster)
        panel_room = min(cluster, key=lambda r: math.hypot(
            centroids[r].x - cx, centroids[r].y - cy))
        cands = cand_by_room.get(panel_room) or []
        if cands:
            panel_si = min(cands, key=lambda c: math.hypot(
                c[1][0] - cx, c[1][1] - cy))[0]
        else:
            panel_si = index[("dev", panel_room)]

        # Loop ordered by nearest neighbour on straight-line device distance.
        # Every device in the cluster is visited, including the panel room's.
        dev_pts = {rid: rooms[rid]["device_point"] for rid in cluster}
        order = []
        remaining = set(dev_pts)
        cur_pos = (cx, cy)
        while remaining:
            nxt = min(remaining, key=lambda r: math.hypot(
                dev_pts[r].x - cur_pos[0], dev_pts[r].y - cur_pos[1]))
            order.append(nxt)
            remaining.discard(nxt)
            cur_pos = (dev_pts[nxt].x, dev_pts[nxt].y)
        loop = [panel_si] + [index[("dev", r)] for r in order] + [panel_si]

        rec = build_panel_record(panel_si, loop, report, D, B, cluster, areas_m2)
        over = sum(areas_m2[r] for r in cluster) - PANEL_AREA_CAP_M2
        rec["capacity_violation_m2"] = round(over, 2) if over > 1e-9 else 0.0
        panels.append(rec)

    solution = {"plan_id": report["plan_id"], "mode": "baseline", "panels": panels,
                "metrics": {"unroutable_rooms": sorted(unroutable)}}
    return summarize(solution)


# ------------------------------------------------------------------
# Optimized mode (loop-first, panel-snap)
# ------------------------------------------------------------------

def optimized_solution(plan, report, scale):
    rooms, portals, room_graph, areas_m2, eligible, unroutable = derive_structures(
        plan, report, scale
    )
    index, D, B = build_index_and_matrices(report)
    k, total_area, n_comp = min_panels(areas_m2, eligible, room_graph)

    def loop_cost_fn(cluster):
        _, ln = solve_loop(cluster, index, D)
        return ln

    def cluster_cost_fn(cluster):
        # Full metric: device loop + cheapest panel insertion, matching what
        # the final solution is measured on.
        si, cost, _ = best_panel_for_tour(cluster, report, index, D)
        return cost if si is not None else loop_cost_fn(cluster)

    clusters, k_used, k_min, capacity_relaxed = find_partition(
        areas_m2, eligible, room_graph, cluster_cost_fn
    )
    clusters = boundary_swap_improve(
        clusters, areas_m2, eligible, room_graph, cluster_cost_fn
    )

    panels = []
    for cluster in clusters:
        panel_si, cost, loop = best_panel_for_tour(cluster, report, index, D)
        if panel_si is None:
            # Fallback: panel in the largest room's device node.
            rid = max(cluster, key=lambda r: areas_m2[r])
            panel_si = index[("dev", rid)]
            dev_idx = [index[("dev", r)] for r in sorted(cluster) if r != rid]
            loop = [panel_si] + dev_idx + [panel_si]
        rec = build_panel_record(panel_si, loop, report, D, B, cluster, areas_m2)
        over = sum(areas_m2[r] for r in cluster) - PANEL_AREA_CAP_M2
        rec["capacity_violation_m2"] = round(over, 2) if over > 1e-9 else 0.0
        panels.append(rec)

    solution = {"plan_id": report["plan_id"], "mode": "optimized", "panels": panels,
                "metrics": {"k_min_theoretical": k_min, "k_used": k_used,
                            "capacity_relaxed": capacity_relaxed,
                            "unroutable_rooms": sorted(unroutable)}}
    return summarize(solution)


# ------------------------------------------------------------------
# Quick render
# ------------------------------------------------------------------

def render_solution(plan, solution, out_png):
    fig, ax = plt.subplots(figsize=(14, 11))
    m2.draw_geom(ax, plan.get("inner"), "#FFFFFF", "#777777", 0.15)
    m2.draw_geom(ax, plan.get("wall"), "#555555", "#333333", 0.9)
    rooms = m2.extract_rooms(plan)
    palette = ["#E74C3C", "#2980B9", "#27AE60", "#8E44AD", "#F39C12"]
    for k, panel in enumerate(solution["panels"]):
        color = palette[k % len(palette)]
        for rid in panel["assigned_rooms"]:
            m2.draw_geom(ax, rooms[rid]["geometry"], color, color, 0.18)
        coords = panel["loop_coords"]
        if coords:
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            ax.plot(xs, ys, color=color, linewidth=2.0, zorder=5)
        if panel["panel_position"]:
            ax.plot(*panel["panel_position"], marker="*", markersize=18,
                    color=color, zorder=6)
        for rid in panel["assigned_rooms"]:
            d = rooms[rid]["device_point"]
            ax.plot(d.x, d.y, marker="s", markersize=7, color=color, zorder=6)
    ax.set_title(
        f"Module 3 ({solution['mode']}): {solution['metrics']['panel_count']} panels, "
        f"{solution['metrics']['total_cable_length_m']} m cable, "
        f"{solution['metrics']['total_bends']} bends"
    )
    ax.set_aspect("equal", adjustable="box")
    plt.tight_layout()
    plt.savefig(out_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-id", default="14433")
    ap.add_argument("--mode", choices=["baseline", "optimized", "both"], default="both")
    ap.add_argument("--matrix", default=None)
    args = ap.parse_args()

    plan = common.load_plan(args.plan_id)
    scale = m2.calibrate(plan)["scale_m_per_raw"]
    report = load_matrix(args.plan_id, args.matrix)

    for mode in (["baseline", "optimized"] if args.mode == "both" else [args.mode]):
        t0 = time.time()
        sol = (baseline_solution if mode == "baseline" else optimized_solution)(
            plan, report, scale
        )
        sol["metrics"]["runtime_s"] = round(time.time() - t0, 3)

        out_json = f"solution_{mode}_{args.plan_id}.json"
        out_png = f"solution_{mode}_{args.plan_id}.png"
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(sol, f, indent=2)
        render_solution(plan, sol, out_png)

        print(f"[{mode}] panels={sol['metrics']['panel_count']} "
              f"cable={sol['metrics']['total_cable_length_m']} m "
              f"bends={sol['metrics']['total_bends']} "
              f"routed={sol['metrics']['all_loops_routed']} "
              f"runtime={sol['metrics']['runtime_s']}s")
        for p in sol["panels"]:
            print(f"   panel@{p['panel_room']}: rooms={p['assigned_rooms']} "
                  f"area={p['assigned_area_m2']} m2 "
                  f"loop={p['loop_length_m']} m bends={p['loop_bends']} "
                  f"devices={len(p['device_order'])}")


if __name__ == "__main__":
    main()
