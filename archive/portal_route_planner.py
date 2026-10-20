import json
import pickle
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx

from shapely.geometry import Point, LineString, Polygon

DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

PLAN_ID = "14433"
PANEL_ROOM = "living_0"

OUTPUT_JSON = Path("room_constrained_routes_14433.json")
OUTPUT_IMAGE = Path("room_constrained_routes_14433.png")

WALL_CLEARANCE = 0.5
WAYPOINT_OFFSET = 1.0
MAX_WAYPOINTS = 250

# Provisional portal candidates from our geometry audit.
PORTAL_IDS = {
    "bedroom_0": 1,
    "bedroom_1": 2,
    "bedroom_2": 3,
}


def flatten(geometry):
    if geometry is None or geometry.is_empty:
        return []

    if hasattr(geometry, "geoms"):
        result = []
        for item in geometry.geoms:
            result.extend(flatten(item))
        return result

    return [geometry]


def load_plan():
    with DATASET_PATH.open("rb") as f:
        plans = pickle.load(f)

    plan = next(
        (p for p in plans if str(p.get("id")) == PLAN_ID),
        None,
    )

    if plan is None:
        raise ValueError(f"Plan {PLAN_ID} not found")

    return plan


def build_obstacles(walls):
    if walls is None or walls.is_empty:
        return []

    buffered = walls.buffer(WALL_CLEARANCE)

    return [
        part for part in flatten(buffered)
        if isinstance(part, Polygon)
    ]


def generate_waypoints(obstacles, room):
    points = []

    for obstacle in obstacles:
        # Keep only obstacle boundaries relevant to this room.
        if not obstacle.intersects(room):
            continue

        simplified = obstacle.simplify(
            1.0,
            preserve_topology=True,
        )

        expanded = simplified.buffer(
            WAYPOINT_OFFSET,
            join_style=2,
        )

        for polygon in flatten(expanded):
            if not isinstance(polygon, Polygon):
                continue

            for x, y in list(polygon.exterior.coords)[:-1]:
                point = Point(x, y)

                if room.covers(point):
                    points.append((float(x), float(y)))

    points = list(dict.fromkeys(points))

    if len(points) > MAX_WAYPOINTS:
        raise ValueError(
            f"Room generated {len(points)} waypoints; "
            f"limit is {MAX_WAYPOINTS}."
        )

    return points


def segment_valid(a, b, room, obstacles):
    segment = LineString([a, b])

    if segment.length == 0:
        return False

    if not room.covers(segment):
        return False

    if any(segment.intersects(obstacle) for obstacle in obstacles):
        return False

    return True


def shortest_path(start, end, room, obstacles):
    start_point = Point(start)
    end_point = Point(end)

    if not room.covers(start_point):
        return None

    if not room.covers(end_point):
        return None

    waypoints = generate_waypoints(obstacles, room)
    points = [start, end] + waypoints

    visibility = nx.Graph()
    visibility.add_nodes_from(range(len(points)))

    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            a = points[i]
            b = points[j]

            if segment_valid(a, b, room, obstacles):
                visibility.add_edge(
                    i,
                    j,
                    weight=Point(a).distance(Point(b)),
                )

    try:
        indices = nx.shortest_path(
            visibility,
            source=0,
            target=1,
            weight="weight",
        )
    except nx.NetworkXNoPath:
        return None

    return LineString([points[i] for i in indices])


def main():
    print("Loading plan...")
    plan = load_plan()

    graph = plan["graph"]
    inner = plan.get("inner")
    walls = plan.get("wall")
    doors = flatten(plan.get("door"))

    if inner is None or inner.is_empty:
        raise ValueError("Building interior geometry is missing")

    rooms = {}

    for node, attrs in graph.nodes(data=True):
        geometry = attrs.get("geometry")

        if (
            attrs.get("type") in {
                "living", "bedroom", "kitchen", "storage"
            }
            and geometry is not None
            and not geometry.is_empty
        ):
            rooms[node] = {
                "geometry": geometry,
                "point": geometry.representative_point(),
                "type": attrs["type"],
            }

    if PANEL_ROOM not in rooms:
        raise ValueError(f"Panel room {PANEL_ROOM} not found")

    obstacles = build_obstacles(walls)
    panel_point = rooms[PANEL_ROOM]["point"]

    results = []
    route_geometries = []

    print("Eligible rooms:", len(rooms))
    print("Obstacle polygons:", len(obstacles))

    for bedroom, door_index in PORTAL_IDS.items():
        print(f"\nChecking {PANEL_ROOM} -> {bedroom}")

        living_geometry = rooms[PANEL_ROOM]["geometry"]
        bedroom_geometry = rooms[bedroom]["geometry"]
        door = doors[door_index]

        center = door.centroid
        minx, miny, maxx, maxy = door.bounds

        if maxx - minx < maxy - miny:
            pair = [
                (center.x - 2, center.y),
                (center.x + 2, center.y),
            ]
        else:
            pair = [
                (center.x, center.y - 2),
                (center.x, center.y + 2),
            ]

        a, b = pair

        # Orient the points according to room proximity.
        if (
            living_geometry.distance(Point(b))
            + bedroom_geometry.distance(Point(a))
            <
            living_geometry.distance(Point(a))
            + bedroom_geometry.distance(Point(b))
        ):
            a, b = b, a

        # The crossing must lie entirely inside the door polygon.
        crossing = LineString([a, b])

        if not door.covers(crossing):
            status = "CROSSING_OUTSIDE_DOOR"
            route = None
        else:
            # Find room-contained paths to the portal endpoints.
            first = shortest_path(
                (panel_point.x, panel_point.y),
                a,
                living_geometry,
                obstacles,
            )

            second = shortest_path(
                b,
                (
                    rooms[bedroom]["point"].x,
                    rooms[bedroom]["point"].y,
                ),
                bedroom_geometry,
                obstacles,
            )

            if first is None:
                route = None
                status = "NO_ROOM_CONSTRAINED_PATH_TO_PORTAL"
            elif second is None:
                route = None
                status = "NO_ROOM_CONSTRAINED_PATH_TO_DEVICE"
            else:
                coordinates = (
                    list(first.coords)
                    + [b]
                    + list(second.coords)[1:]
                )

                route = LineString(coordinates)

                # Validate the two room segments individually.
                # The crossing is evaluated separately because the
                # dataset's wall polygons overlap door polygons.
                valid_first = all(
                    segment_valid(p, q, living_geometry, obstacles)
                    for p, q in zip(
                        list(first.coords),
                        list(first.coords)[1:],
                    )
                )

                valid_second = all(
                    segment_valid(p, q, bedroom_geometry, obstacles)
                    for p, q in zip(
                        list(second.coords),
                        list(second.coords)[1:],
                    )
                )

                if not valid_first or not valid_second:
                    route = None
                    status = "ROOM_SEGMENT_VALIDATION_FAILED"
                else:
                    status = "ROOM_CONSTRAINED_CANDIDATE"

        if route is None:
            print("  Result:", status)

            results.append({
                "room_id": bedroom,
                "portal_id": f"door_{door_index}",
                "status": status,
                "coordinates": [],
                "length_raw_units": None,
                "physical_passage_verified": False,
            })
            continue

        print(f"  Candidate length: {route.length:.3f} raw units")

        route_geometries.append((bedroom, route))

        results.append({
            "room_id": bedroom,
            "portal_id": f"door_{door_index}",
            "status": status,
            "coordinates": [
                [round(x, 5), round(y, 5)]
                for x, y in route.coords
            ],
            "length_raw_units": round(route.length, 5),
            "physical_passage_verified": False,
        })

    fig, ax = plt.subplots(figsize=(14, 11))

    for polygon in flatten(inner):
        if isinstance(polygon, Polygon):
            x, y = polygon.exterior.xy
            ax.plot(x, y, color="black", linewidth=1.2)

    for obstacle in obstacles:
        x, y = obstacle.exterior.xy
        ax.fill(x, y, color="gray", alpha=0.55)

    for room_id, room in rooms.items():
        point = room["point"]
        ax.scatter(point.x, point.y, marker="s", s=45)
        ax.text(point.x, point.y, room_id, fontsize=8)

    for room_id, route in route_geometries:
        x, y = route.xy
        ax.plot(x, y, linewidth=2, label=room_id)

    ax.scatter(
        panel_point.x,
        panel_point.y,
        marker="*",
        s=200,
        label="Provisional panel",
    )

    ax.set_title("Room-Constrained Routing Candidates — Plan 14433")
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("Raw dataset X")
    ax.set_ylabel("Raw dataset Y")
    ax.grid(True, alpha=0.2)
    ax.legend()

    plt.tight_layout()
    plt.savefig(OUTPUT_IMAGE, dpi=200, bbox_inches="tight")
    plt.close(fig)

    report = {
        "plan_id": PLAN_ID,
        "status": "ROOM_CONSTRAINED_ROUTING_PROTOTYPE",
        "panel_room": PANEL_ROOM,
        "physical_passages_verified": False,
        "closed_loop_constructed": False,
        "routes": results,
        "limitations": [
            "Portal crossing is still provisional.",
            "The kitchen connection remains unresolved.",
            "Doorway clear width is not validated.",
            "Panel placement is fixed.",
            "Raw coordinate units are not calibrated.",
            "No closed-loop visitation tour is constructed.",
        ],
    }

    OUTPUT_JSON.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print("\nSaved:", OUTPUT_JSON.resolve())
    print("Saved:", OUTPUT_IMAGE.resolve())
    print("Physical passage verification: NOT COMPLETE")
    print("Closed loop: NOT IMPLEMENTED")


if __name__ == "__main__":
    main()
