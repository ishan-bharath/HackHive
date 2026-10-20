"""Shared assertion helpers for the PS4 test suite."""


def all_segments(polyline):
    return list(zip(polyline[:-1], polyline[1:]))


def assert_axis_aligned(final, tol=1e-6):
    """Property: every polyline segment of every ring is H/V."""
    for panel in final["solution"]["panels"]:
        loop = panel["loop_coords"]
        for a, b in zip(loop[:-1], loop[1:]):
            assert abs(a[0] - b[0]) <= tol or abs(a[1] - b[1]) <= tol, \
                f"diagonal segment {a} -> {b}"
