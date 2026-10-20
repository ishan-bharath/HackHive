"""HackHive PS4 - joint hub placement and closed-ring cable routing on
ResPlan floor plans (official PS4 rules-compliant pipeline).

Package layout:
  config    - constants and dataset paths (former common.py)
  data      - dataset loading + plan dict <-> JSON round trip
  geometry  - portal verification, scale calibration, axis-aligned routing graph
  matrices  - APSP D/B matrix build (Tier 1)
  optimize  - partitioning + exact/J-aware ring sequencing (Tier 2)
  validate  - independent PS4-rule validator + Honeywell physics
  render    - blueprint and quick-look PNGs
  scoring   - official cost J = L + 5X + O + 0.5B
  export    - organisers' submission-schema exporter
  pipeline  - batch runner
  demo      - Flask demo UI
"""

__version__ = "2.0.0"