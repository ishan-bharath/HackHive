"""CI smoke run: pipeline on 3 synthetic plans + axis-alignment gate.

Runs entirely in-process (no dataset needed), mirroring what the real
pipeline does on dataset plans. Exits non-zero on any failure.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hackhive_ps4.data import plan_to_jsonable  # noqa: E402
from hackhive_ps4.export import export, verify  # noqa: E402
from hackhive_ps4.synthetic import make_row_plan, run_full  # noqa: E402

PLANS = [(2, 0), (3, 1), (4, 2)]

failures = []
for n_rooms, seed in PLANS:
    plan = make_row_plan(n_rooms, seed=seed)
    pid = str(plan["id"])
    report, fo, fb = run_full(plan)
    for name, final in (("optimized", fo), ("baseline", fb)):
        if not final["validation"]["all_valid"]:
            failures.append(f"{pid} [{name}]: {final['validation']['violations']}")
        for panel in final["solution"]["panels"]:
            loop = panel["loop_coords"]
            for a, b in zip(loop[:-1], loop[1:]):
                if abs(a[0] - b[0]) > 1e-6 and abs(a[1] - b[1]) > 1e-6:
                    failures.append(f"{pid} [{name}]: diagonal segment {a}->{b}")
    sub = export(pid, fo, report)
    try:
        verify(sub)
    except AssertionError as exc:
        failures.append(f"{pid}: submission verification failed: {exc}")
    # round-trip through the upload JSON format must behave identically
    from hackhive_ps4.data import json_to_plan

    revived = json_to_plan(json.loads(json.dumps(plan_to_jsonable(plan))))
    report2, fo2, _ = run_full(revived)
    if (fo2["solution"]["metrics"]["total_cable_length_m"]
            != fo["solution"]["metrics"]["total_cable_length_m"]):
        failures.append(f"{pid}: upload round trip changed the result")
    print(f"smoke {pid}: hubs={fo['solution']['metrics']['panel_count']} "
          f"cable={fo['solution']['metrics']['total_cable_length_m']} m "
          f"J-inputs OK")

if failures:
    print("\nSMOKE FAILED:")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print(f"\nSMOKE PASSED: {len(PLANS)} plans valid, axis-aligned, exported, round-trip OK")
