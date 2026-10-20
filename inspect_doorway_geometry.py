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
OUTPUT_DIR = Path("doorway_diagnostics_14433")

# Diagnostic threshold in raw dataset units; not physically calibrated.
DISTANCE_THRESHOLD = 5.0


def components(geometry):
    if geometry is None or geometry.is_empty:
        return []

    if hasattr(geometry, "geoms"):
        return [
            part for part in geometry.geoms
            if not part.is_empty
        ]

    return [geometry]


def load_plan():
    with DATASET_PATH.open("rb") as f:
        plans = pickle.load(f)

    plan = next(
        (p for p in plans if str(p.get("id")) == PLAN_ID),
        None,
    )

    if plan is None:
        raise ValueError(f"Plan {PLAN_ID} not found.")

    return plan


def draw_geometry(ax, geometry, color, linewidth=1.5, alpha=1.0):
    for part in components(geometry):
        if isinstance(part, Polygon):
            x, y = part.exterior.xy
            ax.fill(
                x, y,
                facecolor=color,
                edgecolor=color,
                linewidth=linewidth,
                alpha=alpha,
            )
        else:
            try:
                x, y = part.xy
                ax.plot(x, y, color=color, linewidth=linewidth)
            except (AttributeError, NotImplementedError):
                pass


def draw_outline(ax, geometry, color, linewidth=2):
    for part in components(geometry):
        if isinstance(part, Polygon):
            x, y = part.exterior.xy
            ax.plot(x, y, color=color, linewidth=linewidth)
        else:
            try:
                x, y = part.xy
                ax.plot(x, y, color=color, linewidth=linewidth)
            except (AttributeError, NotImplementedError):
                pass


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    print("Loading Plan", PLAN_ID)
    plan = load_plan()
    graph = plan["graph"]

    rooms = {}

    for node_id, attrs in graph.nodes(data=True):
        geometry = attrs.get("geometry")

        if geometry is None or geometry.is_empty:
            continue

        rooms[node_id] = {
            "type": attrs.get("type", "unknown"),
            "geometry": geometry,
        }

    doors = components(plan.get("door"))
    windows = components(plan.get("window"))
    walls = plan.get("wall")

    results = []

    # Inspect every original via_door edge.
    for room_a, room_b, attrs in graph.edges(data=True):
        edge_type = attrs.get("type", "unknown")

        if edge_type != "via_door":
            continue

        if room_a not in rooms or room_b not in rooms:
            continue

        geom_a = rooms[room_a]["geometry"]
        geom_b = rooms[room_b]["geometry"]

        nearby_connectors = []

        for index, door in enumerate(doors):
            distance_a = door.distance(geom_a)
            distance_b = door.distance(geom_b)

            if (
                distance_a <= DISTANCE_THRESHOLD
                and distance_b <= DISTANCE_THRESHOLD
            ):
                nearby_connectors.append({
                    "connector": f"door_{index}",
                    "distance_to_room_a": round(distance_a, 4),
                    "distance_to_room_b": round(distance_b, 4),
                })

        boundary_distance = geom_a.boundary.distance(
            geom_b.boundary
        )

        shared_boundary_length = geom_a.boundary.intersection(
            geom_b.boundary
        ).length

        record = {
            "room_a": room_a,
            "room_b": room_b,
            "edge_type": edge_type,
            "boundary_distance_raw_units": round(
                boundary_distance, 4
            ),
            "shared_boundary_length_raw_units": round(
                shared_boundary_length, 4
            ),
            "nearby_door_candidates": nearby_connectors,
            "physical_passage_verified": False,
        }

        results.append(record)

        print(
            f"\n{room_a} <-> {room_b}"
            f"\n  Boundary distance: {boundary_distance:.3f}"
            f"\n  Shared boundary length: {shared_boundary_length:.3f}"
            f"\n  Nearby doors: {nearby_connectors}"
        )

        # Create a separate zoomed diagnostic image.
        fig, ax = plt.subplots(figsize=(9, 8))

        draw_geometry(ax, geom_a, "#9CC9F0", alpha=0.45)
        draw_geometry(ax, geom_b, "#F0C89C", alpha=0.45)

        draw_outline(ax, geom_a, "#286090")
        draw_outline(ax, geom_b, "#A65A19")

        if walls is not None:
            draw_outline(ax, walls, "#333333", linewidth=1.5)

        # Draw nearby door candidates.
        for candidate in nearby_connectors:
            index = int(candidate["connector"].split("_")[1])
            door = doors[index]

            draw_outline(ax, door, "#00A878", linewidth=3)

            point = door.representative_point()
            ax.text(
                point.x,
                point.y,
                candidate["connector"],
                fontsize=9,
                color="#007A56",
                weight="bold",
            )

        # Draw nearby windows for context, but never treat them
        # as valid interior passages in this diagnostic.
        for index, window in enumerate(windows):
            if (
                window.distance(geom_a) <= DISTANCE_THRESHOLD
                and window.distance(geom_b) <= DISTANCE_THRESHOLD
            ):
                draw_outline(ax, window, "#E5A000", linewidth=2)

                point = window.representative_point()
                ax.text(
                    point.x,
                    point.y,
                    f"window_{index}",
                    fontsize=8,
                    color="#996600",
                )

        point_a = geom_a.representative_point()
        point_b = geom_b.representative_point()

        ax.text(
            point_a.x,
            point_a.y,
            room_a,
            fontsize=9,
            ha="center",
            bbox=dict(facecolor="white", alpha=0.8),
        )

        ax.text(
            point_b.x,
            point_b.y,
            room_b,
            fontsize=9,
            ha="center",
            bbox=dict(facecolor="white", alpha=0.8),
        )

        # Zoom around both room geometries and nearby connectors.
        combined = geom_a.union(geom_b)

        for candidate in nearby_connectors:
            index = int(candidate["connector"].split("_")[1])
            combined = combined.union(doors[index])

        min_x, min_y, max_x, max_y = combined.bounds
        padding = 12

        ax.set_xlim(min_x - padding, max_x + padding)
        ax.set_ylim(min_y - padding, max_y + padding)
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, alpha=0.2)

        ax.set_title(
            f"{room_a} <-> {room_b}\n"
            "Green = nearby door candidate; not verified"
        )

        filename = (
            f"{room_a}__{room_b}"
            .replace("/", "_")
            + ".png"
        )

        fig.tight_layout()
        fig.savefig(
            OUTPUT_DIR / filename,
            dpi=180,
            bbox_inches="tight",
        )
        plt.close(fig)

    report = {
        "plan_id": PLAN_ID,
        "distance_threshold_raw_units": DISTANCE_THRESHOLD,
        "threshold_physically_calibrated": False,
        "physical_passage_validation_complete": False,
        "edges": results,
    }

    output_json = OUTPUT_DIR / "doorway_geometry_report.json"

    output_json.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 60)
    print("Diagnostic images saved in:", OUTPUT_DIR.resolve())
    print("JSON report saved in:", output_json.resolve())
    print("Physical passage validation: NOT COMPLETE")


if __name__ == "__main__":
    main()
