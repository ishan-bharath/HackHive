"""Data layer tests: plan <-> JSON round trip."""

import json

from hackhive_ps4.data import json_to_plan, plan_to_jsonable
from hackhive_ps4.synthetic import make_row_plan, run_full


def test_round_trip_preserves_pipeline_behavior():
    plan = make_row_plan(2, seed=0)
    report, fo, _ = run_full(plan)
    revived = json_to_plan(json.loads(json.dumps(plan_to_jsonable(plan))))
    report2, fo2, _ = run_full(revived)
    assert report2["calibration"]["scale_m_per_raw"] == \
        report["calibration"]["scale_m_per_raw"]
    assert (fo2["solution"]["metrics"]["total_cable_length_m"]
            == fo["solution"]["metrics"]["total_cable_length_m"])
    assert fo2["validation"]["all_valid"] is True


def test_jsonable_form_is_plain_json():
    blob = json.dumps(plan_to_jsonable(make_row_plan(3, seed=1)))
    data = json.loads(blob)
    assert set(data) >= {"id", "graph", "inner", "wall", "door"}
    assert set(data["graph"]) == {"nodes", "edges"}


def test_json_to_plan_rejects_missing_keys():
    import pytest
    with pytest.raises(ValueError, match="missing required key"):
        json_to_plan({"id": "x", "graph": {}, "inner": None, "wall": None,
                      "door": None})


def test_json_to_plan_rejects_non_object():
    import pytest
    with pytest.raises(ValueError, match="single object"):
        json_to_plan([1, 2, 3])
