# Postmortem: how we got disqualified, and what we did about it

**Project:** Honeywell HackHive Hackathon 2026, problem statement PS4 — joint
optimization of control-panel ("hub") placement and closed-loop fire-alarm cable
routing on [ResPlan](https://www.kaggle.com/datasets/resplan/resplan) residential
floor plans (17,000 of them).
**Format:** 48 hours. Our first commit landed at 11:45 on 16 Oct 2026; the deadline
was the afternoon of 17 Oct 2026.
**Outcome:** disqualified after the second check-in. Then rebuilt, properly, after
the deadline — which is what this repository now contains.

This document is the honest version. No excuses, no fake modesty.

---

## 1. What the organisers asked

PS4 sounds simple and is not. For any ResPlan plan you must decide:

1. how many fire-alarm control panels ("hubs") to place, and where each one goes;
2. which rooms and nodes each hub serves;
3. the order in which each hub's nodes are visited;
4. the physical cable route of every ring.

The hard rules (their slides, which we now keep verbatim in
[`docs/`](Cable%20Ring%20Challenge%20-%20Problem%20Statement4.pptx)):

- one fixed node in **every** eligible room (living, bedroom, kitchen, storage);
  every room + node assigned to exactly one hub, never split;
- each hub serves **≤ 100 m²** of eligible area **and** **≤ 5 nodes** — both limits
  at once;
- each hub's rooms form one contiguous zone, connected through **doors and open
  passages only** — windows and wall-only adjacency don't count;
- one **closed, non-branching ring** per hub (`H → N1 → … → Nn → H`), each node
  exactly once; retracing a door to reach a single-door room is allowed, and shared
  line length counts as overlap;
- cable runs **only horizontally or vertically**, never through walls or windows,
  between rooms only through door/open-passage gaps;
- the hub point sits inside a room it serves, **≥ 0.5 m from walls**;
- raw ResPlan coordinates are drawing units, not metres — convert with the mandated
  scale `sqrt(inner.area / plan["area"])`; `net_area` is never used (it is 0 in 32%
  of plans).

Ranking: **fewest hubs first**, then lowest cost **J = L + 5X + O + 0.5B** — cable
length at 1/m, crossings at 5 each, same-line overlap at 1/m, 90° bends at 0.5
each, 1 mm tolerance, computed by the checker **from the submitted polylines**.
Deliverables per plan: a visual overlay (zones, hub/node IDs, visiting order, rings,
violations in red) and a JSON in their exact schema.

## 2. What we built in 48 hours (and were proud of)

We committed our first working checkpoint at 11:45 on day two and by the deadline
had a working end-to-end system:

- **Tier 1 — expensive geometry, computed once per plan.** Geometrically verified
  portals (ResPlan's adjacency graph has `fallback` edges and `via_window` edges
  that are not trustworthy — we only accepted passages we could verify in the wall
  geometry), a wall-hugging raceway graph inside buffered room interiors, and
  all-pairs shortest-path matrices: **D** in true metres and **B** in 90° bend
  counts between every device and candidate panel spot.
- **Tier 2 — fast combinatorics.** Capacity-feasible contiguous partitioning by
  region-growing, ring sequencing, and hub placement ("Loop-First / Panel-Snap").
- An **independent validator** (M4) that re-derives geometry from the raw plan and
  re-checks the rules, a **CAD-style blueprint renderer** with visitation-order
  badges and a full legend, and a **Flask demo UI** that judges could drive from a
  browser with no setup.

By our own validator, the 25-plan batch ran **25/25 valid** in both baseline and
optimized modes, with a mean cable gain of 5.24% for the optimizer over the
baseline. We committed after every verified step — the git log from those two days
is dense and honest (`6ec7211` → `7f180cf`).

We were proud of the portal verification, the D/B matrix idea (routing becomes
table lookup), and the demo. All of that survived. It was also all irrelevant to
the next section.

## 3. The disqualification: exactly what broke

After the second check-in we were disqualified. The reason: **our routes were not
axis-aligned**. The router treated "a segment between two visible points" as a
legal edge — the old `segment_valid` checked containment and wall-crossing but
nothing about direction — so whenever a cable could save distance by going
diagonally, it went diagonally. Cables ran straight across rooms. It is visible in
every blueprint from that era.

Once we sat down with the slides and audited ourselves, the diagonal routing was
one of **four spec deviations**:

| # | Rule said | We did |
|---|---|---|
| 1 | Cable only horizontal/vertical | Straight-line graph edges; Dijkstra happily took diagonals across rooms |
| 2 | Scale = `sqrt(inner.area / plan["area"])` (slide 4) | Calibrated units-per-metre from a nominal 0.85 m door width (`NOMINAL_DOOR_WIDTH_M` in our old `common.py`) — we thought it was better engineering. It wasn't the mandated formula |
| 3 | ≤ 5 nodes per hub | `PANEL_DEVICE_CAP = 20` |
| 4 | Hub ≥ 0.5 m from walls | Panel candidates sat on the raceway ring inset only 0.15 m from walls (`WALL_CLEARANCE_M = 0.15`) |

And the painful meta-failure underneath all four:

> **Our own validator never caught any of it — because it re-derived geometry from
> the same assumptions the router used. We validated our interpretation of the
> spec instead of validating against the spec.**

The validator was genuinely independent in code (separate module, re-derives
geometry) but not independent in *assumptions*. It measured clearance against our
0.15 m constant, counted nodes against our 20-node cap, and — like the router —
never checked direction. Every check passed because every check compared the
output to the input's assumptions. A validator that shares the builder's world
model is a mirror, not a check.

## 4. The compliant rebuild

Same afternoon, after the DQ notice. Commits `0ee8978` → `3fc8bce` (nine commits,
all on 17 Oct 2026):

- **Orthogonal L-shaped routing**: every inter-point connection is now an
  H-then-V or V-then-H staircase, with inserted bend vertices. The raceway graph
  itself was rebuilt axis-aligned so shortest paths are correct *per metre and per
  bend*, not per Euclidean distance.
- **The mandated scale formula** replaced the door-width calibration. This
  immediately exposed something our old calibration had masked: plan **1448**'s
  living room measures **107.26 m² under the official scale** — above the 100 m²
  hub cap, and rule 1 forbids splitting a room across hubs. Plan 1448 is
  **officially unsolvable by construction**; the organisers' own slide 2 says
  benchmark plans are pre-filtered to have no room over 100 m². Our validator now
  correctly *refuses* the plan with that exact reason instead of faking validity,
  and the exporter/scorer skip it with the same one-line evidence note. The final
  artifacts are kept in the repo as evidence.
- **5-node hub cap** and **0.6 m hub-candidate inset** (with a fallback chain down
  to just above the official 0.5 m minimum), plus two new validator checks —
  `hub_clearance` (against the official 0.5 m, not our inset) and `axis_aligned`
  (0-diagonal gate).
- **A standalone axis gate** ([`check_axis_aligned.py`](../check_axis_aligned.py))
  over every output file: **0 diagonal segments across 75 files** (50 final JSONs +
  25 matrices). The original DQ bug is mechanically dead.
- **The official scorer** ([`compute_cost.py`](../compute_cost.py)): J = L + 5X +
  O + 0.5B recomputed from polylines at 1 mm tolerance, matching slide 6/7, with
  the crossing provenance and overlap behaviour verified across all **137 portals**
  of the batch.

Honest cost of compliance: plan 14433's ring went from 33.9 m of (illegal, shorter)
diagonal-rich cable to 38.8 m of legal staircase, bends 8 → 25. That is what rule
5 buys you: correctness, by construction, longer.

Result: **24/25 plans valid in both modes** (1448 being the officially-unsolvable
exception), 24 verified submissions in the organisers' slide-8 schema
([`submissions/`](../submissions/)), mean official J = 93.8 over the batch.

## 5. Beyond spec: the rebuild that was actually fun

With the deadline gone, we kept going — first for the plot, then because the
findings were real.

**Exact ring sequencing — and the length-vs-cost trap.** With ≤ 5 nodes per hub a
ring has ≤ 5! = 120 visiting orders, so exact TSP by exhaustive permutation is
cheap and provably length-optimal. We shipped it. It made official J **worse on 7
of 24 plans** (e.g. 7607: 91 → 115; worst case 14926: +29.1). Why: *length-optimality
is not cost-optimality*. A shorter ring can cross itself more, and X costs 5 each;
our exact-order tie-break was blind to O and X. The measured `ΔL` between exact and
2-opt orders was 0.000 everywhere — 2-opt was already length-optimal on all 24 —
so the exact order was buying nothing and costing crossings.

The fix is the part we like most: **dual-candidate ring selection**. For each hub
we generate *both* candidate orders (exact-L and 2-opt), build both rings' actual
geometry, evaluate the **official J** on each candidate's real polylines, and keep
the better one. Result: 6 plans improved, 18 unchanged, none worse; total
ΔJ = −53.3 across the batch (e.g. 13342: 121.2 → 102.7). Mean J over the 24
submissions: **93.8 → 91.5**, with crossings down (X: 191 → 183) and same-line
overlap down (O: 164.8 → 158.9 m) while total length stayed 795.8 m. Commit
`3c6910e`.

**Engineering hygiene.** Package restructure into `hackhive_ps4/` with 12 focused
modules and thin CLI wrappers (`e712abd`), a **76-test suite at 79% coverage**
(synthetic rectilinear plans, bend counting, validator break-cases that *fail the
validator on purpose*, scoring metric, golden-file export, an axis-alignment
property test), `ruff` + `mypy` clean, and a CI workflow (lint, types, tests, and a
3-plan synthetic smoke run with the axis gate) — commits `3006491`–`f156ad7`.

**The 500-plan benchmark** (`a19a7c9`): multiprocessing run over 500 ResPlan plans
— **500/500 pipeline completion, 474/500 valid** (the 26 invalid are the
officially-unsolvable class — largest room over 100 m² under the mandated scale —
plus sealed rooms the dataset gives no doorway for), mean official-J gain
**+10.8%** over baseline, 307.5 s wall time, full per-plan data in
[`benchmark/results.csv`](../benchmark/results.csv).

**The single-door trick.** A single-door room forces the ring to enter and leave
through the same doorway. A true retrace runs out and back **on the same line**,
and same-line overlap costs 1/m. But the organisers' own slides draw the sanctioned
alternative: **two parallel runs**. We offset the in/out runs at the doorway by
**±8 cm** — parallel lines, which slide 7 explicitly counts as zero overlap. Legal
and cheaper; verified across all 137 portals of the batch (zero overlap stretches
on portal centrelines, minimum pin separation 0.1599 m — exactly the designed
2 × 8 cm). Diagram: [DESIGN.md §8](DESIGN.md#8-the-parallel-offset-retrace-trick).

## 6. Lessons learned

1. **Spec literalism is a feature, not a lack of creativity.** "We calibrate from
   door width, it's more robust" was engineering judgment applied where the spec
   said *use this formula*. The spec's formula is not a suggestion; it is the
   interface between your output and their checker. Same for 20 nodes vs 5, and
   0.15 m vs 0.5 m. Every one of those was a decision we made *for* the judges
   without asking them.
2. **Checker-first development.** Write the scorer from the official rules first,
   make it the acceptance test, and develop against it. We built a beautiful
   pipeline and scored it with our own metric until the last day. The official J
   disagrees with internal metrics in specific, predictable ways (5× crossings!),
   and knowing that *changes what you optimize*.
3. **Independent validation must be independent in assumptions, not just in code.**
   Our M4 was a separate module that re-derived geometry — and reproduced every
   wrong constant. The fix was mundane and effective: validator checks keyed to
   the *spec's* numbers (0.5 m, ≤ 5, the scale formula), plus an external axis
   gate that inspects the output files without knowing how they were made.
4. **Read the scoring function before optimizing anything.** The exact-TSP
   regression is the cleanest example of our whole hackathon in miniature: we
   optimized L because L was easy to reason about, while the ranked metric was J.
   A shorter ring that crosses itself loses. Optimize the function you are ranked
   on, on the geometry you actually emit.
5. **A disqualification is cheaper than a habit.** The diagonal-routing bug
   survived two check-ins because nothing in our loop could detect it. The axis
   gate now fails CI in seconds. Most of this repository's post-deadline value
   (tests, gates, benchmark, official scorer) exists to make the next silent
   assumption loud.

---

*Everything cited above is traceable: rules and metric to the organisers' pptx in
[`docs/`](Cable%20Ring%20Challenge%20-%20Problem%20Statement4.pptx), numbers to
[`PROJECT_CONTEXT.md`](../PROJECT_CONTEXT.md),
[`benchmark/summary.json`](../benchmark/summary.json),
[`submissions/cost_summary.json`](../submissions/cost_summary.json), and the git
log itself (`6ec7211`…`177fbe1`).*
