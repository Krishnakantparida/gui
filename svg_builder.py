"""Build an interactive SVG for a CassetteModel.

Each module is rendered as a filled+outlined shape with its module code
and (u,v) coordinates drawn as text on top, plus a transparent "hit"
overlay that drives hover tooltips via a few small global JS functions
(defined once in main_test.py via ui.add_head_html). Engines are drawn
as filled circles with their own hit overlays. Hover math is done in
screen pixels against the display container's bounding rect, so it works
correctly regardless of how the SVG is scaled to fit its flex-1 container.
"""

from __future__ import annotations

import html
import json

from dxf_model import CassetteModel, Module, Engine

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
    """Tooltip text for a module: everything NOT already drawn on the shape."""
    lines = [f"Code: {m.code}"]
    if m.uv is not None:
        lines.append(f"(u, v): ({m.uv[0]}, {m.uv[1]})")
    lines.append(f"Shape: {SHAPE_LABEL.get(m.shape, m.shape)}")
    lines.append(f"Train: {train_label}")
    r, g, b = m.color_rgb
    lines.append(f"Color: rgb({r}, {g}, {b})")
    return "\n".join(lines)


def _engine_tooltip(e: Engine, train_label: str) -> str:
    """Tooltip text for an engine."""
    lines = ["Engine"]
    lines.append(f"Train: {train_label}")
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

    # translate module points into a top-left-origin, Y-down coordinate
    # space sized (view_w, view_h) so the viewBox can start at 0,0
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
    # choose a readable text color per module: white on dark fills, dark on light fills
    def text_color(rgb: tuple[int, int, int]) -> str:
        r, g, b = rgb
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        return "#0f172a" if luminance > 140 else "#f8fafc"

    for m in model.modules:
        points = pts_str(m.polygon)
        r, g, b = m.color_rgb
        fill = f"rgb({r},{g},{b})"
        train_label = train_label_by_id.get(m.train_id, m.train_id)
        tooltip_json = json.dumps(_module_tooltip(m, train_label))
        tooltip_text = html.escape(tooltip_json, quote=True)
        data_train = html.escape(m.train_id, quote=True)

        parts.append(
            f'<polygon points="{points}" fill="{fill}" fill-opacity="0.82" '
            f'stroke="{SHAPE_STROKE.get(m.shape, "#e2e8f0")}" stroke-width="{stroke_width:.3f}" '
            f'class="module-shape" data-shape="{html.escape(m.shape)}" '
            f'data-train="{data_train}"></polygon>'
        )
        # module code + (u,v) text drawn at the centroid
        cx, cy = m.centroid
        sx, sy = tx(cx), ty(cy)
        tcolor = text_color(m.color_rgb)
        label_lines = [m.code]
        if m.uv is not None:
            label_lines.append(f"({m.uv[0]},{m.uv[1]})")
        parts.append(
            f'<text x="{sx:.2f}" y="{sy:.2f}" text-anchor="middle" '
            f'dominant-baseline="central" fill="{tcolor}" '
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

    for e in model.engines:
        cx, cy = e.center
        sx, sy = tx(cx), ty(cy)
        radius = e.radius / 2.5
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
    """Tooltip text for a module in the test-results view."""
    lines = [f"Code: {m.code}"]
    if m.uv is not None:
        lines.append(f"(u, v): ({m.uv[0]}, {m.uv[1]})")
    lines.append(f"Shape: {SHAPE_LABEL.get(m.shape, m.shape)}")
    lines.append(f"Test: {'Pass' if passed else 'Fail'}")
    lines.append(f"Reason: N/A")
    return "\n".join(lines)


def build_test_svg(model: CassetteModel, results: dict[str, bool]) -> str:
    """Build an interactive SVG showing per-module test results.

    ``results`` maps ``Module.id`` -> pass/fail (True = pass). Modules are
    colored green (pass) or red (fail); engines are omitted. Each module's
    ``data-status`` attribute ("pass"/"fail") drives the legend's checkbox
    toggling via the shared ``setTrainVisible`` JS helper.
    """
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
