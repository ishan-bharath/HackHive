import json
import pickle
from pathlib import Path

import networkx as nx
from shapely.geometry import Polygon, MultiPolygon

import common


# ============================================================
# CONFIGURATION
# ============================================================

DATASET_PATH = common.DATASET_PKL

PLAN_ID = "14433"

OUTPUT_PATH = Path("portal_report_14433.json")
GRAPH_OUTPUT_PATH = Path("candidate_passage_graph_14433.json")

ELIGIBLE_ROOMS = {
    "living",
    "bedroom",
    "kitchen",
    "storage",
}

# These edge types are candidates for physical connections.
# They still require independent geometric verification.
CANDIDATE_PASSAGE_TYPES = {
    "via_door",
    "via_opening",
}

# These types are explicitly not accepted as physical passages.
REJECTED_PASSAGE_TYPES = {
    "adjacency",
    "fallback",
}

# Door proximity is only a diagnostic, not proof of connectivity.
DOOR_ASSOCIATION_TOLERANCE = 1.0


# ============================================================
# DATA LOADING
# ============================================================

def load_plan(dataset_path, plan_id):
    """Load a single floor plan from the ResPlan dataset."""

    print("Loading ResPlan dataset...")

    with dataset_path.open("rb") as file:
        plans = pickle.load(file)

    print(f"Dataset contains {len(plans)} plans.")

    for plan in plans:
        if str(plan.get("id")) == str(plan_id):
            print(f"Found plan {plan_id}.")
            return plan

    raise ValueError(f"Plan {plan_id} was not found.")


# ============================================================
# GEOMETRY HELPERS
# ============================================================

def get_polygons(geometry):
    """Extract polygon components from supported geometries."""

    if geometry is None or geometry.is_empty:
        return []

    if isinstance(geometry, Polygon):
        return [geometry]

    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)

    if hasattr(geometry, "geoms"):
        polygons = []

        for component in geometry.geoms:
            polygons.extend(get_polygons(component))

        return polygons

    return []


def geometry_summary(geometry):
    """Return a JSON-compatible summary of a geometry."""

    if geometry is None:
        return {"present": False}

    if geometry.is_empty:
        return {
            "present": True,
            "empty": True,
            "geometry_type": geometry.geom_type,
        }

    return {
        "present": True,
        "empty": False,
        "geometry_type": geometry.geom_type,
        "area_raw_units_squared": float(geometry.area),
        "length_raw_units": float(geometry.length),
        "bounds_raw_units": [
            float(value) for value in geometry.bounds
        ],
        "is_valid": bool(geometry.is_valid),
    }


# ============================================================
# ROOM EXTRACTION
# ============================================================

def extract_rooms(graph):
    """Extract all usable room nodes, including non-eligible rooms."""

    rooms = {}

    for node, attributes in graph.nodes(data=True):
        geometry = attributes.get("geometry")

        if geometry is None or geometry.is_empty:
            continue

        room_type = attributes.get("type", "unknown")

        rooms[str(node)] = {
            "room_type": str(room_type),
            "eligible_for_device": room_type in ELIGIBLE_ROOMS,
            "geometry": geometry,
            "area_raw_units_squared": float(geometry.area),
        }

    return rooms


# ============================================================
# DOOR DIAGNOSTICS
# ============================================================

def associate_doors_with_rooms(door_geometry, rooms):
    """
    Record nearby room candidates.

    This does not prove a door connects the listed rooms.
    """

    results = []

    for index, door in enumerate(get_polygons(door_geometry)):
        nearby_rooms = []

        for room_name, room_data in rooms.items():
            room_geometry = room_data["geometry"]
            distance = float(door.distance(room_geometry))

            if distance <= DOOR_ASSOCIATION_TOLERANCE:
                nearby_rooms.append({
                    "room": room_name,
                    "room_type": room_data["room_type"],
                    "distance_raw_units": distance,
                    "intersects": bool(
                        door.intersects(room_geometry)
                    ),
                })

        results.append({
            "door_component": index,
            "geometry": geometry_summary(door),
            "nearby_room_candidates": nearby_rooms,
            "association_status": (
                "TWO_OR_MORE_CANDIDATES"
                if len(nearby_rooms) >= 2
                else "UNRESOLVED"
            ),
            "warning": (
                "Proximity is not proof of a physical connection."
            ),
        })

    return results


# ============================================================
# GRAPH CLASSIFICATION
# ============================================================

def build_candidate_passage_graph(graph):
    """
    Preserve all room nodes but only retain candidate physical
    passage edges in the candidate graph.

    This is NOT a physically validated routing graph.
    """

    candidate_graph = nx.Graph()

    for node, attributes in graph.nodes(data=True):
        candidate_graph.add_node(
            str(node),
            room_type=str(attributes.get("type", "unknown")),
            eligible_for_device=(
                attributes.get("type") in ELIGIBLE_ROOMS
            ),
        )

    edge_report = []

    for first, second, attributes in graph.edges(data=True):
        edge_type = str(attributes.get("type", "unknown"))

        if edge_type in CANDIDATE_PASSAGE_TYPES:
            classification = "CANDIDATE_PHYSICAL_PASSAGE"
            included = True

        elif edge_type in REJECTED_PASSAGE_TYPES:
            classification = "REJECTED_AS_PHYSICAL_PASSAGE"
            included = False

        elif edge_type == "direct":
            classification = "ENTRANCE_CONNECTION_REQUIRES_REVIEW"
            included = False

        else:
            classification = "UNKNOWN_CONNECTION_REQUIRES_REVIEW"
            included = False

        edge_report.append({
            "room_a": str(first),
            "room_b": str(second),
            "original_type": edge_type,
            "classification": classification,
            "included_in_candidate_graph": included,
            "geometrically_verified": False,
        })

        if included:
            candidate_graph.add_edge(
                str(first),
                str(second),
                original_type=edge_type,
                geometrically_verified=False,
            )

    return candidate_graph, edge_report


def serialize_graph(graph):
    """Convert a NetworkX graph to JSON-compatible data."""

    return {
        "nodes": [
            {
                "id": str(node),
                **attributes,
            }
            for node, attributes in graph.nodes(data=True)
        ],
        "edges": [
            {
                "room_a": str(first),
                "room_b": str(second),
                **attributes,
            }
            for first, second, attributes
            in graph.edges(data=True)
        ],
    }


# ============================================================
# REPORT GENERATION
# ============================================================

def build_report(plan):
    graph = plan["graph"]

    rooms = extract_rooms(graph)

    eligible_rooms = {
        name: data
        for name, data in rooms.items()
        if data["eligible_for_device"]
    }

    door_report = associate_doors_with_rooms(
        plan.get("door"),
        rooms,
    )

    candidate_graph, edge_report = (
        build_candidate_passage_graph(graph)
    )

    room_report = {}

    for room_name, room_data in rooms.items():
        room_report[room_name] = {
            "room_type": room_data["room_type"],
            "eligible_for_device": (
                room_data["eligible_for_device"]
            ),
            "area_raw_units_squared": (
                room_data["area_raw_units_squared"]
            ),
            "geometry": geometry_summary(
                room_data["geometry"]
            ),
        }

    candidate_graph_report = {
        **serialize_graph(candidate_graph),
        "node_count": candidate_graph.number_of_nodes(),
        "edge_count": candidate_graph.number_of_edges(),
        "connected_components": [
            sorted(component)
            for component in nx.connected_components(candidate_graph)
        ],
        "warning": (
            "Edges are candidate passages only. Physical passage "
            "and cable-route feasibility have not been verified."
        ),
    }

    report = {
        "plan_id": str(plan.get("id")),
        "dataset": "ResPlan",

        "rooms": room_report,

        "eligible_room_ids": sorted(eligible_rooms.keys()),

        "door_candidates": door_report,

        "original_graph": {
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
        },

        "edge_classifications": edge_report,

        "candidate_passage_graph": {
            "node_count": candidate_graph.number_of_nodes(),
            "edge_count": candidate_graph.number_of_edges(),
            "connected_components": (
                candidate_graph_report["connected_components"]
            ),
        },

        "geometry": {
            "inner": geometry_summary(plan.get("inner")),
            "walls": geometry_summary(plan.get("wall")),
            "doors": geometry_summary(plan.get("door")),
            "windows": geometry_summary(plan.get("window")),
        },

        "metadata": {
            "reported_total_area": (
                float(plan["area"])
                if plan.get("area") is not None
                else None
            ),
            "reported_net_area": (
                float(plan["net_area"])
                if plan.get("net_area") is not None
                else None
            ),
            "wall_depth_raw_units": (
                float(plan["wall_depth"])
                if plan.get("wall_depth") is not None
                else None
            ),
        },

        "calibration": {
            "status": "UNVERIFIED",
            "geometry_unit": "unknown",
            "warning": (
                "Do not convert geometry areas into square metres "
                "until coordinate calibration has been validated."
            ),
        },

        "validation": {
            "candidate_graph_built": True,
            "portal_graph_verified": False,
            "cable_routes_verified": False,
            "panel_constraints_verified": False,
        },
    }

    return report, candidate_graph_report


# ============================================================
# MAIN
# ============================================================

def main():
    plan = load_plan(DATASET_PATH, PLAN_ID)

    report, candidate_graph_report = build_report(plan)

    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)

    with GRAPH_OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(candidate_graph_report, file, indent=2)

    print("\n" + "=" * 55)
    print("CANDIDATE PASSAGE GRAPH DIAGNOSTICS")
    print("=" * 55)

    print(f"Plan ID: {PLAN_ID}")
    print("All usable room nodes:", len(report["rooms"]))
    print("Eligible device rooms:", len(report["eligible_room_ids"]))

    print(
        "Original graph edges:",
        report["original_graph"]["edge_count"],
    )

    print(
        "Candidate passage edges:",
        report["candidate_passage_graph"]["edge_count"],
    )

    print(
        "Candidate graph components:",
        len(report["candidate_passage_graph"]["connected_components"]),
    )

    print("\nCandidate graph edges:")

    for edge in candidate_graph_report["edges"]:
        print(
            f"  {edge['room_a']} <-> {edge['room_b']} "
            f"({edge['original_type']})"
        )

    print("\nCalibration: UNVERIFIED")
    print("Physical passage validation: NOT YET IMPLEMENTED")
    print("Cable routing: NOT YET IMPLEMENTED")

    print(f"\nReport saved: {OUTPUT_PATH.resolve()}")
    print(f"Candidate graph saved: {GRAPH_OUTPUT_PATH.resolve()}")


if __name__ == "__main__":
    main()