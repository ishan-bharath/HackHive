# Honeywell HackHive (Problem Statement 4) 

Joint optimization of hub placement and closed-ring cable routing
(Honeywell HackHive, problem statement PS4).

## Problem
For any ResPlan floor plan: decide hub count/positions, room→hub
assignment, and closed-ring cable routes. One node in every eligible room,
max 5 nodes / 100 m² per hub, contiguous territories, one closed
non-branching ring per hub, axis-aligned cable only through verified
doors/open passages.

## Package layout
Implementation lives in the `hackhive_ps4/` package; the root-level scripts
(`run_pipeline.py`, `module2/3/4_*.py`, `compute_cost.py`,
`export_submission.py`, `app.py`) are thin backwards-compatible CLI wrappers.

| Module | What it does |
|---|---|
| `hackhive_ps4/config.py` | Constants + dataset paths (former common.py) |
| `hackhive_ps4/data.py` | Dataset loading, plan dict <-> JSON round trip |
| `hackhive_ps4/geometry.py` | Portal verification, scale calibration, axis-aligned routing graph |
| `hackhive_ps4/matrices.py` | APSP D/B matrix build (Tier 1) + module2 CLI |
| `hackhive_ps4/optimize.py` | Partitioning + exact/J-aware ring sequencing (Tier 2) |
| `hackhive_ps4/validate.py` | Independent PS4-rule validator + Honeywell physics |
| `hackhive_ps4/render.py` | Blueprint + quick-look PNGs |
| `hackhive_ps4/scoring.py` | Official cost J = L + 5X + O + 0.5B |
| `hackhive_ps4/export.py` | Organisers' submission-schema exporter |
| `hackhive_ps4/pipeline.py` | Batch runner |
| `hackhive_ps4/demo.py` | Flask demo UI |
| `hackhive_ps4/synthetic.py` | Synthetic rectilinear plans for tests/CI |

Quality gates: `pytest` (76 tests, 79% coverage), `ruff`, `mypy`, CI workflow
in `.github/workflows/ci.yml` (lint + types + tests + 3-plan synthetic smoke).
Benchmark harness: `benchmark/run_benchmark.py` (500-plan multiprocessing run,
results in `benchmark/`). Early prototype scripts live in `archive/`.

## Pipeline
| Module | File | What it does |
|---|---|---|
| M1 | `module1_portal_and_calibration.py` | Portal graph + calibration diagnostics |
| M2 | `module2_wall_router_and_matrix.py` | Verified portals, wall-hugging router, APSP D/B matrices (true indoor metres + bend counts) |
| M3 | `module3_joint_optimizer.py` | Contiguous partitioning, exact + J-aware ring sequencing, Loop-First/Panel-Snap; baseline vs optimized |
| M4 | `module4_validator_and_blueprint.py` | Independent validator, NFPA/NEC physics, CAD-style blueprint + final JSON |
| —  | `run_pipeline.py` | Full chain + benchmark per plan (`--plan-id all --limit 25` for batch) |
| —  | `export_submission.py` | Converts final JSONs to the organisers' submission schema (`submissions/<id>.json`) |
| —  | `compute_cost.py` | Official ranking metric J = L + 5X + O + 0.5B from submitted polylines |

## Usage
```powershell
python run_pipeline.py --plan-id 14433          # single plan
python run_pipeline.py --plan-id all --limit 25 # batch smoke test
python export_submission.py --all --limit 25    # submissions/<id>.json
python compute_cost.py                          # submissions/cost_summary.json
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
See `PROJECT_CONTEXT.md` for the live project state and results. Official
rules compliance (axis-aligned routing, ≤5 nodes/hub, 0.5 m hub clearance,
official scale, submission export + cost J) is tracked there.
