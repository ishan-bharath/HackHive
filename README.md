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

## Status
See `PROJECT_CONTEXT.md` for the live project state, verified bug list, and
next steps. Current verified results: optimized solutions valid on 15/16
completed smoke-test plans; optimized cable shorter than baseline in 14/14
comparable plans (mean 6.1%, max 16.1%).
