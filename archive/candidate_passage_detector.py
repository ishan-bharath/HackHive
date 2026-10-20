import json
import pickle
from pathlib import Path



DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

PLAN_ID = "14433"

OUTPUT_PATH = Path("candidate_passages_14433.json")

# Exploratory tolerance in raw dataset units.
# This is not a verified physical measurement.
WALL_BUFFER = 0.5

# Room types that can receive devices.
ELIGIBLE_TYPES = {
    "living",
    "bedroom",
    "kitchen",
    "storage",
}


def get_geometries(geometry):
    """Return individual geometries from Polygon/MultiPolygon inputs."""
    if geometry is None or geometry.is_empty:
        return []

    if hasattr(geometry, "geoms"):
        return [
            g for g in geometry.geoms
            if not g.is_empty
        ]

    return [geometry]


def get_line_components(geometry):
    """Extract non-empty line components from a geometry."""
    if geometry is None or geometry.is_empty:
        return []

    if geometry.geom_type == "LineString":
        return [geometry] if geometry.length > 0 else []

    if hasattr(geometry, "geoms"):
        result = []

        for component in geometry.geoms:
            result.extend(get_line_components(component))

        return result

    return []


def connector_evidence(segment, connectors, tolerance):
    """Find nearby door/window geometries for a candidate segment."""
    candidates = []

    for connector_id, connector_type, geometry in connectors:
        distance = segment.distance(geometry)

        if distance <= tolerance:
            candidates.append({
                "connector_id": connector_id,
                "connector_type": connector_type,
                "distance_raw_units": round(distance, 4),
                "intersects_segment": segment.intersects(
                    geometry
                ),
            })

    return candidates


def main():
    print("Loading ResPlan dataset...")

    with DATASET_PATH.open("rb") as f:
        plans = pickle.load(f)

    plan = next(
        p for p in plans
        if str(p.get("id")) == PLAN_ID
    )

    graph = plan["graph"]

    walls = plan.get("wall")

    if walls is None or walls.is_empty:
        raise ValueError(
            "Plan has no usable wall geometry."
        )

    wall_band = walls.buffer(WALL_BUFFER)

    # Collect doors and windows without treating either as
    # automatically valid walkable passages.
    connectors = []

    for category in ("door", "window"):
        for i, geometry in enumerate(
            get_geometries(plan.get(category))
        ):
            connectors.append((
                f"{category}_{i}",
                category,
                geometry,
            ))

    rooms = {}

    for node_id, attributes in graph.nodes(data=True):
        geometry = attributes.get("geometry")

        if geometry is None or geometry.is_empty:
            continue

        rooms[node_id] = {
            "id": node_id,
            "type": attributes.get("type", "unknown"),
            "eligible_for_device": (
                attributes.get("type") in ELIGIBLE_TYPES
            ),
            "geometry": geometry,
        }

    passage_candidates = []

    room_ids = list(rooms)

    for i, room_a_id in enumerate(room_ids):
        for room_b_id in room_ids[i + 1:]:
            room_a = rooms[room_a_id]
            room_b = rooms[room_b_id]

            geom_a = room_a["geometry"]
            geom_b = room_b["geometry"]

            original_edge = graph.get_edge_data(
                room_a_id,
                room_b_id,
            )

            edge_type = (
                original_edge.get("type", "unknown")
                if original_edge
                else None
            )

            # Look for shared room boundary.
            shared_boundary = (
                geom_a.boundary.intersection(
                    geom_b.boundary
                )
            )

            # Remove the buffered wall region to identify
            # possible wall-free boundary segments.
            wall_free = shared_boundary.difference(
                wall_band
            )

            segments = get_line_components(wall_free)

            # Look for connectors that could be associated
            # with both spaces.
            connector_candidates = []

            for connector_id, connector_type, connector in connectors:
                near_a = (
                    connector.distance(geom_a)
                    <= WALL_BUFFER * 2
                )

                near_b = (
                    connector.distance(geom_b)
                    <= WALL_BUFFER * 2
                )

                if near_a and near_b:
                    connector_candidates.append({
                        "connector_id": connector_id,
                        "connector_type": connector_type,
                        "distance_to_room_a": round(
                            connector.distance(geom_a), 4
                        ),
                        "distance_to_room_b": round(
                            connector.distance(geom_b), 4
                        ),
                    })

            # Include pairs supported by at least one
            # candidate signal. These remain unverified.
            if not (
                original_edge
                or segments
                or connector_candidates
            ):
                continue

            segment_records = []

            for segment in segments:
                segment_records.append({
                    "length_raw_units": round(
                        segment.length, 4
                    ),
                    "bounds": [
                        round(v, 4)
                        for v in segment.bounds
                    ],
                    "connector_evidence": connector_evidence(
                        segment,
                        connectors,
                        WALL_BUFFER * 2,
                    ),
                })

            passage_candidates.append({
                "room_a": room_a_id,
                "room_b": room_b_id,
                "room_a_type": room_a["type"],
                "room_b_type": room_b["type"],
                "room_a_device_eligible": (
                    room_a["eligible_for_device"]
                ),
                "room_b_device_eligible": (
                    room_b["eligible_for_device"]
                ),
                "original_graph_edge": bool(original_edge),
                "original_edge_type": edge_type,
                "shared_boundary_length": round(
                    shared_boundary.length, 4
                ),
                "wall_free_segments": segment_records,
                "connector_candidates": (
                    connector_candidates
                ),
                "status": "UNVERIFIED",
            })

    report = {
        "plan_id": PLAN_ID,
        "method": "candidate_geometric_diagnostics",
        "wall_buffer_raw_units": WALL_BUFFER,
        "wall_buffer_is_physically_calibrated": False,
        "room_count": len(rooms),
        "eligible_room_count": sum(
            r["eligible_for_device"]
            for r in rooms.values()
        ),
        "candidate_pair_count": len(passage_candidates),
        "verification_status": "NOT_IMPLEMENTED",
        "warnings": [
            "Candidate geometry does not prove walkability.",
            "Door/window proximity does not prove a valid passage.",
            "Wall-free boundary segments may be geometric artifacts.",
            "No cable routes have been validated.",
        ],
        "candidates": passage_candidates,
    }

    OUTPUT_PATH.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print("\nPASSAGE CANDIDATE DETECTION")
    print("=" * 60)
    print("Plan ID:", PLAN_ID)
    print("Rooms examined:", len(rooms))
    print("Eligible device rooms:", report["eligible_room_count"])
    print("Candidate room pairs:", len(passage_candidates))

    print("\nCandidate connections:")

    for candidate in passage_candidates:
        segment_count = len(
            candidate["wall_free_segments"]
        )

        print(
            f"  {candidate['room_a']} <-> "
            f"{candidate['room_b']} | "
            f"graph={candidate['original_edge_type']} | "
            f"wall-free segments={segment_count} | "
            f"connectors={len(candidate['connector_candidates'])}"
        )

    print("\nPhysical passage validation: NOT IMPLEMENTED")
    print("Cable routing: NOT IMPLEMENTED")
    print("Report saved:", OUTPUT_PATH.resolve())


if __name__ == "__main__":
    main()
