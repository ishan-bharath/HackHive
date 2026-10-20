import pickle
from pathlib import Path

BASE = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan\resplan\versions\12"
)

print("Loading ResPlan dataset...")

with open(BASE / "ResPlan.pkl", "rb") as f:
    data = pickle.load(f)

print("\nDataset type:", type(data))
print("Number of plans:", len(data))

plan = data[0]

print("\nFirst plan ID:", plan.get("id"))
print("\nAvailable categories:")

for key, value in plan.items():
    if key == "id":
        continue

    if hasattr(value, "geom_type"):
        print(
            f"{key}: type={value.geom_type}, "
            f"area={value.area:.2f}, "
            f"empty={value.is_empty}"
        )

    elif hasattr(value, "nodes") and hasattr(value, "edges"):
        print("Graph:", type(value))
        print("Nodes:", value.number_of_nodes())
        print("Edges:", value.number_of_edges())

        print("\nRoom nodes:")
        for node, attrs in value.nodes(data=True):
            print(node, attrs.get("type"), attrs.get("area"))

        print("\nConnections:")
        for u, v, attrs in value.edges(data=True):
            print(u, "<->", v, attrs.get("type"))

    else:
        print(f"{key}: {type(value)}")
print("\n" + "=" * 40)
print("GEOMETRY AND UNIT INSPECTION")
print("=" * 40)

print("\nPlan area metadata:", plan.get("area"))
print("Net area metadata:", plan.get("net_area"))

for key in ["inner", "wall", "door", "window", "living",
            "kitchen", "bedroom", "front_door"]:

    geom = plan.get(key)

    if geom is not None and not geom.is_empty:
        print(f"\n{key.upper()}")
        print("  Bounds:", geom.bounds)
        print("  Area:", round(geom.area, 2))
        print("  Valid:", geom.is_valid)

print("\n" + "=" * 40)
print("ROOM GRAPH EDGE TYPES")
print("=" * 40)

from collections import Counter

edge_types = Counter(
    attrs.get("type", "unknown")
    for _, _, attrs in plan["graph"].edges(data=True)
)

print(edge_types)
