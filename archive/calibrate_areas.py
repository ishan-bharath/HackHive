import pickle
from pathlib import Path
from statistics import median

BASE = Path(
    r"C:\Users\Amogh\.cache\kagglehub\datasets\resplan\resplan\versions\12"
)

ELIGIBLE_TYPES = {"living", "bedroom", "kitchen", "storage"}


def main():
    with open(BASE / "ResPlan.pkl", "rb") as f:
        dataset = pickle.load(f)

    results = []
    rejected = 0

    for plan in dataset[:500]:
        inner = plan.get("inner")
        total_area = float(plan.get("area") or 0)

        if (
            inner is None
            or inner.is_empty
            or not inner.is_valid
            or inner.area <= 0
            or not 20 <= total_area <= 1000
        ):
            rejected += 1
            continue

        rooms = [
            attrs["geometry"]
            for _, attrs in plan["graph"].nodes(data=True)
            if attrs.get("type") in ELIGIBLE_TYPES
            and attrs.get("geometry") is not None
            and not attrs["geometry"].is_empty
            and attrs["geometry"].is_valid
        ]

        if not rooms:
            rejected += 1
            continue

        scale = total_area / inner.area

        eligible_area = sum(
            room.area * scale for room in rooms
        )

        results.append({
            "id": plan.get("id"),
            "total_area": total_area,
            "scale": scale,
            "eligible_area": eligible_area,
            "room_count": len(rooms),
        })

    if not results:
        print("No valid plans found.")
        return

    print(f"Plans tested: {min(500, len(dataset))}")
    print(f"Accepted: {len(results)}")
    print(f"Rejected: {rejected}")
    print(
        "Median estimated eligible-room area:",
        f"{median(r['eligible_area'] for r in results):.2f} m²"
    )

    print("\nFirst 10 accepted plans:")

    for r in results[:10]:
        print(
            f"ID={r['id']} | "
            f"total={r['total_area']:.2f} m² | "
            f"scale={r['scale']:.6f} | "
            f"eligible={r['eligible_area']:.2f} m² | "
            f"rooms={r['room_count']}"
        )


if __name__ == "__main__":
    main()
