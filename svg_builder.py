"""Build interactive SVGs for a CassetteModel.

Three kinds of elements are rendered:
  - Module polygons (solid border, filled, with code + (u,v) label text)
  - Wagon connector rectangles (dotted border, semi-transparent, placed
    between consecutive modules in a train — branched for sideways trains)
  - Wingboard rectangles (longer blocks at the outer edge of E/G modules)
  - Engine circles (with motherboard metadata replacing engine info when
    a motherboard is present)

Hover tooltips are driven by transparent "hit" overlays + global JS
functions defined in main_test.py.
"""

from __future__ import annotations

import html
import json
import math

from dxf_model import CassetteModel, Module, Engine, Wingboard

PADDING_RATIO = 0.08
PASS_FILL = "#22c55e"
FAIL_FILL = "#ef4444"
SHAPE_STROKE = "#e2e8f0"
SHAPE_LABEL = {
    "hex_full": "Full hexagonal",
    "hex_partial": "Partial hexagonal",
    "tile": "Tile",
}


def _module_tooltip(m: Module, train_label: str) -> str:
    lines = [f"Code: {m.code}"]
    if m.uv is not None:
        lines.append(f"(u, v): ({m.uv[0]}, {m.uv[1]})")
    lines.append(f"Shape: {SHAPE_LABEL.get(m.shape, m.shape)}")
    lines.append(f"Train: {train_label}")
    if m.module_type:
        lines.append(f"Type: {m.module_type}")
    if m.i_rot is not None:
        lines.append(f"Rotation: {m.i_rot}")
    if m.trig_links is not None:
        lines.append(f"Trig links: {m.trig_links}")
    if m.daq_links is not None:
        lines.append(f"DAQ links: {m.daq_links}")
    if m.wingboard:
        lines.append(f"Wingboard: {m.wingboard}")
    if m.motherboard:
        lines.append(f"Motherboard: {m.motherboard}")
    r, g, b = m.color_rgb
    lines.append(f"Color: rgb({r}, {g}, {b})")
    return "\n".join(lines)


def _wagon_tooltip(m: Module, train_label: str) -> str:
    lines = [f"Wagon: {m.wagon_name}" if m.wagon_name else "Wagon"]
    lines.append(f"Module code: {m.code}")
    if m.uv is not None:
        lines.append(f"(u, v): ({m.uv[0]}, {m.uv[1]})")
    lines.append(f"Train: {train_label}")
    if m.module_type:
        lines.append(f"Type: {m.module_type}")
    if m.i_rot is not None:
        lines.append(f"Rotation: {m.i_rot}")
    if m.trig_links is not None:
        lines.append(f"Trig links: {m.trig_links}")
    if m.daq_links is not None:
        lines.append(f"DAQ links: {m.daq_links}")
    return "\n".join(lines)


def _engine_tooltip(e: Engine, train_label: str) -> str:
    if e.motherboard:
        lines = [f"Motherboard: {e.motherboard}"]
    else:
        lines = [f"Engine: {e.engine_type}" if e.engine_type else "Engine"]
    lines.append(f"Train: {train_label}")
    if e.engine_type:
        lines.append(f"Type: {e.engine_type}")
    r, g, b = e.color_rgb
    lines.append(f"Color: rgb({r}, {g}, {b})")
    cx, cy = e.center
    lines.append(f"Center: ({cx:.1f}, {cy:.1f})")
    lines.append(f"Radius: {e.radius:.1f}")
    return "\n".join(lines)


def _wingboard_tooltip(wb: Wingboard, train_label: str) -> str:
    lines = [f"Wingboard: {wb.wingboard_name}" if wb.wingboard_name else "Wingboard"]
    lines.append(f"Train: {train_label}")
    return "\n".join(lines)


def _compute_wagon_connectors(model: CassetteModel) -> list[dict]:
    """Compute wagon connector rectangles between consecutive modules.

    For each train with wagon modules, connectors link module 1->2, 2->3, etc.
    For sideways-arranged trains (where west and east modules diverge), the
    connector from module 1 branches to modules 2 and 3 instead of a linear
    chain.

    Returns a list of dicts: {from_mod, to_mod, rect_pts, centroid, train_id,
    wagon_name, from_code, to_code, from_uv, to_uv}
    """
    connectors = []
    for train in model.trains:
        if not train.is_real:
            continue
        train_mods = [m for m in model.modules if m.train_id == train.id]
        if len(train_mods) < 2:
            continue
        # Sort by module number
        train_mods.sort(key=lambda m: m.module_num)

        # Determine if this is a sideways train (has both W* and E* modules)
        west_mods = [m for m in train_mods if m.code.startswith("W")]
        east_mods = [m for m in train_mods if m.code.startswith("E")]
        sideways = bool(west_mods and east_mods)

        if sideways:
            # Branched: module 1 connects to 2 and 3
            # West side: W1->W2->W3 (linear)
            for mods_list in [west_mods, east_mods]:
                mods_list.sort(key=lambda m: m.module_num)
                for i in range(len(mods_list) - 1):
                    connectors.append(_make_connector(mods_list[i], mods_list[i + 1], train.id))
            # Also connect W1 to E1 (crossing the engine)
            if west_mods and east_mods:
                connectors.append(_make_connector(west_mods[0], east_mods[0], train.id))
        else:
            # Linear: 1->2->3->...
            for i in range(len(train_mods) - 1):
                connectors.append(_make_connector(train_mods[i], train_mods[i + 1], train.id))

    return connectors


def _make_connector(mod_from: Module, mod_to: Module, train_id: str) -> dict:
    """Create a wagon connector rectangle between two modules."""
    x1, y1 = mod_from.centroid
    x2, y2 = mod_to.centroid
    mx = (x1 + x2) / 2
    my = (y1 + y2) / 2
    dx = x2 - x1
    dy = y2 - y1
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1e-6:
        return {
            "from_mod": mod_from, "to_mod": mod_to, "rect_pts": [],
            "centroid": (mx, my), "train_id": train_id,
            "wagon_name": mod_from.wagon_name or mod_to.wagon_name,
            "from_code": mod_from.code, "to_code": mod_to.code,
            "from_uv": mod_from.uv, "to_uv": mod_to.uv,
        }
    # Rectangle along the line, with small width
    ux, uy = dx / length, dy / length
    perp_x, perp_y = -uy, ux
    half_w = 15.0  # narrow width
    # Shorten so it doesn't overlap module polygons
    shrink = 35.0
    sx, sy = x1 + ux * shrink, y1 + uy * shrink
    ex, ey = x2 - ux * shrink, y2 - uy * shrink
    p1 = (sx + perp_x * half_w, sy + perp_y * half_w)
    p2 = (sx - perp_x * half_w, sy - perp_y * half_w)
    p3 = (ex - perp_x * half_w, ey - perp_y * half_w)
    p4 = (ex + perp_x * half_w, ey + perp_y * half_w)
    return {
        "from_mod": mod_from, "to_mod": mod_to,
        "rect_pts": [p1, p2, p3, p4],
        "centroid": (mx, my), "train_id": train_id,
        "wagon_name": mod_from.wagon_name or mod_to.wagon_name,
        "from_code": mod_from.code, "to_code": mod_to.code,
        "from_uv": mod_from.uv, "to_uv": mod_to.uv,
    }


def _connector_tooltip(conn: dict, train_label: str) -> str:
    lines = [f"Wagon: {conn['wagon_name']}" if conn["wagon_name"] else "Wagon"]
    lines.append(f"Connects: {conn['from_code']} -> {conn['to_code']}")
    if conn["from_uv"] and conn["to_uv"]:
        lines.append(f"From: ({conn['from_uv'][0]},{conn['from_uv'][1]})")
        lines.append(f"To: ({conn['to_uv'][0]},{conn['to_uv'][1]})")
    lines.append(f"Train: {train_label}")
    return "\n".join(lines)


def build_svg(model: CassetteModel) -> str:
    minx, miny, maxx, maxy = model.bounds
    w = max(maxx - minx, 1e-6)
    h = max(maxy - miny, 1e-6)
    pad_x = w * PADDING_RATIO
    pad_y = h * PADDING_RATIO
    view_minx = minx - pad_x
    view_miny = miny - pad_y
    view_w = w + 2 * pad_x
    view_h = h + 2 * pad_y

    def tx(x):
        return x - view_minx

    def ty(y):
        return view_h - (y - view_miny)

    def pts_str(points):
        return " ".join(f"{tx(x):.2f},{ty(y):.2f}" for x, y in points)

    train_label_by_id = {t.id: t.label for t in model.trains}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view_w:.2f} {view_h:.2f}" '
             f'preserveAspectRatio="xMidYMid meet" style="width:100%;height:100%;display:block;">']

    if not model.modules and not model.engines:
        parts.append(f'<text x="{view_w/2:.2f}" y="{view_h/2:.2f}" text-anchor="middle" '
                      f'fill="#94a3b8" font-size="{max(view_w,view_h)*0.04:.2f}">No modules detected</text>')
        parts.append("</svg>")
        return "".join(parts)

    stroke_w = max(view_w, view_h) * 0.003
    font_size = max(view_w, view_h) * 0.018

    # --- Wingboards (drawn first, behind modules) ---
    for wb in model.wingboards:
        if not wb.polygon:
            continue
        points = pts_str(wb.polygon)
        tl = train_label_by_id.get(wb.train_id, wb.train_id)
        tt_json = json.dumps(_wingboard_tooltip(wb, tl))
        tt = html.escape(tt_json, quote=True)
        dt = html.escape(wb.train_id, quote=True)
        parts.append(
            f'<polygon points="{points}" fill="rgba(100,116,139,0.3)" '
            f'stroke="#64748b" stroke-width="{stroke_w:.3f}" '
            f'class="wingboard-shape" data-train="{dt}"></polygon>'
        )
        cx, cy = wb.centroid
        sx, sy = tx(cx), ty(cy)
        parts.append(
            f'<text x="{sx:.2f}" y="{sy:.2f}" text-anchor="middle" '
            f'dominant-baseline="central" font-size="{font_size*0.7:.2f}" '
            f'font-family="monospace" fill="#94a3b8" pointer-events="none" '
            f'class="wingboard-label" data-train="{dt}">WB</text>'
        )
        parts.append(
            f'<polygon points="{points}" fill="transparent" stroke="none" '
            f'class="wingboard-hit" style="cursor:pointer;" data-train="{dt}" '
            f'onmouseenter="cassetteHover(event, {tt})" '
            f'onmousemove="cassetteMove(event)" '
            f'onmouseleave="cassetteLeave(event)"></polygon>'
        )

    # --- Wagon connectors (drawn behind modules, above wingboards) ---
    connectors = _compute_wagon_connectors(model)
    for conn in connectors:
        if not conn["rect_pts"]:
            continue
        points = pts_str(conn["rect_pts"])
        tl = train_label_by_id.get(conn["train_id"], conn["train_id"])
        tt_json = json.dumps(_connector_tooltip(conn, tl))
        tt = html.escape(tt_json, quote=True)
        dt = html.escape(conn["train_id"], quote=True)
        parts.append(
            f'<polygon points="{points}" fill="rgba(148,163,184,0.35)" '
            f'stroke="#94a3b8" stroke-width="{stroke_w:.3f}" '
            f'stroke-dasharray="{stroke_w*2:.2f} {stroke_w:.2f}" '
            f'class="wagon-connector" data-train="{dt}" data-wagon="true"></polygon>'
        )
        # Label on connector: from_code -> to_code
        cx, cy = conn["centroid"]
        sx, sy = tx(cx), ty(cy)
        label_text = f"{conn['from_code']}-{conn['to_code']}"
        parts.append(
            f'<text x="{sx:.2f}" y="{sy:.2f}" text-anchor="middle" '
            f'dominant-baseline="central" font-size="{font_size*0.55:.2f}" '
            f'font-family="monospace" fill="#cbd5e1" pointer-events="none" '
            f'class="wagon-connector-label" data-train="{dt}" data-wagon="true">'
            f'{html.escape(label_text)}</text>'
        )
        parts.append(
            f'<polygon points="{points}" fill="transparent" stroke="none" '
            f'class="wagon-connector-hit" style="cursor:pointer;" '
            f'data-train="{dt}" data-wagon="true" '
            f'onmouseenter="cassetteHover(event, {tt})" '
            f'onmousemove="cassetteMove(event)" '
            f'onmouseleave="cassetteLeave(event)"></polygon>'
        )

    # --- Modules ---
    for m in model.modules:
        points = pts_str(m.polygon)
        r, g, b = m.color_rgb
        tl = train_label_by_id.get(m.train_id, m.train_id)
        dt = html.escape(m.train_id, quote=True)

        if m.is_wagon:
            fill = f"rgba({r},{g},{b},0.45)"
            tt_json = json.dumps(_wagon_tooltip(m, tl))
            tt = html.escape(tt_json, quote=True)
            parts.append(
                f'<polygon points="{points}" fill="{fill}" '
                f'stroke="{SHAPE_STROKE}" stroke-width="{stroke_w:.3f}" '
                f'stroke-dasharray="{stroke_w*2:.2f} {stroke_w:.2f}" '
                f'class="module-shape wagon-shape" data-train="{dt}" data-wagon="true"></polygon>'
            )
            cx, cy = m.centroid
            sx, sy = tx(cx), ty(cy)
            label_lines = [m.code]
            if m.uv is not None:
                label_lines.append(f"({m.uv[0]},{m.uv[1]})")
            parts.append(
                f'<text x="{sx:.2f}" y="{sy:.2f}" text-anchor="middle" '
                f'dominant-baseline="central" font-size="{font_size:.2f}" '
                f'font-family="monospace" font-weight="600" pointer-events="none" '
                f'class="module-label" data-train="{dt}" data-wagon="true">'
                + "".join(f'<tspan x="{sx:.2f}" dy="{i*1.1:.2f}em">{html.escape(ln)}</tspan>'
                          for i, ln in enumerate(label_lines))
                + "</text>"
            )
            parts.append(
                f'<polygon points="{points}" fill="transparent" stroke="none" '
                f'class="module-hit wagon-hit" style="cursor:pointer;" '
                f'data-train="{dt}" data-wagon="true" '
                f'onmouseenter="cassetteHover(event, {tt})" '
                f'onmousemove="cassetteMove(event)" '
                f'onmouseleave="cassetteLeave(event)"></polygon>'
            )
        else:
            fill = f"rgb({r},{g},{b})"
            tt_json = json.dumps(_module_tooltip(m, tl))
            tt = html.escape(tt_json, quote=True)
            parts.append(
                f'<polygon points="{points}" fill="{fill}" fill-opacity="0.82" '
                f'stroke="{SHAPE_STROKE}" stroke-width="{stroke_w:.3f}" '
                f'class="module-shape" data-train="{dt}"></polygon>'
            )
            cx, cy = m.centroid
            sx, sy = tx(cx), ty(cy)
            label_lines = [m.code]
            if m.uv is not None:
                label_lines.append(f"({m.uv[0]},{m.uv[1]})")
            parts.append(
                f'<text x="{sx:.2f}" y="{sy:.2f}" text-anchor="middle" '
                f'dominant-baseline="central" font-size="{font_size:.2f}" '
                f'font-family="monospace" font-weight="600" pointer-events="none" '
                f'class="module-label" data-train="{dt}">'
                + "".join(f'<tspan x="{sx:.2f}" dy="{i*1.1:.2f}em">{html.escape(ln)}</tspan>'
                          for i, ln in enumerate(label_lines))
                + "</text>"
            )
            parts.append(
                f'<polygon points="{points}" fill="transparent" stroke="none" '
                f'class="module-hit" style="cursor:pointer;" data-train="{dt}" '
                f'onmouseenter="cassetteHover(event, {tt})" '
                f'onmousemove="cassetteMove(event)" '
                f'onmouseleave="cassetteLeave(event)"></polygon>'
            )

    # --- Engines ---
    for e in model.engines:
        cx, cy = e.center
        sx, sy = tx(cx), ty(cy)
        radius = e.radius / 2.5
        r, g, b = e.color_rgb
        fill = f"rgb({r},{g},{b})"
        tl = train_label_by_id.get(e.train_id, e.train_id)
        tt_json = json.dumps(_engine_tooltip(e, tl))
        tt = html.escape(tt_json, quote=True)
        dt = html.escape(e.train_id, quote=True)
        parts.append(
            f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{radius:.2f}" fill="{fill}" '
            f'fill-opacity="0.95" stroke="{SHAPE_STROKE}" stroke-width="{stroke_w:.3f}" '
            f'class="engine-shape" data-train="{dt}"></circle>'
        )
        parts.append(
            f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{radius:.2f}" fill="transparent" '
            f'stroke="none" class="engine-hit" style="cursor:pointer;" data-train="{dt}" '
            f'onmouseenter="cassetteHover(event, {tt})" '
            f'onmousemove="cassetteMove(event)" '
            f'onmouseleave="cassetteLeave(event)"></circle>'
        )

    parts.append("</svg>")
    return "".join(parts)


def build_test_svg(model: CassetteModel, results: dict[str, bool]) -> str:
    """Build an interactive SVG showing per-module test results."""
    minx, miny, maxx, maxy = model.bounds
    w = max(maxx - minx, 1e-6)
    h = max(maxy - miny, 1e-6)
    pad_x = w * PADDING_RATIO
    pad_y = h * PADDING_RATIO
    view_minx = minx - pad_x
    view_miny = miny - pad_y
    view_w = w + 2 * pad_x
    view_h = h + 2 * pad_y

    def tx(x):
        return x - view_minx

    def ty(y):
        return view_h - (y - view_miny)

    def pts_str(points):
        return " ".join(f"{tx(x):.2f},{ty(y):.2f}" for x, y in points)

    train_label_by_id = {t.id: t.label for t in model.trains}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view_w:.2f} {view_h:.2f}" '
             f'preserveAspectRatio="xMidYMid meet" style="width:100%;height:100%;display:block;">']

    if not model.modules:
        parts.append(f'<text x="{view_w/2:.2f}" y="{view_h/2:.2f}" text-anchor="middle" '
                      f'fill="#94a3b8" font-size="{max(view_w,view_h)*0.04:.2f}">No modules detected</text>')
        parts.append("</svg>")
        return "".join(parts)

    stroke_w = max(view_w, view_h) * 0.003
    font_size = max(view_w, view_h) * 0.018

    for m in model.modules:
        points = pts_str(m.polygon)
        passed = bool(results.get(m.id, True))
        fill = PASS_FILL if passed else FAIL_FILL
        status = "pass" if passed else "fail"
        tl = train_label_by_id.get(m.train_id, m.train_id)
        tt_lines = [f"Code: {m.code}"]
        if m.uv is not None:
            tt_lines.append(f"(u, v): ({m.uv[0]}, {m.uv[1]})")
        if m.is_wagon and m.wagon_name:
            tt_lines.append(f"Wagon: {m.wagon_name}")
        if m.module_type:
            tt_lines.append(f"Type: {m.module_type}")
        tt_lines.append(f"Test: {'Pass' if passed else 'Fail'}")
        tt_json = json.dumps("\n".join(tt_lines))
        tt = html.escape(tt_json, quote=True)
        ds = html.escape(status, quote=True)
        wagon_attr = ' data-wagon="true"' if m.is_wagon else ""

        if m.is_wagon:
            parts.append(
                f'<polygon points="{points}" fill="{fill}" fill-opacity="0.55" '
                f'stroke="{SHAPE_STROKE}" stroke-width="{stroke_w:.3f}" '
                f'stroke-dasharray="{stroke_w*2:.2f} {stroke_w:.2f}" '
                f'class="module-shape wagon-shape" data-train="{ds}"{wagon_attr}></polygon>'
            )
        else:
            parts.append(
                f'<polygon points="{points}" fill="{fill}" fill-opacity="0.82" '
                f'stroke="{SHAPE_STROKE}" stroke-width="{stroke_w:.3f}" '
                f'class="module-shape" data-train="{ds}"></polygon>'
            )
            cx, cy = m.centroid
            sx, sy = tx(cx), ty(cy)
            label_lines = [m.code]
            if m.uv is not None:
                label_lines.append(f"({m.uv[0]},{m.uv[1]})")
            parts.append(
                f'<text x="{sx:.2f}" y="{sy:.2f}" text-anchor="middle" '
                f'dominant-baseline="central" fill="#f8fafc" font-size="{font_size:.2f}" '
                f'font-family="monospace" font-weight="600" pointer-events="none" '
                f'class="module-label" data-train="{ds}">'
                + "".join(f'<tspan x="{sx:.2f}" dy="{i*1.1:.2f}em">{html.escape(ln)}</tspan>'
                          for i, ln in enumerate(label_lines))
                + "</text>"
            )
        parts.append(
            f'<polygon points="{points}" fill="transparent" stroke="none" '
            f'class="module-hit" style="cursor:pointer;" data-train="{ds}"{wagon_attr} '
            f'onmouseenter="cassetteHover(event, {tt})" '
            f'onmousemove="cassetteMove(event)" '
            f'onmouseleave="cassetteLeave(event)"></polygon>'
        )

    parts.append("</svg>")
    return "".join(parts)
