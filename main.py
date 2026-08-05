#######################################################################################################
"""
*=======--::::::::::::::::::::::::::::::::::+
*--------------::...........................=
*-------------------:.......................=
*----*#=--+*--#=------*-.:*=.-*.............=
*---#=--------*%+----*#+-=%:..........:+:...=
*--=%=-------=+-#=--*-**--=#%#-.....:=-.....=
*--=%=-------*=-=%=+=-+#-----=%=..:=-.......=
*---=#+---==-*=--=%=--+%-=+--=#=---.........=
*------===-----------------==--+=-:.........=
*---------------------------=+=-----........=
+:::----------------------==---------::+:...=
+:::::::::-------------=+=----------=+-.....=
+:::::::::::::-------+=-----------+=---:....=
+:::::::::::::::-==+----------=+=-------:...=
+:::::::::::::-+=-:-------=+==-------==--:..=
+:::::::::::==:::::-==++=-----------==----..=
+:::::::::+-::-+=--:::------------+=-------.=
+::::::-+::=+-:::::::::-------=+=----------:=
*=-:::+-==::::-=------==++===---------------=
*---====-=+-:::-::::::::-----------=--------+
*--++=+=-:-------::::::::--------==---------+
*=***=+=--:::::::::-=++====-===+=-----------*
*+*==-----:::::::::::::::-------------------*
#+========----------------==================*
"""
#######################################################################################################
# HGCAL Single Cassette Tester GUI main code (alpha)
# Developed by: Krishna Kant Parida
#        Email: krishna.kant.parida@cern.ch
# Developed on: July 2, 2026
#######################################################################################################

# Dev guides (Notes from bolt.new agent on the current code state):
"""NiceGUI GUI for the HGCAL single-cassette DXF tester.

Enter a cassette name (the .dxf filename without extension) to load its
layout: module footprints are classified (hexagonal / partial-hexagonal /
tile) and grouped into "trains" by their fill color, and engines (the
red circles on the ENGINES layer) are rendered alongside them. A
checkbox legend -- overlaid in the top-left corner of the cassette
display -- lets you toggle the visibility of each train (and the
engines) in the interactive SVG. Hovering a module or engine reveals a
tooltip with its details.

Running a cassette test produces a second interactive display showing
per-module Pass/Fail results (green/red); arrow buttons in the top-right
corner of the display region toggle between the trains view and the
test-results view.
"""

#######################################################################################################
# 2. PACKAGE LISTINGS
#######################################################################################################
import os
import io
import sys
import pytest
import easysnmp
import asyncio
import json
import random
import tempfile
from pathlib import Path
from easysnmp import Session

import ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.svg import SVGBackend
from ezdxf.addons.drawing.layout import Page, Margins

sys.path.append('../test_mpod_ctrl')

from utils.mpod_settings import (
    MPOD_OIDS,
    MPOD_IP,
    CHANNEL_SETTINGS_OFF,
    CHANNEL_SETTINGS_ON
)
from dxf_model import load_cassette, summarize, save_dxf
from svg_builder import build_svg, build_test_svg

from nicegui import ui, app


#######################################################################################################
# 3. GLOBAL VARIABLES AND CONFIGURATIONS
#######################################################################################################

TEST_SCRIPT = Path("/home/hgcal_dev/pytest_dev/dev_gui/test_mpod_ctrl/scripts/test_powerSupply.py")
REPORT_FILE = Path(os.environ.get("SCT", ".")) / "reports" / "power_off.json"

CASSETTE_PATH = Path(__file__).parent / "cassette_layouts"
CMS_LOGO = Path(__file__).parent / "standard_images" / "CMS_logo-002.png"

SHAPE_LABELS = {
    "hex_full": "Full hexagonal modules",
    "hex_partial": "Partial hexagonal modules",
    "tile": "Tile modules",
}

# Ensure report directory exists
REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

# Global UI variable placeholders (populated when the display section builds)
log = None
report_table = None
summary_label = None
is_test_running = False
dark_mode = None

# Available cassette names (populated in the display section)
available: list[str] = []

# State shared between the input handler, the legend, and the test workflow
state = {
    "model": None,            # last loaded CassetteModel
    "visible_trains": {},      # train_id -> bool (trains view)
    "engines_visible": True,
    "wagons_visible": False,
    "wingboards_visible": True,
    "motherboards_visible": True,
    "hd_engines_visible": True,
    "ld_engines_visible": True,
    "test_results": {},        # module.id -> bool (True = pass)
    "view_mode": "trains",     # "trains" | "test"
    "test_in_progress": False,
    "trains_svg_file": None,   # path to temp .svg for the trains view
    "test_svg_file": None,    # path to temp .svg for the test-results view
    "test_svg_history": [],    # list of temp .svg file paths from each test run
    "test_svg_index": -1,     # current index in test_svg_history
    "test_toggle_left": None,  # ui.Button for test-history nav (created dynamically)
    "test_toggle_right": None,
    "save_button": None,       # ui.Button for DXF export (created dynamically)
}

# ---- CSS Styling and theme ----
ui.add_css('''
    @layer utilities {
       .red-background {
           background-color: red !important;
           color: white !important;
        }
       .green-background {
           background-color: green !important;
           color: white !important;
        }
       .blue-background {
           background-color: blue !important;
           color: white !important;
        }
       .yellow-background {
           background-color: yellow !important;
           color: white !important;
        }
    }
    .legend-row { gap: 6px; }
    .legend-swatch {
        width: 18px; height: 18px; border-radius: 4px;
        border: 1px solid rgba(148,163,184,0.5);
        flex-shrink: 0;
    }
    .legend-swatch.engine {
        border-radius: 50%;
    }
    .cassette-svg-wrap svg {
        max-width: 100%; max-height: 100%;
    }
    .module-shape, .module-label, .module-hit,
    .engine-shape, .engine-hit {
        transition: opacity 0.2s ease;
    }
    .dimmed { opacity: 0.12 !important; }
    /* Legend overlay: pinned to the top-left corner of the display area,
       semi-transparent so it doesn't fully obscure the cassette beneath. */
    .legend-overlay {
        position: absolute;
        top: 5px;
        left: 5px;
        z-index: 40;
        max-width: 160px;
        max-height: calc(100% - 10px);
        overflow-y: auto;
        padding: 7px 8px;
        border-radius: 5px;
        border: 1px solid rgba(148,163,184,0.35);
        background: rgba(15, 23, 42, 0.82);
        backdrop-filter: blur(4px);
    }
    .legend-overlay .q-checkbox__label {
        font-size: 0.85rem;
    }
    .legend-overlay .q-checkbox { min-height: 0; padding: 0; }
    .legend-overlay .q-checkbox__inner { width: 22px; height: 22px; }
    .legend-overlay .legend-row { gap: 4px; }
    /* View-toggle arrow buttons pinned to the top-right of the display. */
    .view-toggle {
        position: absolute;
        top: 5px;
        right: 5px;
        z-index: 40;
        gap: 2px;
    }
    .view-toggle .q-btn { min-height: 0; padding: 2px 4px; }
    .view-toggle .q-btn .q-icon { font-size: 18px; }
    /* Progress-bar overlay shown while a test is running. */
    .progress-overlay {
        position: absolute;
        bottom: 8px; left: 8px; right: 8px;
        z-index: 30;
        padding: 10px 14px;
        border-radius: 8px;
        border: 1px solid rgba(148, 163, 184, 0.25);
        background: rgba(15, 23, 42, 0.92);
    }
    .test-display-buttons {
        position: absolute;
        top: 8px; right: 8px;
        z-index: 20;
        gap: 2px;
        padding: 2px 4px;
        border-radius: 8px;
        border: 1px solid rgba(148, 163, 184, 0.25);
        background: rgba(15, 23, 42, 0.82);
    }
    /* ---- Theme-aware display components ---- */
    /* Dark mode is the DEFAULT (the app starts in dark mode). Light mode
       is opt-in via the .cassette-light class on <body>. Train fill colors
       are NEVER changed -- only strokes, labels, legend and tooltip. */
    .cassette-svg-wrap .module-shape,
    .cassette-svg-wrap .engine-shape,
    .cassette-svg-wrap .wagon-shape,
    .cassette-svg-wrap .board-shape {
        stroke: #ffffff;
    }
    .cassette-svg-wrap .module-label,
    .cassette-svg-wrap .wagon-label,
    .cassette-svg-wrap .board-label {
        fill: #f8fafc !important;
    }
    .legend-overlay {
        border-color: rgba(148, 163, 184, 0.35);
        background: rgba(15, 23, 42, 0.82);
    }
    .legend-overlay .text-gray-400 {
        color: #94a3b8 !important;
    }
    .progress-overlay .text-gray-200 {
        color: #e2e8f0 !important;
    }
    #cassette-tooltip {
        background: rgba(15, 23, 42, 0.95);
        border-color: rgba(148, 163, 184, 0.4);
        color: #f1f5f9;
    }
    #cassette-display-area {
        background: rgba(255, 255, 255, 0.02);
    }
    /* Light mode overrides */
    .cassette-light .cassette-svg-wrap .module-shape,
    .cassette-light .cassette-svg-wrap .engine-shape,
    .cassette-light .cassette-svg-wrap .wagon-shape,
    .cassette-light .cassette-svg-wrap .board-shape {
        stroke: #000000;
    }
    .cassette-light .cassette-svg-wrap .module-label,
    .cassette-light .cassette-svg-wrap .wagon-label,
    .cassette-light .cassette-svg-wrap .board-label {
        fill: #0f172a !important;
    }
    .cassette-light .legend-overlay {
        border-color: rgba(100, 116, 139, 0.35);
        background: rgba(241, 245, 249, 0.88);
    }
    .cassette-light .legend-overlay .text-gray-400 {
        color: #475569 !important;
    }
    .cassette-light .progress-overlay .text-gray-200 {
        color: #0f172a !important;
    }
    .cassette-light #cassette-tooltip {
        background: rgba(241, 245, 249, 0.95);
        border-color: rgba(100, 116, 139, 0.4);
        color: #0f172a;
    }
    .cassette-light #cassette-display-area {
        background: rgba(0, 0, 0, 0.02);
    }
''')

# ---- Cassette display hover/tooltip JS + visibility toggle JS ----
ui.add_head_html(
    """
    <script>
    function cassetteHover(evt, text) {
        const tip = document.getElementById('cassette-tooltip');
        if (!tip) return;
        tip.innerText = text;
        tip.style.display = 'block';
        cassetteMove(evt);
    }
    function cassetteMove(evt) {
        const tip = document.getElementById('cassette-tooltip');
        const container = document.getElementById('cassette-display-area');
        if (!tip || !container) return;
        const rect = container.getBoundingClientRect();
        let x = evt.clientX - rect.left + 14;
        let y = evt.clientY - rect.top + 14;
        const maxX = Math.max(rect.width - tip.offsetWidth - 8, 0);
        const maxY = Math.max(rect.height - tip.offsetHeight - 8, 0);
        x = Math.min(Math.max(x, 0), maxX);
        y = Math.min(Math.max(y, 0), maxY);
        tip.style.left = x + 'px';
        tip.style.top = y + 'px';
    }
    function cassetteLeave() {
        const tip = document.getElementById('cassette-tooltip');
        if (!tip) return;
        tip.style.display = 'none';
    }
    // Dark mode is the CSS default (no class needed). Light mode is opt-in
    // via the .cassette-light class on <body>.
    // Toggle visibility of every SVG element belonging to a train. When a
    // train is unchecked, its modules/engines/labels are dimmed (not
    // removed) so the layout stays stable and re-toggling is instant.
    function setTrainVisible(trainId, visible) {
        const svg = document.querySelector((wrapSelector || '.cassette-svg-wrap') + ' svg');
        if (!svg) return;
        const sel = `[data-train="${CSS.escape(trainId)}"]`;
        svg.querySelectorAll(sel).forEach((el) => {
            if (visible) el.classList.remove('dimmed');
            else el.classList.add('dimmed');
        });
    }
    function setWagonsVisible(visible, wrapSelector) {
        const svg = document.querySelector((wrapSelector || '.cassette-svg-wrap') + ' svg');
        if (!svg) return;
        svg.querySelectorAll('[data-wagon="true"]').forEach((el) => {
            if (visible) el.classList.remove('dimmed');
            else el.classList.add('dimmed');
        });
    }
    function setEnginesVisible(visible, wrapSelector) {
        const svg = document.querySelector((wrapSelector || '.cassette-svg-wrap') + ' svg');
        if (!svg) return;
        svg.querySelectorAll('.engine-shape, .engine-hit').forEach((el) => {
            if (visible) el.classList.remove('dimmed');
            else el.classList.add('dimmed');
        });
    }
    function setBoardsVisible(visible, wrapSelector) {
        const svg = document.querySelector((wrapSelector || '.cassette-svg-wrap') + ' svg');
        if (!svg) return;
        svg.querySelectorAll('.board-shape, .board-hit').forEach((el) => {
            if (visible) el.classList.remove('dimmed');
            else el.classList.add('dimmed');
        });
    }
    function setHDEnginesVisible(visible, wrapSelector) {
        const svg = document.querySelector((wrapSelector || '.cassette-svg-wrap') + ' svg');
        if (!svg) return;
        svg.querySelectorAll('[data-engine-density="HD"]').forEach((el) => {
            if (visible) el.classList.remove('dimmed');
            else el.classList.add('dimmed');
        });
    }
    function setLDEnginesVisible(visible, wrapSelector) {
        const svg = document.querySelector((wrapSelector || '.cassette-svg-wrap') + ' svg');
        if (!svg) return;
        svg.querySelectorAll('[data-engine-density="LD"]').forEach((el) => {
            if (visible) el.classList.remove('dimmed');
            else el.classList.add('dimmed');
        });
    }
    function setMotherboardsVisible(visible, wrapSelector) {
        const svg = document.querySelector((wrapSelector || '.cassette-svg-wrap') + ' svg');
        if (!svg) return;
        svg.querySelectorAll('[data-motherboard="true"]').forEach((el) => {
            if (visible) el.classList.remove('dimmed');
            else el.classList.add('dimmed');
        });
    }
    </script>
    """
)

# ---- MPOD test table appearance controls ----
ui.add_css('''
    .test-table {
        font-size: 0.9em;
    }
    .test-table tbody tr {
        padding: 8px;
    }
    :root {
    --table-odd-bg: #fafafa;
    --table-even-bg: #ffffff;
    --table-text: #222222;
    }
    body.body--dark {
    --table-odd-bg: #2a2a2a;
    --table-even-bg: #1e1e1e;
    --table-text: #eeeeee;
    }

    .test-table tbody tr:nth-child(odd) {
        background-color: var(--table-odd-bg);
        color: var(--table-text);
    }
    .test-table tbody tr:nth-child(even) {
        background-color: var(--table-even-bg);
        color: var(--table-text);
    }
    .passed-row {
        background-color: #f0f8f0 !important;
        color: #2d5016;
    }
    .failed-row {
        background-color: #ffe6e6 !important;
        color: #8b0000;
    }
''')

dark_mode = ui.dark_mode()
dark_mode.enable()  # start in dark mode


#######################################################################################################
# 4. ALL UI AND INTERACTIVE FUNCTIONS
#######################################################################################################

def discover_cassettes() -> list[str]:
    if not CASSETTE_PATH.exists():
        return []
    return sorted(p.stem for p in CASSETTE_PATH.glob("*.dxf"))


def _on_theme_toggle(e):
    """Toggle dark mode and the cassette display's colour scheme."""
    if e.value:
        dark_mode.enable()
        ui.run_javascript('document.body.classList.remove("cassette-light");')
    else:
        dark_mode.disable()
        ui.run_javascript('document.body.classList.add("cassette-light");')


# ---- Test history navigation (arrow buttons) ----

def _update_toggle_buttons() -> None:
    tl = state.get("test_toggle_left")
    tr = state.get("test_toggle_right")
    if tl is None or tr is None:
        return
    history = state.get("test_svg_history", [])
    idx = state.get("test_svg_index", -1)
    if not history or idx < 0:
        tl.props("disabled")
        tr.props("disabled")
        return
    if idx > 0:
        tl.props(remove="disabled")
    else:
        tl.props("disabled")
    if idx < len(history) - 1:
        tr.props(remove="disabled")
    else:
        tr.props("disabled")


def _on_test_toggle_left() -> None:
    history = state.get("test_svg_history", [])
    idx = state.get("test_svg_index", -1)
    if idx > 0:
        state["test_svg_index"] = idx - 1
        svg_content = _load_svg_temp(history[idx - 1])
        if svg_content is not None:
            _render_svg_content(svg_content, test_svg_slot)
            model = state["model"]
            if model is not None:
                _render_test_legend(model, state["test_results"])
    _update_toggle_buttons()


def _on_test_toggle_right() -> None:
    history = state.get("test_svg_history", [])
    idx = state.get("test_svg_index", -1)
    if idx < len(history) - 1:
        state["test_svg_index"] = idx + 1
        svg_content = _load_svg_temp(history[idx + 1])
        if svg_content is not None:
            _render_svg_content(svg_content, test_svg_slot)
            model = state["model"]
            if model is not None:
                _render_test_legend(model, state["test_results"])
    _update_toggle_buttons()


# ---- Save DXF button ----

def _update_save_button() -> None:
    sb = state.get("save_button")
    if sb is None:
        return
    if state.get("test_results"):
        sb.props(remove="disabled")
    else:
        sb.props("disabled")


def _on_save_dxf() -> None:
    model = state["model"]
    if model is None:
        return
    import tempfile, os
    fd, tmp_path = tempfile.mkstemp(suffix=".dxf", prefix="cassette_")
    os.close(fd)
    save_dxf(model, tmp_path)
    ui.download(tmp_path)


# ---- Legend rendering (trains view) ----

def _render_legend(model) -> None:
    """Build the checkbox legend from the model's trains and engines."""
    legend_container.clear()
    with legend_container:
        ui.label("Trains and Engines").classes(
            "text-sm text-gray-400"
        )
        train_has_elements = {
            t.id: (
                any(m.train_id == t.id for m in model.modules)
                or any(e.train_id == t.id for e in model.engines)
                or any(w.train_id == t.id for w in model.wagon_links)
                or any(wb.train_id == t.id for wb in model.wingboards)
            )
            for t in model.trains
        }
        for t in model.trains:
            if not train_has_elements.get(t.id, False):
                continue
            r, g, b = t.color_rgb
            swatch = f"rgb({r},{g},{b})"

            label = t.label
            if label.startswith("Train "):
                engine_types = sorted(
                    {e.engine_type for e in model.engines if e.train_id == t.id and e.engine_type}
                )
                label = f"Engine: {', '.join(engine_types)}" if engine_types else "Engine"
            with ui.row().classes("legend-row w-full items-center"):
                cb = ui.checkbox(
                    text=t.label,
                    value=True,
                    on_change=lambda e, tid=t.id: _on_train_toggle(tid, e.value),
                ).classes("flex-1")
                cb.tooltip(f"Color: rgb({r}, {g}, {b})  |  Train ID: {t.id}")
                ui.element("div").classes("legend-swatch").style(
                    f"background:{swatch};"
                )

        if model.engines:
            ui.separator().classes("w-full")
            with ui.row().classes("legend-row w-full items-center"):
                e0 = model.engines[0]
                r, g, b = e0.color_rgb
                swatch = f"rgb({r},{g},{b})"
                ui.checkbox(
                    text="Engines",
                    value=state["engines_visible"],
                    on_change=lambda e: _on_engines_toggle(e.value),
                ).classes("flex-1").tooltip("Engine circles on the ENGINES layer")
                ui.element("div").classes("legend-swatch engine").style(
                    f"background:{swatch};"
                )
            # Motherboards checkbox
            has_motherboards = any(e.motherboard for e in model.engines)
            if has_motherboards:
                with ui.row().classes("legend-row w-full items-center"):
                    ui.checkbox(
                        text="Motherboards",
                        value=state["motherboards_visible"],
                        on_change=lambda e: _on_motherboards_toggle(e.value),
                    ).classes("flex-1").tooltip("Motherboard info overlaid on engines")
                    ui.element("div").classes("legend-swatch engine").style(
                        "background:#a78bfa;"
                    )
            # HD Engines checkbox
            hd_engines = [e for e in model.engines if e.density == "HD"]
            if hd_engines:
                with ui.row().classes("legend-row w-full items-center"):
                    ui.checkbox(
                        text="HD Engines",
                        value=state["hd_engines_visible"],
                        on_change=lambda e: _on_hd_engines_toggle(e.value),
                    ).classes("flex-1").tooltip("High Density silicon module engines")
                    ui.element("div").classes("legend-swatch engine").style(
                        "background:#f97316;"
                    )
            # LD Engines checkbox
            ld_engines = [e for e in model.engines if e.density == "LD"]
            if ld_engines:
                with ui.row().classes("legend-row w-full items-center"):
                    ui.checkbox(
                        text="LD Engines",
                        value=state["ld_engines_visible"],
                        on_change=lambda e: _on_ld_engines_toggle(e.value),
                    ).classes("flex-1").tooltip("Low Density silicon module engines")
                    ui.element("div").classes("legend-swatch engine").style(
                        "background:#3b82f6;"
                    )

        has_wagons = bool(model.wagon_links)
        if has_wagons:
            ui.separator().classes("w-full")
            with ui.row().classes("legend-row w-full items-center"):
                ui.checkbox(
                    text="Wagons",
                    value=state["wagons_visible"],
                    on_change=lambda e: _on_wagons_toggle(e.value),
                ).classes("flex-1").tooltip("Dashed wagon connector overlays")
                ui.element("div").classes("legend-swatch wagon").style(
                    "background:rgba(148,163,184,0.45);border-style:dashed;"
                )
        # Wingboards just below wagons
        if model.wingboards:
            ui.separator().classes("w-full")
            with ui.row().classes("legend-row w-full items-center"):
                ui.checkbox(
                    text="Wingboards",
                    value=state["wingboards_visible"],
                    on_change=lambda e: _on_wingboards_toggle(e.value),
                ).classes("flex-1").tooltip("Wingboard blocks at E/G module boundaries")
                ui.element("div").classes("legend-swatch wingboard").style(
                    "background:rgba(56,189,248,0.42);border-style:dashed;border-color:#e0f2fe;"
                )


# ---- Legend rendering (test results view) ----

def _render_test_legend(model, results) -> None:
    """Build the checkbox legend for the test-results view showing Pass/Fail counts."""
    test_legend_container.clear()
    with test_legend_container:
        ui.label("Test Results").classes("text-sm text-gray-400")
        passed = sum(1 for v in results.values() if v)
        failed = sum(1 for v in results.values() if not v)
        with ui.row().classes("legend-row w-full items-center"):
            ui.checkbox(
                text=f"Pass ({passed})",
                value=True,
                on_change=lambda e: _on_test_toggle("pass", e.value),
            ).classes("flex-1").tooltip("Modules that passed the test")
            ui.element("div").classes("legend-swatch").style("background:#22c55e;")
        with ui.row().classes("legend-row w-full items-center"):
            ui.checkbox(
                text=f"Fail ({failed})",
                value=True,
                on_change=lambda e: _on_test_toggle("fail", e.value),
            ).classes("flex-1").tooltip("Modules that failed the test")
            ui.element("div").classes("legend-swatch").style("background:#ef4444;")


# ---- Visibility toggle handlers (trains view) ----

def _on_train_toggle(train_id: str, visible: bool) -> None:
    state["visible_trains"][train_id] = visible
    ui.run_javascript(
        f'setTrainVisible({train_id!r}, {"true" if visible else "false"}, \'.trains-svg-wrap\');'
    )


def _on_wagons_toggle(visible: bool) -> None:
    state["wagons_visible"] = visible
    v = "true" if visible else "false"
    ui.run_javascript(f"setWagonsVisible({v}, '.trains-svg-wrap');")


def _on_wingboards_toggle(visible: bool) -> None:
    state["wingboards_visible"] = visible
    v = "true" if visible else "false"
    ui.run_javascript(f"setBoardsVisible({v}, '.trains-svg-wrap');")


def _on_motherboards_toggle(visible: bool) -> None:
    state["motherboards_visible"] = visible
    v = "true" if visible else "false"
    ui.run_javascript(f"setMotherboardsVisible({v}, '.trains-svg-wrap');")


def _on_hd_engines_toggle(visible: bool) -> None:
    state["hd_engines_visible"] = visible
    v = "true" if visible else "false"
    ui.run_javascript(f"setHDEnginesVisible({v}, '.trains-svg-wrap');")


def _on_ld_engines_toggle(visible: bool) -> None:
    state["ld_engines_visible"] = visible
    v = "true" if visible else "false"
    ui.run_javascript(f"setLDEnginesVisible({v}, '.trains-svg-wrap');")


def _on_engines_toggle(visible: bool) -> None:
    state["engines_visible"] = visible
    ui.run_javascript(f'setEnginesVisible({"true" if visible else "false"}, \'.trains-svg-wrap\');')


# ---- Visibility toggle handler (test view) ----

def _on_test_toggle(status: str, visible: bool) -> None:
    ui.run_javascript(
        f'setTrainVisible({status!r}, {"true" if visible else "false"}, \'.test-svg-wrap\');'
    )


# ---- SVG temp file helpers ----

def _save_svg_temp(svg_content: str, label: str) -> str | None:
    """Write SVG content to a temp file and return its path."""
    try:
        fd, path = tempfile.mkstemp(suffix=f"_{label}.svg", prefix="cassette_")
        with os.fdopen(fd, "w") as f:
            f.write(svg_content)
        return path
    except OSError:
        return None


def _load_svg_temp(path: str) -> str | None:
    """Read SVG content back from a temp file."""
    try:
        with open(path, "r") as f:
            return f.read()
    except (OSError, FileNotFoundError):
        return None


def _render_svg_content(svg_content: str, slot=None) -> None:
    """Push SVG markup into a svg slot (default: trains)."""
    if slot is None:
        slot = trains_svg_slot
    slot.clear()
    with slot:
        ui.html(svg_content, sanitize=False).classes("w-full h-full")


# ---- View rendering ----

def _render_view() -> None:
    """Render SVGs for both display sections.

    The trains display always shows the cassette layout. The test display
    shows test results if available, or a placeholder otherwise.
    """
    model = state["model"]
    if model is None:
        return

    # Always render the trains view in the top display
    svg_content = build_svg(model)
    _render_legend(model)
    state["trains_svg_file"] = _save_svg_temp(svg_content, "trains")
    _render_svg_content(svg_content, trains_svg_slot)

    # Apply visibility state via JS (fixes wagons-showing-on-load bug)
    ui.run_javascript(
        f'setWagonsVisible({"true" if state["wagons_visible"] else "false"}, '
        f"'.trains-svg-wrap');"
    )
    ui.run_javascript(
        f'setEnginesVisible({"true" if state["engines_visible"] else "false"}, '
        f"'.trains-svg-wrap');"
    )
    ui.run_javascript(
        f'setBoardsVisible({"true" if state["wingboards_visible"] else "false"}, '
        f"'.trains-svg-wrap');"
    )
    ui.run_javascript(
        f'setMotherboardsVisible({"true" if state["motherboards_visible"] else "false"}, '
        f"'.trains-svg-wrap');"
    )
    ui.run_javascript(
        f'setHDEnginesVisible({"true" if state["hd_engines_visible"] else "false"}, '
        f"'.trains-svg-wrap');"
    )
    ui.run_javascript(
        f'setLDEnginesVisible({"true" if state["ld_engines_visible"] else "false"}, '
        f"'.trains-svg-wrap');"
    )
    for tid, vis in state["visible_trains"].items():
        ui.run_javascript(
            f'setTrainVisible({tid!r}, {"true" if vis else "false"}, '
            f"'.trains-svg-wrap');"
        )

    # Render the test display if results exist
    if state["test_results"]:
        test_svg = build_test_svg(model, state["test_results"])
        _render_test_legend(model, state["test_results"])
        state["test_svg_file"] = _save_svg_temp(test_svg, "test")
        _render_svg_content(test_svg, test_svg_slot)
    else:
        test_svg_slot.clear()
        with test_svg_slot:
            ui.label("Run a test to see results.").classes(
                "text-sm text-gray-400"
            )


# ---- Cassette loading ----

def load_selected(name: str) -> None:
    trains_svg_slot.clear()
    test_svg_slot.clear()
    test_legend_container.clear()
    dynamic_container.clear()
    summary_table.rows = []
    summary_table.update()
    legend_container.clear()
    with legend_container:
        ui.label("Load a cassette to see trains.").classes(
            "text-sm text-gray-400"
        )
    with test_legend_container:
        ui.label("Run a test to see results.").classes(
            "text-sm text-gray-400"
        )

    # reset test/view state on every (re)load
    state["model"] = None
    state["test_results"] = {}
    state["view_mode"] = "trains"
    state["test_in_progress"] = False
    state["test_svg_history"] = []
    state["test_svg_index"] = -1
    progress_container.style("display:none;")
    _update_toggle_buttons()
    _update_save_button()

    # reset cassette test summary table
    cassette_test_summary_table.rows = []
    cassette_test_summary_table.update()

    if not name:
        return

    filepath = CASSETTE_PATH / f"{name}.dxf"
    if not filepath.exists():
        with trains_svg_slot:
            ui.label(
                f"No file named '{name}.dxf' in cassette_layouts/."
            ).classes("text-red-400")
        if available:
            with legend_container:
                ui.label(
                    f"Available: {', '.join(available)}"
                ).classes("text-sm text-gray-400")
        return

    try:
        model = load_cassette(str(filepath), name)
    except Exception as ex:
        with trains_svg_slot:
            ui.label(f"Failed to load {name}: {ex}").classes("text-red-400")
        return

    state["model"] = model
    state["visible_trains"] = {t.id: True for t in model.trains}
    state["engines_visible"] = True
    state["wagons_visible"] = True
    state["wingboards_visible"] = True
    state["motherboards_visible"] = True
    state["hd_engines_visible"] = True
    state["ld_engines_visible"] = True

    summary = summarize(model)
    summary_table.rows = [
        {"field": "Cassette", "value": name},
        {"field": "Cassette Type", "value": summary.cassette_type},
        {"field": "Full Hex Modules", "value": summary.full_hex},
        {"field": "Partial Hex Modules", "value": summary.partial_hex},
        {"field": "Tile Modules", "value": summary.tile},
        {"field": "Trains", "value": summary.trains},
        {"field": "Engines", "value": summary.engines},
        {"field": "Wingboards", "value": summary.wingboards},
        {"field": "Motherboards", "value": summary.motherboards},
    ]
    summary_table.update()

    _render_view()
    _update_toggle_buttons()
    _update_save_button()

    # cassette is fully loaded (table + display populated) -- enable the
    # run button so a test can be executed for this cassette.
    with dynamic_container:
        with ui.row().classes("w-full gap-2 items-center"):
            cassette_run_button = ui.button(
                "Run Cassette Test",
                on_click=run_tests,
            ).classes("green-background flex-1")


# ---- MPOD report data helpers ----

def load_report_data():
    """Load report and extract test data for table display"""
    if REPORT_FILE.exists():
        try:
            with open(REPORT_FILE) as f:
                report = json.load(f)

                # Extract summary
                summary = report.get("summary", {})
                passed = summary.get("passed", 0)
                total = summary.get("total", 0)
                collected = summary.get("collected", 0)
                deselected = summary.get("deselected", 0)

                # Extract test details
                tests = report.get("tests", [])

                return {
                    "summary": summary,
                    "passed": passed,
                    "total": total,
                    "collected": collected,
                    "deselected": deselected,
                    "tests": tests
                }
        except Exception as e:
            print(f"Error loading report: {e}")
            return None
    return None


def update_summary_stats():
    """Update the summary statistics label"""
    global summary_label
    summary_data = load_report_data()

    if summary_data and summary_label:
        total = summary_data['total']
        passed = summary_data['passed']
        deselected = summary_data['deselected']
        summary_label.text = f"Total: {total} | Passed: {passed} | Deselected: {deselected}"


def refresh_report_table():
    """Refresh the report table with latest data"""
    global report_table
    summary_data = load_report_data()

    if summary_data and summary_data['tests'] and report_table is not None:
        rows = []
        for test in summary_data['tests'][:50]:  # Show first 50 tests for performance
            test_nodeid = test.get('nodeid', '')
            test_name = test_nodeid.split('::')[-1] if '::' in test_nodeid else test_nodeid

            call_data = test.get('call', {})
            duration_ms = call_data.get('duration', 0) * 1000
            outcome = test.get('outcome', 'unknown').upper()

            rows.append({
                'test_name': test_name,
                'outcome': outcome,
                'duration': f"{duration_ms:.2f}",
                'line_no': test.get('lineno', '-'),
            })

        # Update table rows (use update method instead of setting rows directly)
        report_table.rows = rows
        report_table.update()
        update_summary_stats()


async def update_report_continuously():
    """Continuously refresh the report while tests are running."""
    while is_test_running:
        try:
            refresh_report_table()
        except Exception as e:
            print(f"Error updating report: {e}")

        await asyncio.sleep(1)


#######################################################################################################
# 5. ALL MAJOR TEST FUNCTIONS
#######################################################################################################

# MPOD test (configured for VCUs available in Fermilab SiDet Lab C)
async def run_mpod_tests():
    """Run pytest tests and display live output"""
    global is_test_running

    if is_test_running:
        ui.notify("Tests already running", color="warning")
        return

    is_test_running = True
    mpod_run_button.enabled = False

    try:
        log.clear()

        # Remove old report file
        if REPORT_FILE.exists():
            REPORT_FILE.unlink()

        # Start continuous report update task
        update_task = asyncio.create_task(update_report_continuously())

        # Run pytest
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m", "pytest",
            str(TEST_SCRIPT),
            "--json-report",
            f"--json-report-file={REPORT_FILE}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        # Stream output to log
        while True:
            line = await process.stdout.readline()

            if not line:
                break

            log.push(line.decode().rstrip())

        returncode = await process.wait()

        # Stop update task
        update_task.cancel()
        try:
            await update_task
        except asyncio.CancelledError:
            pass

        # Final update
        refresh_report_table()

        # Notify result
        if returncode == 0:
            ui.notify("All Tests Passed", color="positive")
        else:
            ui.notify("Some Tests Failed", color="negative")

    except Exception as e:
        ui.notify(f"Error running tests: {str(e)}", color="negative")
        log.push(f"ERROR: {str(e)}")

    finally:
        is_test_running = False
        mpod_run_button.enabled = True


# Cassette baseline test
# (placeholder with RNG, to be updated with actual test guided using fe_micromanager)
async def run_tests() -> None:
    """Run a (simulated) cassette test and display per-module results.

    Uses the model already loaded by ``load_selected`` -- the run button is
    kept disabled until that load completes, so ``state["model"]`` is
    guaranteed to be set when this handler fires.
    """
    model = state["model"]
    if model is None or state["test_in_progress"]:
        return

    state["test_in_progress"] = True

    # show the progress overlay and reset the bar
    progress_container.style("display:flex;")
    progress_container.update()
    progress_bar.value = 0.0
    progress_bar.update()
    progress_label.text = "Running cassette test..."
    progress_label.update()

    # simulate test work with incremental progress
    for pct in range(0, 101, 5):
        progress_bar.value = pct / 100.0
        progress_bar.update()
        await asyncio.sleep(0.05)

    progress_label.text = "Test complete!"
    progress_label.update()
    await asyncio.sleep(0.2)

    # classify ~5% of modules as failed, rest pass
    module_ids = [m.id for m in model.modules]
    fail_count = max(1, round(len(module_ids) * 0.05)) if module_ids else 0
    failed = set(random.sample(module_ids, fail_count)) if module_ids else set()
    results = {mid: (mid not in failed) for mid in module_ids}
    state["test_results"] = results

    # update cassette test summary table
    passed_count = sum(1 for v in results.values() if v)
    failed_count = sum(1 for v in results.values() if not v)
    cassette_test_summary_table.rows = [
        {"status": "Total Modules", "count": len(results)},
        {"status": "Passed", "count": passed_count},
        {"status": "Failed", "count": failed_count},
    ]
    cassette_test_summary_table.update()

    # hide the progress overlay
    progress_container.style("display:none;")
    progress_container.update()

    # switch to the test-results view
    state["view_mode"] = "test"
    _render_view()

    # Save this test SVG to history for arrow-button navigation
    svg_file = state.get("test_svg_file")
    if svg_file:
        state["test_svg_history"].append(svg_file)
        state["test_svg_index"] = len(state["test_svg_history"]) - 1
    _update_toggle_buttons()
    _update_save_button()

    state["test_in_progress"] = False


#######################################################################################################
# 6. DISPLAY SECTION
#######################################################################################################

# =====================================================================================================
# 6a. UI Header (logo, heading, and dropdown menu)
# =====================================================================================================
with ui.row().classes('w-full items-center justify-between'):

    with ui.row().classes("items-center gap-4 no-wrap"):
        # CMS logo first
        with ui.column().classes("gap-0"):
            ui.image("standard_images/CMS_logo-002.png").style(
                "height:90px; width:90px;"
            ).props("alt=CMS logo")
        # then the title
        with ui.column().classes("gap-0"):
            ui.label("High Granularity Calorimeter (CE-H)").style(
                "font-size:24px;font-weight:bold;"
            )
            ui.label("Single Cassette Tester").style(
                "font-size:24px;font-weight:bold;"
            )

    # Top-right dropdown menu section
    with ui.button(icon='menu').props('flat round'):
        with ui.menu().props('trigger="hover"'):
            with ui.menu_item(auto_close=False):
                with ui.row().classes("items-center gap-3 no-wrap"):
                    ui.label("Theme").classes("text-sm")
                    ui.switch(
                        value=True,
                        on_change=lambda e: dark_mode.enable() if e.value else dark_mode.disable(),
                    ).props('checked-icon="dark_mode" unchecked-icon="light_mode" color="blue-grey-7"')

            ui.menu_item('Test Workflow')
            ui.menu_item('Documentation')
            ui.menu_item('Settings')

            ui.separator()

            ui.menu_item(
                'Shutdown',
                on_click=lambda: app.shutdown()
            ).classes('red-background')

ui.separator()

# =====================================================================================================
# 6b. Cassette Information
#    LEFT: Cassette name entry box + summary table
#    RIGHT: Interactive display for trains and all components
# =====================================================================================================
with ui.row().classes("w-full gap-4 flex-nowrap").style("height: 78vh;"):
    # ---- LEFT COLUMN: Cassette Selection + summary table ----
    with ui.column().classes("flex-1 gap-3"):
        ui.markdown("## Cassette Information")

        available = discover_cassettes()
        placeholder = "e.g. Cassette_7B_33B"
        if available:
            placeholder = f"e.g. {available[0]}"
        cassette_input = ui.input(
            label="Cassette name:",
            placeholder=placeholder,
        ).classes("w-full").tooltip("Enter the .dxf filename without extension")

        summary_table = (
            ui.table(
                columns=[
                    {"name": "field", "label": "Field", "field": "field", "align": "left"},
                    {"name": "value", "label": "Value", "field": "value", "align": "left"},
                ],
                rows=[],
                row_key="field",
            )
            .classes("w-full")
            .props("flat bordered hide-header")
        )

    # ---- RIGHT COLUMN: Interactive cassette display ----
    with ui.column().classes("flex-1 h-full"):
        with (
            ui.column()
            .classes("w-full h-full border rounded-lg relative overflow-hidden")
            .props('id="cassette-display-area"')
            .style("position: relative; min-height: 0;")
        ):
            trains_svg_slot = ui.element("div").classes(
                "cassette-svg-wrap trains-svg-wrap w-full h-full flex items-center justify-center"
            )

            # Legend overlay pinned to the top-left corner of the display area
            with ui.column().classes("legend-overlay gap-1") as legend_container:
                legend_hint = ui.label("Load a cassette to see trains.").classes(
                    "text-sm text-gray-400"
                )

            ui.element("div").props('id="cassette-tooltip"').classes(
                "absolute rounded-md border px-3 py-2 text-sm shadow-lg whitespace-pre-line"
            ).style(
                "display:none; position:absolute; z-index:50; pointer-events:none; "
                "max-width: 260px;"
            )

# Bind cassette input changes to the load handler
cassette_input.on_value_change(lambda e: load_selected(e.value))

ui.separator()

# =====================================================================================================
# 6c. MPOD Testing
#    LEFT: MPOD ID + Run MPOD Test button + output log
#    RIGHT: Pytest report table
# =====================================================================================================
with ui.row().classes("w-full gap-4"):

    # ---- LEFT COLUMN: Controls and Logs ----
    with ui.column().classes("flex-1"):

        ui.markdown("## MPOD Information")
        ui.label(f"MPOD IP: {MPOD_IP}").style("font-weight: bold;")

        # Control Buttons
        with ui.row().classes("w-1/2 gap-2"):
            mpod_run_button = ui.button(
                "Run MPOD Tests",
                on_click=run_mpod_tests,
            ).classes("green-background flex-1")

        ui.separator()

        # Pytest Logs
        ui.markdown("## Pytest Logs")
        log = ui.log().classes("w-full h-96 border")

    # ---- RIGHT COLUMN: Report Table ----
    with ui.column().classes("flex-1"):

        ui.markdown("## Pytest Report")

        # Summary Statistics
        with ui.row().classes("w-full gap-4 mb-4"):
            summary_label = ui.label("No tests run yet").style("font-weight: bold;")

        # Test Results Table
        columns = [
            {'name': 'test_name', 'label': 'Test Name', 'field': 'test_name', 'align': 'left'},
            {'name': 'outcome', 'label': 'Outcome', 'field': 'outcome', 'align': 'center'},
            {'name': 'duration', 'label': 'Duration (ms)', 'field': 'duration', 'align': 'right'},
            {'name': 'line_no', 'label': 'Line No', 'field': 'line_no', 'align': 'center'},
        ]

        report_table = ui.table(
            columns=columns,
            rows=[]
        ).classes("test-table w-full").props('table-style="max-height: 525px"')

ui.separator()

# =====================================================================================================
# 6d. Cassette Testing
#    LEFT: Run Cassette Test button + summary table (pass/fail counts)
#    RIGHT: Interactive display for tested cassettes (arrows + save button)
# =====================================================================================================
with ui.row().classes("w-full gap-4 flex-nowrap").style("height: 78vh;"):
    # ---- LEFT COLUMN: Test Control Button + Summary Table ----
    with ui.column().classes("w-1/4 gap-3"):
        ui.markdown("## Cassette Test")

        # Dynamic container for the run button (populated when a cassette loads)
        dynamic_container = ui.row().classes("w-full")

        ui.separator()

        ui.markdown("### Test Summary")
        cassette_test_summary_table = (
            ui.table(
                columns=[
                    {"name": "status", "label": "Status", "field": "status", "align": "left"},
                    {"name": "count", "label": "Count", "field": "count", "align": "center"},
                ],
                rows=[],
                row_key="status",
            )
            .classes("w-full")
            .props("flat bordered")
        )

    # ---- RIGHT COLUMN: Interactive tested cassette display ----
    with (
        ui.column()
        .classes("w-full flex-1 border rounded-lg relative overflow-hidden")
        .props('id="test-display-area"')
        .style("position: relative; min-height: 0;")
    ):
        test_svg_slot = ui.element("div").classes(
            "cassette-svg-wrap test-svg-wrap w-full h-full flex items-center justify-center"
        )
        with ui.column().classes("legend-overlay gap-1") as test_legend_container:
            ui.label("Run a test to see results.").classes(
                "text-sm text-gray-400"
            )
        # Arrow + save buttons pinned to top-right of test display
        with ui.row().classes("test-display-buttons") as test_buttons_row:
            state["test_toggle_left"] = ui.button(icon="arrow_back").props(
                "flat round dense color=blue-grey-4"
            ).props("disabled").tooltip("Previous test result")
            state["test_toggle_right"] = ui.button(icon="arrow_forward").props(
                "flat round dense color=blue-grey-4"
            ).props("disabled").tooltip("Next test result")
            state["save_button"] = ui.button(icon="save").props(
                "flat round dense color=blue-grey-4"
            ).props("disabled").tooltip("Save tested cassette as .dxf")
            state["test_toggle_left"].on_click(_on_test_toggle_left)
            state["test_toggle_right"].on_click(_on_test_toggle_right)
            state["save_button"].on_click(_on_save_dxf)

        # Progress-bar overlay shown while a test is running.
        with ui.column().classes("progress-overlay") as progress_container:
            progress_label = ui.label("Running cassette test...").classes(
                "text-sm text-gray-200 mb-2"
            )
            progress_bar = ui.linear_progress(value=0).props(
                "color=green-6 rounded"
            ).classes("w-full")
        progress_container.style("display:none;")


#######################################################################################################
# Running GUI at Port 9000
#######################################################################################################

ui.run(
    title="[HGCAL] Single Cassette Tester",
    port=9000
)
