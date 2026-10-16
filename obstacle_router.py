import json
import pickle
import heapq
from pathlib import Path
from itertools import combinations

import matplotlib.pyplot as plt
import networkx as nx

from shapely.geometry import (
    Point,
    LineString,
    Polygon,
    MultiPolygon,
    GeometryCollection,
)
from shapely.ops import unary_union

DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

PLAN_ID = "14433"

OUTPUT_JSON = Path("obstacle_routes_14433.json")
OUTPUT_IMAGE = Path("obstacle_routes_14433.png")

ELIGIBLE_TYPES = {"living", "bedroom", "kitchen", "storage"}
PANEL_ROOM = "living_0"

# Exploratory raw coordinate units, not physical cable clearance.
WALL_CLEARANCE = 0.5

# Additional offset used to generate candidate waypoints.
WAYPOINT_OFFSET = 1.0

# Limit waypoint count to keep the visibility graph manageable.
MAX_WAYPOINTS = 500


def parts(geometry):
    if geometry is None or geometry.is_empty:
        return []

    if hasattr(geometry, "geoms"):
        return [g for g in geometry.geoms if not g.is_empty]

    return [geometry]


def load_plan():
    with DATASET_PATH.open("rb") as f:
        plans = pickle.load(f)

    plan = next(
        (p for p in plans if str(p.get("id")) == PLAN_ID),
        None,
    )

    if plan is None:
        raise ValueError(f"Plan {PLAN_ID} not found.")

    return plan


def polygon_obstacles(walls):
    """Return polygonal wall obstacles."""
    if walls is None or walls.is_empty:
        return []

    buffered = walls.buffer(WALL_CLEARANCE)

    return [
        p for p in parts(buffered)
        if isinstance(p, Polygon) and not p.is_empty
    ]

def boundary_waypoints(obstacles, offset):
    """
    Generate a reduced set of candidate waypoints from simplified
    obstacle boundaries. Coordinates are in raw dataset units.
    """
    points = []

    for obstacle in obstacles:
        # Reduce unnecessary vertices while preserving the broad shape.
        simplified = obstacle.simplify(
            tolerance=1.0,
            preserve_topology=True,
        )

        expanded = simplified.buffer(
            offset,
            join_style=2,
        )

        for polygon in parts(expanded):
            if not isinstance(polygon, Polygon):
                continue

            coordinates = list(polygon.exterior.coords)[:-1]

            for x, y in coordinates:
                points.append((float(x), float(y)))

    # Remove duplicate points.
    unique = list(dict.fromkeys(points))

    print("Generated candidate waypoints:", len(unique))

    if len(unique) > MAX_WAYPOINTS:
        raise ValueError(
            f"Still generated {len(unique)} waypoints. "
            "Further reduce obstacle complexity before routing."
        )

    return unique

def valid_segment(a, b, inner, obstacles):
    """Check a candidate segment against the building and obstacles."""
    segment = LineString([a, b])

    if segment.length == 0:
        return False

    if not inner.covers(segment):
        return False

    for obstacle in obstacles:
        if segment.intersects(obstacle):
            return False

    return True


def build_visibility_graph(start, end, inner, obstacles, waypoints):
    points = [start, end] + waypoints

    graph = nx.Graph()

    for index, point in enumerate(points):
        graph.add_node(index, point=point)

    # Connect pairs with collision-free line segments.
    for i, j in combinations(range(len(points)), 2):
        a = points[i]
        b = points[j]

        if valid_segment(a, b, inner, obstacles):
            distance = Point(a).distance(Point(b))

            graph.add_edge(
                i,
                j,
                weight=distance,
            )

    return graph, points


def shortest_route(start_point, end_point, inner, obstacles, waypoints):
    graph, points = build_visibility_graph(
        start_point,
        end_point,
        inner,
        obstacles,
        waypoints,
    )

    try:
        indices = nx.shortest_path(
            graph,
            source=0,
            target=1,
            weight="weight",
        )
    except nx.NetworkXNoPath:
        return None

    route_points = [points[i] for i in indices]

    route = LineString(route_points)

    return {
        "coordinates": [
            [round(x, 5), round(y, 5)]
            for x, y in route_points
        ],
        "length_raw_units": round(route.length, 5),
        "waypoint_count": len(route_points),
        "geometry": route,
    }


def main():
    print("Loading plan...")
    plan = load_plan()

    graph = plan["graph"]
    inner = plan.get("inner")
    walls = plan.get("wall")

    if inner is None or inner.is_empty:
        raise ValueError("Building interior geometry is missing.")

    rooms = {}

    for node_id, attrs in graph.nodes(data=True):
        room_type = attrs.get("type", "unknown")
        geometry = attrs.get("geometry")

        if (
            room_type in ELIGIBLE_TYPES
            and geometry is not None
            and not geometry.is_empty
        ):
            rooms[node_id] = {
                "type": room_type,
                "geometry": geometry,
                "point": geometry.representative_point(),
            }

    if PANEL_ROOM not in rooms:
        raise ValueError(f"Panel room {PANEL_ROOM} not found.")

    obstacles = polygon_obstacles(walls)

    # Build candidate waypoints from wall geometry.
    waypoints = boundary_waypoints(
        obstacles,
        WAYPOINT_OFFSET,
    )

    panel_point = rooms[PANEL_ROOM]["point"]
    results = []
    route_geometries = []

    print("Eligible device rooms:", len(rooms))
    print("Obstacle polygons:", len(obstacles))
    print("Candidate waypoints:", len(waypoints))

    for room_id, room in rooms.items():
        if room_id == PANEL_ROOM:
            continue

        device_point = room["point"]

        result = shortest_route(
            (panel_point.x, panel_point.y),
            (device_point.x, device_point.y),
            inner,
            obstacles,
            waypoints,
        )

        if result is None:
            print(f"{room_id}: NO COLLISION-FREE PATH FOUND")

            results.append({
                "room_id": room_id,
                "status": "NO_COLLISION_FREE_PATH_FOUND",
                "coordinates": [],
                "length_raw_units": None,
                "physical_passage_verified": False,
            })

            continue

        print(
            f"{room_id}: candidate length "
            f"{result['length_raw_units']}"
        )

        route_geometries.append(result["geometry"])

        results.append({
            "room_id": room_id,
            "status": "GEOMETRIC_PATH_CANDIDATE",
            "coordinates": result["coordinates"],
            "length_raw_units": result["length_raw_units"],
            "physical_passage_verified": False,
        })

    # Plot the candidate paths.
    fig, ax = plt.subplots(figsize=(14, 11))

    for polygon in parts(inner):
        if isinstance(polygon, Polygon):
            x, y = polygon.exterior.xy
            ax.plot(x, y, color="#777777", linewidth=1.2)

    for obstacle in obstacles:
        x, y = obstacle.exterior.xy
        ax.fill(
            x,
            y,
            color="#555555",
            alpha=0.75,
        )

    for room_id, room in rooms.items():
        point = room["point"]

        ax.scatter(
            point.x,
            point.y,
            marker="s",
            s=55,
        )

        ax.text(
            point.x,
            point.y,
            room_id,
            fontsize=8,
        )

    for route in route_geometries:
        x, y = route.xy
        ax.plot(x, y, linewidth=2)

    ax.scatter(
        panel_point.x,
        panel_point.y,
        marker="*",
        s=250,
        label="Provisional panel",
    )

    ax.set_title(
        f"Plan {PLAN_ID} — Obstacle-Aware Routing Candidates\n"
        "Geometric paths only; passage validity is unverified"
    )

    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("Dataset X coordinate (raw units)")
    ax.set_ylabel("Dataset Y coordinate (raw units)")
    ax.grid(True, alpha=0.2)
    ax.legend()

    plt.tight_layout()
    plt.savefig(OUTPUT_IMAGE, dpi=200, bbox_inches="tight")
    plt.close(fig)

    report = {
        "plan_id": PLAN_ID,
        "status": "GEOMETRIC_ROUTING_PROTOTYPE",
        "panel_room": PANEL_ROOM,
        "eligible_device_count": len(rooms),
        "obstacle_count": len(obstacles),
        "waypoint_count": len(waypoints),
        "wall_clearance_raw_units": WALL_CLEARANCE,
        "waypoint_offset_raw_units": WAYPOINT_OFFSET,
        "physical_passage_verified": False,
        "closed_loop_constructed": False,
        "routes": results,
        "limitations": [
            "Panel location is fixed.",
            "Each device is routed independently.",
            "No closed-loop visitation tour is constructed.",
            "Room-to-room passage connectivity is not verified.",
            "No area or panel capacity optimization is performed.",
            "Raw coordinate units are not calibrated.",
        ],
    }

    OUTPUT_JSON.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print("\nSaved:", OUTPUT_JSON.resolve())
    print("Saved:", OUTPUT_IMAGE.resolve())
    print("Passage verification: NOT COMPLETE")
    print("Closed-loop construction: NOT IMPLEMENTED")


if __name__ == "__main__":
    main()