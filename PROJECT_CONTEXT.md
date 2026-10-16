# PROJECT_CONTEXT.md — Shared Memory for Any Model/Agent

Read this file FIRST before doing anything. It is the single source of truth for
project state. Update it after every milestone (what changed, what works, what's next).
Keep it under ~200 lines so it never blows a context window.

## 1. Project Identity

- **Hackathon:** Honeywell HackHive (48h) — DEADLINE: under 15 hours remaining as of 2026-10-16.
- **Problem statement:** PS4 — Joint Optimization of Control-Panel Placement and Closed-Loop Cable Routing.
- **Repo:** https://github.com/ishan-bharath/HackHive (branch: main).
- **Goal:** system that, for any ResPlan floor plan, jointly decides panel count/positions,
  room->panel assignment, and closed-loop cable routes, then validates + visualizes + exports JSON.
- **Tone of PS4 rules:** topological constraints, geometric scoring. Physical validity is mandatory:
  cables may cross rooms ONLY through real doors/open passages; never cross walls/windows/exterior.

## 2. Hard Constraints (from PS4)

1. One device in EVERY eligible room: living room, bedroom, kitchen, storage room.
2. Each panel serves max 20 devices AND max 100 m^2 of eligible-room area.
3. Every eligible room assigned to exactly ONE panel.
4. Rooms of a panel form a CONTIGUOUS territory (connected via valid indoor passages).
5. One closed, non-branching loop per panel: Panel -> D1 -> D2 -> ... -> DN -> Panel,
   every device visited exactly once.
6. Routes stay inside building; cross between rooms only through verified portals.
7. Deliverables: visual overlay (CAD blueprint style) + matching JSON + benchmark vs baseline.

## 3. Dataset Facts (ResPlan)

- `archive.zip` in repo root contains: ResPlan.pkl (~286MB, ~17,000 plans),
  resplan_utils.py, split.json, README.md. EXTRACTED to: `dataset/` folder (gitignored).
- Plan structure: dict with keys `id`, `graph` (networkx-like), `inner` (interior polygon),
  `wall`, `door`, `window`, `frontdoor` (shapely geoms), room layers, metadata.
- `plan["graph"]`: nodes = rooms with attrs `type`, `geometry` (shapely), `net_area`;
  edges have `type` in {via_door, via_window, via_opening, adjacency, direct, fallback}.
- TRAP: do NOT trust `fallback` edges or blind `adjacency`; `via_window` promoted to `via_door`
  by dataset heuristics is unverified. Verify portals geometrically.
- TRAP: coordinate units are raw (NOT meters). Metadata areas inconsistent
  (5,458/17,000 plans have bad net_area). Calibration approach: scale so that door
  widths ~0.8-0.9 m. Scale factor explored ~median room areas -> ~98 m^2 median total eligible area.
- Key test plan: **14433** (5 eligible rooms: living_0, kitchen_0, bedroom_0/1/2, 11 nodes, 16 edges).

## 4. Agreed Architecture: Two-Tier "Precomputed Metric Closure"

Tier 1 (geometry, run once per plan):
- Verified portal graph: portals = intersections of buffered room polygons with door/opening geoms.
- Wall-hugging orthogonal raceways: `room.exterior.buffer(-clearance)` paths inside each room
  between portals and device point.
- Dead-end rooms (single door): cable passes through same doorway twice -> offset in/out
  paths by +/-8cm so loop stays a simple (non-self-intersecting) polygon.
- APSP matrices: D[i,j] = true indoor cable length, B[i,j] = 90-degree bend count,
  between all devices and candidate panel wall locations.

Tier 2 (combinatorics, fast on matrices):
- K_min = max(ceil(total_area/100), ceil(n_devices/20), n_connected_components).
- Partition room graph into K contiguous clusters (BFS region-growing + local swaps,
  contiguity guarded via networkx articulation points).
- Per cluster: TSP over D (2-opt/Or-opt) for the closed loop.
- "Loop-First, Panel-Snap": panel placed on interior wall alongside an edge of the optimal
  tour (preferring living-room/corridor entry walls) — near-zero marginal cable.

## 5. Honeywell Differentiators (NFPA/NEC framing)

- Loops = NFPA 72 Class A/Class X SLC. Class X survivability: penalize reusing the same
  doorway for out+return when an alternate door exists; flag unavoidable single-door
  double-passes as "pinch points".
- Conduit pull tension: T_out = T_in * exp(mu * theta); NEC: max 360 deg (4x90 bends) between
  pull boxes. Cost = w1*Length_m + w2*Bends_90 + w3*PullBoxes.
- 24V DC loop voltage drop: 18 AWG ~0.021 ohm/m, verify worst-case single-fault loop resistance.

## 6. Module Map + Status (UPDATE THIS AS YOU GO)

| Module | File | Status |
|---|---|---|
| M1 | module1_portal_and_calibration.py | DONE (portal graph, candidate passages, calibration report) |
| M2 | module2_wall_router_and_matrix.py | DONE + VERIFIED on plan 14433 (see notes) |
| M2v | verify_module2.py | DONE — checks all APSP paths: 0 wall crossings, 0 window hits, inside building |
| M3 | module3_joint_optimizer.py | DONE + run on 14433: baseline 37.5m/2 panels vs optimized 33.1m/2 panels (12% better), all loops routed |
| M4 | module4_validator_and_blueprint.py | NOT STARTED |
| runner | run_pipeline.py | NOT STARTED |

M3 verified facts (plan 14433):
- D-matrix weights are METRES (scale applied at graph build in M2). Matrix JSON keys: paths["i_j"], source_order entries are ['dev'|'cand_N', room_id].
- Candidate id gotcha: src[0] is 'cand_0'/'cand_1'/... -> use startswith('cand'), never == 'cand'.
- Contiguity: transit (non-eligible) rooms may be traversed; OTHER panels' eligible rooms may not (cluster_connected_strict(cluster, room_graph, eligible)).
- Plan 14433 eligible graph is a STAR around living_0: the only valid 2-partition is {living,kitchen,bed_0,bed_2} + {bed_1}. find_partition tries k=k_min..1, falls back with capacity_violation_m2 flagged per panel.
- Baseline: panel at candidate nearest cluster centroid, NN tour on Euclidean device distances.
- Optimized: BFS region-growing split (accept as soon as both sides contiguous + within caps) + 2-opt TSP on D + Loop-First/Panel-Snap panel insertion.
- OUTPUT: solution_{baseline,optimized}_14433.json/png. Loop coords are true routed polylines.

M2 verified facts (plan 14433):
- Calibration scale = sqrt(reported_area/inner_area) = 0.0512 m/raw-unit; door cross-check median 0.951 m (plausible). wall_depth raw = 4.5 (=0.23 m).
- KEY INSIGHT: room polygons do NOT share boundary lines (separated by wall thickness) and DO overlap wall bands (~0.12 m). Door association must be by PROXIMITY (<0.3 m to both rooms). Open passages = wall-free spans of room-polygon line intersection (living-kitchen has a 3.0 m opening, no door leaf).
- Graph: 248 nodes, 5412 edges, 1 component; 45 APSP sources (5 devices + 40 panel candidates).
- Matrix JSON: matrix_14433.json (D_m, B_bends, paths, source_order, node_pos).
- Bend counting: turns >= 45 deg on the length-optimal path (bends not optimized yet).

Legacy scripts (diagnostics/prototypes, keep for reference, don't extend):
cable_router.py, obstacle_router.py, passage_constrained_router.py, portal_route_planner.py
(prototype router; known issue: paths can leave room interior), portal_cable_router.py,
plus inspect_*/audit_*/visualize_*/diagnose_* diagnostics.

## 7. Environment (this machine)

- Windows, PowerShell, Python 3.11.9 at `python`.
- Installed: shapely, networkx, matplotlib, numpy 1.26.4, opencv-python.
- Working dir: C:\Users\admin\Projects\HackHive\HackHive
- Dataset path: read via `common.py` -> `DATASET_DIR / "ResPlan.pkl"` (see common.py).
  NO hardcoded per-user paths anywhere.

## 8. Conventions

- Every module: CLI args `--plan-id`, `--out` where sensible; JSON outputs with explicit
  `status` fields; never claim validity without the M4 validator.
- Verify after every build step (run it, check JSON/plot, then commit).
- Git: commit after each milestone; user pushes to GitHub.

## 9. Current Next Step

(Update always) -> Build module3_joint_optimizer.py: K_min clusters (contiguous partition
of the room-portal graph), per-cluster TSP loops over D (2-opt), panel-snap; baseline mode
first. Then module4 validator.
