"""Axis-alignment gate (official PS4 rule 5: cable runs only horizontally or
vertically).

Asserts that EVERY polyline segment in the given files is axis-aligned:
abs(dx) < 1e-6 OR abs(dy) < 1e-6, in raw drawing units (the official 1 mm
tolerance is far coarser than this; 1e-6 catches any true diagonal).

Checks:
  final_*.json      - every panel's loop_coords
  matrix_*.json     - every per-pair path polyline in report["paths"]

Usage:
  python check_axis_aligned.py                     # all final_*.json
  python check_axis_aligned.py file1.json file2..  # explicit files
  python check_axis_aligned.py --include-matrices  # + all matrix_*.json

Exit code 0 when every checked file passes, 1 otherwise.
"""

import glob
import json
import sys

TOL = 1e-6


def segments(polyline):
    for a, b in zip(polyline[:-1], polyline[1:]):
        yield a, b


def diagonal_count(polyline):
    return sum(
        1 for a, b in segments(polyline)
        if abs(a[0] - b[0]) >= TOL and abs(a[1] - b[1]) >= TOL
    )


def check_final(data):
    """Returns (segments_checked, diagonals, examples)."""
    checked = diags = 0
    examples = []
    for panel in data.get("solution", {}).get("panels", []):
        loop = panel.get("loop_coords") or []
        d = diagonal_count(loop)
        checked += max(0, len(loop) - 1)
        diags += d
        if d and len(examples) < 3:
            examples.append(f"panel {panel.get('panel_room')}")
    return checked, diags, examples


def check_matrix(data):
    """Matrix reports: every path polyline in report['paths']."""
    checked = diags = 0
    examples = []
    for key, path in (data.get("paths") or {}).items():
        d = diagonal_count(path)
        checked += max(0, len(path) - 1)
        diags += d
        if d and len(examples) < 3:
            examples.append(f"path {key}")
    return checked, diags, examples


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    include_matrices = "--include-matrices" in sys.argv
    if args:
        files = args
    else:
        files = sorted(glob.glob("final_*.json"))
        if include_matrices:
            files += sorted(glob.glob("matrix_*.json"))
    if not files:
        print("no files to check")
        return 1

    total_bad = 0
    for fn in files:
        with open(fn, encoding="utf-8") as f:
            data = json.load(f)
        if "solution" in data:
            checked, diags, examples = check_final(data)
        else:
            checked, diags, examples = check_matrix(data)
        status = "PASS" if diags == 0 else "FAIL"
        total_bad += diags
        extra = f" | diagonal examples: {examples}" if examples else ""
        print(f"{status}  {fn}: {checked} segments, {diags} diagonal{extra}")

    print(f"\n{'GATE PASSED' if total_bad == 0 else 'GATE FAILED'}: "
          f"{total_bad} diagonal segment(s) across {len(files)} file(s)")
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
