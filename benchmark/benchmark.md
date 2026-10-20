# PS4 pipeline benchmark

Plans: **500** | success rate: **100.0%** | wall time: 307.5 s (5 workers)

| metric | value |
|---|---|
| optimized valid | 474/500 |
| baseline valid | 474/500 |
| runtime median / mean / max | 2.55 / 2.94 / 13.36 s |
| official J gain (optimized vs baseline, 472 comparable) | mean 10.8%, median 10.35% |
| J wins / ties / losses | 390 / 13 / 69 (of the losses, 2 use FEWER hubs than the baseline - the official ranking puts hub count first, so those are correct-by-rule tradeoffs) |

## Hub-count histogram

| hubs | plans |
|---|---|
| 1 | 256 |
| 2 | 117 |
| 3 | 86 |
| 4 | 33 |
| 5 | 5 |
| 6 | 3 |

Per-plan data: `results.csv`. Chart: `docs/assets/benchmark_overview.png`.

## Known findings

- ~14% of same-hub-count plans show higher J for the optimizer: partitioning and boundary swaps minimize ring LENGTH, not the official J's within-ring overlap/crossing terms. This is the Tier-3 optimisation target (J-aware partition costs), not a validity problem - every counted ring passes all PS4 hard rules.
- Invalid plans are concentrated in plans whose largest room exceeds the 100 m^2 hub cap under the mandated scale (officially unsolvable, see PROJECT_CONTEXT 7b) and in plans with sealed rooms the dataset gives no doorway for.
- Errors (<1%) are recorded per plan in results.csv with their exception type; they do not stop the batch.
