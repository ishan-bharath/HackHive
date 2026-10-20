import json
import pickle
from pathlib import Path


DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

PLAN_ID = "14433"
OUTPUT_JSON = Path("portal_geometry_test_14433.json")

ROOM_PAIRS = [
    ("living_0", "bedroom_0"),
    ("living_0", "bedroom_1"),
    ("living_0", "bedroom_2"),
]

ASSOCIATION_THRESHOLD = 5.0  # Exploratory raw units only
WALL_CLEARANCE = 0.5         # Exploratory raw units only


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


def main():
    plan = load_plan()
    graph = plan["graph"]

    rooms = {
        node: attrs["geometry"]
        for node, attrs in graph.nodes(data=True)
        if attrs.get("geometry") is not None
        and not attrs["geometry"].is_empty
    }

    doors = flatten(plan.get("door"))
    walls = plan.get("wall")

    wall_obstacle = (
        walls.buffer(WALL_CLEARANCE)
        if walls is not None and not walls.is_empty
        else None
    )

    results = []

    for room_a, room_b in ROOM_PAIRS:
        a = rooms[room_a]
        b = rooms[room_b]

        print(f"\n{room_a} <--> {room_b}")

        candidates = []

        for index, door in enumerate(doors):
            da = a.distance(door)
            db = b.distance(door)

            if max(da, db) > ASSOCIATION_THRESHOLD:
                continue

            # Use the door's representative point as a diagnostic
            # location, NOT as a confirmed cable portal.
            point = door.representative_point()

            point_in_a = a.covers(point)
            point_in_b = b.covers(point)

            candidates.append({
                "door_id": f"door_{index}",
                "distance_to_room_a": round(da, 4),
                "distance_to_room_b": round(db, 4),
                "representative_point": [
                    round(point.x, 5),
                    round(point.y, 5),
                ],
                "point_in_room_a": point_in_a,
                "point_in_room_b": point_in_b,
                "physical_passage_verified": False,
            })

        for candidate in candidates:
            print(
                f"  {candidate['door_id']}: "
                f"dA={candidate['distance_to_room_a']}, "
                f"dB={candidate['distance_to_room_b']}, "
                f"inside A={candidate['point_in_room_a']}, "
                f"inside B={candidate['point_in_room_b']}"
            )

        results.append({
            "room_a": room_a,
            "room_b": room_b,
            "candidates": candidates,
            "physical_passage_verified": False,
        })

    report = {
        "plan_id": PLAN_ID,
        "status": "PORTAL_DIAGNOSTIC",
        "association_threshold_raw_units": ASSOCIATION_THRESHOLD,
        "wall_clearance_raw_units": WALL_CLEARANCE,
        "thresholds_calibrated": False,
        "physical_passages_verified": False,
        "connections": results,
        "limitations": [
            "Door proximity does not prove room connectivity.",
            "Representative points are not actual doorway centre-lines.",
            "Door opening geometry and width are not validated.",
            "Cable paths are not yet routed through these candidates.",
        ],
    }

    OUTPUT_JSON.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print("\nSaved:", OUTPUT_JSON.resolve())
    print("Physical passage verification: NOT COMPLETE")


if __name__ == "__main__":
    main()
