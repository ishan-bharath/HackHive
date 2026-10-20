import pickle
from pathlib import Path

DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

PLAN_ID = "14433"


def main():
    print("Loading dataset...")

    with DATASET_PATH.open("rb") as f:
        plans = pickle.load(f)

    plan = next(
        p for p in plans
        if str(p.get("id")) == PLAN_ID
    )

    graph = plan["graph"]

    living = graph.nodes["living_0"]["geometry"]
    kitchen = graph.nodes["kitchen_0"]["geometry"]

    # Shared boundary between living room and kitchen.
    shared_boundary = living.boundary.intersection(
        kitchen.boundary
    )

    doors = plan["door"]
    door_components = list(doors.geoms)

    walls = plan["wall"]

    print("\nKITCHEN-LIVING SHARED BOUNDARY")
    print("-" * 45)
    print("Geometry type:", shared_boundary.geom_type)
    print("Length:", round(shared_boundary.length, 3))
    print("Bounds:", tuple(round(v, 3) for v in shared_boundary.bounds))

    print("\nDOOR COMPONENT DIAGNOSTICS")
    print("-" * 70)

    for i, door in enumerate(door_components):
        distance = shared_boundary.distance(door)
        wall_overlap = walls.intersection(door).area

        print(
            f"D{i}: "
            f"distance_to_shared_boundary={distance:.3f}, "
            f"door_area={door.area:.3f}, "
            f"wall_overlap_area={wall_overlap:.3f}"
        )

    print("\nGRAPH EDGE")
    print("-" * 45)
    print(
        graph.get_edge_data(
            "living_0",
            "kitchen_0"
        )
    )

    print("\nINTERPRETATION")
    print("-" * 45)
    print(
        "These measurements are diagnostic only. "
        "They do not establish that a doorway is physically valid."
    )


if __name__ == "__main__":
    main()
