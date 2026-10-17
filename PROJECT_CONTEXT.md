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

## 2. Hard Constraints (OFFICIAL, from docs/"Cable Ring Challenge - Problem Statement4.pptx")

1. One fixed NODE in EVERY eligible room: living, bedroom, kitchen, storage.
2. Each hub serves max 100 m^2 eligible area AND max 5 nodes (both at once);
   hubs needed >= max(ceil(area/100), ceil(nodes/5)).
3. Every eligible room + node assigned to exactly ONE hub; hub's rooms form one
   connected zone through doors/open passages only.
4. Ring: H -> N1 -> ... -> Nn -> same H. Closed, non-branching, each node once.
   Retracing a door is allowed; shared line length counts as overlap (O).
5. Free space: cable axis-aligned (horizontal/vertical only), inside inner
   boundary, outside walls/windows, between rooms only through door/open-passage
   gaps.
6. Hub point: inside an eligible room it serves, >= 0.5 m from walls.
7. Scale (slide 4): scale_units_per_m = sqrt(inner.area / plan["area"]);
   net_area NEVER used (0 in 32% of plans).
8. Ranking: fewest hubs first, then J = L + 5X + O + 0.5B (slide 6/7, 1 mm
   tolerance). Tie-break: smaller assigned-area gap between hubs.

## 3. Dataset Facts (ResPlan)

- `archive.zip` (gitignored) → extracted to `dataset/` (gitignored): ResPlan.pkl (~286MB, ~17k plans).
- Plan dict: `id`, `graph`, `inner`, `wall`, `door`, `window`, `frontdoor`, room layers, metadata.
- TRAP: do NOT trust `fallback` edges or blind `adjacency`; `via_window` edges are unverified.
- TRAP: raw coordinates are NOT metres. OFFICIAL scale (slide 4):
  `scale = sqrt(inner.area / plan["area"])` units per metre; door-width median
  is kept only as a printed sanity cross-check; net_area never used.

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
| M4 | module4_validator_and_blueprint.py | DONE: always exits 0; official checks hub_clearance + axis_aligned; blueprint shows H#/N# badges + red violations |
| runner | run_pipeline.py | unchanged; batch works |
| export | export_submission.py | DONE: organisers' slide-8 schema -> submissions/<id>.json, parse-back verified; skips 1448 with evidence note |
| cost | compute_cost.py | DONE: official J = L + 5X + O + 0.5B from polylines -> submissions/cost_summary.json |
| gate | check_axis_aligned.py | DONE: 0 diagonal segments across all final/matrix JSONs |

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

## 7. Tier 1 COMPLIANCE RESULTS (2026-10-17, post-official-rules)

Compliance commit `0ee8978` (axis-aligned L-routing, official scale, 5-node
cap, 0.5 m hub clearance + validator checks `hub_clearance`/`axis_aligned`).

- **Axis gate** (`check_axis_aligned.py`): 0 diagonal segments across 50 final
  JSONs (25 optimized + 25 baseline) + 25 matrices. THE ORIGINAL DQ BUG IS GONE.
- **Batch**: 24/25 plans valid in BOTH modes. Plan 1448 is OFFICIALLY
  UNSOLVABLE, not a bug: under the mandated scale its room living_0 = 107.26
  m^2 > 100 m^2 hub cap, and rule 1 forbids splitting a room across hubs.
  This is a FEATURE: the validator correctly identifies out-of-benchmark
  plans (organisers guarantee "no room over 100 m^2" in benchmark plans,
  slide 2). final_* artifacts kept as evidence; exporter/cost skip it with
  the same one-line reason.
- Old vs new (unofficial-scale diagonal routes -> compliant L-routes):
  14433 cable 33.9 -> 38.8 m, bends 8 -> 25; routes are staircase-shaped -
  correct per rule 5, longer by construction.
- **Official cost J** (`compute_cost.py` over 24 submissions, 1 mm tol):
  mean 93.8, median 92.7, min 64.8 (3796), max 124.0 (2372); total
  L = 795.8 m, X = 191, O = 164.8 m, B = 670. Full per-plan table:
  submissions/cost_summary.json.
- **O == 0 at doors VERIFIED**: across all 137 portals, 0 overlap stretches
  lie on a portal centreline and 0 pin pairs coincide (min pin separation
  0.1599 m = the designed 2x8 cm). Door retraces are parallel runs on
  DIFFERENT lines -> O = 0 per slide 7. The counted O (and X) comes from
  DIFFERENT legs sharing the same wall-raceway corridors away from doors -
  legitimate per the metric, and the top optimisation target for Tier 2
  (ring-wide edge-disjoint routing instead of independent per-leg Dijkstra).
- X provenance verified (`debug_x.py`): crossing points are genuine
  perpendicular meetings of different legs away from nodes/hubs, deduped
  within 1 mm.

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

1. Tier 1 (official-rules compliance) is DONE: axis-aligned routing, official
   scale, 5-node cap, hub clearance, exporter, cost metric, gates green.
2. Tier 2 target (biggest J lever): routes are valid but different legs share
   the same wall-raceway corridors -> O = 164.8 m and X = 191 over 24 plans.
   Ring-wide routing (edge-disjoint single cycle per hub, spur-free) or
   J-aware TSP costs (penalise reused edges) would cut J substantially.
   This touches M3 routing logic - plan carefully, keep the axis gate green.
3. Portfolio polish: docs site (awaiting approval), final deck, J table in
   deck from submissions/cost_summary.json.
