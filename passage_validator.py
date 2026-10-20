import json
from pathlib import Path

INPUT_PATH = Path("candidate_passages_14433.json")
OUTPUT_PATH = Path("validated_passages_14433.json")


def classify_candidate(candidate):
    edge_type = candidate["original_edge_type"]
    segments = candidate["wall_free_segments"]
    connectors = candidate["connector_candidates"]

    # A front-door connection requires separate treatment.
    if edge_type == "direct":
        return (
            "REVIEW_REQUIRED",
            "Entrance connection requires boundary-specific validation."
        )

    # A wall-free shared-boundary segment is evidence for a
    # possible opening, but does not prove walkability.
    if segments:
        return (
            "SUPPORTED_CANDIDATE",
            "Wall-free shared-boundary segment found; "
            "physical passage remains unverified."
        )

    # A connector near both room geometries is a candidate,
    # not proof that it connects those rooms.
    if connectors:
        return (
            "SUPPORTED_CANDIDATE",
            "Nearby door/window geometry found; "
            "connector association requires validation."
        )

    # Graph evidence alone is insufficient for physical validation.
    if edge_type in {"via_door", "via_opening"}:
        return (
            "REVIEW_REQUIRED",
            "Graph indicates a passage, but geometric evidence "
            "is insufficient."
        )

    # Adjacency is not proof of a walkable connection.
    if edge_type == "adjacency":
        return (
            "REVIEW_REQUIRED",
            "Adjacency edge has no supporting connector or "
            "wall-free segment."
        )

    return (
        "REVIEW_REQUIRED",
        "Insufficient evidence to classify this connection."
    )


def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"Input report not found: {INPUT_PATH.resolve()}"
        )

    report = json.loads(
        INPUT_PATH.read_text(encoding="utf-8")
    )

    results = []

    for candidate in report["candidates"]:
        status, reason = classify_candidate(candidate)

        results.append({
            "room_a": candidate["room_a"],
            "room_b": candidate["room_b"],
            "original_edge_type": candidate["original_edge_type"],
            "status": status,
            "reason": reason,
            "wall_free_segment_count": len(
                candidate["wall_free_segments"]
            ),
            "connector_candidate_count": len(
                candidate["connector_candidates"]
            ),
        })

    counts = {
        status: sum(
            item["status"] == status
            for item in results
        )
        for status in (
            "SUPPORTED_CANDIDATE",
            "REVIEW_REQUIRED",
            "REJECTED_CANDIDATE",
        )
    }

    output = {
        "plan_id": report["plan_id"],
        "method": "evidence_based_candidate_classification",
        "physical_validation_complete": False,
        "cable_routing_complete": False,
        "summary": counts,
        "connections": results,
        "warning": (
            "Statuses indicate candidate evidence only. "
            "No connection has been physically verified."
        ),
    }

    OUTPUT_PATH.write_text(
        json.dumps(output, indent=2),
        encoding="utf-8",
    )

    print("\nPASSAGE VALIDATION SUMMARY")
    print("=" * 45)

    for status, count in counts.items():
        print(f"{status}: {count}")

    print("\nCONNECTIONS")
    print("-" * 70)

    for item in results:
        print(
            f"{item['room_a']} <-> {item['room_b']} | "
            f"{item['status']} | {item['reason']}"
        )

    print("\nPhysical passage validation: NOT COMPLETE")
    print("Cable routing: NOT IMPLEMENTED")
    print("Saved:", OUTPUT_PATH.resolve())


if __name__ == "__main__":
    main()
