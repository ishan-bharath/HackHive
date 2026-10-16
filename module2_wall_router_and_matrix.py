"""Module 2: Wall-hugging raceway router + APSP distance/bend matrices.

Tier 1 of the two-tier architecture. Given one floor plan this module:
  1. Calibrates the raw coordinate scale to metres (area-based, door-width cross-check).
  2. Extracts eligible + transit rooms and geometrically verifies portals between them.
  3. Builds a room-local routing graph per room (raceway ring vertices, device point,
     portal anchor pins) with segments validated against room interiors and walls.
  4. Stitches rooms through portal crossings into one global routing graph.
  5. Runs Dijkstra from every device point and panel candidate point, producing:
       D[i,j] = true indoor cable length (metres)
       B[i,j] = number of ~90-degree bends
       P[i,j] = polyline of node coordinates for reconstruction

Output: JSON matrix report + verification PNG. Matrices feed Module 3.
"""

import argparse
import json
import math
from itertools import combinations

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

import common

ELIGIBLE = common.ELIGIBLE_TYPES

# Indoor zero-demand transit room types (included in routing, carry no device).
TRANSIT_TYPES = {
    "bathroom", "hall", "hallway", "corridor", "foyer", "landing",
    "lobby", "closet", "laundry", "stairs",
}

# Outdoor / non-routing room types.
EXCLUDED_TYPES = {
    "balcony", "garden", "parking", "pool", "land", "front_door",
}

# Graph edge types accepted as candidate physical passages.
CANDIDATE_EDGE_TYPES = {"via_door", "via_opening"}

WALL_CLEARANCE_M = 0.15
PORTAL_OFFSET_M = 0.08          # +/- offset for enter/exit pins through one doorway
RING_SPACING_M = 2.0            # panel candidate spacing along inset ring
MAX_CANDIDATES_PER_ROOM = 16
BEND_ANGLE_THRESHOLD_DEG = 45.0


# ------------------------------------------------------------------
# Geometry helpers
# ------------------------------------------------------------------

def parts(geom):
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, (Polygon,)):
        return [geom]
    if hasattr(geom, "geoms"):
        return [g for g in geom.geoms if not g.is_empty and isinstance(g, Polygon)]
    return [geom]


def largest(geom):
    ps = parts(geom)
    return max(ps, key=lambda g: g.area) if ps else None


def unit(vec):
    n = math.hypot(*vec)
    return (vec[0] / n, vec[1] / n) if n > 1e-12 else (0.0, 0.0)


def turn_angle(prev, cur, nxt):
    v1 = (cur[0] - prev[0], cur[1] - prev[1])
    v2 = (nxt[0] - cur[0], nxt[1] - cur[1])
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 < 1e-12 or n2 < 1e-12:
        return 0.0
    dot = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def count_bends(coords):
    return sum(
        1
        for i in range(1, len(coords) - 1)
        if turn_angle(coords[i - 1], coords[i], coords[i + 1]) >= BEND_ANGLE_THRESHOLD_DEG
    )


# ------------------------------------------------------------------
# Calibration
# ------------------------------------------------------------------

def calibrate(plan):
    inner = largest(plan.get("inner"))
    reported = plan.get("area") or plan.get("net_area")
    if inner is None or not reported:
        raise ValueError("Cannot calibrate: missing inner geometry or area metadata.")

    scale = math.sqrt(float(reported) / inner.area)

    door_widths_m = []
    for d in parts(plan.get("door")):
        cs = list(d.minimum_rotated_rectangle.exterior.coords)
        e1 = math.dist(cs[0], cs[1])
        e2 = math.dist(cs[1], cs[2])
        door_widths_m.append(max(e1, e2) * scale)
    med_door = float(np.median(door_widths_m)) if door_widths_m else None

    return {
        "scale_m_per_raw": scale,
        "reported_area_m2": float(reported),
        "inner_area_raw": inner.area,
        "median_door_width_m": med_door,
        "door_width_plausible": med_door is not None and 0.6 <= med_door <= 1.2,
        "wall_depth_m": (plan.get("wall_depth") or 0.0) * scale,
    }


# ------------------------------------------------------------------
# Rooms
# ------------------------------------------------------------------

def extract_rooms(plan):
    rooms = {}
    for node_id, attrs in plan["graph"].nodes(data=True):
        rtype = attrs.get("type", "unknown")
        geom = attrs.get("geometry")
        if geom is None or geom.is_empty:
            continue
        if rtype in EXCLUDED_TYPES:
            continue
        rooms[node_id] = {
            "id": node_id,
            "type": rtype,
            "eligible": rtype in ELIGIBLE,
            "geometry": geom,
            "device_point": geom.representative_point(),
        }
    return rooms


def raceway_ring(room, scale, walls_union):
    """Inset ring (wall-hugging raceway) vertices inside a room, kept clear
    of wall geometry."""
    clearance_raw = WALL_CLEARANCE_M / scale
    base = room["geometry"]
    if walls_union is not None:
        base = base.difference(walls_union)
    inset = base.buffer(-clearance_raw * 0.8)
    if inset.is_empty:
        inset = base.buffer(-clearance_raw * 0.4)
    if inset.is_empty:
        inset = base.buffer(-0.05 / scale)
    if inset.is_empty or inset.geom_type != "Polygon":
        inset = largest(inset)
    if inset is None:
        return None, None
    ring = inset.exterior.simplify(0.1)
    if ring.geom_type != "LinearRing" or len(ring.coords) < 4:
        ring = inset.exterior
    coords = list(ring.coords)[:-1]
    return inset, coords


# ------------------------------------------------------------------
# Portals
# ------------------------------------------------------------------

def _rot_axes(polygon):
    cs = list(polygon.minimum_rotated_rectangle.exterior.coords)
    e1 = (cs[1][0] - cs[0][0], cs[1][1] - cs[0][1])
    e2 = (cs[2][0] - cs[1][0], cs[2][1] - cs[1][1])
    if math.hypot(*e1) >= math.hypot(*e2):
        return e1, e2
    return e2, e1


def _shared_boundary(ga, gb, eps_raw):
    """Shared boundary between two rooms: the line intersection of the
    (possibly overlapping) room polygons."""
    b = ga.intersection(gb)
    lines = []
    if b.is_empty:
        return lines
    if b.geom_type == "LineString":
        lines = [b]
    elif hasattr(b, "geoms"):
        lines = [g for g in b.geoms if g.geom_type == "LineString"]
    return lines


def find_portals(plan, rooms, scale):
    """Geometry-first portal detection.

    Door portals: a door polygon associated with both rooms (room polygons are
    separated by wall thickness, so association is by proximity, not contact).
    Open-passage portals: for connected pairs with no door, wall-free spans of
    the line intersection of the room polygons are the opening.
    """
    walls_union = unary_union(parts(plan.get("wall"))) if parts(plan.get("wall")) else None
    door_polys = parts(plan.get("door"))
    door_tol = 0.30 / scale
    min_width_raw = 0.6 / scale

    portals = []
    seen = set()

    for a, b, attrs in plan["graph"].edges(data=True):
        if a not in rooms or b not in rooms:
            continue
        if attrs.get("type") not in CANDIDATE_EDGE_TYPES:
            continue
        key = tuple(sorted((a, b)))
        if key in seen:
            continue

        ga, gb = rooms[a]["geometry"], rooms[b]["geometry"]
        found_for_pair = False

        # --- Door-leaf portals (dedupe overlapping door polygons) ---
        doors_here = []
        for d in door_polys:
            if d.distance(ga) >= door_tol or d.distance(gb) >= door_tol:
                continue
            long_ax, short_ax = _rot_axes(d)
            width_m = math.hypot(*long_ax) * scale
            if width_m < 0.6:
                continue
            c = d.centroid
            if any(math.hypot(c.x - pc[0], c.y - pc[1]) < 0.5 * width_m / scale
                   for _, pc, _ in doors_here):
                continue
            doors_here.append((d, (c.x, c.y), (short_ax, long_ax, width_m)))

        for d, center, (short_ax, long_ax, width_m) in doors_here:
            portals.append({
                "rooms": (a, b),
                "polygon": d,
                "center": center,
                "cross_axis": unit(short_ax),
                "along_axis": unit(long_ax),
                "width_m": width_m,
                "kind": "door",
                "edge_type": attrs.get("type"),
            })
            found_for_pair = True

        if found_for_pair:
            seen.add(key)
            continue

        # --- Open-passage portals (wall-free spans of the shared line) ---
        boundary_lines = _shared_boundary(ga, gb, 0.05 / scale)
        for bl in boundary_lines:
            if walls_union is None:
                spans = [bl]
            else:
                free = bl.difference(walls_union)
                gs = [free] if free.geom_type == "LineString" else list(getattr(free, "geoms", []))
                spans = [g for g in gs if g.geom_type == "LineString"]
            for span in spans:
                if span.length < min_width_raw:
                    continue
                coords = list(span.coords)
                (x0, y0), (x1, y1) = coords[0], coords[-1]
                mid = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
                along = unit((x1 - x0, y1 - y0))
                cross = (-along[1], along[0])
                probe = Point(mid[0] + cross[0], mid[1] + cross[1])
                if gb.buffer(0.05 / scale).covers(probe):
                    cross = (-cross[0], -cross[1])
                portals.append({
                    "rooms": (a, b),
                    "polygon": span.buffer(0.5),
                    "center": mid,
                    "cross_axis": cross,
                    "along_axis": along,
                    "width_m": span.length * scale,
                    "kind": "opening",
                    "edge_type": attrs.get("type"),
                })
                seen.add(key)

    return portals


def portal_pins(portal, room_id, geometry, scale, wall_depth_raw):
    """Two enter/exit pin points for one side of a portal, offset +/- 8 cm
    along the opening axis so a dead-end room loop stays a simple polygon."""
    cx, cy = portal["center"]
    ax, ay = portal["along_axis"]
    off = PORTAL_OFFSET_M / scale

    # Orient the crossing direction so it points into this room.
    cand = [portal["cross_axis"], (-portal["cross_axis"][0], -portal["cross_axis"][1])]
    into = None
    for direction in cand:
        if geometry.covers(Point(cx + direction[0] * wall_depth_raw * 0.75,
                                 cy + direction[1] * wall_depth_raw * 0.75)):
            into = direction
            break
    if into is None:
        rep = geometry.representative_point()
        into = unit((rep.x - cx, rep.y - cy))

    depth = wall_depth_raw * 0.75
    base = (cx + into[0] * depth, cy + into[1] * depth)
    return {
        1: (base[0] + ax * off, base[1] + ay * off),
        2: (base[0] - ax * off, base[1] - ay * off),
    }


# ------------------------------------------------------------------
# Routing graph
# ------------------------------------------------------------------

def segment_valid(seg, room_geom, walls_union, portal_union_local, eps_raw):
    """Segment stays inside the room and does not pass through wall geometry
    (except through this room's own portal openings)."""
    if seg.length < 1e-9:
        return True
    if not room_geom.buffer(eps_raw).covers(seg):
        return False
    if walls_union is not None:
        bad = seg.intersection(walls_union).difference(portal_union_local)
        if bad.length > 1e-9:
            return False
    return True


def build_local_graph(room, portals_here, ring, inset, scale, candidate_points,
                      walls_union):
    """Nodes: device point, portal pins, ring vertices, panel candidates.
    Edges validated against the room interior and wall geometry."""
    gid = room["id"]
    g = nx.Graph()
    eps_raw = 0.05 / scale

    if portals_here:
        portal_union_local = unary_union(
            [p["polygon"] for p in portals_here.values()]
        )
    else:
        portal_union_local = None

    nodes = {}
    dev = ("dev", gid)
    nodes[dev] = (room["device_point"].x, room["device_point"].y)
    g.add_node(dev, pos=nodes[dev], kind="device")

    for key, portal in portals_here.items():
        for pin_idx, pos in portal["pins"][gid].items():
            nid = (f"pin_{key}_{pin_idx}", gid)
            nodes[nid] = pos
            g.add_node(nid, pos=pos, kind="pin")

    if ring:
        for i, pos in enumerate(ring):
            nid = (f"ring_{i}", gid)
            nodes[nid] = pos
            g.add_node(nid, pos=pos, kind="ring")

    for k, pos in enumerate(candidate_points):
        nid = (f"cand_{k}", gid)
        nodes[nid] = pos
        g.add_node(nid, pos=pos, kind="candidate")

    names = list(nodes)
    for u, v in combinations(names, 2):
        seg = LineString([nodes[u], nodes[v]])
        if segment_valid(seg, room["geometry"], walls_union, portal_union_local, eps_raw):
            g.add_edge(u, v, weight=seg.length * scale)

    return g, nodes


def build_global_graph(plan, rooms, portals, scale):
    wall_depth_raw = (plan.get("wall_depth") or (WALL_CLEARANCE_M / scale * 2))
    eps_raw = 0.05 / scale
    walls_union = unary_union(parts(plan.get("wall"))) if parts(plan.get("wall")) else None

    portals_by_room = {}
    for i, portal in enumerate(portals):
        portal["id"] = i
        portal["pins"] = {}
        for rid in portal["rooms"]:
            portal["pins"][rid] = portal_pins(
                portal, rid, rooms[rid]["geometry"], scale, wall_depth_raw
            )
            portals_by_room.setdefault(rid, {})[i] = portal

    rooms_graph_data = {}
    global_graph = nx.Graph()

    for rid, room in rooms.items():
        inset, ring = raceway_ring(room, scale, walls_union)
        cands_here = panel_candidates(rid, inset, scale)
        local, nodes = build_local_graph(
            room, portals_by_room.get(rid, {}), ring, inset, scale,
            [pos for _, pos in cands_here], walls_union,
        )
        rooms_graph_data[rid] = {
            "inset": inset, "local": local, "nodes": nodes,
            "candidates": cands_here,
        }
        global_graph.add_nodes_from(local.nodes(data=True))
        global_graph.add_edges_from(local.edges(data=True))

    # Portal crossing edges: every pin pair across the opening. The part of
    # the crossing that overlaps walls must lie inside the opening.
    for portal in portals:
        a, b = portal["rooms"]
        pa, pb = portal["pins"][a], portal["pins"][b]
        opening = portal["polygon"].buffer(eps_raw)
        for i in (1, 2):
            for j in (1, 2):
                na = (f"pin_{portal['id']}_{i}", a)
                nb = (f"pin_{portal['id']}_{j}", b)
                seg = LineString([pa[i], pb[j]])
                bad = (
                    seg.intersection(walls_union).difference(opening)
                    if walls_union is not None else None
                )
                if walls_union is None or bad.length <= 1e-9:
                    global_graph.add_edge(
                        na, nb, weight=seg.length * scale, portal=portal["id"]
                    )

    return global_graph, rooms_graph_data, portals


# ------------------------------------------------------------------
# Panel candidates
# ------------------------------------------------------------------

def panel_candidates(room, inset, scale):
    if inset is None:
        return []
    spacing = RING_SPACING_M / scale
    coords = list(inset.exterior.coords)
    cands, carried = [], 0.0
    for i in range(len(coords) - 1):
        x0, y0 = coords[i]
        x1, y1 = coords[i + 1]
        seg_len = math.hypot(x1 - x0, y1 - y0)
        pos = spacing - carried
        while pos <= seg_len:
            t = pos / seg_len if seg_len > 0 else 0.0
            cands.append((room, (x0 + t * (x1 - x0), y0 + t * (y1 - y0))))
            pos += spacing
        carried = (carried + seg_len) % spacing
        if len(cands) >= MAX_CANDIDATES_PER_ROOM:
            return cands[:MAX_CANDIDATES_PER_ROOM]
    return cands


# ------------------------------------------------------------------
# APSP
# ------------------------------------------------------------------

def shortest_paths(global_graph, sources):
    """Dijkstra from each source; returns dict src -> (dist, paths)."""
    result = {}
    for src in sources:
        dist, paths = nx.single_source_dijkstra(global_graph, src, weight="weight")
        result[src] = (dist, paths)
    return result


# ------------------------------------------------------------------
# Visualization
# ------------------------------------------------------------------

def draw_geom(ax, geom, fc, ec, alpha=0.3, lw=1.0):
    for p in parts(geom):
        xs, ys = p.exterior.xy
        ax.fill(xs, ys, facecolor=fc, edgecolor=ec, alpha=alpha, linewidth=lw)


def render(plan, rooms, portals, rooms_graph_data, global_graph, sample_routes, out_png):
    fig, ax = plt.subplots(figsize=(14, 11))
    draw_geom(ax, plan.get("inner"), "#FFFFFF", "#777777", 0.15)
    draw_geom(ax, plan.get("wall"), "#555555", "#333333", 0.9)
    for room in rooms.values():
        fc = "#A7CBE8" if room["eligible"] else "#DDDDDD"
        draw_geom(ax, room["geometry"], fc, "#356A91", 0.35)

    for portal in portals:
        ax.plot(*portal["center"], marker="^", color="#E67E22", markersize=9)

    for rid, data in rooms_graph_data.items():
        inset = data["inset"]
        if inset is not None:
            xs, ys = inset.exterior.xy
            ax.plot(xs, ys, color="#999999", linewidth=0.6, alpha=0.7)

    styles = ["#D35400", "#8E44AD", "#16A085", "#C0392B", "#2980B9"]
    for k, (coords, label) in enumerate(sample_routes):
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        ax.plot(xs, ys, color=styles[k % len(styles)], linewidth=2.0, label=label)

    for room in rooms.values():
        if room["eligible"]:
            d = room["device_point"]
            ax.plot(d.x, d.y, marker="s", color="#244B70", markersize=7)

    ax.set_title("Module 2 - raceway graph, verified portals, sample routes")
    ax.set_aspect("equal", adjustable="box")
    ax.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(out_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-id", default="14433")
    ap.add_argument("--out", default=None)
    ap.add_argument("--png", default=None)
    args = ap.parse_args()

    plan = common.load_plan(args.plan_id)
    cal = calibrate(plan)
    scale = cal["scale_m_per_raw"]

    print(f"Plan {args.plan_id} | scale {scale:.4f} m/raw-unit | "
          f"median door width {cal['median_door_width_m'] and round(cal['median_door_width_m'], 3)} m | "
          f"plausible={cal['door_width_plausible']}")

    rooms = extract_rooms(plan)
    eligible_ids = [rid for rid, r in rooms.items() if r["eligible"]]
    print(f"Rooms: {len(rooms)} total, {len(eligible_ids)} eligible")

    portals = find_portals(plan, rooms, scale)
    print(f"Verified portals: {len(portals)}")

    global_graph, rooms_graph_data, portals = build_global_graph(plan, rooms, portals, scale)
    print(f"Global routing graph: {global_graph.number_of_nodes()} nodes, "
          f"{global_graph.number_of_edges()} edges")

    # Reachability check for eligible rooms.
    if global_graph.number_of_nodes() > 0:
        comps = list(nx.connected_components(global_graph))
        print(f"Connected components: {len(comps)}")

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


if __name__ == "__main__":
    main()
