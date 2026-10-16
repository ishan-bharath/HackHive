import pickle
from pathlib import Path

import matplotlib.pyplot as plt
from shapely.geometry import Polygon

DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

PLAN_ID = "14433"


def parts(geometry):
    if geometry is None or geometry.is_empty:
        return []

    if hasattr(geometry, "geoms"):
        result = []
        for item in geometry.geoms:
            result.extend(parts(item))
        return result

    return [geometry]


def main():
    with DATASET_PATH.open("rb") as f:
        plans = pickle.load(f)

    plan = next(
        p for p in plans
        if str(p.get("id")) == PLAN_ID
    )

    graph = plan["graph"]
    doors = parts(plan.get("door"))
    walls = plan.get("wall")

    selected_rooms = [
        "living_0",
        "bedroom_0",
        "bedroom_1",
        "bedroom_2",
    ]

    fig, axes = plt.subplots(2, 2, figsize=(14, 11))
    axes = axes.flatten()

    for ax, bedroom in zip(
        axes,
        ["bedroom_0", "bedroom_1", "bedroom_2", "bedroom_0"],
    ):
        living = graph.nodes["living_0"]["geometry"]
        bedroom_geometry = graph.nodes[bedroom]["geometry"]

        # Show both room boundaries.
        for geometry in [living, bedroom_geometry]:
            for polygon in parts(geometry):
                if isinstance(polygon, Polygon):
                    x, y = polygon.exterior.xy
                    ax.plot(x, y, linewidth=2)

        # Display doors near either room.
        relevant = []

        for index, door in enumerate(doors):
            da = living.distance(door)
            db = bedroom_geometry.distance(door)

            if max(da, db) <= 5.0:
                relevant.append((index, door, da, db))

        for index, door, da, db in relevant:
            for polygon in parts(door):
                if isinstance(polygon, Polygon):
                    x, y = polygon.exterior.xy
                    ax.fill(x, y, alpha=0.65)

            point = door.representative_point()

            ax.annotate(
                f"D{index}\n{da:.1f}, {db:.1f}",
                (point.x, point.y),
                fontsize=9,
            )

        if walls is not None:
            for wall in parts(walls):
                if isinstance(wall, Polygon):
                    x, y = wall.exterior.xy
                    ax.plot(x, y, linewidth=1, alpha=0.5)

        ax.set_title(
            f"Living room ↔ {bedroom}\n"
            "Door candidates; distances are raw units"
        )
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, alpha=0.2)

    plt.tight_layout()
    output = Path("door_candidate_detail_14433.png")
    plt.savefig(output, dpi=200, bbox_inches="tight")
    plt.close(fig)

    print("Saved:", output.resolve())


if __name__ == "__main__":
    main()