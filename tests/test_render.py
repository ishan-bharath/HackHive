"""Render smoke tests: all three renderers produce PNG bytes."""

from hackhive_ps4.render import render, render_blueprint, render_solution


def test_blueprint_renders(two_room_plan, two_room_artifacts):
    import io

    report, fo, fb = two_room_artifacts
    scale = fo["scale_m_per_raw"]
    buf = io.BytesIO()
    render_blueprint(two_room_plan, fo["solution"], fo["validation"], scale,
                     "unused.png", out=buf)
    assert buf.getvalue()[:8] == b"\x89PNG\r\n\x1a\n"


def test_solution_quicklook_renders(two_room_plan, two_room_artifacts, tmp_path):
    _, fo, _ = two_room_artifacts
    out = tmp_path / "sol.png"
    render_solution(two_room_plan, fo["solution"], str(out))
    assert out.stat().st_size > 1000


def test_module2_routes_renders(two_room_plan, tmp_path):
    out = tmp_path / "m2.png"
    render(two_room_plan, {}, [], {}, {}, [], str(out))
    assert out.stat().st_size > 1000


def test_failed_validation_drawn_in_red(two_room_plan, two_room_artifacts):
    """The blueprint renders even when validation fails (violations overlay)."""
    import io

    import copy
    _, fo, _ = two_room_artifacts
    bad = copy.deepcopy(fo)
    bad["validation"] = dict(bad["validation"])
    bad["validation"]["all_valid"] = False
    bad["validation"]["violations"] = ["panel 0 area 999 m^2 exceeds 100 m^2"]
    buf = io.BytesIO()
    render_blueprint(two_room_plan, bad["solution"], bad["validation"],
                     fo["scale_m_per_raw"], "unused.png", out=buf)
    assert buf.getvalue()[:8] == b"\x89PNG\r\n\x1a\n"
