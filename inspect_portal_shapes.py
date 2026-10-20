import pickle
from pathlib import Path

DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

PLAN_ID = "14433"


def flatten(geometry):
    if geometry is None or geometry.is_empty:
        return []

    if hasattr(geometry, "geoms"):
        result = []
        for item in geometry.geoms:
            result.extend(flatten(item))
        return result

    return [geometry]


with DATASET_PATH.open("rb") as f:
    plans = pickle.load(f)

plan = next(
    p for p in plans
    if str(p.get("id")) == PLAN_ID
)

doors = flatten(plan.get("door"))
walls = plan.get("wall")
graph = plan["graph"]

for index, door in enumerate(doors):
    if index not in {0, 1, 2, 3, 4}:
        continue

    print(f"\nDOOR {index}")
    print("Geometry type:", door.geom_type)
    print("Bounds:", tuple(round(v, 4) for v in door.bounds))
    print("Area:", round(door.area, 4))
    print("Length:", round(door.length, 4))
    print("Centroid:", (
        round(door.centroid.x, 4),
        round(door.centroid.y, 4),
    ))

    if walls is not None:
        print(
            "Distance to wall geometry:",
            round(door.distance(walls), 4),
        )

    for room_id in [
        "living_0",
        "bedroom_0",
        "bedroom_1",
        "bedroom_2",
    ]:
        room = graph.nodes[room_id]["geometry"]

        print(
            f"Distance to {room_id}:",
            round(door.distance(room), 4),
        )

    print("WKT:", door.wkt[:500])
