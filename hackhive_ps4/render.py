"""Blueprint and quick-look PNG renderers (former render functions of
module2/module3/module4, moved verbatim)."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from . import geometry as m2


def render_blueprint(plan, solution, validation, scale, out_png, out=None):
    """Render the CAD-style blueprint. Writes to `out` when given (file path
    or file-like object, e.g. BytesIO); otherwise to `out_png` exactly as
    before. Default behavior is unchanged."""
    rooms = m2.extract_rooms(plan)
    fig, ax = plt.subplots(figsize=(16, 12))
    fig.patch.set_facecolor("#FFFFFF")

    m2.draw_geom(ax, plan.get("inner"), "#FDFDFD", "#333333", 1.0, lw=1.0)
    for p in m2.parts(plan.get("wall")):
        xs, ys = p.exterior.xy
        ax.fill(xs, ys, facecolor="#2B2B2B", edgecolor="#111111", lw=0.4)

    palette = ["#C0392B", "#2471A3", "#1E8449", "#7D3C98", "#CA6F1E"]
    n_base = 0
    for k, panel in enumerate(solution["panels"]):
        color = palette[k % len(palette)]
        for rid in panel["assigned_rooms"]:
            m2.draw_geom(ax, rooms[rid]["geometry"], color, color, 0.10, lw=0.6)
        coords = panel["loop_coords"]
        if coords:
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            ax.plot(xs, ys, color=color, linewidth=2.2, zorder=5,
                    solid_joinstyle="round")
            # Direction arrow at the loop start (panel -> first device).
            if len(coords) >= 2:
                (x0, y0), (x1, y1) = coords[0], coords[1]
                t = 0.45
                ax.annotate("", xy=(x0 + (x1 - x0) * (t + 0.12),
                                    y0 + (y1 - y0) * (t + 0.12)),
                            xytext=(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t),
                            arrowprops=dict(arrowstyle="-|>", color=color,
                                            lw=2.0), zorder=6)
        if panel.get("panel_position"):
            px, py = panel["panel_position"]
            ax.plot(px, py, marker="*", markersize=260 / fig.dpi * 3,
                    markerfacecolor=color, markeredgecolor="#111111", zorder=7)
            ax.text(px, py, f"  H{k+1}", fontsize=10, fontweight="bold",
                    color="#111111", zorder=8)
        # Node ID badges: N1.. across the whole plan, numbered in visiting
        # order (hub by hub), matching export_submission.py's assigned_nodes.
        for j, rid in enumerate(panel.get("device_order") or []):
            nid = f"N{n_base + j + 1}"
            d = rooms[rid]["device_point"]
            ax.plot(d.x, d.y, marker="s", markersize=6, color=color,
                    markeredgecolor="#111111", zorder=6)
            ax.text(d.x, d.y, nid, fontsize=5.5, fontweight="bold",
                    ha="center", va="center", color="#111111", zorder=9,
                    bbox=dict(boxstyle="round,pad=0.22",
                              facecolor="#FFFFFF", edgecolor=color, lw=1.0))
        n_base += len(panel.get("device_order") or [])
        for rid in panel["assigned_rooms"]:
            if rid in (panel.get("device_order") or []):
                continue
            d = rooms[rid]["device_point"]
            ax.plot(d.x, d.y, marker="s", markersize=6, color=color,
                    markeredgecolor="#111111", zorder=6)

    for pp in validation["physics"]["nfpa72_classX_pinch_points"]:
        if pp["type"].startswith("unavoidable"):
            rid_a, rid_b = pp["room_pair"]
            for portal in m2.find_portals(plan, rooms, scale):
                if set(portal["rooms"]) == {rid_a, rid_b}:
                    cx, cy = portal["center"]
                    ax.plot(cx, cy, marker="X", markersize=9, color="#FF8C00",
                            zorder=8)

    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    # Failed validation: draw the violations in red on the image itself.
    if not validation["all_valid"] and validation["violations"]:
        lines = ["VIOLATIONS (design invalid):"]
        lines += [f"- {v}" for v in validation["violations"][:6]]
        if len(validation["violations"]) > 6:
            lines.append(f"- ... +{len(validation['violations']) - 6} more")
        ax.text(0.01, 0.99, "\n".join(lines), transform=ax.transAxes,
                fontsize=9, fontweight="bold", color="#C0392B",
                va="top", ha="left", zorder=10,
                bbox=dict(boxstyle="round,pad=0.4", facecolor="#FDEDEC",
                          edgecolor="#C0392B", lw=1.2, alpha=0.92))
    # Legend: symbols, route semantics, visiting order.
    handles = [
        Line2D([], [], marker="*", ls="none", markersize=13,
               markerfacecolor="#666666", markeredgecolor="#111111",
               label="Hub  H# (ring start/end)"),
        Line2D([], [], marker="s", ls="none", markersize=8,
               markerfacecolor="#666666", markeredgecolor="#111111",
               label="Node N# - visiting order, matches the submission JSON"),
        Line2D([], [], color="#666666", lw=2.2,
               label="Cable loop (closed, non-branching, through portals only)"),
        Line2D([], [], marker="X", ls="none", markersize=9, color="#FF8C00",
               label="Unavoidable doorway pinch point (NFPA 72 Class X)"),
    ]
    handles += [Patch(facecolor=c, alpha=0.35, edgecolor=c,
                      label=f"Hub {i+1} territory (rooms served)")
                for i, c in enumerate(palette[:len(solution["panels"])])]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.01),
              ncol=3, fontsize=8, framealpha=0.92, title="LEGEND",
              title_fontsize=9)
    metrics = solution["metrics"]
    title = (
        f"PS4 Solution Blueprint - plan {solution['plan_id']} ({solution['mode']})\n"
        f"hubs: {metrics['panel_count']} | cable: {metrics['total_cable_length_m']} m | "
        f"bends: {metrics['total_bends']} | "
        f"validator: {'PASS' if validation['all_valid'] else 'FAIL'}"
    )
    ax.set_title(title, fontsize=13)
    plt.tight_layout()
    target = out_png if out is None else out
    save_kwargs = dict(dpi=200, bbox_inches="tight", facecolor="#FFFFFF")
    if out is not None:
        save_kwargs["format"] = "png"
    plt.savefig(target, **save_kwargs)
    plt.close(fig)



def render_solution(plan, solution, out_png):
    fig, ax = plt.subplots(figsize=(14, 11))
    m2.draw_geom(ax, plan.get("inner"), "#FFFFFF", "#777777", 0.15)
    m2.draw_geom(ax, plan.get("wall"), "#555555", "#333333", 0.9)
    rooms = m2.extract_rooms(plan)
    palette = ["#E74C3C", "#2980B9", "#27AE60", "#8E44AD", "#F39C12"]
    for k, panel in enumerate(solution["panels"]):
        color = palette[k % len(palette)]
        for rid in panel["assigned_rooms"]:
            m2.draw_geom(ax, rooms[rid]["geometry"], color, color, 0.18)
        coords = panel["loop_coords"]
        if coords:
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            ax.plot(xs, ys, color=color, linewidth=2.0, zorder=5)
        if panel["panel_position"]:
            ax.plot(*panel["panel_position"], marker="*", markersize=18,
                    color=color, zorder=6)
        for rid in panel["assigned_rooms"]:
            d = rooms[rid]["device_point"]
            ax.plot(d.x, d.y, marker="s", markersize=7, color=color, zorder=6)
    ax.set_title(
        f"Module 3 ({solution['mode']}): {solution['metrics']['panel_count']} panels, "
        f"{solution['metrics']['total_cable_length_m']} m cable, "
        f"{solution['metrics']['total_bends']} bends"
    )
    ax.set_aspect("equal", adjustable="box")
    plt.tight_layout()
    plt.savefig(out_png, dpi=180, bbox_inches="tight")
    plt.close(fig)



def render(plan, rooms, portals, rooms_graph_data, global_graph, sample_routes, out_png):
    fig, ax = plt.subplots(figsize=(14, 11))
    m2.draw_geom(ax, plan.get("inner"), "#FFFFFF", "#777777", 0.15)
    m2.draw_geom(ax, plan.get("wall"), "#555555", "#333333", 0.9)
    for room in rooms.values():
        fc = "#A7CBE8" if room["eligible"] else "#DDDDDD"
        m2.draw_geom(ax, room["geometry"], fc, "#356A91", 0.35)

    for portal in portals:
        ax.plot(*portal["center"], marker="^", color="#E67E22", markersize=9)

    for rid, data in rooms_graph_data.items():
        inset = data["inset"]
        if inset is not None:
            xs, ys = inset.exterior.xy
            ax.plot(xs, ys, color="#999999", linewidth=0.6, alpha=0.7)

    styles = ["#D35400", "#8E44AD", "#16A085", "#C0392B", "#2980B9"]
    for k, (coords, label) in enumerate(sample_routes):
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        ax.plot(xs, ys, color=styles[k % len(styles)], linewidth=2.0, label=label)

    for room in rooms.values():
        if room["eligible"]:
            d = room["device_point"]
            ax.plot(d.x, d.y, marker="s", color="#244B70", markersize=7)

    ax.set_title("Module 2 - raceway graph, verified portals, sample routes")
    ax.set_aspect("equal", adjustable="box")
    ax.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(out_png, dpi=180, bbox_inches="tight")
    plt.close(fig)
