"""Scale calibration tests (official formula: sqrt(inner.area / area))."""

import math

import pytest
from shapely.geometry import box

from hackhive_ps4.geometry import calibrate


def base_plan(inner, **extra):
    plan = {"id": "t", "inner": inner, "door": box(1, 1, 1.8, 1.2)}
    plan.update(extra)
    return plan


def test_scale_is_sqrt_inner_over_area():
    inner = box(0, 0, 8, 3)  # 24 units^2
    cal = calibrate(base_plan(inner, area=24.0))
    assert cal["scale_m_per_raw"] == pytest.approx(1.0)
    assert cal["units_per_m"] == pytest.approx(1.0)
    assert cal["method"] == "official_inner_area_ratio"

    cal = calibrate(base_plan(inner, area=96.0))
    assert cal["scale_m_per_raw"] == pytest.approx(2.0)
    assert cal["units_per_m"] == pytest.approx(0.5)

    cal = calibrate(base_plan(inner, area=6.0))
    assert cal["scale_m_per_raw"] == pytest.approx(0.5)
    assert cal["units_per_m"] == pytest.approx(2.0)
    assert math.isclose(cal["units_per_m"] * cal["scale_m_per_raw"], 1.0)


def test_net_area_is_never_used():
    inner = box(0, 0, 8, 3)
    with pytest.raises(ValueError):
        calibrate(base_plan(inner, net_area=24.0))


def test_missing_area_raises():
    inner = box(0, 0, 8, 3)
    with pytest.raises(ValueError, match="plan\\['area'\\]"):
        calibrate(base_plan(inner))


def test_nonpositive_area_raises():
    inner = box(0, 0, 8, 3)
    for bad in (0.0, -5.0):
        with pytest.raises(ValueError, match="> 0"):
            calibrate(base_plan(inner, area=bad))


def test_missing_inner_raises():
    with pytest.raises(ValueError, match="inner"):
        calibrate({"id": "t", "area": 24.0})


def test_door_width_reported_as_cross_check():
    inner = box(0, 0, 8, 3)
    # door 0.8 raw x 0.2 raw -> median door raw width 0.8
    plan = base_plan(inner, area=24.0)
    cal = calibrate(plan)
    assert cal["median_door_width_m"] == pytest.approx(0.8)
    assert cal["area_implied_door_width_m"] == pytest.approx(0.8)
    assert cal["area_door_width_plausible"] is True
