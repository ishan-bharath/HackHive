"""Judge-facing demo web app for HackHive PS4.

Runs the full pipeline IN-PROCESS for any ResPlan plan:
  module2 (verified portals + wall-hugging raceways + D/B matrices)
  -> module3 (contiguous partition + 2-opt closed loops + panel snap)
  -> module4 (independent validator + CAD blueprint PNG).

Two input modes on one page:
  - Upload a plan JSON (judge mode; no dataset needed), or
  - Enter a plan ID (demo mode; requires dataset/ResPlan.pkl).

Usage:
  python app.py                 # http://127.0.0.1:8000, auto-opens browser
  python app.py --host 0.0.0.0  # judges on the same WiFi can open the LAN URL
  python app.py --port 8080 --no-browser

Utility (needs dataset): python app.py --dump <plan_id> <out.json>
  writes a JSON-serialized plan dict that upload mode accepts.
"""

import argparse
import base64
import io
import json
import socket
import threading
import time
import uuid
import webbrowser

from flask import Flask, Response, render_template_string, request

from . import data
from . import optimize as m3
from . import validate as m4
from .data import json_to_plan, plan_to_jsonable
from .matrices import build_report
from .render import render_blueprint

app = Flask(__name__)

# Completed results keyed by token, so the JSON can be downloaded after render.
RESULTS: dict[str, str] = {}

REQUIRED_PLAN_KEYS = ("id", "graph", "inner", "wall", "door")




# ------------------------------------------------------------------
# Pipeline in-process
# ------------------------------------------------------------------

def _png_b64(plan, solution, validation, scale):
    buf = io.BytesIO()
    render_blueprint(plan, solution, validation, scale, "unused.png", out=buf)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def run_pipeline(plan, plan_id):
    """Returns (context dict for the result template, final_optimized dict)."""
    t0 = time.time()
    report = build_report(plan, plan_id)
    scale = report["calibration"]["scale_m_per_raw"]

    base = m3.baseline_solution(plan, report, scale)
    opt = m3.optimized_solution(plan, report, scale)
    base_val = m4.validate(plan, base, scale)
    opt_val = m4.validate(plan, opt, scale)

    img_opt = _png_b64(plan, opt, opt_val, scale)
    img_base = _png_b64(plan, base, base_val, scale)

    final_opt = {
        "plan_id": str(plan_id),
        "mode": "optimized",
        "scale_m_per_raw": scale,
        "solution": opt,
        "validation": opt_val,
    }
    final_base = {
        "plan_id": str(plan_id),
        "mode": "baseline",
        "scale_m_per_raw": scale,
        "solution": base,
        "validation": base_val,
    }

    elapsed = round(time.time() - t0, 2)
    bm = {
        "base": _bench_row(base, base_val, elapsed),
        "opt": _bench_row(opt, opt_val, elapsed),
    }
    gain = None
    if bm["base"]["cable"] and bm["opt"]["cable"] and bm["base"]["cable"] > 0:
        gain = (1 - bm["opt"]["cable"] / bm["base"]["cable"]) * 100

    ctx = {
        "plan_id": str(plan_id),
        "valid": opt_val["all_valid"],
        "img_opt": img_opt,
        "img_base": img_base,
        "checks": opt_val["checks"],
        "violations": opt_val["violations"],
        "sealed_rooms": opt_val.get("dataset_sealed_rooms") or [],
        "bm": bm,
        "gain": gain,
        "physics": opt_val["physics"],
        "final_json": json.dumps(final_opt, indent=2),
        "final_base_json": json.dumps(final_base, indent=2),
        "elapsed_s": elapsed,
    }
    return ctx, final_opt


def _bench_row(solution, validation, elapsed):
    m = solution["metrics"]
    return {
        "panels": m["panel_count"],
        "devices": m["devices_total"],
        "cable": m["total_cable_length_m"],
        "bends": m["total_bends"],
        "runtime": round(elapsed, 2),
        "valid": validation["all_valid"],
    }


# ------------------------------------------------------------------
# Templates
# ------------------------------------------------------------------

STYLE = """
body { font-family: 'Segoe UI', Arial, sans-serif; margin: 0; background: #F4F6F8; color: #1C2833; }
.wrap { max-width: 1100px; margin: 0 auto; padding: 24px 16px 60px; }
header.hero { background: #1B2631; color: #ECF0F1; padding: 26px 16px; }
header.hero .wrap { padding-bottom: 0; }
h1 { margin: 0 0 6px; font-size: 24px; }
.sub { color: #AEB6BF; margin: 0; font-size: 14px; }
.card { background: #FFFFFF; border: 1px solid #D5DBDB; border-radius: 8px; padding: 18px 20px; margin: 18px 0; }
h2 { font-size: 18px; margin-top: 0; }
.note { color: #5D6D7E; font-size: 13px; }
input[type=file], input[type=text] { margin-right: 8px; }
button, .btn { background: #1E8449; border: none; color: #fff; padding: 9px 18px; border-radius: 5px; font-size: 14px; cursor: pointer; text-decoration: none; display: inline-block; }
button:disabled { background: #95A5A6; cursor: wait; }
.banner { padding: 12px 16px; border-radius: 6px; font-weight: bold; font-size: 16px; margin: 14px 0; }
.pass { background: #D4EFDF; color: #145A32; border: 1px solid #1E8449; }
.fail { background: #FADBD8; color: #641E16; border: 1px solid #C0392B; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 14px; }
th, td { border: 1px solid #D5DBDB; padding: 7px 10px; text-align: left; }
th { background: #EAEDED; }
img.blueprint { width: 100%; height: auto; border: 1px solid #333; background: #fff; }
.check { font-weight: bold; }
.check.pass { color: #1E8449; }
.check.fail { color: #C0392B; }
ul.violations { color: #C0392B; }
details { margin: 10px 0; }
pre { background: #1B2631; color: #D5DBDB; padding: 14px; border-radius: 6px; overflow-x: auto; font-size: 12px; max-height: 480px; }
.small { font-size: 12px; color: #5D6D7E; }
"""

FORM_PAGE = """
<!doctype html><html><head><meta charset="utf-8">
<title>HackHive PS4 - Panel Placement &amp; Cable Routing Demo</title>
<style>{{ style }}</style></head><body>
<header class="hero"><div class="wrap">
<h1>PS4 - Joint Optimization of Control-Panel Placement and Closed-Loop Cable Routing</h1>
<p class="sub">Upload a floor plan - the system places control panels, routes compliant
closed-loop fire-alarm cable through real doorways, and independently validates every constraint.</p>
</div></header>
<div class="wrap">
<div class="card">
<h2>Option A - Upload a plan (JSON)</h2>
<form action="/run" method="post" enctype="multipart/form-data"
      onsubmit="var b=this.querySelector('button'); b.disabled=true; b.textContent='Processing... (1-20 s)';">
  <input type="file" name="file" accept=".json,application/json" required>
  <button type="submit">Run pipeline</button>
</form>
<p class="note">One ResPlan plan dict per file. Sample plan files are provided - ask the presenter.</p>
</div>
<div class="card">
<h2>Option B - Plan ID from the local dataset</h2>
{% if dataset_available %}
<form action="/run" method="post"
      onsubmit="var b=this.querySelector('button'); b.disabled=true; b.textContent='Processing... (1-20 s)';">
  <input type="text" name="plan_id" placeholder="e.g. 14433" required>
  <button type="submit">Run pipeline</button>
</form>
<p class="note">Batch-tested plans: 14433, 3467, 2373, 7607, 5616, 4625, ...</p>
{% else %}
<p class="note">Dataset (dataset/ResPlan.pkl) is not present on this machine -
please use Option A. Upload mode needs no dataset.</p>
{% endif %}
</div>
<p class="note">Processing runs synchronously and typically takes 1-20 s per plan
(geometry precompute dominates). The button stays disabled until the result page loads.</p>
</div></body></html>
"""

RESULT_PAGE = """
<!doctype html><html><head><meta charset="utf-8">
<title>Plan {{ plan_id }} - PS4 result</title>
<style>{{ style }}</style></head><body>
<header class="hero"><div class="wrap">
<h1>Plan {{ plan_id }} - PS4 solution blueprint</h1>
<p class="sub">Pipeline finished in {{ elapsed_s }} s (optimized + baseline + independent validation).</p>
</div></header>
<div class="wrap">
<div class="banner {{ 'pass' if valid else 'fail' }}">
  {{ 'VALIDATOR: PASS - all PS4 hard constraints satisfied' if valid else 'VALIDATOR: FAIL - see violations below' }}
</div>
{% if sealed_rooms %}
<p class="note">Dataset-sealed rooms excluded (no verified portal, unwirable by any solution):
{{ sealed_rooms | join(', ') }}</p>
{% endif %}

<div class="card">
<h2>Optimized blueprint</h2>
<img class="blueprint" src="data:image/png;base64,{{ img_opt }}" alt="optimized blueprint">
<p class="note">Legend: node badges N# = visiting order (matches the submission JSON); H# = hub (ring start/end);
arrow = loop direction; orange X = unavoidable doorway pinch point.</p>
</div>

<div class="card">
<h2>Baseline comparison</h2>
<details>
  <summary>Show baseline comparison</summary>
  <img class="blueprint" src="data:image/png;base64,{{ img_base }}" alt="baseline blueprint">
  <p class="note">Baseline = naive panel-first placement + nearest-neighbour loops on
  straight-line distances.</p>
</details>
</div>

<div class="card">
<h2>Validation checklist (optimized)</h2>
<table>
  <tr><th>Constraint</th><th>Result</th></tr>
  {% for name, ok in checks.items() %}
  <tr><td>{{ name }}</td><td class="check {{ 'pass' if ok else 'fail' }}">{{ 'PASS' if ok else 'FAIL' }}</td></tr>
  {% endfor %}
</table>
{% if violations %}
<ul class="violations">
  {% for v in violations %}<li>{{ v }}</li>{% endfor %}
</ul>
{% endif %}
</div>

<div class="card">
<h2>Metrics - baseline vs optimized</h2>
<table>
  <tr><th>Metric</th><th>Baseline</th><th>Optimized</th></tr>
  <tr><td>Panels</td><td>{{ bm.base.panels }}</td><td>{{ bm.opt.panels }}</td></tr>
  <tr><td>Devices</td><td>{{ bm.base.devices }}</td><td>{{ bm.opt.devices }}</td></tr>
  <tr><td>Cable (m)</td><td>{{ bm.base.cable }}</td><td>{{ bm.opt.cable }}</td></tr>
  <tr><td>Bends</td><td>{{ bm.base.bends }}</td><td>{{ bm.opt.bends }}</td></tr>
  <tr><td>Valid</td><td class="check {{ 'pass' if bm.base.valid else 'fail' }}">{{ bm.base.valid }}</td>
      <td class="check {{ 'pass' if bm.opt.valid else 'fail' }}">{{ bm.opt.valid }}</td></tr>
  {% if gain is not none %}
  <tr><td>Cable saving (optimized vs baseline)</td>
      <td colspan="2" class="check pass">+{{ '%.1f' | format(gain) }}% less cable with the optimizer</td></tr>
  {% endif %}
</table>
</div>

<div class="card">
<h2>Honeywell physics (optimized)</h2>
<p><b>NFPA 72 Class X pinch points:</b> {{ physics['nfpa72_classX_pinch_points'] | length }}
{% for pp in physics['nfpa72_classX_pinch_points'] %}
  <span class="small">- panel {{ pp.panel + 1 }}, rooms {{ pp.room_pair | join(' <-> ') }},
  {{ pp.uses }} crossings ({{ pp.type }})</span>
{% else %}<span class="small">none</span>{% endfor %}</p>
<p><b>NEC bend flags:</b> {{ physics['nec_bend_violations'] | length }}
{% for f in physics['nec_bend_violations'] %}
  <span class="small">- panel {{ f.panel + 1 }}: max {{ f.max_bends_between_pulls }} bends between pull points</span>
{% else %}<span class="small">none</span>{% endfor %}</p>
<p><b>24 V loop voltage drop (18 AWG):</b> worst {{ worst_drop_v }} V across
{{ n_panels }} panel(s) - limit 3 V -
<span class="check {{ 'pass' if all_within else 'fail' }}">{{ 'PASS' if all_within else 'FAIL' }}</span></p>
{% if not all_within %}
<table>
  <tr><th>Panel</th><th>Loop length (m)</th><th>Resistance (ohm)</th><th>Current (A)</th>
      <th>Drop (V)</th><th>Within 3 V limit</th></tr>
  {% for v in physics['voltage_drop_24v'] %}
  <tr {% if not v.within_limit %}style="background:#FADBD8"{% endif %}>
      <td>{{ v.panel + 1 }}</td><td>{{ v.loop_length_m }}</td><td>{{ v.loop_resistance_ohm }}</td>
      <td>{{ v.current_a }}</td><td>{{ v.voltage_drop_v }}</td>
      <td class="check {{ 'pass' if v.within_limit else 'fail' }}">{{ v.within_limit }}</td></tr>
  {% endfor %}
</table>
{% endif %}
</div>

<div class="card">
<h2>Result JSON (optimized)</h2>
<details>
  <summary>Show full JSON (solution + validation, same schema as final_optimized_*.json)</summary>
  <pre>{{ final_json }}</pre>
</details>
<a class="btn" href="/download/{{ token }}">Download JSON</a>
</div>

<p><a href="/">Run another plan</a></p>
</div></body></html>
"""

ERROR_PAGE = """
<!doctype html><html><head><meta charset="utf-8">
<title>Could not process plan</title>
<style>{{ style }}</style></head><body>
<header class="hero"><div class="wrap"><h1>Could not process this plan</h1></div></header>
<div class="wrap">
<div class="banner fail">{{ error }}</div>
<div class="card">
<p>{{ detail }}</p>
<p class="note">Hints:
<ul class="note">
<li>Upload mode expects ONE ResPlan plan dict (id, graph, inner, wall, door, ...) -
produce one with <code>python app.py --dump &lt;plan_id&gt; plan.json</code>.</li>
<li>Some dataset plans contain sealed rooms with no verified doorway; those are
reported and excluded rather than failed - but a plan with no eligible rooms at
all cannot be wired.</li>
</ul></p>
</div>
<p><a href="/">Back to the form</a></p>
</div></body></html>
"""


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@app.route("/")
def index():
    return render_template_string(
        FORM_PAGE, style=STYLE, dataset_available=data.dataset_available())


@app.route("/run", methods=["POST"])
def run():
    try:
        upload = request.files.get("file")
        if upload and upload.filename:
            try:
                payload = json.load(upload.stream)
            except Exception as exc:
                return _error_page(f"Could not parse uploaded JSON: {exc}",
                                   "The file must contain one plan dict as JSON.")
            try:
                plan = json_to_plan(payload)
            except ValueError as exc:
                return _error_page(str(exc),
                                   "Check the upload format and try again.")
            plan_id = str(plan.get("id", "upload"))
        else:
            plan_id = (request.form.get("plan_id") or "").strip()
            if not plan_id:
                return _error_page("No file uploaded and no plan ID given.",
                                   "Pick one of the two options on the form.")
            if not data.dataset_available():
                return _error_page(
                    "Dataset not available on this server.",
                    "dataset/ResPlan.pkl is missing - use the upload option.")
            try:
                plan = data.load_plan(plan_id)
            except Exception as exc:
                return _error_page(f"Plan {plan_id} not found: {exc}",
                                   "Double-check the plan ID and try again.")
        ctx, final_opt = run_pipeline(plan, plan_id)
        # Voltage-drop summary for the result page (full table only on FAIL).
        vd = ctx["physics"]["voltage_drop_24v"]
        ctx["worst_drop_v"] = max((v["voltage_drop_v"] for v in vd), default=0.0)
        ctx["all_within"] = all(v["within_limit"] for v in vd)
        ctx["n_panels"] = len(vd)
        token = uuid.uuid4().hex[:12]
        RESULTS[token] = json.dumps(final_opt, indent=2)
        return render_template_string(
            RESULT_PAGE, style=STYLE, token=token, **ctx)
    except Exception as exc:  # pipeline failure -> clean page, never a traceback
        return _error_page(
            f"Pipeline error: {exc}",
            "The plan may be unwirable or sealed (no verified doorways), or its "
            "geometry may be malformed. The batch-validated plans are known good.")


def _error_page(message, detail):
    return render_template_string(ERROR_PAGE, style=STYLE,
                                  error=message, detail=detail)


@app.route("/download/<token>")
def download(token):
    payload = RESULTS.get(token)
    if payload is None:
        return _error_page("Result expired or unknown token.",
                           "Run a plan again, then download from its result page.")
    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition":
                 f"attachment; filename=final_optimized_{token}.json"})


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser(description="PS4 demo web app")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--dump", nargs=2, metavar=("PLAN_ID", "OUT_JSON"),
                    help="write an uploadable JSON plan dict and exit")
    args = ap.parse_args()

    if args.dump:
        plan = data.load_plan(args.dump[0])
        with open(args.dump[1], "w", encoding="utf-8") as f:
            json.dump(plan_to_jsonable(plan), f)
        print(f"Dumped plan {args.dump[0]} -> {args.dump[1]}")
        return

    local_url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}"
    print(f"Serving on {local_url} (LAN: http://{lan_ip()}:{args.port})")
    if args.host == "0.0.0.0":
        print("Judges on the same WiFi can open the LAN URL above.")
    if not args.no_browser:
        threading.Timer(
            1.0, lambda: print(f"Browser auto-open: {webbrowser.open(local_url)}")
        ).start()
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
