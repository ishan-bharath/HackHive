"""Shared fixtures: synthetic rectilinear plans + full-pipeline runner."""

import pytest

from hackhive_ps4.synthetic import make_row_plan, run_full


@pytest.fixture(scope="session")
def two_room_plan():
    return make_row_plan(2, seed=0)


@pytest.fixture(scope="session")
def two_room_artifacts(two_room_plan):
    """Full pipeline artifacts for the 2-room synthetic plan."""
    return run_full(two_room_plan)
