"""Shared configuration and dataset loading for HackHive PS4.

All modules import dataset access from here. No hardcoded per-user paths.
Override the dataset location with the HACKHIVE_DATASET_DIR environment
variable or the --dataset CLI argument where supported.
"""

import os
import pickle
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

DEFAULT_DATASET_DIR = PROJECT_ROOT / "dataset"
DATASET_DIR = Path(
    os.environ.get("HACKHIVE_DATASET_DIR", DEFAULT_DATASET_DIR)
)

DATASET_PKL = DATASET_DIR / "ResPlan.pkl"

ELIGIBLE_TYPES = {"living", "bedroom", "kitchen", "storage"}

# Nominal door clear width in metres used to calibrate raw coordinate scale.
NOMINAL_DOOR_WIDTH_M = 0.85

# Physical constants for Honeywell metrics.
WALL_CLEARANCE_M = 0.15
DEAD_END_PORTAL_OFFSET_M = 0.08
WIRE_OHMS_PER_M_18AWG = 0.021
SUPPLY_VOLTAGE_V = 24.0
MAX_VOLTAGE_DROP_V = 3.0

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
