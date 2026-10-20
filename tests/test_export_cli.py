"""Exporter CLI test: exports from a temp working directory."""

import json

from hackhive_ps4 import export as export_mod


def test_cli_export_and_skip_message(two_room_artifacts, tmp_path, monkeypatch,
                                     capsys):
    report, fo, _ = two_room_artifacts
    monkeypatch.chdir(tmp_path)
    pid = str(fo["solution"]["plan_id"])
    with open(f"final_optimized_{pid}.json", "w", encoding="utf-8") as f:
        json.dump(fo, f)
    with open(f"matrix_{pid}.json", "w", encoding="utf-8") as f:
        json.dump(report, f)

    monkeypatch.setattr(__import__("sys"), "argv",
                        ["export_submission.py", "--plan-id", pid])
    export_mod.main()
    out = capsys.readouterr().out
    assert "[verified]" in out
    sub = json.loads((tmp_path / f"submissions/{pid}.json").read_text(
        encoding="utf-8"))
    assert sub["units"] == "m"


def test_cli_skips_invalid_final(two_room_artifacts, tmp_path, monkeypatch,
                                 capsys):
    report, fo, _ = two_room_artifacts
    monkeypatch.chdir(tmp_path)
    pid = str(fo["solution"]["plan_id"])
    bad = dict(fo)
    bad["validation"] = {"all_valid": False, "violations": ["boom"]}
    with open(f"final_optimized_{pid}.json", "w", encoding="utf-8") as f:
        json.dump(bad, f)
    with open(f"matrix_{pid}.json", "w", encoding="utf-8") as f:
        json.dump(report, f)
    monkeypatch.setattr(__import__("sys"), "argv",
                        ["export_submission.py", "--plan-id", pid])
    export_mod.main()
    assert "validation FAILED" in capsys.readouterr().out
