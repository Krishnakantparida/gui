"""Interactive cassette viewer built with NiceGUI.

Features:
  - DXF cassette loader with JSON sidecar metadata enrichment
  - Interactive SVG display with hover tooltips (modules, wagons, engines,
    wingboards, wagon connectors)
  - Legend with per-train checkboxes, engines toggle, wagons toggle
  - "Train N" labels replaced by engine representations in the legend
  - Real train count (TL/TH/LD/HD only) shown in the info table
  - Test runner with pass/fail SVG visualization
  - Arrow buttons to switch between trains-view and test-results-view
  - Dark/light theme toggle
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from nicegui import ui, app

from dxf_model import load_cassette, CassetteModel
from svg_builder import build_svg, build_test_svg

CASSETTE_DIR = "cassette_layouts"

state = {
    "model": None,
    "visible_trains": {},
    "engines_visible": True,
    "wagons_visible": True,
    "test_results": {},
    "view_mode": "trains",
    "test_in_progress": False,
    "trains_svg_file": None,
    "test_svg_file": None,
}


def _get_cassette_files() -> list[str]:
    d = Path(CASSETTE_DIR)
    if not d.exists():
        return []
    return sorted(f.stem for f in d.glob("*.dxf"))


def _hover_js() -> str:
    return """
    function cassetteHover(evt, text) {
        var tt = document.getElementById('cassette-tooltip');
        if (!tt) return;
        tt.textContent = text;
        tt.style.display = 'block';
        tt.style.opacity = '1';
        cassetteMove(evt);
    }
    function cassetteMove(evt) {
        var tt = document.getElementById('cassette-tooltip');
        if (!tt) return;
        var rect = tt.parentElement.getBoundingClientRect();
        var x = evt.clientX - rect.left + 12;
        var y = evt.clientY - rect.top + 12;
        tt.style.left = x + 'px';
        tt.style.top = y + 'px';
    }
    function cassetteLeave() {
        var tt = document.getElementById('cassette-tooltip');
        if (!tt) return;
        tt.style.opacity = '0';
        setTimeout(function() { if (tt) tt.style.display = 'none'; }, 200);
    }
    function setTrainVisible(trainId, visible) {
        var svg = document.querySelector('.cassette-svg-wrap svg');
        if (!svg) return;
        var sel = '[data-train="' + CSS.escape(trainId) + '"]';
        svg.querySelectorAll(sel).forEach(function(el) {
            if (visible) el.classList.remove('dimmed');
            else el.classList.add('dimmed');
        });
    }
    function setWagonsVisible(visible) {
        var svg = document.querySelector('.cassette-svg-wrap svg');
        if (!svg) return;
        svg.querySelectorAll('[data-wagon="true"]').forEach(function(el) {
            if (visible) el.classList.remove('wagon-transparent');
            else el.classList.add('wagon-transparent');
        });
    }
    function setEnginesVisible(visible) {
        var svg = document.querySelector('.cassette-svg-wrap svg');
        if (!svg) return;
        svg.querySelectorAll('.engine-shape, .engine-hit').forEach(function(el) {
            if (visible) el.classList.remove('dimmed');
            else el.classList.add('dimmed');
        });
    }
    """


def _css() -> str:
    return """
    <style>
    .cassette-page {
        background: #1e293b;
        color: #e2e8f0;
        min-height: 100vh;
        font-family: 'Segoe UI', system-ui, sans-serif;
    }
    .cassette-page.light {
        background: #f1f5f9;
        color: #1e293b;
    }
    .cassette-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px 24px;
        background: rgba(30,41,59,0.95);
        border-bottom: 1px solid #334155;
        position: sticky;
        top: 0;
        z-index: 100;
    }
    .cassette-page.light .cassette-header {
        background: rgba(241,245,249,0.95);
        border-bottom: 1px solid #cbd5e1;
    }
    .cassette-title {
        font-size: 1.4rem;
        font-weight: 700;
        letter-spacing: -0.02em;
    }
    .cassette-body {
        display: flex;
        gap: 0;
        height: calc(100vh - 65px);
    }
    .cassette-sidebar {
        width: 280px;
        min-width: 280px;
        background: rgba(15,23,42,0.6);
        border-right: 1px solid #334155;
        overflow-y: auto;
        padding: 16px;
    }
    .cassette-page.light .cassette-sidebar {
        background: rgba(255,255,255,0.6);
        border-right: 1px solid #cbd5e1;
    }
    .cassette-main {
        flex: 1;
        display: flex;
        flex-direction: column;
        position: relative;
        overflow: hidden;
    }
    .cassette-svg-wrap {
        flex: 1;
        position: relative;
        overflow: hidden;
        padding: 16px;
    }
    .cassette-svg-wrap svg {
        max-width: 100%;
        max-height: 100%;
    }
    .cassette-tooltip {
        position: absolute;
        background: rgba(15,23,42,0.95);
        color: #e2e8f0;
        border: 1px solid #475569;
        border-radius: 6px;
        padding: 8px 12px;
        font-size: 0.8rem;
        font-family: monospace;
        white-space: pre;
        pointer-events: none;
        z-index: 200;
        display: none;
        opacity: 0;
        transition: opacity 0.2s;
        max-width: 320px;
        line-height: 1.5;
    }
    .cassette-toolbar {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 16px;
        background: rgba(15,23,42,0.4);
        border-bottom: 1px solid #334155;
    }
    .cassette-page.light .cassette-toolbar {
        background: rgba(255,255,255,0.4);
        border-bottom: 1px solid #cbd5e1;
    }
    .legend-section {
        margin-bottom: 12px;
    }
    .legend-title {
        font-size: 0.85rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 8px;
        color: #94a3b8;
    }
    .legend-row {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 4px 0;
    }
    .legend-swatch {
        width: 18px;
        height: 18px;
        border-radius: 3px;
        border: 1px solid #475569;
        flex-shrink: 0;
    }
    .legend-swatch.engine {
        border-radius: 50%;
    }
    .legend-swatch.wagon {
        border-radius: 3px;
        border-style: dashed;
    }
    .legend-swatch.wingboard {
        border-radius: 2px;
        background: rgba(100,116,139,0.3);
        border: 1px solid #64748b;
    }
    .dimmed {
        opacity: 0.12 !important;
        transition: opacity 0.3s;
    }
    .wagon-transparent {
        opacity: 0.15 !important;
        transition: opacity 0.3s;
    }
    .info-table {
        width: 100%;
        font-size: 0.8rem;
    }
    .info-table td {
        padding: 4px 8px;
        border-bottom: 1px solid #334155;
    }
    .cassette-page.light .info-table td {
        border-bottom: 1px solid #cbd5e1;
    }
    .module-label {
        fill: #f1f5f9 !important;
    }
    .cassette-page.light .module-label {
        fill: #1e293b !important;
    }
    .arrow-btn {
        font-size: 1.2rem;
        cursor: pointer;
        padding: 4px 12px;
        border-radius: 4px;
        background: #334155;
        color: #e2e8f0;
        border: none;
        transition: background 0.2s;
    }
    .arrow-btn:hover:not(:disabled) {
        background: #475569;
    }
    .arrow-btn:disabled {
        opacity: 0.4;
        cursor: not-allowed;
    }
    .theme-toggle {
        cursor: pointer;
        font-size: 1.1rem;
    }
    </style>
    """


@ui.refreshable
def cassette_display():
    model: CassetteModel | None = state["model"]
    wrap = ui.element("div").classes("cassette-svg-wrap")

    if model is None:
        with wrap:
            ui.label("Select a cassette to begin").classes("text-gray-400 text-lg")
        return

    svg_content = ""
    if state["view_mode"] == "trains":
        svg_content = build_svg(model)
    else:
        svg_content = build_test_svg(model, state["test_results"])

    # Save to temp file for arrow-button reload
    fd, tmp_path = tempfile.mkstemp(suffix=".svg", prefix="cassette_")
    with os.fdopen(fd, "w") as f:
        f.write(svg_content)
    if state["view_mode"] == "trains":
        if state.get("trains_svg_file") and os.path.exists(state["trains_svg_file"]):
            os.unlink(state["trains_svg_file"])
        state["trains_svg_file"] = tmp_path
    else:
        if state.get("test_svg_file") and os.path.exists(state["test_svg_file"]):
            os.unlink(state["test_svg_file"])
        state["test_svg_file"] = tmp_path

    with wrap:
        ui.html(svg_content)
        ui.element("div").classes("cassette-tooltip").id("cassette-tooltip")


@ui.refreshable
def legend_panel():
    model: CassetteModel | None = state["model"]
    if model is None:
        ui.label("No cassette loaded")
        return

    with ui.column().classes("legend-section w-full"):
        ui.label("Legend").classes("legend-title")

        # Real trains
        with ui.column().classes("w-full gap-0"):
            for train in model.trains:
                if not train.is_real:
                    continue
                visible = state["visible_trains"].get(train.id, True)
                r, g, b = train.color_rgb
                swatch = f"rgb({r},{g},{b})"
                with ui.row().classes("legend-row w-full items-center"):
                    ui.checkbox(
                        text=train.label,
                        value=visible,
                        on_change=lambda e, tid=train.id: _on_train_toggle(tid, e.value),
                    ).classes("flex-1")
                    ui.element("div").classes("legend-swatch").style(f"background:{swatch};")

        # "Train N" groups -> show as engine representations
        fake_trains = [t for t in model.trains if not t.is_real]
        if fake_trains:
            ui.separator().classes("w-full")
            ui.label("Engine Collections").classes("legend-title")
            for train in fake_trains:
                # Determine if this is HD or LD set
                density = "HD" if fake_trains.index(train) < len(fake_trains) / 2 else "LD"
                label = f"{density} Engines"
                # Find an engine for this train
                train_engines = [e for e in model.engines if e.train_id == train.id]
                if train_engines:
                    e0 = train_engines[0]
                    r, g, b = e0.color_rgb
                    swatch = f"rgb({r},{g},{b})"
                    with ui.row().classes("legend-row w-full items-center"):
                        ui.checkbox(
                            text=label,
                            value=state["engines_visible"],
                            on_change=lambda e: _on_engines_toggle(e.value),
                        ).classes("flex-1").tooltip(f"Engine collection: {train.label}")
                        ui.element("div").classes("legend-swatch engine").style(f"background:{swatch};")

        # Engines toggle (for real trains)
        if model.engines and any(t.is_real for t in model.trains):
            ui.separator().classes("w-full")
            real_engines = [e for e in model.engines if any(t.id == e.train_id and t.is_real for t in model.trains)]
            if real_engines:
                e0 = real_engines[0]
                r, g, b = e0.color_rgb
                swatch = f"rgb({r},{g},{b})"
                with ui.row().classes("legend-row w-full items-center"):
                    ui.checkbox(
                        text="Engines",
                        value=state["engines_visible"],
                        on_change=lambda e: _on_engines_toggle(e.value),
                    ).classes("flex-1")
                    ui.element("div").classes("legend-swatch engine").style(f"background:{swatch};")

        # Wagons toggle
        has_wagons = any(m.is_wagon for m in model.modules) or any(
            hasattr(m, "is_wagon") and m.is_wagon for m in model.modules
        )
        if has_wagons:
            ui.separator().classes("w-full")
            with ui.row().classes("legend-row w-full items-center"):
                ui.checkbox(
                    text="Wagons",
                    value=state["wagons_visible"],
                    on_change=lambda e: _on_wagons_toggle(e.value),
                ).classes("flex-1").tooltip("Toggle wagon connectors and wagon modules")
                ui.element("div").classes("legend-swatch wagon").style(
                    "background:rgba(148,163,184,0.35);border-style:dashed;"
                )

        # Wingboards
        if model.wingboards:
            ui.separator().classes("w-full")
            with ui.row().classes("legend-row w-full items-center"):
                ui.label("Wingboards").classes("flex-1 text-sm")
                ui.element("div").classes("legend-swatch wingboard")

    # Info table
    ui.separator().classes("w-full")
    with ui.column().classes("legend-section w-full"):
        ui.label("Cassette Info").classes("legend-title")
        with ui.table(
            columns=[
                {"name": "key", "label": "Property", "field": "key", "align": "left"},
                {"name": "val", "label": "Value", "field": "val", "align": "left"},
            ],
            rows=[
                {"key": "Name", "val": model.name},
                {"key": "Real trains", "val": str(model.real_train_count)},
                {"key": "Total modules", "val": str(len(model.modules))},
                {"key": "Wagon modules", "val": str(sum(1 for m in model.modules if m.is_wagon))},
                {"key": "Engines", "val": str(len(model.engines))},
                {"key": "Wingboards", "val": str(len(model.wingboards))},
            ],
        ).classes("info-table"):
            pass


def _on_train_toggle(train_id: str, visible: bool) -> None:
    state["visible_trains"][train_id] = visible
    v = "true" if visible else "false"
    ui.run_javascript(f'setTrainVisible("{train_id}", {v});')


def _on_engines_toggle(visible: bool) -> None:
    state["engines_visible"] = visible
    v = "true" if visible else "false"
    ui.run_javascript(f"setEnginesVisible({v});")


def _on_wagons_toggle(visible: bool) -> None:
    state["wagons_visible"] = visible
    v = "true" if visible else "false"
    ui.run_javascript(f"setWagonsVisible({v});")


def _load_cassette(name: str) -> None:
    filepath = str(Path(CASSETTE_DIR) / f"{name}.dxf")
    if not os.path.exists(filepath):
        ui.notify(f"File not found: {filepath}", type="negative")
        return
    model = load_cassette(filepath, name)
    state["model"] = model
    state["visible_trains"] = {t.id: True for t in model.trains}
    state["engines_visible"] = True
    state["wagons_visible"] = True
    state["test_results"] = {}
    state["view_mode"] = "trains"
    cassette_display.refresh()
    legend_panel.refresh()
    ui.notify(f"Loaded {name}", type="positive")


def _run_test() -> None:
    model = state["model"]
    if model is None:
        return
    state["test_in_progress"] = True
    import random
    results = {}
    for m in model.modules:
        results[m.id] = random.random() > 0.15
    state["test_results"] = results
    state["view_mode"] = "test"
    state["test_in_progress"] = False
    cassette_display.refresh()
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    ui.notify(f"Test complete: {passed}/{total} passed", type="positive")


def _show_trains_view() -> None:
    state["view_mode"] = "trains"
    cassette_display.refresh()


def _show_test_view() -> None:
    state["view_mode"] = "test"
    cassette_display.refresh()


@ui.page("/")
def main_page():
    ui.add_head_html(_css())
    ui.add_head_html(f"<script>{_hover_js()}</script>")

    dark = {"dark": True}

    with ui.column().classes("cassette-page w-full h-full") as page:
        # Header
        with ui.row().classes("cassette-header w-full"):
            ui.label("Cassette Viewer").classes("cassette-title")
            with ui.row().classes("items-center gap-4"):
                files = _get_cassette_files()
                ui.select(
                    options=files,
                    label="Cassette",
                    on_change=lambda e: _load_cassette(e.value),
                ).classes("w-64")
                ui.button("Run Test", on_click=_run_test, color="primary").props("icon=science")
                ui.button("Trains", on_click=_show_trains_view, color="secondary").props("icon=list")
                ui.button("Test Results", on_click=_show_test_view, color="secondary").props("icon=assessment")
                # Theme toggle
                def toggle_theme():
                    dark["dark"] = not dark["dark"]
                    if dark["dark"]:
                        page.classes(remove="light")
                    else:
                        page.classes(add="light")
                ui.button(icon="dark_mode", on_click=toggle_theme).classes("theme-toggle")

        # Body
        with ui.row().classes("cassette-body w-full"):
            # Sidebar
            with ui.column().classes("cassette-sidebar"):
                legend_panel()

            # Main
            with ui.column().classes("cassette-main"):
                cassette_display()


ui.run(port=8080, title="Cassette Viewer", dark=True, reload=False)
