import pickle
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection

DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

PLAN_ID = "14433"
OUTPUT_FILE = Path("visual_passage_review_14433.png")

# These are exploratory visualization settings, not physical measurements.
ROOM_COLOR = "#DCEAF7"
WALL_COLOR = "#333333"
DOOR_COLOR = "#00A878"
WINDOW_COLOR = "#E5A000"


def draw_geometry(ax, geometry, **kwargs):
    """Draw polygon boundaries and polygon interiors."""
    if geometry is None or geometry.is_empty:
        return

    if isinstance(geometry, Polygon):
        x, y = geometry.exterior.xy
        ax.fill(x, y, **kwargs)

        for ring in geometry.interiors:
            x, y = ring.xy
            ax.plot(x, y, color="white", linewidth=0.7)

    elif isinstance(geometry, (MultiPolygon, GeometryCollection)):
        for part in geometry.geoms:
            draw_geometry(ax, part, **kwargs)


def plot_outline(ax, geometry, color, linewidth=1.5, linestyle="-"):
    """Draw geometry outlines without filling them."""
    if geometry is None or geometry.is_empty:
        return

    if hasattr(geometry, "geoms") and not isinstance(geometry, Polygon):
        for part in geometry.geoms:
            plot_outline(ax, part, color, linewidth, linestyle)
        return

    if isinstance(geometry, Polygon):
        x, y = geometry.exterior.xy
        ax.plot(
            x,
            y,
            color=color,
            linewidth=linewidth,
            linestyle=linestyle,
        )

        for ring in geometry.interiors:
            x, y = ring.xy
            ax.plot(x, y, color=color, linewidth=linewidth)


def main():
    print("Loading dataset...")

    with DATASET_PATH.open("rb") as f:
        plans = pickle.load(f)

    plan = next(
        (p for p in plans if str(p.get("id")) == PLAN_ID),
        None,
    )

    if plan is None:
        raise ValueError(f"Plan {PLAN_ID} not found.")

    graph = plan["graph"]

    fig, ax = plt.subplots(figsize=(16, 12))

    # 1. Draw the building interior boundary.
    draw_geometry(
        ax,
        plan.get("inner"),
        facecolor="#FFFFFF",
        edgecolor="#777777",
        alpha=0.25,
        linewidth=0.8,
    )

    # 2. Draw walls.
    plot_outline(
        ax,
        plan.get("wall"),
        color=WALL_COLOR,
        linewidth=2.0,
    )

    # 3. Draw room geometries and labels.
    for node_id, attributes in graph.nodes(data=True):
        geometry = attributes.get("geometry")

        if geometry is None or geometry.is_empty:
            continue

        room_type = attributes.get("type", "unknown")

        draw_geometry(
            ax,
            geometry,
            facecolor=ROOM_COLOR,
            edgecolor="#5A7895",
            alpha=0.35,
            linewidth=0.8,
        )

        point = geometry.representative_point()

        ax.text(
            point.x,
            point.y,
            f"{node_id}\n[{room_type}]",
            fontsize=7,
            ha="center",
            va="center",
            color="#152536",
            bbox=dict(
                boxstyle="round,pad=0.2",
                facecolor="white",
                alpha=0.8,
                edgecolor="none",
            ),
        )

    # 4. Draw door and window components.
    for category, color in (
        ("door", DOOR_COLOR),
        ("window", WINDOW_COLOR),
    ):
        geometry = plan.get(category)

        if geometry is None or geometry.is_empty:
            continue

        parts = (
            list(geometry.geoms)
            if hasattr(geometry, "geoms")
            else [geometry]
        )

        for index, part in enumerate(parts):
            plot_outline(
                ax,
                part,
                color=color,
                linewidth=2.5,
            )

            point = part.representative_point()

            ax.text(
                point.x,
                point.y,
                f"{category[0].upper()}{index}",
                fontsize=7,
                color=color,
                weight="bold",
            )

    # 5. Mark original graph edges between room representative points.
    # Dashed lines are schematic only; they are NOT cable routes.
    for node_a, node_b, attributes in graph.edges(data=True):
        geom_a = graph.nodes[node_a].get("geometry")
        geom_b = graph.nodes[node_b].get("geometry")

        if geom_a is None or geom_b is None:
            continue

        if geom_a.is_empty or geom_b.is_empty:
            continue

        point_a = geom_a.representative_point()
        point_b = geom_b.representative_point()

        edge_type = attributes.get("type", "unknown")

        color = {
            "via_door": "#2764AE",
            "via_opening": "#2764AE",
            "via_window": WINDOW_COLOR,
            "adjacency": "#B44B4B",
            "direct": "#7D3C98",
            "fallback": "#777777",
        }.get(edge_type, "#777777")

        ax.plot(
            [point_a.x, point_b.x],
            [point_a.y, point_b.y],
            linestyle="--",
            linewidth=0.8,
            color=color,
            alpha=0.65,
        )

    legend_items = [
        Line2D([0], [0], color=WALL_COLOR, linewidth=2, label="Wall outline"),
        Line2D([0], [0], color=DOOR_COLOR, linewidth=2.5, label="Door geometry"),
        Line2D([0], [0], color=WINDOW_COLOR, linewidth=2.5, label="Window geometry"),
        Line2D([0], [0], color="#2764AE", linestyle="--", label="Graph: door/opening"),
        Line2D([0], [0], color="#B44B4B", linestyle="--", label="Graph: adjacency"),
        Line2D([0], [0], color="#7D3C98", linestyle="--", label="Graph: direct connection"),
    ]

    ax.legend(handles=legend_items, loc="upper left", fontsize=8)

    ax.set_title(
        f"Plan {PLAN_ID} — Visual Passage Review\n"
        "Dashed graph links are schematic, not verified physical passages",
        fontsize=13,
    )

    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("Dataset X coordinate (raw units)")
    ax.set_ylabel("Dataset Y coordinate (raw units)")
    ax.grid(True, alpha=0.15)

    plt.tight_layout()
    plt.savefig(OUTPUT_FILE, dpi=220, bbox_inches="tight")
    plt.close(fig)

    print(f"Saved visualization: {OUTPUT_FILE.resolve()}")
    print("Reminder: this image does not establish physical passage validity.")


if __name__ == "__main__":
    main()
