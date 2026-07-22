"""NiceGUI GUI for the HGCAL single-cassette DXF tester.

Enter a cassette name (the .dxf filename without extension) to load its
layout: module footprints are classified (hexagonal / partial-hexagonal /
tile) and grouped into "trains" by their fill color, and engines (the
red circles on the ENGINES layer) are rendered alongside them. A
checkbox legend -- overlaid in the top-left corner of the cassette
display -- lets you toggle the visibility of each train (and the
engines) in the interactive SVG. Hovering a module or engine reveals a
tooltip with its details.
"""

from pathlib import Path

from nicegui import ui, app

from dxf_model import load_cassette, summarize
from svg_builder import build_svg

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
        border: 1px solid rgba(148,163,184,0.35);
        background: rgba(15, 23, 42, 0.82);
        backdrop-filter: blur(4px);
    }
    .legend-overlay .q-checkbox__label {
        font-size: 0.57rem;
    }
    .legend-overlay .q-checkbox { min-height: 0; padding: 0; }
    .legend-overlay .q-checkbox__inner { width: 22px; height: 22px; }
    .legend-overlay .legend-row { gap: 4px; }
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
                        on_change=lambda e: dark_mode.enable()
                        if e.value
                        else dark_mode.disable(),
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

# state shared between the input handler and the legend
state = {
    "model": None,            # last loaded CassetteModel
    "visible_trains": {},      # train_id -> bool
    "engines_visible": True,
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
            .style("position: relative; background: rgba(255,255,255,0.02);")
        ):
            svg_slot = ui.element("div").classes(
                "cassette-svg-wrap w-full h-full flex items-center justify-center"
            )

            # Legend overlay pinned to the top-left corner of the display area
            with ui.column().classes("legend-overlay gap-1") as legend_container:
                ui.label("Load a cassette to see trains.").classes(
                    "text-sm text-gray-400"
                )

            ui.element("div").props('id="cassette-tooltip"').classes(
                "absolute rounded-md border px-3 py-2 text-sm shadow-lg whitespace-pre-line"
            ).style(
                "display:none; position:absolute; z-index:50; pointer-events:none; "
                "background: rgba(15, 23, 42, 0.95); border-color: rgba(148,163,184,0.4); "
                "color: #f1f5f9; max-width: 260px;"
            )


def _render_legend(model) -> None:
    """Build the checkbox legend from the model's trains and engines."""
    legend_container.clear()
    with legend_container:
        ui.label("Tick a train to show it; untick to hide it.").classes(
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


def _render_view() -> None:
    """Render the SVG for the current model into svg_slot."""
    model = state["model"]
    if model is None:
        return
    svg_slot.clear()
    svg_content = build_svg(model)
    _render_legend(model)
    with svg_slot:
        # sanitize=False: the SVG is our own trusted output (not user input) and
        # relies on inline onmouse* handlers for hover tooltips, which NiceGUI's
        # default DOMPurify sanitization strips.
        ui.html(svg_content, sanitize=False).classes("w-full h-full")


def load_selected(name: str) -> None:
    svg_slot.clear()
    summary_table.rows = []
    summary_table.update()
    legend_container.clear()
    with legend_container:
        ui.label("Load a cassette to see trains.").classes(
            "text-sm text-gray-400"
        )

    state["model"] = None

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


cassette_input.on_value_change(lambda e: load_selected(e.value))

# Control Buttons
with ui.row().classes("w-1/4 gap-2"):
    run_button = ui.button(
        "▶ Run Cassette Test",
        on_click=lambda: None,
    ).classes("green-background flex-1")

ui.run(
    title="[HGCAL] Single Cassette Tester",
)
