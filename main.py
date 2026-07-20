######################################################################
# HGCAL Single Cassette Tester GUI main code (alpha)
# Developed by: Krishna Kant Parida
#        Email: krishna.kant.parida@cern.ch
# Developed on: July 2, 2026
######################################################################

# package listings
import os
import sys
import pytest
import easysnmp
import asyncio
import json
from pathlib import Path
from easysnmp import Session

sys.path.append('../test_mpod_ctrl')

from utils.mpod_settings import (
    MPOD_OIDS,
    MPOD_IP,
    CHANNEL_SETTINGS_OFF,
    CHANNEL_SETTINGS_ON
)

from nicegui import ui, app

######################################################################
# Configuration
######################################################################

TEST_SCRIPT = Path("/home/hgcal_dev/pytest_dev/dev_gui/test_mpod_ctrl/scripts/test_powerSupply.py")
REPORT_FILE = Path(os.environ.get("SCT", ".")) / "reports" / "power_off.json"

# Ensure report directory exists
REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

######################################################################
# CSS Styling and theme
######################################################################

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
''')

ui.add_css('''
    .test-table {
        font-size: 0.9em;
    }
    .test-table tbody tr {
        padding: 8px;
    }
    .test-table tbody tr:nth-child(odd) {
        background-color: #fafafa;
    }
    .test-table tbody tr:nth-child(even) {
        background-color: #ffffff;
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
current_theme = "high_contrast"

def set_theme(theme_name: str):
    global current_theme
    current_theme = theme_name

    if theme_name == "light":
        ui.notify("Light Mode selected")

        ui.colors(
            primary='#1976D2',
            secondary='#26A69A',
            accent='#9C27B0',
            dark='#FFFFFF',
            positive='#21BA45',
            negative='#C10015',
            warning='#F2C037',
        )

    elif theme_name == "dark":
        ui.notify("Dark Mode selected")

        ui.dark_mode().enable()

    elif theme_name == "high_contrast":
        ui.notify("High Contrast Dark Mode selected")

        ui.dark_mode().enable()

        ui.colors(
            primary='#FFD700',
            secondary='#FFFFFF',
            accent='#00FFFF',
            dark='#000000',
            positive='#00FF00',
            negative='#FF0000',
            warning='#FFFF00',
        )

######################################################################
# Global UI Variables (declared at module level)
######################################################################

log = None
report_table = None
summary_label = None
is_test_running = False

######################################################################
# Utility Functions
######################################################################

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


async def run_tests():
    """Run pytest tests and display live output"""
    global is_test_running
    
    if is_test_running:
        ui.notify("Tests already running", color="warning")
        return
    
    is_test_running = True
    run_button.enabled = False
    
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
            ui.notify("✓ All Tests Passed", color="positive")
        else:
            ui.notify("✗ Some Tests Failed", color="negative")
    
    except Exception as e:
        ui.notify(f"Error running tests: {str(e)}", color="negative")
        log.push(f"ERROR: {str(e)}")
    
    finally:
        is_test_running = False
        run_button.enabled = True

######################################################################
# UI Layout
######################################################################

set_theme(current_theme)
with ui.row().classes('w-full items-center justify-between'):

    # Title section
    with ui.column():
        ui.label("High Granularity Calorimeter (CE-H)").style(
            "font-size:24px;font-weight:bold;"
        )
        ui.label("Single Cassette Tester").style(
            "font-size:24px;font-weight:bold;"
        )

    # Top-right menu
    with ui.button(icon='menu').props('flat round'):
        with ui.menu():
            # Appearance submenu
            with ui.menu_item('Appearance'):
                with ui.menu():

                    ui.menu_item(
                        'Light Mode',
                        on_click=lambda: set_theme('light')
                    )

                    ui.menu_item(
                        'Dark Mode',
                        on_click=lambda: set_theme('dark')
                    )

                    ui.menu_item(
                        'High Contrast Dark Mode',
                        on_click=lambda: set_theme('high_contrast')
                    )

            ui.menu_item('Test Workflow')
            ui.menu_item('Documentation')
            ui.menu_item('Settings')

            ui.separator()

            # Move Shutdown here
            ui.menu_item(
                '⏻ Shutdown',
                on_click=lambda: app.shutdown()
            ).classes("red-background flex-1")

ui.separator()

# Main layout with left and right columns
with ui.row().classes("w-full gap-4"):
    
    # ============================================================
    # LEFT COLUMN - Controls and Logs
    # ============================================================
    with ui.column().classes("flex-1"):
        
        ui.markdown("## MPOD Information")
        ui.label(f"MPOD IP: {MPOD_IP}").style("font-weight: bold;")
        
        # Control Buttons
        with ui.row().classes("w-1/2 gap-2"):
            run_button = ui.button(
                "▶ Run Tests",
                on_click=run_tests,
            ).classes("green-background flex-1")
        
        ui.separator()
        
        # Pytest Logs
        ui.markdown("## Pytest Logs")
        log = ui.log().classes("w-full h-96 border")
    
    # ============================================================
    # RIGHT COLUMN - Report Table
    # ============================================================
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
        ).classes("test-table w-full")
        
        # Initial load if report exists - only if file exists
        if REPORT_FILE.exists():
            initial_data = load_report_data()
            if initial_data and initial_data['tests']:
                refresh_report_table()

######################################################################
# Running GUI at port 9000
######################################################################

ui.run(
    title="[HGCAL] Single Cassette Tester",
    port=9000
)
