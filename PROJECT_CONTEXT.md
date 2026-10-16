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

## 5. Module Map + Status (2026-10-16 15:00)

| Module | File | Status |
|---|---|---|
| M1 | module1_portal_and_calibration.py | DONE (superseded by M2's calibration; diagnostics only) |
| M2 | module2_wall_router_and_matrix.py | REWRITTEN (uncommitted): opposite-side door test `_door_opens_between`, portals from all touching room pairs (not just graph edges), door-width calibration, `unroutable_rooms` report |
| M2v | verify_module2.py | EDITED (uncommitted): wall erosion 0.02 m, expanded building envelope |
| M3 | module3_joint_optimizer.py | EDITED (uncommitted): find_partition tries k_min..k_min+4 ascending; consumes `unroutable_rooms`; **KNOWN BUG — see §6** |
| M4 | module4_validator_and_blueprint.py | EDITED (uncommitted): sealed rooms excluded from assignment check (module4:82); **KNOWN BUG — see §6** |
| runner | run_pipeline.py | unchanged; works but gated on M4 exit code |

SMOKE-TESTED after the abrupt agent stop: `python module3_joint_optimizer.py --plan-id
14433 --mode both` + M4 both modes → ALL CHECKS PASS (baseline 36.939 m, optimized
33.866 m, 1 panel, 5 devices).

## 6. Verified Open Bugs (priority order — FIX THESE FIRST)

1. **M3 capacity check missing on component pre-split.** When the eligible graph
   pre-splits into components (e.g. a sealed room), `grow_partition` returns components
   as-is WITHOUT checking the 100 m² cap per cluster. Evidence: plan 3467 optimized
   panel 0 = 123.73 m² (final_optimized_3467.json), `capacity_relaxed=False` yet invalid.
   FIX: validate `sum(areas) <= 100` for every cluster in find_partition before returning;
   if a component alone exceeds the cap, split it or mark capacity_relaxed=True.
2. **M4 `raise SystemExit(1)` on validation FAIL** (end of main()). run_pipeline gates
   M4-baseline on M4-optimized success (`ok &= run(...)`), so whenever optimized is
   invalid the baseline benchmark is silently SKIPPED (final_baseline_3467.json missing).
   FIX: always exit 0 — the verdict is data, not a crash; aggregate pass/fail in runner.
3. **Baseline policy:** last-resort attach ignores contiguity (plan 10808 "territory not
   contiguous") and capacity (plan 2373 baseline 107.36 m²). FIX: attach only if
   contiguous, else give the room its own panel.
4. **Stale outputs:** everything except 3467/13342/14433 was produced by PRE-rewrite M2/M3.
   After fixes 1-2: full batch re-run `python run_pipeline.py --plan-id all --limit 25`,
   then compare against the recorded 16/20 baseline and investigate regressions.

## 7. Results So Far (old M2/M3, 16 plans completed of 20 smoke-tested)

- Optimized valid 15/16, baseline 14/16 (old M4).
- Optimized cable < baseline in 14/14 comparable plans: mean 6.1%, max 16.1% (7607);
  14433: 36.9 → 33.9 m. M3 runtime ~0.02 s/plan.
- 13342 optimized now VALID with new M3. 3467 fails only on bug §6.1.
- Sealed-room design decision: rooms with no verified portal (`unroutable_rooms`) are
  excluded from eligible and reported separately, not failed. RATIONALE: dataset gives
  no physical opening → unwirable by ANY solution. CAVEAT: soft interpretation of PS4
  rule 1 — must be disclosed in final deck/README.

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

1. Fix §6.1 (capacity check in find_partition) + §6.2 (M4 exit code).
2. Batch re-run 20 plans; verify ≥ old 16/20, no regressions from new portal logic.
3. Fix §6.3 baseline policy.
4. Commit each step. Then stretch: bend-weighted TSP cost, 100+ plan stats,
   final deliverables polish (PPT in repo root: Cable Ring Challenge - Intermediate
   Update Template.pptx — team name/members still placeholder).
