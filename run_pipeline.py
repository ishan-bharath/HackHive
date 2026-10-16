"""Pipeline runner: module 2 -> module 3 -> module 4 for one plan, then a
baseline-vs-optimized benchmark table.

Usage:
  python run_pipeline.py --plan-id 14433
  python run_pipeline.py --plan-id all --limit 25   # batch smoke test
"""

import argparse
import json
import subprocess
import sys
import time


def run(cmd):
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-12:])
    print(tail)
    if result.returncode != 0:
        print(f"FAILED (exit {result.returncode}): {' '.join(cmd)}")
        return False
    return True


def benchmark(plan_id):
    rows = []
    for mode in ("baseline", "optimized"):
        try:
            with open(f"final_{mode}_{plan_id}.json", encoding="utf-8") as f:
                final = json.load(f)
            sol = final["solution"]
            val = final["validation"]
            rows.append({
                "mode": mode,
                "panels": sol["metrics"]["panel_count"],
                "cable_m": sol["metrics"]["total_cable_length_m"],
                "bends": sol["metrics"]["total_bends"],
                "valid": val["all_valid"],
                "violations": len(val["violations"]),
                "runtime_s": sol["metrics"].get("runtime_s"),
            })
        except FileNotFoundError:
            rows.append({"mode": mode, "error": "missing output"})
    return rows


def print_benchmark(plan_id, rows):
    print(f"\nBENCHMARK - plan {plan_id}")
    print(f"{'mode':<11} {'panels':>6} {'cable_m':>9} {'bends':>6} "
          f"{'valid':>6} {'runtime_s':>10}")
    for r in rows:
        if "error" in r:
            print(f"{r['mode']:<11} ERROR: {r['error']}")
            continue
        print(f"{r['mode']:<11} {r['panels']:>6} {r['cable_m']:>9} "
              f"{r['bends']:>6} {str(r['valid']):>6} {r['runtime_s']:>10}")
    ok = [r for r in rows if r.get("mode") == "optimized" and r.get("valid")]
    base = [r for r in rows if r.get("mode") == "baseline" and r.get("valid")]
    if ok and base and ok[0]["cable_m"] and base[0]["cable_m"]:
        gain = (1 - ok[0]["cable_m"] / base[0]["cable_m"]) * 100
        print(f"  optimized cable vs baseline: {gain:+.1f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-id", default="14433")
    ap.add_argument("--limit", type=int, default=None,
                    help="when --plan-id all: cap number of plans")
    ap.add_argument("--skip-module1", action="store_true")
    args = ap.parse_args()

    plan_ids = (
        __import__("common").plan_ids(args.limit)
        if args.plan_id == "all" else [args.plan_id]
    )

    failures = []
    for pid in plan_ids:
        print(f"\n{'='*60}\nPLAN {pid}\n{'='*60}")
        ok = True
        ok &= run([sys.executable, "module2_wall_router_and_matrix.py",
                   "--plan-id", pid])
        if ok:
            ok &= run([sys.executable, "module3_joint_optimizer.py",
                       "--plan-id", pid])
        if ok:
            ok &= run([sys.executable, "module4_validator_and_blueprint.py",
                       "--plan-id", pid, "--mode", "optimized"])
        if ok:
            ok &= run([sys.executable, "module4_validator_and_blueprint.py",
                       "--plan-id", pid, "--mode", "baseline"])
        if ok:
            print_benchmark(pid, benchmark(pid))
        else:
            failures.append(pid)

    if len(plan_ids) > 1:
        print(f"\nBATCH SUMMARY: {len(plan_ids) - len(failures)}/{len(plan_ids)} "
              f"plans completed; failures: {failures or 'none'}")


if __name__ == "__main__":
    main()
