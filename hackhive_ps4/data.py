"""Dataset loading and plan dict <-> JSON round trip.

load_plan/plan_ids/dataset_available moved verbatim from former common.py;
plan_to_jsonable/json_to_plan moved verbatim from former app.py.
"""

import pickle

import networkx as nx
from shapely.geometry import mapping, shape

from .config import DATASET_PKL

_PLAN_CACHE = None


def dataset_available():
    return DATASET_PKL.is_file()


def load_plan(plan_id):
    """Load a single plan (dict) by string id. Caches the full pickle in memory."""
    global _PLAN_CACHE
    if _PLAN_CACHE is None:
        if not dataset_available():
            raise FileNotFoundError(
                f"ResPlan.pkl not found at {DATASET_PKL}. "
                "Extract archive.zip into ./dataset or set HACKHIVE_DATASET_DIR."
            )
        with DATASET_PKL.open("rb") as f:
            _PLAN_CACHE = pickle.load(f)
    target = str(plan_id)
    for plan in _PLAN_CACHE:
        if str(plan.get("id")) == target:
            return plan
    raise ValueError(f"Plan {plan_id} not found in dataset.")


def plan_ids(limit=None):
    global _PLAN_CACHE
    if _PLAN_CACHE is None:
        load_plan("0")  # forces cache load
    ids = [str(p.get("id")) for p in _PLAN_CACHE]
    return ids[:limit] if limit else ids


# ------------------------------------------------------------------
# Plan dict <-> JSON round trip (upload mode)
# ------------------------------------------------------------------

REQUIRED_PLAN_KEYS = ("id", "graph", "inner", "wall", "door")


def _geojson_or_none(geom):
    return None if geom is None else mapping(geom)


def plan_to_jsonable(plan):
    """Serialize a ResPlan plan dict (nx graph + shapely geoms) to plain JSON."""
    g = plan["graph"]
    nodes = {}
    for nid, attrs in g.nodes(data=True):
        nodes[str(nid)] = {
            "type": attrs.get("type"),
            "geometry": _geojson_or_none(attrs.get("geometry")),
        }
    edges = [[str(a), str(b), attrs.get("type")]
             for a, b, attrs in g.edges(data=True)]
    out = {
        "id": plan.get("id"),
        "graph": {"nodes": nodes, "edges": edges},
        "inner": _geojson_or_none(plan.get("inner")),
        "wall": _geojson_or_none(plan.get("wall")),
        "door": _geojson_or_none(plan.get("door")),
        "window": _geojson_or_none(plan.get("window")),
        "frontdoor": _geojson_or_none(plan.get("frontdoor")),
    }
    for key in ("area", "net_area", "wall_depth"):
        if plan.get(key) is not None:
            out[key] = plan[key]
    return out


def json_to_plan(data):
    """Rebuild a pipeline-ready plan dict from a JSON-serialized plan."""
    if not isinstance(data, dict):
        raise ValueError("JSON must be a single object (one plan dict), "
                         f"got {type(data).__name__}.")
    missing = [k for k in REQUIRED_PLAN_KEYS if data.get(k) is None]
    if missing:
        raise ValueError(
            "Plan dict is missing required key(s): " + ", ".join(missing)
            + ". Expected one ResPlan plan (id, graph, inner, wall, door, ...)."
        )
    g = nx.Graph()
    for nid, attrs in data["graph"]["nodes"].items():
        geom = attrs.get("geometry")
        g.add_node(nid, type=attrs.get("type"),
                   geometry=shape(geom) if geom is not None else None)
    for a, b, etype in data["graph"].get("edges", []):
        g.add_edge(a, b, type=etype)
    plan = {
        "id": data.get("id", "upload"),
        "graph": g,
        "inner": shape(data["inner"]),
        "wall": shape(data["wall"]),
        "door": shape(data["door"]),
    }
    for key in ("window", "frontdoor", "area", "net_area", "wall_depth"):
        if data.get(key) is not None:
            plan[key] = (shape(data[key]) if key in ("window", "frontdoor")
                         else data[key])
    return plan

