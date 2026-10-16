import json
import pickle
from pathlib import Path

from shapely.geometry import Polygon

DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

PLAN_ID = "14433"

ELIGIBLE_TYPES = {
    "living",
    "bedroom",
    "kitchen",
    "storage",
}

PASSAGE_TYPES = {"via_door", "via_opening"}

OUTPUT_JSON = Path("passage_geometry_audit_14433.json")


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


def flatten(geometry):
    if geometry is None or geometry.is_empty:
        return []

    if hasattr(geometry, "geoms"):
        result = []
        for item in geometry.geoms:
            result.extend(flatten(item))
        return result

    return [geometry]


def main():
    plan = load_plan()
    graph = plan["graph"]

    doors = plan.get("door")
    windows = plan.get("window")
    walls = plan.get("wall")

    door_parts = flatten(doors)
    window_parts = flatten(windows)

    rooms = {
        node: attrs["geometry"]
        for node, attrs in graph.nodes(data=True)
        if attrs.get("type") in ELIGIBLE_TYPES
        and attrs.get("geometry") is not None
        and not attrs["geometry"].is_empty
    }

    results = []

    for u, v, attrs in graph.edges(data=True):
        if u not in rooms or v not in rooms:
            continue

        edge_type = attrs.get("type", "unknown")

        if edge_type not in PASSAGE_TYPES:
            continue

        room_a = rooms[u]
        room_b = rooms[v]

        shared = room_a.boundary.intersection(room_b.boundary)

        associated_doors = []
        associated_windows = []

        for index, door in enumerate(door_parts):
            distance_a = room_a.distance(door)
            distance_b = room_b.distance(door)

            if max(distance_a, distance_b) <= 5.0:
                associated_doors.append({
                    "id": f"door_{index}",
                    "distance_to_a": round(distance_a, 4),
                    "distance_to_b": round(distance_b, 4),
                })

        for index, window in enumerate(window_parts):
            distance_a = room_a.distance(window)
            distance_b = room_b.distance(window)

            if max(distance_a, distance_b) <= 5.0:
                associated_windows.append({
                    "id": f"window_{index}",
                    "distance_to_a": round(distance_a, 4),
                    "distance_to_b": round(distance_b, 4),
                })

        record = {
            "room_a": u,
            "room_b": v,
            "graph_edge_type": edge_type,
            "shared_boundary_length_raw": round(shared.length, 4),
            "candidate_doors": associated_doors,
            "candidate_windows": associated_windows,
            "physical_passage_verified": False,
        }

        results.append(record)

        print(f"\n{u} <--> {v}")
        print(f"  Graph label: {edge_type}")
        print(f"  Shared boundary: {shared.length:.3f} raw units")
        print(f"  Nearby door candidates: {len(associated_doors)}")
        print(f"  Nearby window candidates: {len(associated_windows)}")

        for door in associated_doors:
            print(
                f"    {door['id']}: "
                f"A={door['distance_to_a']}, "
                f"B={door['distance_to_b']}"
            )

        for window in associated_windows:
            print(
                f"    {window['id']}: "
                f"A={window['distance_to_a']}, "
                f"B={window['distance_to_b']}"
            )

    report = {
        "plan_id": PLAN_ID,
        "status": "GEOMETRIC_ASSOCIATION_DIAGNOSTIC",
        "association_threshold_raw_units": 5.0,
        "threshold_is_calibrated": False,
        "physical_passages_verified": False,
        "connections": results,
        "limitations": [
            "Proximity does not prove a doorway is usable.",
            "The threshold is exploratory and uncalibrated.",
            "Doorway orientation and clear width are not checked.",
            "Cable traversability is not established.",
        ],
    }

    OUTPUT_JSON.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print("\nSaved:", OUTPUT_JSON.resolve())
    print("\nReminder: nearby geometry is evidence, not proof.")


if __name__ == "__main__":
    main()