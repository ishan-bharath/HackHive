# PROJECT_CONTEXT.md — Shared Memory for Any Model/Agent

Read this file FIRST. Single source of truth for project state. Update after
every milestone. Keep under ~200 lines.

## 1. Project Identity

- **Hackathon:** Honeywell HackHive (48h) — DEADLINE: ~2026-10-17 afternoon (~10h left as of 2026-10-16 15:00).
- **Problem statement:** PS4 — Joint Optimization of Control-Panel Placement and Closed-Loop Cable Routing.
- **Repo:** https://github.com/ishan-bharath/HackHive (branch: main).
- **Goal:** for any ResPlan floor plan: panel count/positions, room→panel assignment,
  closed-loop cable routes, validated + visualized + exported JSON.
- Physical validity is MANDATORY: cables cross rooms ONLY through real doors/open passages;
  never cross walls/windows/exterior.

## 2. Hard Constraints (from PS4)

1. One device in EVERY eligible room: living room, bedroom, kitchen, storage room.
2. Each panel serves max 20 devices AND max 100 m^2 of eligible-room area.
3. Every eligible room assigned to exactly ONE panel.
4. Rooms of a panel form a CONTIGUOUS territory (valid indoor passages).
5. One closed, non-branching loop per panel, every device visited exactly once.
6. Routes stay inside building; cross between rooms only through verified portals.
7. Deliverables: visual overlay (CAD blueprint style) + matching JSON + benchmark vs baseline.

## 3. Dataset Facts (ResPlan)

- `archive.zip` (gitignored) → extracted to `dataset/` (gitignored): ResPlan.pkl (~286MB, ~17k plans).
- Plan dict: `id`, `graph`, `inner`, `wall`, `door`, `window`, `frontdoor`, room layers, metadata.
- TRAP: do NOT trust `fallback` edges or blind `adjacency`; `via_window` edges are unverified.
- TRAP: raw coordinates are NOT metres; area metadata bad on 5,458/17,000 plans.
- Calibration NOW: door-width based (median door = 0.85 m nominal), area fallback only.

## 4. Architecture (unchanged)

Tier 1 (geometry, once per plan): verified portal graph, wall-hugging orthogonal raceways
in buffered room interiors, ±8 cm doorway offsets for dead-end rooms, APSP D (metres) /
B (90° bends) between devices + candidate panel wall spots.
Tier 2 (combinatorics, fast): K_min clusters via BFS region-growing (contiguity guarded),
per-cluster 2-opt TSP on D, Loop-First/Panel-Snap panel placement.

## 5. Module Map + Status (2026-10-16, after fix round)

| Module | File | Status |
|---|---|---|
| M1 | module1_portal_and_calibration.py | DONE (superseded by M2's calibration; diagnostics only) |
| M2 | module2_wall_router_and_matrix.py | DONE (opposite-side door test, door-width calibration, unroutable_rooms report) |
| M2v | verify_module2.py | DONE (wall erosion 0.02 m, expanded building envelope) |
| M3 | module3_joint_optimizer.py | DONE: find_partition enforces 100 m2 cap per cluster (component pre-split included); fewest-panels-then-least-cable selection; cost-aware splits (MAX_SPLIT_COST_EVALS=160 cap) with stub-aware cluster cost; baseline last-resort attach only if contiguous+within cap else own panel |
| M4 | module4_validator_and_blueprint.py | DONE: always exits 0 (verdict is data); validator unchanged |
| runner | run_pipeline.py | unchanged; batch works, 25/25 complete |

All fixes COMMITTED and PUSHED (see git log). Batch outputs (JSON) committed.

## 6. Verified Open Bugs — ALL RESOLVED (2026-10-16)

1. ~~M3 capacity check missing on component pre-split~~ FIXED: find_partition
   validates `sum(areas) <= 100` per cluster; oversized single components get
   a relaxed-split fallback in grow_partition or `capacity_relaxed=True`.
2. ~~M4 `raise SystemExit(1)`~~ FIXED: always exits 0; baseline benchmark no
   longer skipped.
3. ~~Baseline last-resort attach~~ FIXED: attach only if contiguous AND within
   cap, else the room gets its own panel (3467 and 2373 baselines now valid).
4. ~~Stale outputs~~ FIXED: full batch re-run x2; all 50 final_*.json current.

No known open bugs in the pipeline.

## 7. Results (final batch run 2026-10-16, log: batch_run_step5.log)

- 25/25 plans completed end-to-end; **optimized valid 25/25, baseline valid 25/25**.
- Optimized cable <= baseline on ALL 25 plans: mean 5.24%, max 16.1% (7607).
  Best: 4625 +14.8%, 2373 +14.2%, 5616 +13.9%; 14433: 36.9 -> 33.9 m.
- M3 runtime <= 0.13 s/plan (worst: 2373). M2 dominates runtime.
- History: old M2/M3 was 16/20 completed, 15/16 optimized valid, mean 6.1%
  on 14 comparable plans. Gains since: capacity fix (3467), exit-code fix,
  baseline contiguity/capacity fix (10808, 2373), cost-aware split selection
  (3467 optimized 44.0 -> 33.5 m, now beats baseline; 2373 34.4 -> 30.6 m).
- Sealed-room design decision: rooms with no verified portal (`unroutable_rooms`)
  are excluded from eligible and reported separately, not failed. RATIONALE:
  dataset gives no physical opening -> unwirable by ANY solution. CAVEAT: soft
  interpretation of PS4 rule 1 — must be disclosed in final deck/README.

## 8. Environment (this machine)

- Windows, PowerShell, Python 3.11.9 at `python`.
- Installed: shapely, networkx, matplotlib, numpy 1.26.4, opencv-python, python-pptx, Pillow.
- Working dir: C:\Users\admin\Projects\HackHive\HackHive. Dataset via `common.py`.
- `*.png` outputs are gitignored; JSON outputs are committed.

## 9. Conventions

- CLI args `--plan-id`, `--out`; JSON outputs with explicit `status`; never claim validity
  without the M4 validator. Verify after every build step, then commit.
- All M2/M3/M4 edits from 2026-10-16 14:17-14:44 are COMMITTED (see git log) — this file
  was updated and committed together with them.

## 10. Current Next Step

1. Core pipeline is DONE and green (25/25 valid both modes). Do NOT touch M2/M3
   core logic without re-running the batch.
2. Stretch (optional): bend-weighted TSP cost, 100+ plan stats, final deck polish
   (PPT in repo root — team name/members still placeholder).
3. Documentation website (docs/ static site for GitHub Pages): NOT started —
   awaiting explicit user approval. Build only after go-ahead.
