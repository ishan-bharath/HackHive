import pickle
from pathlib import Path

import networkx as nx

DATASET = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets"
    r"\resplan\resplan\versions\12\ResPlan.pkl"
)

PLAN_ID = 14433

ELIGIBLE_TYPES = {
    "living",
    "bedroom",
    "kitchen",
    "storage",
}

ALLOWED_EDGE_TYPES = {
    "via_door",
    "via_opening",
    "adjacency",
}


def load_plan():
    with open(DATASET, "rb") as f:
        plans = pickle.load(f)

    for plan in plans:
        if plan.get("id") == PLAN_ID:
            return plan

    raise ValueError(f"Plan {PLAN_ID} not found")


def main():
    plan = load_plan()
    graph = plan["graph"]

    eligible = {
        node
        for node, attrs in graph.nodes(data=True)
        if attrs.get("type") in ELIGIBLE_TYPES
    }

    print(f"Plan ID: {PLAN_ID}")
    print(f"Eligible rooms: {len(eligible)}")
    print()

    print("=== DEVICE ROOMS ===")

    for node in sorted(eligible):
        print(f"{node}: {graph.nodes[node].get('type')}")

    print()
    print("=== PASSAGE CANDIDATES ===")

    candidates = nx.Graph()
    candidates.add_nodes_from(eligible)

    for u, v, attrs in graph.edges(data=True):
        if u not in eligible or v not in eligible:
            continue

        edge_type = attrs.get("type", "unknown")

        if edge_type not in ALLOWED_EDGE_TYPES:
            continue

        candidates.add_edge(
            u,
            v,
            edge_type=edge_type,
            verified=False,
        )

        print(f"{u} <--> {v} | type={edge_type}")

    print()
    print("=== CONNECTIVITY ===")

    components = list(nx.connected_components(candidates))

    print(f"Connected components: {len(components)}")

    for index, component in enumerate(components, start=1):
        print(f"Component {index}: {sorted(component)}")

    print()
    print("=== LOOP FEASIBILITY ===")

    if not nx.is_connected(candidates):
        print(
            "NOT CONNECTED: a loop covering all device rooms "
            "cannot be established from these candidate edges alone."
        )
    else:
        print(
            "Candidate graph is connected. This is necessary, "
            "but not sufficient, for a physically valid loop."
        )

    print()
    print("IMPORTANT: Graph edges are candidates, not verified passages.")
    print("Physical doorway and cable geometry validation is still required.")


if __name__ == "__main__":
    main()
