import pickle
import csv
from pathlib import Path
from collections import Counter

DATASET_PATH = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan"
    r"\resplan\versions\12\ResPlan.pkl"
)

OUTPUT_FILE = "multi_plan_passage_audit.csv"

MAX_PLANS = 20

# Exploratory threshold in raw dataset units.
DISTANCE_THRESHOLD = 5.0


def components(geometry):
    if geometry is None or geometry.is_empty:
        return []

    if hasattr(geometry, "geoms"):
        return [g for g in geometry.geoms if not g.is_empty]

    return [geometry]


def main():
    print("Loading dataset...")

    with DATASET_PATH.open("rb") as f:
        plans = pickle.load(f)

    results = []
    summary = Counter()

    for plan in plans[:MAX_PLANS]:
        plan_id = plan.get("id", "unknown")
        graph = plan.get("graph")

        if graph is None:
            continue

        doors = components(plan.get("door"))

        for a, b, attrs in graph.edges(data=True):

            if attrs.get("type") != "via_door":
                continue

            geom_a = graph.nodes[a].get("geometry")
            geom_b = graph.nodes[b].get("geometry")

            if geom_a is None or geom_b is None:
                continue

            if geom_a.is_empty or geom_b.is_empty:
                continue

            shared_length = geom_a.boundary.intersection(
                geom_b.boundary
            ).length

            candidate_doors = []

            for index, door in enumerate(doors):
                da = door.distance(geom_a)
                db = door.distance(geom_b)

                if (
                    da <= DISTANCE_THRESHOLD
                    and db <= DISTANCE_THRESHOLD
                ):
                    candidate_doors.append(index)

            if len(candidate_doors) == 0:
                status = "NO_DOOR_CANDIDATE"
            elif len(candidate_doors) == 1:
                status = "ONE_DOOR_CANDIDATE"
            else:
                status = "MULTIPLE_DOOR_CANDIDATES"

            summary[status] += 1

            results.append({
                "plan_id": plan_id,
                "room_a": a,
                "room_b": b,
                "shared_boundary_raw_units": round(
                    shared_length, 4
                ),
                "candidate_door_count": len(candidate_doors),
                "candidate_door_indices": ",".join(
                    map(str, candidate_doors)
                ),
                "status": status,
            })

    if not results:
        print("No eligible graph edges found.")
        return

    with open(
        OUTPUT_FILE, "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=results[0].keys()
        )
        writer.writeheader()
        writer.writerows(results)

    print("\nMULTI-PLAN AUDIT")
    print("=" * 45)

    print("Plans inspected:", min(MAX_PLANS, len(plans)))
    print("Door-labelled edges:", len(results))

    for status, count in summary.items():
        percentage = count / len(results) * 100
        print(f"{status}: {count} ({percentage:.1f}%)")

    zero_shared = sum(
        row["shared_boundary_raw_units"] == 0
        for row in results
    )

    print(
        f"Edges with zero shared boundary: "
        f"{zero_shared}/{len(results)}"
    )

    print("\nSaved:", Path(OUTPUT_FILE).resolve())
    print("Physical passage validation: NOT PERFORMED")


if __name__ == "__main__":
    main()
