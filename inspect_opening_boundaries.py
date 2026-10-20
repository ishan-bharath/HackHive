import json
import pickle
from pathlib import Path

import matplotlib.pyplot as plt
from shapely.geometry import Polygon

DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

PLAN_ID = "14433"
OUTPUT_DIR = Path("opening_boundary_diagnostics")

# Exploratory only; raw dataset units, not calibrated measurements.
WALL_BUFFER = 0.5


def parts(geometry):
    if geometry is None or geometry.is_empty:
        return []

    if hasattr(geometry, "geoms"):
        return list(geometry.geoms)

    return [geometry]


def draw_outline(ax, geometry, color, linewidth=1.5):
    for part in parts(geometry):
        if isinstance(part, Polygon):
            x, y = part.exterior.xy
            ax.plot(x, y, color=color, linewidth=linewidth)

            for ring in part.interiors:
                x, y = ring.xy
                ax.plot(x, y, color=color, linewidth=linewidth)

        else:
            try:
                x, y = part.xy
                ax.plot(x, y, color=color, linewidth=linewidth)
            except (AttributeError, NotImplementedError):
                pass


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    print("Loading plan...")

    with DATASET_PATH.open("rb") as f:
        plans = pickle.load(f)

    plan = next(
        (p for p in plans if str(p.get("id")) == PLAN_ID),
        None,
    )

    if plan is None:
        raise ValueError(f"Plan {PLAN_ID} not found.")

    graph = plan["graph"]
    walls = plan.get("wall")

    # Focus on connections we need to investigate.
    target_pairs = [
        ("living_0", "bedroom_0"),
        ("living_0", "bathroom_0"),
        ("living_0", "kitchen_0"),
        ("living_0", "bedroom_1"),
        ("living_0", "bedroom_2"),
        ("bedroom_1", "bathroom_2"),
    ]

    report = []

    for room_a, room_b in target_pairs:
        if not graph.has_node(room_a) or not graph.has_node(room_b):
            print(f"Skipping missing rooms: {room_a}, {room_b}")
            continue

        geom_a = graph.nodes[room_a].get("geometry")
        geom_b = graph.nodes[room_b].get("geometry")

        if geom_a is None or geom_b is None:
            continue

        # Shared boundary and portions not covered by buffered walls.
        shared = geom_a.boundary.intersection(geom_b.boundary)

        if walls is not None and not walls.is_empty:
            wall_buffered = walls.buffer(WALL_BUFFER)
            uncovered = shared.difference(wall_buffered)
        else:
            uncovered = shared

        edge_data = graph.get_edge_data(room_a, room_b) or {}

        record = {
            "room_a": room_a,
            "room_b": room_b,
            "original_edge_type": edge_data.get("type", "no_edge"),
            "shared_boundary_length": round(shared.length, 4),
            "uncovered_boundary_length": round(uncovered.length, 4),
            "wall_buffer_raw_units": WALL_BUFFER,
            "physical_passage_verified": False,
        }

        report.append(record)

        print(
            f"\n{room_a} <-> {room_b}"
            f"\n  Graph edge: {record['original_edge_type']}"
            f"\n  Shared boundary: {shared.length:.3f}"
            f"\n  Uncovered boundary: {uncovered.length:.3f}"
        )

        fig, ax = plt.subplots(figsize=(10, 8))

        # Draw the two room boundaries.
        draw_outline(ax, geom_a, "#2878B5", 2)
        draw_outline(ax, geom_b, "#C47A32", 2)

        # Draw walls and relevant connector geometry.
        if walls is not None:
            draw_outline(ax, walls, "#333333", 1.5)

        for category, color in [
            ("door", "#00A878"),
            ("window", "#E5A000"),
        ]:
            connector_geometry = plan.get(category)

            for index, connector in enumerate(parts(connector_geometry)):
                # Show connectors that lie near the shared boundary.
                if connector.distance(shared) <= 12:
                    draw_outline(ax, connector, color, 3)

                    point = connector.representative_point()
                    ax.text(
                        point.x,
                        point.y,
                        f"{category}_{index}",
                        fontsize=8,
                        color=color,
                        weight="bold",
                    )

        draw_outline(ax, shared, "#8E44AD", 3)
        draw_outline(ax, uncovered, "#00A878", 4)

        # Zoom to the shared boundary and surrounding geometry.
        context = geom_a.union(geom_b)

        if shared is not None and not shared.is_empty:
            min_x, min_y, max_x, max_y = shared.bounds
        else:
            min_x, min_y, max_x, max_y = context.bounds

        padding = 15

        ax.set_xlim(min_x - padding, max_x + padding)
        ax.set_ylim(min_y - padding, max_y + padding)
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, alpha=0.2)

        ax.set_title(
            f"{room_a} <-> {room_b}\n"
            "Purple = shared boundary; green = outside buffered walls"
        )

        filename = f"{room_a}__{room_b}.png"
        fig.tight_layout()
        fig.savefig(
            OUTPUT_DIR / filename,
            dpi=180,
            bbox_inches="tight",
        )
        plt.close(fig)

    report_path = OUTPUT_DIR / "boundary_report.json"

    report_path.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print("\nDiagnostic images saved to:", OUTPUT_DIR.resolve())
    print("Report saved to:", report_path.resolve())
    print("These results do not prove physical traversability.")


if __name__ == "__main__":
    main()
