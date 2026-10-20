import pickle
import matplotlib.pyplot as plt
from pathlib import Path

DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

PLAN_ID = "14433"


def draw_geometry(ax, geometry, **kwargs):
    """Draw Polygon or MultiPolygon geometry."""
    if geometry is None or geometry.is_empty:
        return

    polygons = (
        list(geometry.geoms)
        if hasattr(geometry, "geoms")
        and geometry.geom_type == "MultiPolygon"
        else [geometry]
    )

    for polygon in polygons:
        if polygon.geom_type != "Polygon":
            continue

        x, y = polygon.exterior.xy
        ax.plot(x, y, **kwargs)

        for interior in polygon.interiors:
            x, y = interior.xy
            ax.plot(x, y, **kwargs)


def main():
    print("Loading dataset...")

    with DATASET_PATH.open("rb") as f:
        plans = pickle.load(f)

    plan = next(
        p for p in plans
        if str(p.get("id")) == PLAN_ID
    )

    fig, ax = plt.subplots(figsize=(14, 12))

    # Building interior
    draw_geometry(
        ax,
        plan["inner"],
        color="black",
        linewidth=2
    )

    # Walls
    draw_geometry(
        ax,
        plan["wall"],
        color="red",
        linewidth=1
    )

    # Rooms and other graph nodes
    graph = plan["graph"]

    for node_id, attrs in graph.nodes(data=True):
        geometry = attrs.get("geometry")

        if geometry is None:
            continue

        draw_geometry(
            ax,
            geometry,
            color="blue",
            linewidth=0.8
        )

        centroid = geometry.centroid

        ax.text(
            centroid.x,
            centroid.y,
            node_id,
            fontsize=7,
            ha="center",
            va="center"
        )

    # Door components
    doors = plan["door"]

    components = (
        list(doors.geoms)
        if hasattr(doors, "geoms")
        else [doors]
    )

    for i, door in enumerate(components):
        draw_geometry(
            ax,
            door,
            color="magenta",
            linewidth=2
        )

        centroid = door.centroid

        ax.text(
            centroid.x,
            centroid.y,
            f"D{i}",
            color="magenta",
            fontsize=10,
            fontweight="bold"
        )

    # Front door
    draw_geometry(
        ax,
        plan["front_door"],
        color="green",
        linewidth=3
    )

    ax.set_title(
        f"Plan {PLAN_ID}: Rooms, Walls, Doorways and Entrance"
    )

    ax.set_aspect("equal")
    ax.set_xlabel("X coordinate (raw dataset units)")
    ax.set_ylabel("Y coordinate (raw dataset units)")
    ax.grid(True, alpha=0.2)

    plt.tight_layout()

    output = Path("plan_14433_full_geometry.png")
    plt.savefig(output, dpi=200)

    print(f"Saved visualization: {output.resolve()}")

    plt.show()


if __name__ == "__main__":
    main()
