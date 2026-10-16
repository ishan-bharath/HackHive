import json
import pickle
from pathlib import Path

DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

PLAN_ID = "14433"
OUTPUT_PATH = Path("connector_associations_14433.json")

# Exploratory tolerance in raw dataset units.
# Not a calibrated physical measurement.
BUFFER_TOLERANCE = 5.0


def get_geometries(geometry):
    if geometry is None or geometry.is_empty:
        return []

    if hasattr(geometry, "geoms"):
        return [
            g for g in geometry.geoms
            if not g.is_empty
        ]

    return [geometry]


def main():
    print("Loading dataset...")

    with DATASET_PATH.open("rb") as f:
        plans = pickle.load(f)

    plan = next(
        p for p in plans
        if str(p.get("id")) == PLAN_ID
    )

    graph = plan["graph"]

    rooms = {}

    for node_id, attributes in graph.nodes(data=True):
        geometry = attributes.get("geometry")

        if geometry is None or geometry.is_empty:
            continue

        rooms[node_id] = {
            "type": attributes.get("type", "unknown"),
            "geometry": geometry,
        }

    connectors = []

    for category in ("door", "window"):
        for i, geometry in enumerate(
            get_geometries(plan.get(category))
        ):
            connectors.append({
                "id": f"{category}_{i}",
                "type": category,
                "geometry": geometry,
            })

    associations = []

    print("\nCONNECTOR ASSOCIATION AUDIT")
    print("=" * 65)

    for connector in connectors:
        geometry = connector["geometry"]
        nearby_rooms = []

        for room_id, room in rooms.items():
            room_geometry = room["geometry"]

            distance = geometry.distance(room_geometry)

            # Candidate association only.
            if distance <= BUFFER_TOLERANCE:
                nearby_rooms.append({
                    "room_id": room_id,
                    "room_type": room["type"],
                    "distance_raw_units": round(distance, 4),
                    "intersects_room": geometry.intersects(
                        room_geometry
                    ),
                    "intersects_buffered_room": geometry.intersects(
                        room_geometry.buffer(BUFFER_TOLERANCE)
                    ),
                })

        # Compare nearby rooms with graph edges involving
        # these rooms. This is diagnostic, not proof.
        possible_pairs = []

        for i, room_a in enumerate(nearby_rooms):
            for room_b in nearby_rooms[i + 1:]:
                a = room_a["room_id"]
                b = room_b["room_id"]

                edge = graph.get_edge_data(a, b)

                possible_pairs.append({
                    "room_a": a,
                    "room_b": b,
                    "original_edge_type": (
                        edge.get("type", "unknown")
                        if edge else None
                    ),
                    "edge_exists": edge is not None,
                })

        if len(nearby_rooms) == 2 and len(possible_pairs) == 1:
            status = "TWO_ROOM_ASSOCIATION_CANDIDATE"
        elif len(nearby_rooms) > 2:
            status = "AMBIGUOUS_MULTIPLE_ROOMS"
        elif len(nearby_rooms) == 1:
            status = "ONLY_ONE_ROOM_CANDIDATE"
        else:
            status = "NO_ROOM_CANDIDATES"

        record = {
            "connector_id": connector["id"],
            "connector_type": connector["type"],
            "nearby_rooms": nearby_rooms,
            "possible_room_pairs": possible_pairs,
            "candidate_status": status,
            "physical_connection_verified": False,
        }

        associations.append(record)

        print(
            f"{connector['id']} | "
            f"nearby rooms={len(nearby_rooms)} | "
            f"{status}"
        )

        for room in nearby_rooms:
            print(
                f"    {room['room_id']} "
                f"(distance={room['distance_raw_units']})"
            )

    report = {
        "plan_id": PLAN_ID,
        "buffer_tolerance_raw_units": BUFFER_TOLERANCE,
        "tolerance_physically_calibrated": False,
        "connector_count": len(connectors),
        "association_count": len(associations),
        "physical_validation_complete": False,
        "connectors": associations,
    }

    OUTPUT_PATH.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print("\nPhysical passage validation: NOT IMPLEMENTED")
    print("Saved:", OUTPUT_PATH.resolve())


if __name__ == "__main__":
    main()