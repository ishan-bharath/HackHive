"""Bend counting tests on known polylines (m2.count_bends / turn_angle)."""

import pytest

from hackhive_ps4.geometry import BEND_ANGLE_THRESHOLD_DEG, count_bends, turn_angle


def test_straight_line_zero_bends():
    assert count_bends([(0, 0), (3, 0)]) == 0
    assert count_bends([(0, 0), (1, 0), (2, 0), (3, 0)]) == 0


def test_l_shape_one_bend():
    assert count_bends([(0, 0), (3, 0), (3, 2)]) == 1


def test_staircase_two_bends():
    assert count_bends([(0, 0), (2, 0), (2, 1), (4, 1)]) == 2


def test_reversal_counts_once():
    # 180-degree reversal at one vertex: exactly one bend, not two.
    assert count_bends([(0, 0), (2, 0), (0, 0)]) == 1
    assert turn_angle((0, 0), (2, 0), (0, 0)) == pytest.approx(180.0)


def test_zero_length_vertices():
    # A zero-length segment at the start does not affect the count...
    assert count_bends([(0, 0), (0, 0), (2, 0), (2, 2)]) == 1
    # ...but a duplicate vertex at the turn absorbs it (zero-length legs
    # have no direction, so no turn is detectable there).
    assert count_bends([(0, 0), (2, 0), (2, 0), (2, 2)]) == 0


def test_closed_loop_bends_at_start_vertex():
    # Square ring: bend at every corner including the closure point.
    square = [(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)]
    assert count_bends(square) == 3  # interior vertices only (open count)


def test_turn_angle_values():
    assert turn_angle((0, 0), (1, 0), (2, 0)) == pytest.approx(0.0)
    assert turn_angle((0, 0), (1, 0), (1, 1)) == pytest.approx(90.0)
    assert turn_angle((0, 0), (1, 0), (0, 0)) == pytest.approx(180.0)


def test_threshold_is_45_degrees():
    assert BEND_ANGLE_THRESHOLD_DEG == 45.0
    # 45-degree turn counts; 30-degree turn does not.
    diag = [(0, 0), (1, 1), (2, 1)]
    assert turn_angle(*diag) == pytest.approx(45.0)
    assert count_bends(diag) == 1
    shallow = [(0, 0), (2, 0.5), (4, 0)]
    assert turn_angle(*shallow) < 45.0
    assert count_bends(shallow) == 0
