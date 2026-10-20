import json
import pickle
from collections import Counter
from pathlib import Path

DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

PLAN_ID = "14433"

ASSOCIATION_FILE = Path("connector_associations_14433.json")
CANDIDATE_FILE = Path("candidate_passages_14433.json")
OUTPUT_FILE = Path("edge_reconciliation_14433.json")

# Exploratory threshold only; not a calibrated physical measurement.
MAX_DISTANCE = 5.0

# Windows are recorded as evidence but never accepted as ordinary
# interior cable passages by this module.
INTERIOR_PASSAGE_CONNECTORS = {"door"}


def load_json(path):
    if not path.exists():
        raise FileNotFoundError(
            f"Required file not found: {path.resolve()}"
        )

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_pair(a, b):
    """Make an undirected edge comparable regardless of node order."""
    return tuple(sorted((str(a), str(b))))


def get_edge_type(attributes):
    """Support common graph edge-attribute naming."""
    for key in ("type", "edge_type", "relation"):
        if key in attributes:
            return str(attributes[key])

    return "unknown"


def main():
    print("Loading existing reports...")

    association_data = load_json(ASSOCIATION_FILE)
    candidate_data = load_json(CANDIDATE_FILE)

    # Index connector evidence by connector ID.
    connectors = {
        item["connector_id"]: item
        for item in association_data.get("connectors", [])
    }

    # Load the original graph so its edges remain the source of truth
    # for the graph comparison.
    print("Loading original plan graph...")

    with DATASET_PATH.open("rb") as f:
        plans = pickle.load(f)

    plan = next(
        (
            p for p in plans
            if str(p.get("id")) == PLAN_ID
        ),
        None,
    )

    if plan is None:
        raise ValueError(f"Plan {PLAN_ID} was not found.")

    graph = plan["graph"]

    # Index connector candidates by room pair.
    candidate_by_pair = {}

    for item in candidate_data.get("candidate_pairs", []):
        room_a = item.get("room_a")
        room_b = item.get("room_b")

        if room_a is None or room_b is None:
            continue

        pair = normalize_pair(room_a, room_b)

        candidate_by_pair.setdefault(pair, []).append(item)

    # Index connector associations by room pair.
    association_by_pair = {}

    for connector_id, connector in connectors.items():
        for pair_info in connector.get("possible_room_pairs", []):
            room_a = pair_info.get("room_a")
            room_b = pair_info.get("room_b")

            if room_a is None or room_b is None:
                continue

            pair = normalize_pair(room_a, room_b)

            association_by_pair.setdefault(pair, []).append({
                "connector_id": connector_id,
                "connector_type": connector.get("connector_type"),
                "edge_exists_in_connector_report": (
                    pair_info.get("edge_exists", False)
                ),
                "original_edge_type_in_connector_report": (
                    pair_info.get("original_edge_type")
                ),
            })

    results = []

    print("\nEDGE RECONCILIATION")
    print("=" * 78)

    for room_a, room_b, attributes in graph.edges(data=True):
        pair = normalize_pair(room_a, room_b)
        edge_type = get_edge_type(attributes)

        candidates = candidate_by_pair.get(pair, [])
        associated_connectors = association_by_pair.get(pair, [])

        # Keep only door evidence for potential interior passage support.
        door_evidence = [
            c for c in associated_connectors
            if c["connector_type"] in INTERIOR_PASSAGE_CONNECTORS
        ]

        window_evidence = [
            c for c in associated_connectors
            if c["connector_type"] == "window"
        ]

        if edge_type in {"direct", "fallback"}:
            status = "SPECIAL_CASE_REVIEW"

        elif edge_type in {"via_door", "via_opening"}:
            if len(door_evidence) == 1:
                status = "DOOR_ASSOCIATION_CANDIDATE"
            elif len(door_evidence) > 1:
                status = "MULTIPLE_DOOR_CANDIDATES"
            elif window_evidence:
                status = "WINDOW_ONLY_EVIDENCE"
            else:
                status = "NO_DOOR_ASSOCIATION_FOUND"

        elif edge_type == "adjacency":
            status = "ADJACENCY_REQUIRES_PASSAGE_EVIDENCE"

        elif edge_type == "via_window":
            status = "WINDOW_CONNECTION_REVIEW"

        else:
            status = "UNKNOWN_EDGE_TYPE_REVIEW"

        record = {
            "room_a": str(room_a),
            "room_b": str(room_b),
            "original_edge_type": edge_type,
            "reconciliation_status": status,
            "candidate_detector_records": candidates,
            "door_connector_evidence": door_evidence,
            "window_connector_evidence": window_evidence,
            "physical_passage_verified": False,
        }

        results.append(record)

        print(
            f"{room_a} <-> {room_b} | "
            f"{edge_type} | {status}"
        )

        if door_evidence:
            print(
                "    Door candidates:",
                ", ".join(
                    item["connector_id"]
                    for item in door_evidence
                ),
            )

        if window_evidence:
            print(
                "    Window evidence:",
                ", ".join(
                    item["connector_id"]
                    for item in window_evidence
                ),
            )

    summary = Counter(
        item["reconciliation_status"]
        for item in results
    )

    report = {
        "plan_id": PLAN_ID,
        "source_graph_edge_count": graph.number_of_edges(),
        "reconciled_edge_count": len(results),
        "exploratory_distance_threshold_raw_units": MAX_DISTANCE,
        "distance_threshold_physically_calibrated": False,
        "physical_passage_validation_complete": False,
        "interpretation": (
            "Connector associations are geometric candidates only. "
            "They do not establish that an opening is traversable. "
            "Window evidence is kept separate from door evidence."
        ),
        "summary": dict(summary),
        "edges": results,
    }

    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\nSUMMARY")
    print("-" * 40)

    for status, count in sorted(summary.items()):
        print(f"{status}: {count}")

    print("\nSaved:", OUTPUT_FILE.resolve())
    print("Physical passage validation: NOT COMPLETE")


if __name__ == "__main__":
    main()
