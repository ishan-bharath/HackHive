import pickle
from pathlib import Path

BASE = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan\resplan\versions\12"
)

ELIGIBLE_TYPES = {"living", "bedroom", "kitchen", "storage"}


def load_dataset():
    with open(BASE / "ResPlan.pkl", "rb") as f:
        return pickle.load(f)


def extract_rooms(plan):
    """Extract eligible rooms and their geometry from a ResPlan plan."""
    graph = plan["graph"]
    rooms = []

    for room_id, attrs in graph.nodes(data=True):
        room_type = attrs.get("type")

        if room_type not in ELIGIBLE_TYPES:
            continue

        geometry = attrs.get("geometry")

        if geometry is None or geometry.is_empty:
            continue

        rooms.append({
            "room_id": room_id,
            "room_type": room_type,
            "geometry": geometry,
            "geometry_area": geometry.area,
            "centroid": (
                geometry.representative_point().x,
                geometry.representative_point().y,
            ),
        })

    return rooms


if __name__ == "__main__":
    dataset = load_dataset()
    plan = dataset[0]
    rooms = extract_rooms(plan)

    print(f"Plan ID: {plan['id']}")
    print(f"Reported total area: {plan['area']:.2f} m²")
    print(f"Reported net area: {plan['net_area']:.2f} m²")
    print(f"Eligible rooms found: {len(rooms)}")

    for room in rooms:
        print(
            f"{room['room_id']:12} "
            f"type={room['room_type']:8} "
            f"geometry_area={room['geometry_area']:.2f} "
            f"device_count=1"
        )
