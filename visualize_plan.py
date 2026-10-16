import pickle
import sys
import matplotlib.pyplot as plt

DATASET_PATH = (
    r"C:\Users\Amogh\.cache\kagglehub\datasets"
    r"\resplan\resplan\versions\12\ResPlan.pkl"
)

sys.path.append(
    r"C:\Users\Amogh\.cache\kagglehub\datasets"
    r"\resplan\resplan\versions\12"
)

from resplan_utils import plot_plan, normalize_keys

with open(DATASET_PATH, "rb") as f:
    dataset = pickle.load(f)

if isinstance(dataset, dict):
    plans = list(dataset.values())
else:
    plans = list(dataset)

plan = next(
    p for p in plans
    if str(p.get("id", p.get("plan_id", ""))) == "14433"
)

normalize_keys(plan)
plot_plan(plan, title="ResPlan 14433 — Geometry Inspection")
plt.show()