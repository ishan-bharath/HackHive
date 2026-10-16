import json
import pickle
from pathlib import Path

import networkx as nx

DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

PLAN_ID = "14433"
PANEL_ROOM = "living_0"

ELIGIBLE_TYPES = {
    "living",
    "bedroom",
    "kitchen",
    "storage",
}

PASSAGE_TYPES = {
    "via_door",
    "via_opening",
}

OUTPUT_JSON = Path("passage_routes_14433.json")


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


def main():
    print("Loading plan...")
    plan = load_plan()
    original = plan["graph"]

    rooms = {
        node: attrs
        for node, attrs in original.nodes(data=True)
        if attrs.get("type") in ELIGIBLE_TYPES
        and attrs.get("geometry") is not None
        and not attrs["geometry"].is_empty
    }

    if PANEL_ROOM not in rooms:
        raise ValueError(f"Panel room {PANEL_ROOM} not found")

    # Only retain room-to-room edges with candidate passage labels.
    passage_graph = nx.Graph()
    passage_graph.add_nodes_from(rooms)

    for u, v, attrs in original.edges(data=True):
        if u not in rooms or v not in rooms:
            continue

        edge_type = attrs.get("type", "unknown")

        if edge_type in PASSAGE_TYPES:
            passage_graph.add_edge(
                u,
                v,
                edge_type=edge_type,
                physically_verified=False,
            )

    print("Eligible rooms:", len(rooms))
    print("Candidate passage edges:", passage_graph.number_of_edges())
    print("Connected:", nx.is_connected(passage_graph))

    results = []

    for room_id in sorted(rooms):
        if room_id == PANEL_ROOM:
            continue

        record = {
            "room_id": room_id,
            "panel_room": PANEL_ROOM,
            "route_found_in_candidate_graph": False,
            "room_sequence": [],
            "passage_edges": [],
            "physical_passage_verified": False,
        }

        try:
            path = nx.shortest_path(
                passage_graph,
                source=PANEL_ROOM,
                target=room_id,
            )

            record["route_found_in_candidate_graph"] = True
            record["room_sequence"] = path

            for u, v in zip(path, path[1:]):
                record["passage_edges"].append({
                    "from": u,
                    "to": v,
                    "edge_type": passage_graph[u][v]["edge_type"],
                    "verified": False,
                })

            print(f"{room_id}: {' -> '.join(path)}")

        except nx.NetworkXNoPath:
            print(f"{room_id}: NO CANDIDATE PASSAGE PATH")

        results.append(record)

    report = {
        "plan_id": PLAN_ID,
        "status": "PASSAGE_GRAPH_DIAGNOSTIC",
        "panel_room": PANEL_ROOM,
        "eligible_room_count": len(rooms),
        "candidate_passage_edge_count": passage_graph.number_of_edges(),
        "physical_passages_verified": False,
        "routes": results,
        "limitations": [
            "Passage labels are candidate evidence, not physical proof.",
            "Cable geometry has not been routed along these room sequences.",
            "Doorway clearance has not been checked.",
            "A closed device-visitation loop has not been constructed.",
        ],
    }

    OUTPUT_JSON.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print("\nSaved:", OUTPUT_JSON.resolve())
    print("Physical passage verification: NOT COMPLETE")


if __name__ == "__main__":
    main()