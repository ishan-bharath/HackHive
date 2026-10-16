import json
import pickle
from pathlib import Path

DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

OUTPUT_PATH = Path("passage_audit_14433.json")
PLAN_ID = "14433"

# Diagnostic tolerance in raw dataset coordinates.
# This is not a validated physical doorway width.
BUFFER_TOLERANCE = 5.0


def main():
    print("Loading dataset...")

    with DATASET_PATH.open("rb") as f:
        plans = pickle.load(f)

    plan = next(
        p for p in plans
        if str(p.get("id")) == PLAN_ID
    )

    graph = plan["graph"]

    doors = list(plan["door"].geoms)
    windows_geom = plan.get("window")

    windows = (
        list(windows_geom.geoms)
        if windows_geom is not None
        and hasattr(windows_geom, "geoms")
        else [windows_geom]
        if windows_geom is not None
        else []
    )

    connectors = [
        (f"door_{i}", geom, "door")
        for i, geom in enumerate(doors)
    ]

    connectors.extend(
        (f"window_{i}", geom, "window")
        for i, geom in enumerate(windows)
    )

    records = []

    print("\nAUDITING GRAPH EDGES")
    print("=" * 100)

    for u, v, attributes in graph.edges(data=True):
        room_a = graph.nodes[u].get("geometry")
        room_b = graph.nodes[v].get("geometry")

        if room_a is None or room_b is None:
            continue

        # Look for connectors near both rooms.
        candidates = []

        for connector_id, connector, connector_type in connectors:
            distance_a = connector.distance(room_a)
            distance_b = connector.distance(room_b)

            buffered_contact = (
                connector.intersects(
                    room_a.buffer(BUFFER_TOLERANCE)
                )
                and connector.intersects(
                    room_b.buffer(BUFFER_TOLERANCE)
                )
            )

            if buffered_contact:
                candidates.append({
                    "connector_id": connector_id,
                    "connector_type": connector_type,
                    "distance_to_room_a": round(
                        distance_a, 3
                    ),
                    "distance_to_room_b": round(
                        distance_b, 3
                    ),
                    "touches_both_buffered_rooms": True,
                })

        record = {
            "room_a": u,
            "room_b": v,
            "edge_type": attributes.get("type", "unknown"),
            "shared_boundary_length": round(
                room_a.boundary.intersection(
                    room_b.boundary
                ).length,
                3,
            ),
            "connector_candidates": candidates,
            "status": "UNVERIFIED",
        }

        records.append(record)

        print(
            f"{u} <-> {v} | "
            f"type={record['edge_type']} | "
            f"connector candidates={len(candidates)}"
        )

        for candidate in candidates:
            print(
                f"    {candidate['connector_id']} "
                f"({candidate['connector_type']}): "
                f"distance A="
                f"{candidate['distance_to_room_a']}, "
                f"distance B="
                f"{candidate['distance_to_room_b']}"
            )

    report = {
        "plan_id": PLAN_ID,
        "edge_count": len(records),
        "buffer_tolerance_raw_units": BUFFER_TOLERANCE,
        "verification_status": "NOT_IMPLEMENTED",
        "edges": records,
    }

    OUTPUT_PATH.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print("\nAudit completed.")
    print(f"Edges audited: {len(records)}")
    print(f"Report saved: {OUTPUT_PATH.resolve()}")
    print("Physical passage validation: NOT IMPLEMENTED")


if __name__ == "__main__":
    main()