import json
import pickle
from pathlib import Path


DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

PLAN_ID = "14433"

ROOM_PAIRS = [
    ("living_0", "bedroom_0"),
    ("living_0", "bedroom_1"),
    ("living_0", "bedroom_2"),
]

OUTPUT_JSON = Path("portals_14433.json")

# Diagnostic tolerance only; not a physical clearance specification.
MAX_ROOM_DISTANCE = 5.0


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


def describe_door(index, door, room_a, room_b):
    distance_a = room_a.distance(door)
    distance_b = room_b.distance(door)

    minx, miny, maxx, maxy = door.bounds

    return {
        "portal_id": f"door_{index}",
        "geometry_type": door.geom_type,
        "bounds": [
            round(minx, 5),
            round(miny, 5),
            round(maxx, 5),
            round(maxy, 5),
        ],
        "center": [
            round(door.centroid.x, 5),
            round(door.centroid.y, 5),
        ],
        "width_x_raw": round(maxx - minx, 5),
        "width_y_raw": round(maxy - miny, 5),
        "distance_to_room_a": round(distance_a, 5),
        "distance_to_room_b": round(distance_b, 5),
        "touches_room_a": distance_a == 0,
        "touches_room_b": distance_b == 0,
        "candidate_for_both_rooms": (
            distance_a <= MAX_ROOM_DISTANCE
            and distance_b <= MAX_ROOM_DISTANCE
        ),
        "physically_verified": False,
    }


def main():
    plan = load_plan()
    graph = plan["graph"]
    doors = flatten(plan.get("door"))

    results = []

    for room_a_id, room_b_id in ROOM_PAIRS:
        room_a = graph.nodes[room_a_id]["geometry"]
        room_b = graph.nodes[room_b_id]["geometry"]

        candidates = []

        for index, door in enumerate(doors):
            record = describe_door(
                index,
                door,
                room_a,
                room_b,
            )

            if record["candidate_for_both_rooms"]:
                candidates.append(record)

        # Prefer candidates touching both room geometries.
        candidates.sort(
            key=lambda item: (
                not (
                    item["touches_room_a"]
                    and item["touches_room_b"]
                ),
                item["distance_to_room_a"]
                + item["distance_to_room_b"],
            )
        )

        best_candidate = candidates[0] if candidates else None

        print(f"\n{room_a_id} <--> {room_b_id}")

        if best_candidate is None:
            print("No candidate portal found.")
        else:
            print("Best geometric candidate:", best_candidate["portal_id"])
            print("Centre:", best_candidate["center"])
            print(
                "Touches both rooms:",
                best_candidate["touches_room_a"]
                and best_candidate["touches_room_b"],
            )

        results.append({
            "room_a": room_a_id,
            "room_b": room_b_id,
            "best_candidate": best_candidate,
            "all_candidates": candidates,
            "passage_verified": False,
        })

    report = {
        "plan_id": PLAN_ID,
        "status": "PROVISIONAL_PORTAL_EXTRACTION",
        "distance_threshold_raw_units": MAX_ROOM_DISTANCE,
        "threshold_calibrated": False,
        "connections": results,
        "limitations": [
            "Door geometry has not been proven traversable.",
            "Portal centre is not necessarily a cable crossing point.",
            "Doorway clear width is not validated.",
            "Wall intersections have not been resolved.",
            "Kitchen passage remains unresolved.",
        ],
    }

    OUTPUT_JSON.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print("\nSaved:", OUTPUT_JSON.resolve())
    print("Passage verification: NOT COMPLETE")


if __name__ == "__main__":
    main()
