"""Shared configuration for HackHive PS4 (former common.py).

All modules import constants and dataset paths from here. Dataset loading
lives in data.py. Override the dataset location with the HACKHIVE_DATASET_DIR
environment variable.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

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

# Official PS4 rule 6: hub point at least 0.5 m from walls. Candidates are
# generated with a slightly larger 0.6 m inset for tolerance margin.
HUB_CLEARANCE_M = 0.6
HUB_MIN_CLEARANCE_M = 0.5
