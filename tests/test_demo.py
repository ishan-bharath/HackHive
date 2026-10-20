"""Demo UI tests via the Flask test client (no dataset needed)."""

import io
import json

from hackhive_ps4 import demo
from hackhive_ps4.data import plan_to_jsonable
from hackhive_ps4.synthetic import make_row_plan


def make_client():
    demo.app.config["TESTING"] = True
    return demo.app.test_client()


def test_form_page_renders_without_dataset(monkeypatch):
    monkeypatch.setattr(demo.data, "dataset_available", lambda: False)
    r = make_client().get("/")
    assert r.status_code == 200
    assert b"Upload a floor plan" in r.data
    assert b"not present on this machine" in r.data


def test_plan_id_mode_rejected_without_dataset(monkeypatch):
    monkeypatch.setattr(demo.data, "dataset_available", lambda: False)
    r = make_client().post("/run", data={"plan_id": "14433"})
    assert r.status_code == 200
    assert b"Dataset not available" in r.data


def test_garbage_upload_friendly_error():
    r = make_client().post(
        "/run", data={"file": (io.BytesIO(b"this is { not json ]"), "bad.json")},
        content_type="multipart/form-data")
    assert r.status_code == 200
    assert b"Could not parse uploaded JSON" in r.data


def test_missing_keys_friendly_error():
    r = make_client().post(
        "/run", data={"file": (io.BytesIO(b'{"foo": 1}'), "empty.json")},
        content_type="multipart/form-data")
    assert r.status_code == 200
    assert b"missing required key" in r.data


def test_no_input_friendly_error():
    r = make_client().post("/run", data={})
    assert r.status_code == 200
    assert b"No file uploaded and no plan ID given" in r.data


def test_upload_mode_full_pipeline():
    plan_json = json.dumps(plan_to_jsonable(make_row_plan(2, seed=0)))
    r = make_client().post(
        "/run", data={"file": (io.BytesIO(plan_json.encode()), "plan.json")},
        content_type="multipart/form-data")
    assert r.status_code == 200
    html = r.data.decode("utf-8", "replace")
    assert "VALIDATOR: PASS" in html
    assert "data:image/png;base64," in html
    assert "Download JSON" in html
    assert "/download/" in html


def test_download_endpoint_round_trip():
    plan_json = json.dumps(plan_to_jsonable(make_row_plan(2, seed=0)))
    client = make_client()
    r = client.post(
        "/run", data={"file": (io.BytesIO(plan_json.encode()), "plan.json")},
        content_type="multipart/form-data")
    html = r.data.decode("utf-8", "replace")
    token = html.split('href="/download/')[1].split('"')[0]
    d = client.get(f"/download/{token}")
    assert d.status_code == 200
    payload = json.loads(d.data)
    # demo download serves the final-style JSON (solution + validation)
    assert payload["solution"]["metrics"]["panel_count"] >= 1
    assert payload["validation"]["all_valid"] is True


def test_download_unknown_token():
    r = make_client().get("/download/deadbeef")
    assert r.status_code == 200
    assert b"expired or unknown" in r.data


def test_lan_ip_returns_string():
    assert isinstance(demo.lan_ip(), str)
    assert len(demo.lan_ip()) >= 7
