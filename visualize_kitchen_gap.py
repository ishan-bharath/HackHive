import pickle
from pathlib import Path

import matplotlib.pyplot as plt

DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

PLAN_ID = "14433"


def main():
    with DATASET_PATH.open("rb") as f:
        plans = pickle.load(f)

    plan = next(
        p for p in plans
        if str(p.get("id")) == PLAN_ID
    )

    graph = plan["graph"]

    living = graph.nodes["living_0"]["geometry"]
    kitchen = graph.nodes["kitchen_0"]["geometry"]
    walls = plan["wall"]

    shared = living.boundary.intersection(
        kitchen.boundary
    )

    wall_band = walls.buffer(0.5)
    wall_free = shared.difference(wall_band)

    fig, ax = plt.subplots(figsize=(10, 10))

    # Draw the two rooms.
    for name, geom in [
        ("Living room", living),
        ("Kitchen", kitchen),
    ]:
        x, y = geom.exterior.xy
        ax.plot(x, y, linewidth=2, label=name)

    # Draw the walls.
    polygons = (
        list(walls.geoms)
        if hasattr(walls, "geoms")
        else [walls]
    )

    for polygon in polygons:
        if polygon.geom_type == "Polygon":
            x, y = polygon.exterior.xy
            ax.plot(x, y, linewidth=1)

    # Draw the complete shared boundary.
    parts = (
        list(shared.geoms)
        if hasattr(shared, "geoms")
        else [shared]
    )

    for i, part in enumerate(parts):
        if part.geom_type == "LineString":
            x, y = part.xy
            ax.plot(
                x, y,
                linestyle="--",
                linewidth=2,
                label="Shared boundary" if i == 0 else None,
            )

    # Highlight wall-free segments.
    parts = (
        list(wall_free.geoms)
        if hasattr(wall_free, "geoms")
        else [wall_free]
    )

    for i, part in enumerate(parts):
        if part.geom_type == "LineString":
            x, y = part.xy
            ax.plot(
                x, y,
                linewidth=5,
                label="Potential opening" if i == 0 else None,
            )

    ax.set_title(
        "Kitchen–Living Boundary: Potential Opening"
    )
    ax.set_xlabel("X (raw dataset units)")
    ax.set_ylabel("Y (raw dataset units)")
    ax.set_aspect("equal")
    ax.legend()
    ax.grid(True, alpha=0.2)

    output = Path("kitchen_gap_diagnostic.png")
    plt.savefig(output, dpi=180, bbox_inches="tight")

    print(f"Saved: {output.resolve()}")
    plt.show()


if __name__ == "__main__":
    main()
