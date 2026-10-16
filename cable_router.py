import json
import pickle
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
from shapely.geometry import (
    Point,
    LineString,
    Polygon,
    MultiPolygon,
    GeometryCollection,
)

DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

PLAN_ID = "14433"

OUTPUT_JSON = Path("routing_result_14433.json")
OUTPUT_IMAGE = Path("routing_result_14433.png")

ELIGIBLE_TYPES = {
    "living",
    "bedroom",
    "kitchen",
    "storage",
}

# Exploratory geometry setting, in raw dataset units.
# Not a calibrated cable clearance.
WALL_CLEARANCE = 0.5

# Initial prototype: one panel placed inside the living room.
PANEL_ROOM = "living_0"

# Edge types allowed in the provisional connectivity graph.
ALLOWED_EDGE_TYPES = {
    "via_door",
    "via_opening",
    "adjacency",
}


def get_parts(geometry):
    if geometry is None or geometry.is_empty:
        return []

    if hasattr(geometry, "geoms"):
        return [
            part for part in geometry.geoms
            if not part.is_empty
        ]

    return [geometry]


def load_plan():
    print("Loading dataset...")

    with DATASET_PATH.open("rb") as file:
        plans = pickle.load(file)

    plan = next(
        (
            item for item in plans
            if str(item.get("id")) == PLAN_ID
        ),
        None,
    )

    if plan is None:
        raise ValueError(f"Plan {PLAN_ID} not found.")

    return plan


def choose_point_inside(geometry):
    """Return a point guaranteed to lie within the geometry."""
    return geometry.representative_point()


def build_provisional_graph(original_graph, rooms):
    """
    Keep original graph edges as provisional connectivity evidence.

    This does not prove that the corresponding passages are
    physically traversable.
    """
    result = nx.Graph()

    for room_id in rooms:
        result.add_node(room_id)

    for room_a, room_b, attrs in original_graph.edges(data=True):
        if room_a not in rooms or room_b not in rooms:
            continue

        edge_type = attrs.get("type", "unknown")

        if edge_type not in ALLOWED_EDGE_TYPES:
            continue

        geom_a = rooms[room_a]["geometry"]
        geom_b = rooms[room_b]["geometry"]

        # Distance is a routing heuristic, not a doorway measurement.
        distance = geom_a.distance(geom_b)

        result.add_edge(
            room_a,
            room_b,
            weight=max(distance, 1.0),
            original_edge_type=edge_type,
            passage_verified=False,
        )

    return result


def route_inside_building(start, end, inner, walls):
    """
    Find a candidate straight route if it stays within the
    building interior and avoids buffered wall geometry.

    Returns None when no valid straight segment is found.
    This function does not attempt to route around obstacles.
    """
    segment = LineString([start.coords[0], end.coords[0]])

    if not inner.covers(segment):
        return None

    if walls is not None and not walls.is_empty:
        obstacles = walls.buffer(WALL_CLEARANCE)

        if segment.intersects(obstacles):
            return None

    return segment


def draw_geometry(ax, geometry, facecolor, edgecolor, alpha=0.3):
    for part in get_parts(geometry):
        if isinstance(part, Polygon):
            x, y = part.exterior.xy

            ax.fill(
                x,
                y,
                facecolor=facecolor,
                edgecolor=edgecolor,
                alpha=alpha,
            )

        else:
            try:
                x, y = part.xy
                ax.plot(x, y, color=edgecolor)
            except (AttributeError, NotImplementedError):
                pass


def main():
    plan = load_plan()
    original_graph = plan["graph"]

    inner = plan.get("inner")
    walls = plan.get("wall")

    if inner is None or inner.is_empty:
        raise ValueError("Building interior geometry is missing.")

    rooms = {}

    for node_id, attrs in original_graph.nodes(data=True):
        room_type = attrs.get("type", "unknown")
        geometry = attrs.get("geometry")

        if (
            room_type in ELIGIBLE_TYPES
            and geometry is not None
            and not geometry.is_empty
        ):
            rooms[node_id] = {
                "type": room_type,
                "geometry": geometry,
                "device_point": choose_point_inside(geometry),
            }

    if not rooms:
        raise ValueError("No eligible device rooms found.")

    if PANEL_ROOM not in rooms:
        raise ValueError(
            f"Panel room {PANEL_ROOM} is not eligible."
        )

    provisional_graph = build_provisional_graph(
        original_graph,
        rooms,
    )

    panel_point = rooms[PANEL_ROOM]["device_point"]

    print("\nEligible device rooms:", len(rooms))
    print("Panel room:", PANEL_ROOM)
    print("Provisional graph edges:", provisional_graph.number_of_edges())

    # A single panel must be connected to every eligible room.
    reachable = nx.node_connected_component(
        provisional_graph,
        PANEL_ROOM,
    )

    unreachable = sorted(set(rooms) - set(reachable))

    routes = []
    route_segments = []
    total_length = 0.0

    for room_id, room in rooms.items():
        if room_id == PANEL_ROOM:
            continue

        record = {
            "room_id": room_id,
            "device_type": room["type"],
            "panel_room": PANEL_ROOM,
            "status": None,
            "path_rooms": [],
            "route_length_raw_units": None,
            "passages_verified": False,
        }

        if room_id not in reachable:
            record["status"] = "UNREACHABLE_IN_PROVISIONAL_GRAPH"
            routes.append(record)
            continue

        path = nx.shortest_path(
            provisional_graph,
            source=PANEL_ROOM,
            target=room_id,
            weight="weight",
        )

        # Construct a straight-line candidate between the panel
        # and the device, but accept it only if it stays inside
        # the building and avoids buffered walls.
        target_point = room["device_point"]

        segment = route_inside_building(
            panel_point,
            target_point,
            inner,
            walls,
        )

        if segment is None:
            record["status"] = "STRAIGHT_ROUTE_BLOCKED"
            record["path_rooms"] = path
            routes.append(record)
            continue

        length = segment.length
        total_length += length

        record["status"] = "PROVISIONAL_STRAIGHT_ROUTE"
        record["path_rooms"] = path
        record["route_length_raw_units"] = round(length, 4)

        routes.append(record)
        route_segments.append(segment)

    # Save a visualization.
    fig, ax = plt.subplots(figsize=(14, 11))

    draw_geometry(
        ax,
        inner,
        facecolor="#FFFFFF",
        edgecolor="#777777",
        alpha=0.15,
    )

    draw_geometry(
        ax,
        walls,
        facecolor="#555555",
        edgecolor="#333333",
        alpha=0.8,
    )

    for room_id, room in rooms.items():
        draw_geometry(
            ax,
            room["geometry"],
            facecolor="#A7CBE8",
            edgecolor="#356A91",
            alpha=0.4,
        )

        point = room["device_point"]

        ax.scatter(
            point.x,
            point.y,
            marker="s",
            s=55,
            color="#244B70",
        )

        ax.text(
            point.x,
            point.y,
            room_id,
            fontsize=8,
        )

    for segment in route_segments:
        x, y = segment.xy

        ax.plot(
            x,
            y,
            linestyle="--",
            linewidth=1.8,
            color="#D35400",
        )

    ax.scatter(
        panel_point.x,
        panel_point.y,
        marker="*",
        s=250,
        color="#00A878",
        label="Provisional panel",
    )

    ax.set_title(
        f"Plan {PLAN_ID} — Provisional Routing Prototype\n"
        "Dashed routes are straight-line candidates, not validated cable paths"
    )

    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("Dataset X coordinate (raw units)")
    ax.set_ylabel("Dataset Y coordinate (raw units)")
    ax.grid(True, alpha=0.2)
    ax.legend()

    plt.tight_layout()
    plt.savefig(OUTPUT_IMAGE, dpi=200, bbox_inches="tight")
    plt.close(fig)

    result = {
        "plan_id": PLAN_ID,
        "status": "PROTOTYPE_NOT_PHYSICALLY_VALIDATED",
        "panel_room": PANEL_ROOM,
        "eligible_device_count": len(rooms),
        "provisional_graph_edge_count": provisional_graph.number_of_edges(),
        "reachable_rooms_from_panel": sorted(reachable),
        "unreachable_rooms": unreachable,
        "wall_clearance_raw_units": WALL_CLEARANCE,
        "wall_clearance_calibrated": False,
        "total_accepted_straight_route_length_raw_units": round(
            total_length, 4
        ),
        "route_length_is_complete_network_length": False,
        "routes": routes,
        "limitations": [
            "Original graph connections are provisional.",
            "Straight-line candidates are not routed around obstacles.",
            "Panel placement is fixed to the representative point of the living room.",
            "No panel capacity or area constraints are optimized.",
            "No closed-loop visitation route is constructed.",
            "Physical passage validity has not been established.",
            "Raw coordinate units are not calibrated to physical units.",
        ],
    }

    OUTPUT_JSON.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print("\nROUTING SUMMARY")
    print("=" * 45)

    for route in routes:
        print(
            f"{route['room_id']}: "
            f"{route['status']}"
        )

    print("\nUnreachable rooms:", unreachable)
    print("Total accepted straight-route length:", round(total_length, 4))
    print("JSON saved:", OUTPUT_JSON.resolve())
    print("Image saved:", OUTPUT_IMAGE.resolve())
    print("\nThis is a prototype, not a validated routing solution.")


if __name__ == "__main__":
    main()