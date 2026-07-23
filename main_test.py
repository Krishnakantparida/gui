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

import random
from pathlib import Path
import asyncio
from nicegui import ui, app

from dxf_model import load_cassette, summarize
from svg_builder import build_svg, build_test_svg

CASSETTE_DIR = Path(__file__).parent / "cassette_layouts"
CMS_LOGO = Path(__file__).parent / "standard_images" / "CMS_logo-002.png"


def discover_cassettes() -> list[str]:
    if not CASSETTE_DIR.exists():
        return []
    return sorted(p.stem for p in CASSETTE_DIR.glob("*.dxf"))


ui.add_css("""
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
    .legend-row { gap: 4px; }
    .legend-swatch {
        width: 11px; height: 11px; border-radius: 3px;
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
       semi-transparent so it doesn't fully obscure the cassette beneath.
       Sized at 2/3 (~1/1.5) of the original dimensions. */
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
        border: 1px solid rgba(100, 116, 139, 0.35);
        background: rgba(241, 245, 249, 0.88);
        backdrop-filter: blur(4px);
    }
    .legend-overlay .q-checkbox__label {
        font-size: 0.57rem;
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
        top: 50%; left: 50%;
        transform: translate(-50%, -50%);
        z-index: 45;
        width: 60%;
        text-align: center;
    }
    /* ---- Theme-aware display components ---- */
    /* Light mode (default): black strokes, light legend/tooltip */
    .cassette-svg-wrap .module-shape,
    .cassette-svg-wrap .engine-shape {
        stroke: #000000;
    }
    .legend-overlay .text-gray-400 {
        color: #475569 !important;
    }
    .progress-overlay .text-gray-200 {
        color: #0f172a !important;
    }
    #cassette-tooltip {
        background: rgba(241, 245, 249, 0.95);
        border-color: rgba(100, 116, 139, 0.4);
        color: #0f172a;
    }
    #cassette-display-area {
        background: rgba(0, 0, 0, 0.02);
    }
    /* Dark mode: white strokes, dark legend/tooltip */
    .cassette-dark .cassette-svg-wrap .module-shape,
    .cassette-dark .cassette-svg-wrap .engine-shape {
        stroke: #ffffff;
    }
    .cassette-dark .legend-overlay {
        border-color: rgba(148, 163, 184, 0.35);
        background: rgba(15, 23, 42, 0.82);
    }
    .cassette-dark .legend-overlay .text-gray-400 {
        color: #94a3b8 !important;
    }
    .cassette-dark .progress-overlay .text-gray-200 {
        color: #e2e8f0 !important;
    }
    .cassette-dark #cassette-tooltip {
        background: rgba(15, 23, 42, 0.95);
        border-color: rgba(148, 163, 184, 0.4);
        color: #f1f5f9;
    }
    .cassette-dark #cassette-display-area {
        background: rgba(255, 255, 255, 0.02);
    }
""")

# One set of hover-tooltip helpers shared by every rendered SVG. Positioning
# is done in screen pixels against the display container's bounding rect so
# it stays correct no matter how the SVG is scaled to fit its flex-1 box.
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
    // Apply initial dark-mode class (dark mode is the default on page load).
    document.body.classList.add("cassette-dark");
    // Toggle visibility of every SVG element belonging to a train. When a
    // train is unchecked, its modules/engines/labels are dimmed (not
    // removed) so the layout stays stable and re-toggling is instant.
    function setTrainVisible(trainId, visible) {
        const svg = document.querySelector('.cassette-svg-wrap svg');
        if (!svg) return;
        const sel = `[data-train="${CSS.escape(trainId)}"]`;
        svg.querySelectorAll(sel).forEach((el) => {
            if (visible) el.classList.remove('dimmed');
            else el.classList.add('dimmed');
        });
    }
    </script>
    """
)

dark_mode = ui.dark_mode()
dark_mode.enable()  # start in dark mode


def _on_theme_toggle(e):
    """Toggle dark mode and the cassette display's colour scheme."""
    if e.value:
        dark_mode.enable()
        ui.run_javascript('document.body.classList.add("cassette-dark");')
    else:
        dark_mode.disable()
        ui.run_javascript('document.body.classList.remove("cassette-dark");')

# ============================================================
# Header: CMS logo + title on the left, menu dropdown on the right
# ============================================================
with ui.row().classes("w-full items-center justify-between no-wrap"):
    with ui.row().classes("items-center gap-4 no-wrap"):
        # CMS logo first
        if CMS_LOGO.exists():
            ui.image(str(CMS_LOGO)).style(
                "height:56px; width:auto; object-fit:contain;"
            ).props("alt=CMS logo")
        # then the title
        with ui.column().classes("gap-0"):
            ui.label("High Granularity Calorimeter (CE-H)").style(
                "font-size:24px;font-weight:bold;"
            )
            ui.label("Single Cassette Tester").style(
                "font-size:24px;font-weight:bold;"
            )

    with ui.button(icon="menu").props("flat round"):
        with ui.menu().props('trigger="hover"'):
            with ui.menu_item(auto_close=False):
                with ui.row().classes("items-center gap-3 no-wrap"):
                    ui.label("Theme").classes("text-sm")
                    ui.switch(
                        value=True,
                        on_change=_on_theme_toggle,
                    ).props(
                        'checked-icon="dark_mode" unchecked-icon="light_mode" color="blue-grey-7"'
                    ).tooltip("Toggle light / dark mode")

            ui.menu_item("Test Workflow")
            ui.menu_item("Documentation")
            ui.menu_item("Settings")

            ui.separator()

            ui.menu_item("⏻ Shutdown", on_click=lambda: app.shutdown()).classes(
                "red-background"
            )

ui.separator()

# state shared between the input handler, the legend, and the test workflow
state = {
    "model": None,            # last loaded CassetteModel
    "visible_trains": {},      # train_id -> bool (trains view)
    "engines_visible": True,
    "test_results": {},        # module.id -> bool (True = pass)
    "view_mode": "trains",     # "trains" | "test"
    "test_in_progress": False,
}

with ui.row().classes("w-full gap-4 flex-nowrap").style("height: 78vh;"):
    # ============================================================
    # LEFT COLUMN - Cassette entry + summary
    # ============================================================
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

    # ============================================================
    # RIGHT COLUMN - Interactive cassette display with legend overlay
    # ============================================================
    with ui.column().classes("flex-1 h-full"):
        with (
            ui.column()
            .classes("w-full h-full border rounded-lg relative overflow-hidden")
            .props('id="cassette-display-area"')
            .style("position: relative;")
        ):
            svg_slot = ui.element("div").classes(
                "cassette-svg-wrap w-full h-full flex items-center justify-center"
            )

            # Legend overlay pinned to the top-left corner of the display area
            with ui.column().classes("legend-overlay gap-1") as legend_container:
                ui.label("Load a cassette to see trains.").classes(
                    "text-sm text-gray-400"
                )

            # View-toggle arrow buttons pinned to the top-right corner. Hidden
            # until a test has produced results to toggle between.
            with ui.row().classes("view-toggle items-center") as toggle_container:
                toggle_left = ui.button(icon="arrow_back").props(
                    "flat round dense color=blue-grey-4"
                ).props("disabled").tooltip("Show trains view")
                toggle_right = ui.button(icon="arrow_forward").props(
                    "flat round dense color=blue-grey-4"
                ).props("disabled").tooltip("Show test-results view")

            # Progress-bar overlay shown while a test is running.
            with ui.column().classes("progress-overlay") as progress_container:
                progress_label = ui.label("Running cassette test...").classes(
                    "text-sm text-gray-200 mb-2"
                )
                progress_bar = ui.linear_progress(value=0).props(
                    "color=green-6 rounded"
                ).classes("w-full")
            progress_container.style("display:none;")

            ui.element("div").props('id="cassette-tooltip"').classes(
                "absolute rounded-md border px-3 py-2 text-sm shadow-lg whitespace-pre-line"
            ).style(
                "display:none; position:absolute; z-index:50; pointer-events:none; "
                "max-width: 260px;"
            )


def _render_legend(model) -> None:
    """Build the checkbox legend from the model's trains and engines."""
    legend_container.clear()
    with legend_container:
        ui.label("Trains and Engines").classes(
            "text-sm text-gray-400"
        )
        for t in model.trains:
            r, g, b = t.color_rgb
            swatch = f"rgb({r},{g},{b})"
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
                    value=True,
                    on_change=lambda e: _on_engines_toggle(e.value),
                ).classes("flex-1").tooltip("Red circles on the ENGINES layer")
                ui.element("div").classes("legend-swatch engine").style(
                    f"background:{swatch};"
                )


def _render_test_legend(model, results) -> None:
    """Build the checkbox legend for the test-results view."""
    legend_container.clear()
    with legend_container:
        ui.label("Tick a status to show it; untick to hide it.").classes(
            "text-sm text-gray-400"
        )
        with ui.row().classes("legend-row w-full items-center"):
            ui.checkbox(
                text="Passed",
                value=True,
                on_change=lambda e: _on_test_toggle("pass", e.value),
            ).classes("flex-1").tooltip("Modules that passed the test")
            ui.element("div").classes("legend-swatch").style("background:#22c55e;")
        with ui.row().classes("legend-row w-full items-center"):
            ui.checkbox(
                text="Failed",
                value=True,
                on_change=lambda e: _on_test_toggle("fail", e.value),
            ).classes("flex-1").tooltip("Modules that failed the test")
            ui.element("div").classes("legend-swatch").style("background:#ef4444;")


def _on_train_toggle(train_id: str, visible: bool) -> None:
    state["visible_trains"][train_id] = visible
    ui.run_javascript(
        f'setTrainVisible({train_id!r}, {"true" if visible else "false"});'
    )


def _on_engines_toggle(visible: bool) -> None:
    state["engines_visible"] = visible
    model = state["model"]
    if model is None:
        return
    # engines may belong to one or more trains; toggle each
    engine_train_ids = {e.train_id for e in model.engines}
    for tid in engine_train_ids:
        ui.run_javascript(
            f'setTrainVisible({tid!r}, {"true" if visible else "false"});'
        )


def _on_test_toggle(status: str, visible: bool) -> None:
    ui.run_javascript(
        f'setTrainVisible({status!r}, {"true" if visible else "false"});'
    )


def _render_view() -> None:
    """Render the SVG for the current view_mode into svg_slot."""
    model = state["model"]
    if model is None:
        return
    svg_slot.clear()
    if state["view_mode"] == "test":
        svg_content = build_test_svg(model, state["test_results"])
        _render_test_legend(model, state["test_results"])
    else:
        svg_content = build_svg(model)
        _render_legend(model)
    with svg_slot:
        # sanitize=False: the SVG is our own trusted output (not user input) and
        # relies on inline onmouse* handlers for hover tooltips, which NiceGUI's
        # default DOMPurify sanitization strips.
        ui.html(svg_content, sanitize=False).classes("w-full h-full")


def _update_toggle_buttons() -> None:
    has_results = bool(state["test_results"])
    if not has_results:
        toggle_left.props("disabled")
        toggle_right.props("disabled")
        return
    if state["view_mode"] == "test":
        toggle_left.props("disabled=false")
        toggle_right.props("disabled")
    else:  # trains
        toggle_left.props("disabled")
        toggle_right.props("disabled=false")


def _on_toggle_left() -> None:
    if state["view_mode"] != "test":
        return
    state["view_mode"] = "trains"
    _render_view()
    _update_toggle_buttons()


def _on_toggle_right() -> None:
    if state["view_mode"] != "trains" or not state["test_results"]:
        return
    state["view_mode"] = "test"
    _render_view()
    _update_toggle_buttons()


toggle_left.on_click(_on_toggle_left)
toggle_right.on_click(_on_toggle_right)


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

    # hide the progress overlay
    progress_container.style("display:none;")
    progress_container.update()

    # switch to the test-results view
    state["view_mode"] = "test"
    _render_view()
    _update_toggle_buttons()

    state["test_in_progress"] = False


# ============================================================
# Control Buttons -- created AFTER run_tests is defined so we can pass
# it directly (NiceGUI awaits coroutine-function handlers; a lambda
# wrapping a coroutine would NOT be awaited and the test would never run).
# ============================================================
dynamic_container = ui.row().classes("w-full") 


def load_selected(name: str) -> None:
    svg_slot.clear()
    dynamic_container.clear()
    summary_table.rows = []
    summary_table.update()
    legend_container.clear()
    with legend_container:
        ui.label("Load a cassette to see trains.").classes(
            "text-sm text-gray-400"
        )

    # reset test/view state on every (re)load; keep the run button
    # disabled until a cassette is fully loaded (table + display done)
    state["model"] = None
    state["test_results"] = {}
    state["view_mode"] = "trains"
    state["test_in_progress"] = False
    progress_container.style("display:none;")
    _update_toggle_buttons()

    if not name:
        return

    filepath = CASSETTE_DIR / f"{name}.dxf"
    if not filepath.exists():
        with svg_slot:
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
        with svg_slot:
            ui.label(f"Failed to load {name}: {ex}").classes("text-red-400")
        return

    state["model"] = model
    state["visible_trains"] = {t.id: True for t in model.trains}
    state["engines_visible"] = True

    summary = summarize(model)
    summary_table.rows = [
        {"field": "Cassette", "value": name},
        {"field": "Cassette Type", "value": summary.cassette_type},
        {"field": "Full Hex Modules", "value": summary.full_hex},
        {"field": "Partial Hex Modules", "value": summary.partial_hex},
        {"field": "Tile Modules", "value": summary.tile},
        {"field": "Trains", "value": summary.trains},
        {"field": "Engines", "value": summary.engines},
    ]
    summary_table.update()

    _render_view()
    _update_toggle_buttons()

    # cassette is fully loaded (table + display populated) -- enable the
    # run button so a test can be executed for this cassette.
    with dynamic_container:
        with ui.row().classes("w-1/4 gap-2"):
            run_button = ui.button(
                "▶ Run Cassette Test",
                on_click=run_tests,
            ).classes("green-background flex-1")


# Register the input callback last, after run_button and all handler
# functions exist, so load_selected can safely access run_button even if
# on_value_change fires during page setup.
cassette_input.on_value_change(lambda e: load_selected(e.value))

ui.run(
    title="[HGCAL] Single Cassette Tester",
)
