"""Build an interactive SVG for a CassetteModel.

Each module is rendered as a filled+outlined shape with its module code
and (u,v) coordinates drawn as text on top, plus a transparent "hit"
overlay that drives hover tooltips via a few small global JS functions
(defined once in main_test.py via ui.add_head_html). Engines are drawn
as filled circles with their own hit overlays. Wagons are module polygons
with a distinct visual treatment (hatched / lighter fill, no label text).
Hover math is done in screen pixels against the display container's
bounding rect, so it works correctly regardless of how the SVG is scaled
to fit its flex-1 container.
"""

from __future__ import annotations

import html
import json

from dxf_model import CassetteModel, Module, Engine, WagonLink, Wingboard

PADDING_RATIO = 0.06

SHAPE_STROKE = {
    "hex_full": "#e2e8f0",
    "hex_partial": "#e2e8f0",
    "tile": "#e2e8f0",
}

SHAPE_LABEL = {
    "hex_full": "Full hexagonal",
    "hex_partial": "Partial hexagonal",
    "tile": "Tile",
}

PASS_FILL = "#22c55e"
FAIL_FILL = "#ef4444"


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


def _wagon_link_tooltip(w: WagonLink, train_label: str) -> str:
    lines = [f"Wagon: {w.name}" if w.name else "Wagon"]
    lines.append(f"Connects to module: {w.module_code}")
    if w.uv is not None:
        lines.append(f"(u, v): ({w.uv[0]}, {w.uv[1]})")
    lines.append(f"Train: {train_label}")
    return "\n".join(lines)


def _wingboard_tooltip(w: Wingboard, train_label: str) -> str:
    lines = [f"Wingboard: {w.name}" if w.name else "Wingboard"]
    lines.append(f"Boundary module: {w.module_code}")
    lines.append(f"Train: {train_label}")
    return "\n".join(lines)


def _engine_tooltip(e: Engine, train_label: str) -> str:
    is_motherboard = e.engine_type.startswith("WM-MB")
    if is_motherboard:
        lines = [f"Motherboard: {e.engine_type}"]
    else:
        lines = [f"Engine: {e.engine_type}" if e.engine_type else "Engine"]
    lines.append(f"Train: {train_label}")
    if e.engine_type:
        lines.append(f"Type: {e.engine_type}")
    r, g, b = e.color_rgb
    lines.append(f"Color: rgb({r}, {g}, {b})")
    cx, cy = e.center
    lines.append(f"Center: ({cx:.2f}, {cy:.2f})")
    lines.append(f"Radius: {e.radius:.2f}")
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

    def tx(x: float) -> float:
        return x - view_minx

    def ty(y: float) -> float:
        return view_h - (y - view_miny)

    def pts_str(points: list[tuple[float, float]]) -> str:
        return " ".join(f"{tx(x):.2f},{ty(y):.2f}" for x, y in points)

    train_label_by_id = {t.id: t.label for t in model.trains}

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view_w:.2f} {view_h:.2f}" '
        f'preserveAspectRatio="xMidYMid meet" style="width:100%;height:100%;display:block;">'
    )

    if not model.modules and not model.engines:
        parts.append(
            f'<text x="{view_w / 2:.2f}" y="{view_h / 2:.2f}" text-anchor="middle" '
            f'fill="#94a3b8" font-size="{max(view_w, view_h) * 0.04:.2f}">No module regions detected</text>'
        )
        parts.append("</svg>")
        return "".join(parts)

    stroke_width = max(view_w, view_h) * 0.0035
    font_size = max(view_w, view_h) * 0.022

    for m in model.modules:
        points = pts_str(m.polygon)
        r, g, b = m.color_rgb
        train_label = train_label_by_id.get(m.train_id, m.train_id)
        data_train = html.escape(m.train_id, quote=True)

        fill = f"rgb({r},{g},{b})"
        tooltip_json = json.dumps(_module_tooltip(m, train_label))
        tooltip_text = html.escape(tooltip_json, quote=True)
        parts.append(
            f'<polygon points="{points}" fill="{fill}" fill-opacity="0.82" '
            f'stroke="{SHAPE_STROKE.get(m.shape, "#e2e8f0")}" stroke-width="{stroke_width:.3f}" '
            f'class="module-shape" data-shape="{html.escape(m.shape)}" '
            f'data-train="{data_train}"></polygon>'
        )
        cx, cy = m.centroid
        sx, sy = tx(cx), ty(cy)
        label_lines = [m.code]
        if m.uv is not None:
            label_lines.append(f"({m.uv[0]},{m.uv[1]})")
        parts.append(
            f'<text x="{sx:.2f}" y="{sy:.2f}" text-anchor="middle" '
            f'dominant-baseline="central" '
            f'font-size="{font_size:.2f}" font-family="monospace" '
            f'font-weight="600" pointer-events="none" '
            f'class="module-label" data-train="{data_train}">'
            + "".join(
                f'<tspan x="{sx:.2f}" dy="{i * 1.1:.2f}em">{html.escape(ln)}</tspan>'
                for i, ln in enumerate(label_lines)
            )
            + "</text>"
        )
        parts.append(
            f'<polygon points="{points}" fill="transparent" stroke="none" '
            f'class="module-hit" style="cursor:pointer;" '
            f'data-train="{data_train}" '
            f'onmouseenter="cassetteHover(event, {tooltip_text})" '
            f'onmousemove="cassetteMove(event)" '
            f'onmouseleave="cassetteLeave(event)"></polygon>'
        )

    for wb in model.wingboards:
        points = pts_str(wb.polygon)
        train_label = train_label_by_id.get(wb.train_id, wb.train_id)
        tooltip_json = json.dumps(_wingboard_tooltip(wb, train_label))
        tooltip_text = html.escape(tooltip_json, quote=True)
        data_train = html.escape(wb.train_id, quote=True)
        parts.append(
            f'<polygon points="{points}" fill="#38bdf8" fill-opacity="0.42" '
            f'stroke="#e0f2fe" stroke-width="{stroke_width:.3f}" '
            f'class="board-shape wingboard-shape" data-train="{data_train}"></polygon>'
        )
        sx, sy = tx(wb.centroid[0]), ty(wb.centroid[1])
        parts.append(
            f'<text x="{sx:.2f}" y="{sy:.2f}" text-anchor="middle" dominant-baseline="central" '
            f'font-size="{font_size * 0.72:.2f}" font-family="monospace" font-weight="600" '
            f'pointer-events="none" class="board-label" data-train="{data_train}">'
            f'{html.escape(wb.name)}</text>'
        )
        parts.append(
            f'<polygon points="{points}" fill="transparent" stroke="none" '
            f'class="board-hit" style="cursor:pointer;" data-train="{data_train}" '
            f'onmouseenter="cassetteHover(event, {tooltip_text})" '
            f'onmousemove="cassetteMove(event)" '
            f'onmouseleave="cassetteLeave(event)"></polygon>'
        )

    for wlink in model.wagon_links:
        points = pts_str(wlink.polygon)
        r, g, b = wlink.color_rgb
        train_label = train_label_by_id.get(wlink.train_id, wlink.train_id)
        tooltip_json = json.dumps(_wagon_link_tooltip(wlink, train_label))
        tooltip_text = html.escape(tooltip_json, quote=True)
        data_train = html.escape(wlink.train_id, quote=True)
        parts.append(
            f'<polygon points="{points}" fill="rgba({r},{g},{b},0.20)" '
            f'stroke="#f8fafc" stroke-width="{stroke_width:.3f}" '
            f'stroke-dasharray="{stroke_width * 2.2:.2f} {stroke_width * 1.7:.2f}" '
            f'class="wagon-shape" data-train="{data_train}" data-wagon="true"></polygon>'
        )
        sx, sy = tx(wlink.label_point[0]), ty(wlink.label_point[1])
        label_lines = [wlink.module_code]
        if wlink.uv is not None:
            label_lines.append(f"({wlink.uv[0]},{wlink.uv[1]})")
        parts.append(
            f'<text x="{sx:.2f}" y="{sy:.2f}" text-anchor="middle" dominant-baseline="central" '
            f'font-size="{font_size * 0.66:.2f}" font-family="monospace" font-weight="600" '
            f'pointer-events="none" class="wagon-label" data-train="{data_train}" data-wagon="true">'
            + "".join(
                f'<tspan x="{sx:.2f}" dy="{i * 1.05:.2f}em">{html.escape(ln)}</tspan>'
                for i, ln in enumerate(label_lines)
            )
            + "</text>"
        )
        parts.append(
            f'<polygon points="{points}" fill="transparent" stroke="none" '
            f'class="wagon-hit" style="cursor:pointer;" data-train="{data_train}" data-wagon="true" '
            f'onmouseenter="cassetteHover(event, {tooltip_text})" '
            f'onmousemove="cassetteMove(event)" '
            f'onmouseleave="cassetteLeave(event)"></polygon>'
        )

    for e in model.engines:
        cx, cy = e.center
        sx, sy = tx(cx), ty(cy)
        radius = e.radius * 2.5
        r, g, b = e.color_rgb
        fill = f"rgb({r},{g},{b})"
        train_label = train_label_by_id.get(e.train_id, e.train_id)
        tooltip_json = json.dumps(_engine_tooltip(e, train_label))
        tooltip_text = html.escape(tooltip_json, quote=True)
        data_train = html.escape(e.train_id, quote=True)
        parts.append(
            f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{radius:.2f}" fill="{fill}" '
            f'fill-opacity="0.95" stroke="#e2e8f0" stroke-width="{stroke_width:.3f}" '
            f'class="engine-shape" data-train="{data_train}"></circle>'
        )
        parts.append(
            f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{radius:.2f}" fill="transparent" '
            f'stroke="none" class="engine-hit" style="cursor:pointer;" '
            f'data-train="{data_train}" '
            f'onmouseenter="cassetteHover(event, {tooltip_text})" '
            f'onmousemove="cassetteMove(event)" '
            f'onmouseleave="cassetteLeave(event)"></circle>'
        )

    parts.append("</svg>")
    return "".join(parts)


def _test_module_tooltip(m: Module, passed: bool) -> str:
    lines = [f"Code: {m.code}"]
    if m.uv is not None:
        lines.append(f"(u, v): ({m.uv[0]}, {m.uv[1]})")
    lines.append(f"Shape: {SHAPE_LABEL.get(m.shape, m.shape)}")
    if m.wagon_name:
        lines.append(f"Wagon: {m.wagon_name}")
    if m.module_type:
        lines.append(f"Type: {m.module_type}")
    lines.append(f"Test: {'Pass' if passed else 'Fail'}")
    lines.append(f"Reason: N/A")
    return "\n".join(lines)


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

    def tx(x: float) -> float:
        return x - view_minx

    def ty(y: float) -> float:
        return view_h - (y - view_miny)

    def pts_str(points: list[tuple[float, float]]) -> str:
        return " ".join(f"{tx(x):.2f},{ty(y):.2f}" for x, y in points)

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view_w:.2f} {view_h:.2f}" '
        f'preserveAspectRatio="xMidYMid meet" style="width:100%;height:100%;display:block;">'
    )

    if not model.modules:
        parts.append(
            f'<text x="{view_w / 2:.2f}" y="{view_h / 2:.2f}" text-anchor="middle" '
            f'fill="#94a3b8" font-size="{max(view_w, view_h) * 0.04:.2f}">No module regions detected</text>'
        )
        parts.append("</svg>")
        return "".join(parts)

    stroke_width = max(view_w, view_h) * 0.0035
    font_size = max(view_w, view_h) * 0.022

    for m in model.modules:
        points = pts_str(m.polygon)
        passed = bool(results.get(m.id, True))
        fill = PASS_FILL if passed else FAIL_FILL
        status = "pass" if passed else "fail"
        tooltip_json = json.dumps(_test_module_tooltip(m, passed))
        tooltip_text = html.escape(tooltip_json, quote=True)
        data_status = html.escape(status, quote=True)
        parts.append(
            f'<polygon points="{points}" fill="{fill}" fill-opacity="0.82" '
            f'stroke="#e2e8f0" stroke-width="{stroke_width:.3f}" '
            f'class="module-shape" data-shape="{html.escape(m.shape)}" '
            f'data-train="{data_status}"></polygon>'
        )
        cx, cy = m.centroid
        sx, sy = tx(cx), ty(cy)
        label_lines = [m.code]
        if m.uv is not None:
            label_lines.append(f"({m.uv[0]},{m.uv[1]})")
        parts.append(
            f'<text x="{sx:.2f}" y="{sy:.2f}" text-anchor="middle" '
            f'dominant-baseline="central" fill="#f8fafc" '
            f'font-size="{font_size:.2f}" font-family="monospace" '
            f'font-weight="600" pointer-events="none" '
            f'class="module-label" data-train="{data_status}">'
            + "".join(
                f'<tspan x="{sx:.2f}" dy="{i * 1.1:.2f}em">{html.escape(ln)}</tspan>'
                for i, ln in enumerate(label_lines)
            )
            + "</text>"
        )
        parts.append(
            f'<polygon points="{points}" fill="transparent" stroke="none" '
            f'class="module-hit" style="cursor:pointer;" '
            f'data-train="{data_status}" '
            f'onmouseenter="cassetteHover(event, {tooltip_text})" '
            f'onmousemove="cassetteMove(event)" '
            f'onmouseleave="cassetteLeave(event)"></polygon>'
        )

    parts.append("</svg>")
    return "".join(parts)
