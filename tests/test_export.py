"""Submission exporter tests: golden-file schema + parse-back verification."""

import copy
import json

import pytest

from hackhive_ps4.export import export, verify


def _load_golden():
    with open("tests/golden/two_room_submission.json", encoding="utf-8") as f:
        return json.load(f)


def _export_two_room(two_room_artifacts):
    fo = two_room_artifacts[1]
    report = two_room_artifacts[0]
    return export(str(fo["solution"]["plan_id"]), fo, report)


def test_matches_golden_file(two_room_artifacts):
    sub = _export_two_room(two_room_artifacts)
    golden = _load_golden()
    assert json.loads(json.dumps(sub, sort_keys=True)) == golden


def test_verify_accepts_golden():
    assert verify(_load_golden()) is True


def test_verify_rejects_open_sequence(two_room_artifacts):
    sub = copy.deepcopy(_load_golden())
    sub["hubs"][0]["closed_sequence"] = sub["hubs"][0]["closed_sequence"][:-1]
    with pytest.raises(AssertionError):
        verify(sub)


def test_verify_rejects_broken_leg_chain(two_room_artifacts):
    sub = copy.deepcopy(_load_golden())
    segs = sub["hubs"][0]["route_segments"]
    segs[0]["polyline"][-1] = [segs[0]["polyline"][-1][0] + 1.0,
                               segs[0]["polyline"][-1][1]]
    with pytest.raises(AssertionError):
        verify(sub)


def test_exported_ids_are_unique_and_ordered(two_room_artifacts):
    sub = _export_two_room(two_room_artifacts)
    labels = []
    for h in sub["hubs"]:
        labels.append(h["hub_id"])
        labels.extend(h["assigned_nodes"])
    assert labels == ["H1"] + [f"N{i}" for i in
                               range(1, len(labels))]
