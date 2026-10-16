# Honeywell HackHive — PS4

Joint optimization of control-panel placement and closed-loop cable routing
(Honeywell HackHive, problem statement PS4).

## Problem
For any ResPlan floor plan: decide panel count/positions, room→panel
assignment, and closed-loop cable routes. One device in every eligible room,
max 20 devices / 100 m² per panel, contiguous territories, one closed
non-branching loop per panel, cables only through verified doors/open
passages.

## Pipeline
| Module | File | What it does |
|---|---|---|
| M1 | `module1_portal_and_calibration.py` | Portal graph + calibration diagnostics |
| M2 | `module2_wall_router_and_matrix.py` | Verified portals, wall-hugging router, APSP D/B matrices (true indoor metres + bend counts) |
| M3 | `module3_joint_optimizer.py` | Contiguous partitioning, 2-opt TSP loops, Loop-First/Panel-Snap; baseline vs optimized |
| M4 | `module4_validator_and_blueprint.py` | Independent validator, NFPA/NEC physics, CAD-style blueprint + final JSON |
| —  | `run_pipeline.py` | Full chain + benchmark per plan (`--plan-id all --limit 25` for batch) |

## Usage
```powershell
python run_pipeline.py --plan-id 14433          # single plan
python run_pipeline.py --plan-id all --limit 25 # batch smoke test
```

## Demo UI
```powershell
python app.py                   # opens http://127.0.0.1:8000 in your browser
python app.py --host 0.0.0.0    # judges on the same WiFi: http://<your-LAN-IP>:8000
python app.py --port 8080 --no-browser
```
Single-page Flask app (`app.py`, no extra dependencies). Two input modes:
- **Upload**: a `.json` file with one ResPlan plan dict (no dataset needed;
  produce one with `python app.py --dump <plan_id> plan.json`), or
- **Plan ID**: any ID from `dataset/ResPlan.pkl` when the dataset is present.

It runs the full pipeline in-process (M2 → M3 → M4), shows the validated
CAD blueprint (visitation order, legend), the baseline comparison, the
validation checklist, metrics with % cable saving, Honeywell physics, and a
downloadable result JSON. Errors (e.g. unwirable/sealed plans) get a friendly
page, never a traceback.

## Status
See `PROJECT_CONTEXT.md` for the live project state and results. Current
batch (25 plans): optimized AND baseline valid 25/25; optimized cable beats
baseline on all 25 (mean 5.24%, max 16.1%).
