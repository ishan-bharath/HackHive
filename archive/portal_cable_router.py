import json
import pickle
from pathlib import Path

from shapely.geometry import Point, LineString

DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

PLAN_ID = "14433"
PANEL_ROOM = "living_0"

OUTPUT_JSON = Path("portal_cable_routes_14433.json")

# Exploratory geometry parameters; not calibrated physical clearances.
WALL_CLEARANCE = 0.5
PORTAL_OFFSET = 2.0

# Portal candidates supported by the previous geometric audit.
PORTALS = {
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


def make_obstacles(walls):
    if walls is None or walls.is_empty:
        return None

    return walls.buffer(WALL_CLEARANCE)


def candidate_crossings(door, room_a, room_b):
    """
    Produce provisional points on opposite sides of a portal.

    These points are exploratory. They do not establish that
    the opening is physically traversable.
    """
    center = door.centroid

    minx, miny, maxx, maxy = door.bounds
    width_x = maxx - minx
    width_y = maxy - miny

    if width_x < width_y:
        # Door's narrow dimension is horizontal.
        candidates = [
            (
                (center.x - PORTAL_OFFSET, center.y),
                (center.x + PORTAL_OFFSET, center.y),
            ),
        ]
    else:
        # Door's narrow dimension is vertical.
        candidates = [
            (
                (center.x, center.y - PORTAL_OFFSET),
                (center.x, center.y + PORTAL_OFFSET),
            ),
        ]

    valid = []

    for a, b in candidates:
        pa = Point(a)
        pb = Point(b)

        # Keep a pair only if the points can be associated with
        # opposite room geometries.
        if (
            room_a.distance(pa) <= PORTAL_OFFSET + 1
            and room_b.distance(pb) <= PORTAL_OFFSET + 1
        ):
            valid.append((a, b))

        elif (
            room_b.distance(pa) <= PORTAL_OFFSET + 1
            and room_a.distance(pb) <= PORTAL_OFFSET + 1
        ):
            valid.append((b, a))

    return valid


def main():
    print("Loading plan...")
    plan = load_plan()

    graph = plan["graph"]
    doors = flatten(plan.get("door"))
    walls = plan.get("wall")

    obstacle_geometry = make_obstacles(walls)

    panel_room = graph.nodes[PANEL_ROOM]["geometry"]
    panel_point = panel_room.representative_point()

    results = []

    for room_id, door_index in PORTALS.items():
        room = graph.nodes[room_id]["geometry"]
        door = doors[door_index]

        print(f"\nRouting panel to {room_id} through door_{door_index}")

        crossing_pairs = candidate_crossings(
            door,
            panel_room,
            room,
        )

        if not crossing_pairs:
            print("No candidate crossing points found.")

            results.append({
                "room_id": room_id,
                "portal_id": f"door_{door_index}",
                "status": "NO_CANDIDATE_CROSSING",
                "physical_passage_verified": False,
            })

            continue

        # This prototype checks only the short crossing segment.
        # It does not yet route from the panel to the portal or
        # from the portal to the device.
        crossing_results = []

        for a, b in crossing_pairs:
            segment = LineString([a, b])

            intersects_obstacles = (
                obstacle_geometry is not None
                and segment.intersects(obstacle_geometry)
            )

            crossing_results.append({
                "point_a": list(a),
                "point_b": list(b),
                "length_raw_units": round(segment.length, 5),
                "intersects_buffered_walls": intersects_obstacles,
                "physical_passage_verified": False,
            })

            print(
                f"Candidate crossing length={segment.length:.3f}; "
                f"intersects buffered walls={intersects_obstacles}"
            )

        results.append({
            "room_id": room_id,
            "portal_id": f"door_{door_index}",
            "status": "CROSSING_DIAGNOSTIC",
            "candidate_crossings": crossing_results,
            "physical_passage_verified": False,
        })

    report = {
        "plan_id": PLAN_ID,
        "status": "PORTAL_CROSSING_DIAGNOSTIC",
        "panel_room": PANEL_ROOM,
        "wall_clearance_raw_units": WALL_CLEARANCE,
        "portal_offset_raw_units": PORTAL_OFFSET,
        "physical_passages_verified": False,
        "routes": results,
        "limitations": [
            "Only candidate crossing segments are tested.",
            "Complete panel-to-device routes are not constructed.",
            "Wall intersection tests may reject valid doorway crossings.",
            "Doorway geometry has not been independently validated.",
            "Kitchen connection remains unresolved.",
            "Closed-loop construction is not implemented.",
        ],
    }

    OUTPUT_JSON.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print("\nSaved:", OUTPUT_JSON.resolve())
    print("Complete cable routing: NOT IMPLEMENTED")
    print("Physical passage verification: NOT COMPLETE")


if __name__ == "__main__":
    main()
