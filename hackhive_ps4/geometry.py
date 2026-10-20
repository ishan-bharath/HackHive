"""Portal verification, wall-hugging raceway graph and scale calibration
(former module2_wall_router_and_matrix.py, geometry half).

Tier 1 of the two-tier architecture. Given one floor plan this module:
  1. Calibrates the raw coordinate scale to metres (official inner/area
     ratio, door-width cross-check).
  2. Extracts eligible + transit rooms and geometrically verifies portals
     between them.
  3. Builds a room-local routing graph per room (raceway ring vertices,
     device point, portal anchor pins, L-bend corners) with AXIS-ALIGNED
     segments validated against room interiors and walls.
  4. Stitches rooms through portal crossings into one global routing graph.

The APSP D/B matrices live in matrices.py; the CLI in matrices.main; the
verification PNG in render.py. Matrices feed optimize.py.
"""

import math
from itertools import combinations

import numpy as np
import networkx as nx
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import nearest_points, unary_union

from . import config as common

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


def count_bends(coords) -> int:
    return sum(
        1
        for i in range(1, len(coords) - 1)
        if turn_angle(coords[i - 1], coords[i], coords[i + 1]) >= BEND_ANGLE_THRESHOLD_DEG
    )


# ------------------------------------------------------------------
# Calibration
# ------------------------------------------------------------------

def calibrate(plan: dict) -> dict:
    """Official PS4 scale (slide 4): scale_units_per_m = sqrt(inner.area /
    plan['area']), i.e. scale_m_per_raw = 1 / that. The median door width is
    computed only as a printed sanity cross-check. net_area is NEVER used
    (0 in 32% of plans)."""
    inner = largest(plan.get("inner"))
    if inner is None:
        raise ValueError("Cannot calibrate: missing inner geometry.")

    area_val = plan.get("area")
    if area_val is None:
        raise ValueError(
            "Official scale requires plan['area'] (floor area in m^2); "
            "this plan has none and net_area must not be used.")
    area_val = float(area_val)
    if area_val <= 0:
        raise ValueError(
            f"Official scale requires plan['area'] > 0; got {area_val}.")

    units_per_m = math.sqrt(inner.area / area_val)
    scale = 1.0 / units_per_m

    door_widths_raw = []
    for d in parts(plan.get("door")):
        cs = list(d.minimum_rotated_rectangle.exterior.coords)
        e1 = math.dist(cs[0], cs[1])
        e2 = math.dist(cs[1], cs[2])
        door_widths_raw.append(max(e1, e2))
    med_door_raw = float(np.median(door_widths_raw)) if door_widths_raw else None

    door_scale = common.NOMINAL_DOOR_WIDTH_M / med_door_raw if med_door_raw else None
    area_door_check = med_door_raw * scale if med_door_raw else None

    return {
        "scale_m_per_raw": scale,
        "units_per_m": units_per_m,
        "method": "official_inner_area_ratio",
        "reported_area_m2": area_val,
        "inner_area_raw": inner.area,
        "door_based_scale": door_scale,
        "median_door_width_m": med_door_raw * scale if med_door_raw else None,
        "area_implied_door_width_m": area_door_check,
        "area_door_width_plausible": (
            area_door_check is not None and 0.6 <= area_door_check <= 1.2
        ),
        "wall_depth_m": (plan.get("wall_depth") or 0.0) * scale,
    }


# ------------------------------------------------------------------
# Rooms
# ------------------------------------------------------------------

def extract_rooms(plan: dict) -> dict:
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


def _door_opens_between(center, cross, ga, gb, wall_depth_raw):
    """A door connects two rooms only if they lie on OPPOSITE sides of the
    door within a short crossing distance (guards against doors that merely
    come close to both polygons at a corner junction)."""
    for mult in (0.5, 1.0, 1.5, 2.0, 3.0):
        d = wall_depth_raw * mult
        pa = Point(center[0] + cross[0] * d, center[1] + cross[1] * d)
        pb = Point(center[0] - cross[0] * d, center[1] - cross[1] * d)
        if ga.covers(pa) and gb.covers(pb):
            return True
        pa2 = Point(center[0] - cross[0] * d, center[1] - cross[1] * d)
        pb2 = Point(center[0] + cross[0] * d, center[1] + cross[1] * d)
        if ga.covers(pa2) and gb.covers(pb2):
            return True
    return False


def find_portals(plan: dict, rooms: dict, scale: float) -> list:
    """Geometry-first portal detection.

    Door portals: a door polygon associated with both rooms (room polygons are
    separated by wall thickness, so association is by proximity, not contact).
    Open-passage portals: wall-free spans of the line intersection of the room
    polygons.

    Sources: graph edges of candidate types, PLUS every geometrically touching
    or wall-adjacent room pair - the stored graph misses edges in some plans.
    """
    walls_union = unary_union(parts(plan.get("wall"))) if parts(plan.get("wall")) else None
    door_polys = parts(plan.get("door"))
    door_tol = 0.30 / scale
    min_width_raw = 0.6 / scale
    wall_depth_raw = plan.get("wall_depth") or 0.0
    pair_reach = max(1.5 * wall_depth_raw, door_tol)

    portals = []
    seen_pairs = set()

    def portals_for_pair(a, b, edge_type):
        key = tuple(sorted((a, b)))
        if key in seen_pairs:
            return
        ga, gb = rooms[a]["geometry"], rooms[b]["geometry"]
        if ga.distance(gb) > pair_reach:
            return
        found_for_pair = False
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
            if not _door_opens_between(center, unit(short_ax), ga, gb,
                                       wall_depth_raw):
                continue
            portals.append({
                "rooms": (a, b),
                "polygon": d,
                "center": center,
                "cross_axis": unit(short_ax),
                "along_axis": unit(long_ax),
                "width_m": width_m,
                "kind": "door",
                "edge_type": edge_type,
            })
            found_for_pair = True

        if found_for_pair:
            seen_pairs.add(key)
            return

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
                    "edge_type": edge_type,
                })
                seen_pairs.add(key)

    # Pass 1: graph edges of candidate types.
    for a, b, attrs in plan["graph"].edges(data=True):
        if a not in rooms or b not in rooms:
            continue
        if attrs.get("type") not in CANDIDATE_EDGE_TYPES:
            continue
        portals_for_pair(a, b, attrs.get("type"))

    # Pass 2: geometrically adjacent pairs (catches missing graph edges).
    ids = sorted(rooms)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            portals_for_pair(a, b, "geometric")

    return portals


def _ensure_inside(pt, geometry):
    """Return a point guaranteed inside the geometry: pull toward the
    representative point until covered."""
    if geometry.covers(Point(pt)):
        return pt
    rep = geometry.representative_point()
    for t in (0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0):
        q = (pt[0] + (rep.x - pt[0]) * t, pt[1] + (rep.y - pt[1]) * t)
        if geometry.covers(Point(q)):
            return q
    return (rep.x, rep.y)


def portal_pins(portal, room_id, geometry, scale, wall_depth_raw):
    """Two enter/exit pin points for one side of a portal, offset +/- 8 cm
    along the opening axis so a dead-end room loop stays a simple polygon.

    Pin placement: probe along the crossing direction at increasing depths
    until inside the room; fall back to the nearest boundary point nudged
    toward the room interior. Both pins are guaranteed inside the room."""
    from shapely.ops import nearest_points

    cx, cy = portal["center"]
    ax, ay = portal["along_axis"]
    off = PORTAL_OFFSET_M / scale

    cross = portal["cross_axis"]
    base = None
    for direction in (cross, (-cross[0], -cross[1])):
        for mult in (0.25, 0.5, 0.75, 1.0, 1.5, 2.5, 4.0):
            p = (cx + direction[0] * wall_depth_raw * mult,
                 cy + direction[1] * wall_depth_raw * mult)
            if geometry.covers(Point(p)):
                base = p
                break
        if base:
            break
    if base is None:
        ngeom, _ = nearest_points(geometry, Point(cx, cy))
        rep = geometry.representative_point()
        into = unit((rep.x - ngeom.x, rep.y - ngeom.y))
        nudge = max(0.1 * wall_depth_raw, 0.05 / scale)
        base = (ngeom.x + into[0] * nudge, ngeom.y + into[1] * nudge)
        if not geometry.covers(Point(base)):
            base = (ngeom.x, ngeom.y)

    pin1 = _ensure_inside((base[0] + ax * off, base[1] + ay * off), geometry)
    pin2 = _ensure_inside((base[0] - ax * off, base[1] - ay * off), geometry)
    return {1: pin1, 2: pin2}


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
        bad = seg.intersection(walls_union)
        if portal_union_local is not None:
            bad = bad.difference(portal_union_local)
        if bad is not None and not bad.is_empty and bad.length > 1e-9:
            return False
    return True


def build_local_graph(room, portals_here, ring, inset, scale, candidate_points,
                      walls_union):
    """Nodes: device point, portal pins, ring vertices, panel candidates,
    plus L-bend corner nodes. ALL edges are axis-aligned (official PS4 rule 5:
    cable runs only horizontally or vertically):
      - node pairs that already share x or y get a straight edge when covered;
      - every other pair is connected via an L-shaped 2-leg path through a
        bend node at the corner; both orientations are tried and BOTH legs
        must be covered by the room's free area, else the pair gets no edge
        (Dijkstra routes around via other neighbours).
    Edge weight = leg length (manhattan) * scale."""
    gid = room["id"]
    g = nx.Graph()

    free_area = room["geometry"].difference(walls_union) if walls_union is not None \
        else room["geometry"]
    if portals_here:
        free_area = unary_union([free_area] + [p["polygon"] for p in portals_here.values()])

    # Device point must lie in the open floor.
    dev_pos = (room["device_point"].x, room["device_point"].y)
    if not free_area.covers(Point(dev_pos)):
        free_geom = room["geometry"].difference(walls_union) if walls_union is not None \
            else room["geometry"]
        if not free_geom.is_empty:
            near = nearest_points(free_geom, Point(dev_pos))[0]
            dev_pos = (near.x, near.y)
    room = dict(room, device_point=Point(dev_pos))

    nodes = {}
    dev = ("dev", gid)
    nodes[dev] = dev_pos
    g.add_node(dev, pos=dev_pos, kind="device")

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

    # Shared bend-node registry: corners are deduped by position so many
    # L-paths reuse the same rectification vertex.
    bend_pos = {}

    def bend_node(pos):
        key = (round(pos[0], 4), round(pos[1], 4))
        if key not in bend_pos:
            nid = (f"bend_{len(bend_pos)}", gid)
            bend_pos[key] = nid
            nodes[nid] = pos
            g.add_node(nid, pos=pos, kind="bend")
        return bend_pos[key]

    def covered_leg(p, q):
        return LineString([p, q]) if free_area.covers(LineString([p, q])) else None

    def add_leg(p, q, ua, va):
        seg = covered_leg(p, q)
        if seg is None:
            return False
        if seg.length >= 1e-9:
            g.add_edge(ua, va, weight=seg.length * scale)
        return True

    names = list(nodes)
    for u, v in combinations(names, 2):
        pu, pv = nodes[u], nodes[v]
        dx, dy = pv[0] - pu[0], pv[1] - pu[1]
        if abs(dx) < 1e-9 or abs(dy) < 1e-9:
            # Already axis-aligned: straight edge when covered.
            add_leg(pu, pv, u, v)
        else:
            # L-shape through a corner bend node; try both orientations.
            for corner in ((pu[0], pv[1]), (pv[0], pu[1])):
                leg1 = covered_leg(pu, corner)
                leg2 = covered_leg(corner, pv)
                if leg1 is not None and leg2 is not None:
                    c = bend_node(corner)
                    if leg1.length >= 1e-9:
                        g.add_edge(u, c, weight=leg1.length * scale)
                    if leg2.length >= 1e-9:
                        g.add_edge(c, v, weight=leg2.length * scale)
                    break

    # Drop bend nodes that never got connected (failed L attempts).
    for nid in [n for n, d in g.nodes(data=True) if d.get("kind") == "bend"]:
        if g.degree(nid) == 0:
            g.remove_node(nid)
            nodes.pop(nid, None)

    return g, nodes


def draw_geom(ax, geom, fc, ec, alpha=0.3, lw=1.0):
    for p in parts(geom):
        xs, ys = p.exterior.xy
        ax.fill(xs, ys, facecolor=fc, edgecolor=ec, alpha=alpha, linewidth=lw)


def hub_candidates_inset(room, scale, walls_union):
    """Inset polygon for panel-candidate generation: official rule 6 requires
    the hub at least 0.5 m from walls, so candidates are sampled on an inset
    of 0.6 m (with shrinking fallbacks down to just above the 0.5 m minimum).
    Returns None when even the minimum clearance cannot be met."""
    base = room["geometry"]
    if walls_union is not None:
        base = base.difference(walls_union)
    for clearance in (common.HUB_CLEARANCE_M, 0.55, common.HUB_MIN_CLEARANCE_M + 0.005):
        inset = base.buffer(-clearance / scale)
        if inset.is_empty:
            continue
        inset = largest(inset)
        if inset is not None and inset.geom_type == "Polygon" \
                and inset.exterior.length > 4 * clearance / scale:
            return inset
    return None


def build_global_graph(plan: dict, rooms: dict, portals: list,
                        scale: float):
    wall_depth_raw = (plan.get("wall_depth") or (WALL_CLEARANCE_M / scale * 2))
    walls_union = unary_union(parts(plan.get("wall"))) if parts(plan.get("wall")) else None

    portals_by_room: dict = {}
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
        hub_inset = hub_candidates_inset(room, scale, walls_union)
        cands_here = panel_candidates(rid, hub_inset, scale)
        if not cands_here:
            free = room["geometry"].difference(walls_union) if walls_union is not None \
                else room["geometry"]
            if free.is_empty:
                free = room["geometry"]
            rep = largest(free) or free
            rep = rep.representative_point()
            cands_here = [(rid, (rep.x, rep.y))]
        local, nodes = build_local_graph(
            room, portals_by_room.get(rid, {}), ring, inset, scale,
            [pos for _, pos in cands_here], walls_union,
        )
        rooms_graph_data[rid] = {
            "inset": inset, "local": local, "nodes": nodes,
            "candidates": cands_here,
        }
        rooms[rid]["device_point"] = Point(nodes[("dev", rid)])
        global_graph.add_nodes_from(local.nodes(data=True))
        global_graph.add_edges_from(local.edges(data=True))

    # Portal crossing edges: every pin pair across the opening, AXIS-ALIGNED.
    # A straight crossing is used only when the pins share x or y; otherwise
    # an L-bend node is inserted inside the opening polygon (both corner
    # orientations tried). The part of any leg overlapping walls must lie
    # inside the opening (small tolerance for dataset door/wall misalignment).
    crossing_tol = 0.15 / scale
    portal_cross_bends = {}
    for portal in portals:
        a, b = portal["rooms"]
        pa, pb = portal["pins"][a], portal["pins"][b]
        opening = portal["polygon"].buffer(crossing_tol)

        def wall_free(seg):
            if walls_union is None:
                return True
            bad = seg.intersection(walls_union).difference(opening)
            return bad is None or bad.is_empty or bad.length <= 1e-9

        def cross_bend(pos, tag):
            key = (portal["id"], round(pos[0], 4), round(pos[1], 4))
            if key not in portal_cross_bends:
                nid = (f"xpin_{portal['id']}_{tag}", "cross")
                portal_cross_bends[key] = nid
                global_graph.add_node(nid, pos=pos, kind="bend")
            return portal_cross_bends[key]

        for i in (1, 2):
            for j in (1, 2):
                na = (f"pin_{portal['id']}_{i}", a)
                nb = (f"pin_{portal['id']}_{j}", b)
                pu, pv = pa[i], pb[j]
                dx, dy = pv[0] - pu[0], pv[1] - pu[1]
                if abs(dx) < 1e-9 or abs(dy) < 1e-9:
                    seg = LineString([pu, pv])
                    if wall_free(seg):
                        global_graph.add_edge(
                            na, nb, weight=seg.length * scale,
                            portal=portal["id"]
                        )
                    continue
                for corner in ((pu[0], pv[1]), (pv[0], pu[1])):
                    seg1 = LineString([pu, corner])
                    seg2 = LineString([corner, pv])
                    if wall_free(seg1) and wall_free(seg2):
                        c = cross_bend(corner, f"{i}{j}_{len(portal_cross_bends)}")
                        if seg1.length >= 1e-9:
                            global_graph.add_edge(
                                na, c, weight=seg1.length * scale,
                                portal=portal["id"])
                        if seg2.length >= 1e-9:
                            global_graph.add_edge(
                                c, nb, weight=seg2.length * scale,
                                portal=portal["id"])
                        break

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
    if not cands:
        # Degenerate room: fall back to a single candidate at the inset
        # representative point so a wall panel position always exists.
        rep = inset.representative_point()
        cands.append((room, (rep.x, rep.y)))
    return cands


