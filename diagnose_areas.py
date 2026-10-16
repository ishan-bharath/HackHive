import pickle
from pathlib import Path
from statistics import median

BASE = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan\resplan\versions\12"
)


def main():
    with open(BASE / "ResPlan.pkl", "rb") as f:
        dataset = pickle.load(f)

    areas = []
    invalid = 0

    for plan in dataset:
        area = float(plan.get("area") or 0)
        net_area = float(plan.get("net_area") or 0)

        if area <= 0 or net_area <= 0:
            invalid += 1
            continue

        areas.append((area, net_area, plan.get("id")))

    print(f"Total plans: {len(dataset)}")
    print(f"Plans with missing/nonpositive areas: {invalid}")
    print(f"Valid area records: {len(areas)}")

    for label, index in [("Total area", 0), ("Net area", 1)]:
        values = sorted(row[index] for row in areas)

        print(f"\n{label}:")
        print(f"  Minimum: {values[0]:.2f}")
        print(f"  Median:  {median(values):.2f}")
        print(f"  90th percentile: {values[int(0.90 * (len(values) - 1))]:.2f}")
        print(f"  99th percentile: {values[int(0.99 * (len(values) - 1))]:.2f}")
        print(f"  Maximum: {values[-1]:.2f}")

    print("\nPlans with net area above 300 m²:")
    large = [row for row in areas if row[1] > 300]
    print(f"Count: {len(large)}")

    for area, net_area, plan_id in sorted(
        large, key=lambda row: row[1], reverse=True
    )[:10]:
        print(
            f"ID={plan_id} | total={area:.2f} | net={net_area:.2f}"
        )


if __name__ == "__main__":
    main()