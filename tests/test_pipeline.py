"""Pipeline runner unit tests (benchmark table + failure aggregation)."""

import json

import pytest

from hackhive_ps4 import pipeline


@pytest.fixture()
def fake_outputs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for mode in ("optimized", "baseline"):
        with open(f"final_{mode}_synth.json", "w", encoding="utf-8") as f:
            json.dump({
                "solution": {"metrics": {"panel_count": 1,
                                         "total_cable_length_m": 12.5,
                                         "total_bends": 3,
                                         "runtime_s": 0.01}},
                "validation": {"all_valid": True, "violations": []},
            }, f)
    return tmp_path


def test_benchmark_reads_outputs(fake_outputs, capsys):
    rows = pipeline.benchmark("synth")
    assert rows[0]["mode"] == "baseline"
    assert rows[0]["valid"] is True
    assert rows[1]["cable_m"] == 12.5
    pipeline.print_benchmark("synth", rows)
    out = capsys.readouterr().out
    assert "BENCHMARK - plan synth" in out
    assert "+0.0%" in out or "+" in out


def test_benchmark_missing_outputs(fake_outputs, capsys):
    rows = pipeline.benchmark("nope")
    assert rows[0].get("error") == "missing output"
    pipeline.print_benchmark("nope", rows)
    assert "ERROR: missing output" in capsys.readouterr().out


def test_main_aggregates_failures(fake_outputs, monkeypatch, capsys):
    """A plan id the dataset does not know -> recorded as failure, exit 0."""
    monkeypatch.setattr(__import__("sys"), "argv",
                        ["run_pipeline.py", "--plan-id", "no_such_plan"])
    pipeline.main()
    out = capsys.readouterr().out
    assert "FAILURES" in out or "failures" in out.lower()
    assert "no_such_plan" in out


def test_cable_gain_highlighted(fake_outputs, capsys):
    rows = pipeline.benchmark("synth")
    rows[0]["cable_m"] = 25.0  # baseline worse than optimized 12.5
    pipeline.print_benchmark("synth", rows)
    assert "+50.0%" in capsys.readouterr().out
