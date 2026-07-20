"""NiceGUI GUI for the HGCAL single-cassette DXF tester.

Loads a cassette DXF, classifies its module footprints (hexagonal /
partial-hexagonal / tile) and their "train" colors, shows a summary table,
and renders an interactive SVG of the cassette where hovering a module
region reveals its MTEXT label in a small tooltip box.
"""

import os
from pathlib import Path

from nicegui import ui, app

from dxf_model import load_cassette, summarize
from svg_builder import build_svg

CASSETTE_DIR = Path(__file__).parent / "cassette_layouts"
SELECT_DEFAULT = "Enter Cassette Name"

SHAPE_LABELS = {
    "hex_full": "Full hexagonal modules",
    "hex_partial": "Partial hexagonal modules",
    "tile": "Tile modules",
}


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
    </script>
    """
)
dark_mode = ui.dark_mode()
dark_mode.enable()  # start in dark mode
with ui.row().classes("w-full items-center justify-between"):
    # Title section
    with ui.column():
        ui.label("High Granularity Calorimeter (CE-H)").style(
            "font-size:24px;font-weight:bold;"
        )
        ui.label("Single Cassette Tester").style("font-size:24px;font-weight:bold;")

    # Top-right dropdown menu section
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

with ui.row().classes("w-full gap-4 flex-nowrap").style("height: 78vh;"):
    # ============================================================
    # LEFT COLUMN - Cassette Selection + summary table
    # ============================================================
    with ui.column().classes("flex-1 gap-3"):
        ui.markdown("## Cassette Information")

        cassette_options = [SELECT_DEFAULT] + discover_cassettes()
        cassette_select = ui.select(
            options=cassette_options,
            value=SELECT_DEFAULT,
            label="Cassette:",
        ).classes("w-full")

        summary_table = (
            ui.table(
                columns=[
                    {
                        "name": "field",
                        "label": "Field",
                        "field": "field",
                        "align": "left",
                    },
                    {
                        "name": "value",
                        "label": "Value",
                        "field": "value",
                        "align": "left",
                    },
                ],
                rows=[],
                row_key="field",
                column_defaults={"headerClasses": "hidden"},
            )
            .classes("w-full")
            .props("flat bordered hide-header")
        )

    # ============================================================
    # RIGHT COLUMN - Interactive cassette display
    # ============================================================
    with ui.column().classes("flex-1 h-full"):
        with (
            ui.column()
            .classes("w-full h-full border rounded-lg relative overflow-hidden")
            .props('id="cassette-display-area"')
            .style(
                "position: relative; background: rgba(255,255,255,0.02);"
            ) as display_wrapper
        ):
            svg_slot = ui.element("div").classes(
                "w-full h-full flex items-center justify-center"
            )
            ui.element("div").props('id="cassette-tooltip"').classes(
                "absolute rounded-md border px-3 py-2 text-sm shadow-lg whitespace-pre-line"
            ).style(
                "display:none; position:absolute; z-index:50; pointer-events:none; "
                "background: rgba(15, 23, 42, 0.95); border-color: rgba(148,163,184,0.4); "
                "color: #f1f5f9; max-width: 220px;"
            )


def load_selected(e) -> None:
    svg_slot.clear()
    summary_table.rows = []
    summary_table.update()

    name = e.value
    if not name or name == SELECT_DEFAULT:
        return

    filepath = CASSETTE_DIR / f"{name}.dxf"
    try:
        model = load_cassette(str(filepath), name)
    except Exception as ex:
        with svg_slot:
            ui.label(f"Failed to load {name}: {ex}").classes("text-red-400")
        return

    summary = summarize(model)
    summary_table.rows = [
        {"field": "Cassette Type", "value": summary.cassette_type},
        {"field": "Full Hex Modules", "value": summary.full_hex},
        {"field": "Partial Hex Modules", "value": summary.partial_hex},
        {"field": "Tile Modules", "value": summary.tile},
        {"field": "Trains", "value": summary.trains},
    ]
    summary_table.update()

    svg_content = build_svg(model)
    with svg_slot:
        # sanitize=False: the SVG is our own trusted output (not user input) and
        # relies on inline onmouse* handlers for hover tooltips, which NiceGUI's
        # default DOMPurify sanitization strips.
        ui.html(svg_content, sanitize=False).classes("w-full h-full")


cassette_select.on_value_change(load_selected)

ui.run(
    title="[HGCAL] Single Cassette Tester",
)
