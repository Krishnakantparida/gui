"""Build an interactive SVG for a CassetteModel.

Each module is rendered as a filled+outlined shape with a transparent
"hit" overlay that drives hover tooltips via a few small global JS
functions (defined once in main.py via ui.add_head_html). Hover math is
done in screen pixels against the display container's bounding rect, so
it works correctly regardless of how the SVG is scaled to fit its
flex-1 container.
"""

from __future__ import annotations

import html
import json

from dxf_model import CassetteModel

PADDING_RATIO = 0.06

SHAPE_STROKE = {
    "hex_full": "#e2e8f0",
    "hex_partial": "#e2e8f0",
    "tile": "#e2e8f0",
}


def _to_svg_points(points: list[tuple[float, float]], minx: float, height: float, miny: float) -> str:
    return " ".join(f"{(x - minx):.2f},{(height - (y - miny)):.2f}" for x, y in points)


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
    def pts_str(points: list[tuple[float, float]]) -> str:
        return " ".join(f"{(x - view_minx):.2f},{(view_h - (y - view_miny)):.2f}" for x, y in points)

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

    for m in model.modules:
        points = pts_str(m.polygon)
        r, g, b = m.color_rgb
        fill = f"rgb({r},{g},{b})"
        # JSON-encode first (so cassetteHover receives a JS string literal),
        # then HTML-escape the whole thing since it's embedded inside a
        # double-quoted HTML attribute -- otherwise any `"` in the label
        # text (or the JSON encoding itself) terminates the attribute early
        # and truncates the inline onmouseenter handler mid-expression.
        tooltip_json = json.dumps(f"{m.label}\n{m.shape.replace('_', ' ').title()}")
        tooltip_text = html.escape(tooltip_json, quote=True)

        parts.append(
            f'<polygon points="{points}" fill="{fill}" fill-opacity="0.62" '
            f'stroke="{SHAPE_STROKE.get(m.shape, "#e2e8f0")}" stroke-width="{stroke_width:.3f}" '
            f'class="module-shape" data-shape="{html.escape(m.shape)}"></polygon>'
        )
        parts.append(
            f'<polygon points="{points}" fill="transparent" stroke="none" '
            f'class="module-hit" style="cursor:pointer;" '
            f'onmouseenter="cassetteHover(event, {tooltip_text})" '
            f'onmousemove="cassetteMove(event)" '
            f'onmouseleave="cassetteLeave(event)"></polygon>'
        )

    parts.append("</svg>")
    return "".join(parts)
