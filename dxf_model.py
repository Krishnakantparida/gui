"""Parse a cassette DXF into a structured CassetteModel.

Layers:
  SHAPES  — closed LWPOLYLINEs (module hexagons / tiles)
  TEXT    — MTEXT labels: module code + (u,v), and train label
  ENGINES — CIRCLEs (engine positions)

Trains are identified by ACI color of their polylines. Each train's
modules are grouped by spatial proximity to the train label MTEXT.
Engines are matched to trains by proximity to each train's module
centroids (their own ACI color is unreliable).

A JSON sidecar (same basename as the DXF) provides metadata:
  module type, i_rot, trigLinks, daqLinks, engine type, wagon names,
  wingboard and motherboard identifiers.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
from ezdxf.colors import aci2rgb
from shapely.geometry import Point, Polygon


@dataclass
class Module:
    id: str
    polygon: list[tuple[float, float]]
    shape: str  # "hex_full" | "hex_partial" | "tile"
    train_id: str
    color_key: str
    color_rgb: tuple[int, int, int]
    code: str
    uv: tuple[int, int] | None
    label: str
    centroid: tuple[float, float]
    module_type: str = ""
    i_rot: int | None = None
    trig_links: int | None = None
    daq_links: int | None = None
    is_wagon: bool = False
    wagon_name: str = ""
    wagon_side: str = ""  # "west" | "east" | "type"
    module_num: int = 0   # numeric suffix for ordering (W1->1, E2->2, M3->3)
    wingboard: str = ""
    motherboard: str = ""


@dataclass
class Engine:
    id: str
    center: tuple[float, float]
    radius: float
    train_id: str
    color_key: str
    color_rgb: tuple[int, int, int]
    engine_type: str = ""
    motherboard: str = ""


@dataclass
class Wingboard:
    id: str
    train_id: str
    polygon: list[tuple[float, float]]
    centroid: tuple[float, float]
    wingboard_name: str = ""


@dataclass
class Train:
    id: str
    label: str
    color_key: str
    color_rgb: tuple[int, int, int]
    is_real: bool = True   # True for TL/TH/LD/HD, False for "Train N"
    density: str = ""      # "HD" | "LD" | ""


@dataclass
class CassetteModel:
    name: str
    modules: list[Module] = field(default_factory=list)
    engines: list[Engine] = field(default_factory=list)
    wingboards: list[Wingboard] = field(default_factory=list)
    trains: list[Train] = field(default_factory=list)
    bounds: tuple[float, float, float, float] = (0, 0, 1, 1)
    real_train_count: int = 0


def _safe_aci2rgb(aci: int) -> tuple[int, int, int]:
    try:
        rgb = aci2rgb(aci)
        if rgb and len(rgb) >= 3:
            return (rgb[0], rgb[1], rgb[2])
    except Exception:
        pass
    return (128, 128, 128)


def _parse_module_code(label_text: str) -> tuple[str, tuple[int, int] | None]:
    """Extract module code and (u,v) from MTEXT like 'G8\\n(4,6)'."""
    lines = [ln.strip() for ln in label_text.replace("\\n", "\n").split("\n") if ln.strip()]
    if not lines:
        return ("", None)
    code = lines[0]
    uv = None
    if len(lines) >= 2:
        import re
        m = re.match(r"\((\d+)\s*,\s*(\d+)\)", lines[1])
        if m:
            uv = (int(m.group(1)), int(m.group(2)))
    return code, uv


def _module_number(code: str) -> int:
    """Extract numeric suffix: W1->1, E2->2, M3->3, G8->8, B12->12."""
    import re
    m = re.search(r"(\d+)$", code)
    return int(m.group(1)) if m else 0


def _is_real_train(label: str) -> bool:
    """Real trains: TL, TH, LD, HD. Not real: 'Train N'."""
    return label[:2] in ("TL", "TH", "LD", "HD")


def _train_density(label: str) -> str:
    if label.startswith("HD"):
        return "HD"
    if label.startswith("LD"):
        return "LD"
    return ""


def load_cassette(filepath: str, name: str) -> CassetteModel:
    doc = ezdxf.readfile(filepath)
    msp = doc.modelspace()

    # --- Collect polylines (module shapes) grouped by ACI color ---
    polyline_groups: dict[int, list] = {}
    for e in msp.query("LWPOLYLINE"):
        if e.dxf.layer != "SHAPES":
            continue
        aci = e.dxf.get("color", 250)
        pts = list(e.get_points("xy"))
        if len(pts) >= 2 and pts[0] != pts[-1]:
            pts.append(pts[0])
        if len(pts) >= 4:
            polyline_groups.setdefault(aci, []).append(pts)

    # --- Collect MTEXT labels ---
    mtext_entries = []
    for e in msp.query("MTEXT"):
        try:
            text = e.plain_text().strip()
        except Exception:
            text = e.text.strip()
        if not text:
            continue
        color = e.dxf.get("color", 256)
        insert = e.dxf.get("insert", (0, 0))
        mtext_entries.append({
            "text": text,
            "color": color,
            "x": float(insert[0]),
            "y": float(insert[1]),
        })

    # --- Collect engine circles ---
    engine_entries = []
    for e in msp.query("CIRCLE"):
        if e.dxf.layer != "ENGINES":
            continue
        center = e.dxf.center
        radius = e.dxf.radius
        aci = e.dxf.get("color", 1)
        engine_entries.append({
            "cx": float(center[0]),
            "cy": float(center[1]),
            "r": float(radius),
            "aci": aci,
        })

    # --- Identify train labels (color=0 MTEXT) ---
    train_labels = []
    for mt in mtext_entries:
        if mt["color"] == 0:
            train_labels.append(mt)

    # --- Build trains from ACI color groups ---
    # Match each ACI group to the nearest unused train label.
    trains: list[Train] = []
    train_id_by_aci: dict[int, str] = {}
    available_labels = list(train_labels)
    for aci in sorted(polyline_groups.keys()):
        train_id = f"aci:{aci}"
        rgb = _safe_aci2rgb(aci)
        label = f"Train {len(trains) + 1}"
        if available_labels:
            first_pts = polyline_groups[aci][0]
            cx = sum(p[0] for p in first_pts) / len(first_pts)
            cy = sum(p[1] for p in first_pts) / len(first_pts)
            best_idx = 0
            best_dist = float("inf")
            for i, t in enumerate(available_labels):
                d = (t["x"] - cx) ** 2 + (t["y"] - cy) ** 2
                if d < best_dist:
                    best_dist = d
                    best_idx = i
            label = available_labels.pop(best_idx)["text"]
        is_real = _is_real_train(label)
        density = _train_density(label)
        trains.append(Train(
            id=train_id, label=label, color_key=str(aci),
            color_rgb=rgb, is_real=is_real, density=density,
        ))
        train_id_by_aci[aci] = train_id

    # --- Build modules ---
    modules: list[Module] = []
    mod_counter = 0
    for aci, polylines in polyline_groups.items():
        train_id = train_id_by_aci[aci]
        rgb = _safe_aci2rgb(aci)
        for pts in polylines:
            # Determine shape
            n = len(pts) - 1  # last point == first
            if n == 6:
                shape = "hex_full"
            elif n == 4:
                shape = "tile"
            else:
                shape = "hex_partial"
            # Centroid
            poly = Polygon(pts)
            if not poly.is_valid:
                poly = poly.buffer(0)
            cx, cy = poly.centroid.x, poly.centroid.y
            # Find matching MTEXT (color=250, nearest to centroid)
            code = ""
            uv = None
            best_dist = float("inf")
            for mt in mtext_entries:
                if mt["color"] != 250:
                    continue
                d = (mt["x"] - cx) ** 2 + (mt["y"] - cy) ** 2
                if d < best_dist:
                    best_dist = d
                    code, uv = _parse_module_code(mt["text"])
            mod_counter += 1
            modules.append(Module(
                id=f"module-{mod_counter}",
                polygon=pts,
                shape=shape,
                train_id=train_id,
                color_key=str(aci),
                color_rgb=rgb,
                code=code,
                uv=uv,
                label=f"{code}\n({uv[0]},{uv[1]})" if uv else code,
                centroid=(cx, cy),
                module_num=_module_number(code),
            ))

    # --- Build engines ---
    engines: list[Engine] = []
    for i, eng in enumerate(engine_entries):
        aci = eng["aci"]
        rgb = _safe_aci2rgb(aci)
        engines.append(Engine(
            id=f"engine-{i}",
            center=(eng["cx"], eng["cy"]),
            radius=eng["r"],
            train_id=f"aci:{aci}",
            color_key=str(aci),
            color_rgb=rgb,
        ))

    # --- Bounds ---
    all_x = [p[0] for m in modules for p in m.polygon]
    all_y = [p[1] for m in modules for p in m.polygon]
    if engines:
        all_x += [e.center[0] for e in engines]
        all_y += [e.center[1] for e in engines]
    if all_x and all_y:
        bounds = (min(all_x), min(all_y), max(all_x), max(all_y))
    else:
        bounds = (0, 0, 1, 1)

    model = CassetteModel(
        name=name,
        modules=modules,
        engines=engines,
        trains=trains,
        bounds=bounds,
    )

    # --- Enrich from JSON sidecar ---
    json_path = Path(filepath).with_suffix(".json")
    if json_path.exists():
        _enrich_from_json(model, json_path)

    # --- Count real trains ---
    model.real_train_count = sum(1 for t in model.trains if t.is_real)

    # --- Build wingboards ---
    _build_wingboards(model)

    return model


def _enrich_from_json(model: CassetteModel, json_path: Path) -> None:
    try:
        with open(json_path) as f:
            raw = json.load(f)
    except Exception:
        return

    # Flatten all halves: { train_label: train_entry }
    train_entries: dict[str, dict] = {}
    for half_data in raw.values():
        if isinstance(half_data, dict):
            train_entries.update(half_data)

    label_to_train_id = {t.label: t.id for t in model.trains}

    # Build module lookup: (train_id, code) -> Module
    module_lookup: dict[tuple[str, str], Module] = {}
    for m in model.modules:
        module_lookup[(m.train_id, m.code)] = m

    for train_label, train_entry in train_entries.items():
        if not isinstance(train_entry, dict):
            continue
        train_id = label_to_train_id.get(train_label)
        if train_id is None:
            continue

        wagon_west = train_entry.get("wagon_west", "")
        wagon_east = train_entry.get("wagon_east", "")
        wagon_type = train_entry.get("wagon_type", "")
        wingboard = train_entry.get("wingboard", "")
        motherboard = train_entry.get("motherboard", "")

        for key, value in train_entry.items():
            if key in ("engine", "wagon_west", "wagon_east", "wagon_type",
                       "wingboard", "motherboard"):
                continue
            if not isinstance(value, dict):
                continue
            mod = module_lookup.get((train_id, key))
            if mod is None:
                continue
            mod.module_type = value.get("type", "")
            mod.i_rot = value.get("i_rot")
            mod.trig_links = value.get("trigLinks")
            mod.daq_links = value.get("daqLinks")
            mod.wingboard = wingboard
            mod.motherboard = motherboard

            # Wagon detection
            if key.startswith("W") and (wagon_west or wagon_type):
                mod.is_wagon = True
                mod.wagon_name = wagon_west or wagon_type
                mod.wagon_side = "west" if wagon_west else "type"
            elif key.startswith("E") and (wagon_east or wagon_type):
                mod.is_wagon = True
                mod.wagon_name = wagon_east or wagon_type
                mod.wagon_side = "east" if wagon_east else "type"
            elif wagon_type and not key.startswith(("W", "E")):
                mod.is_wagon = True
                mod.wagon_name = wagon_type
                mod.wagon_side = "type"

        # --- Engine enrichment by proximity ---
        eng_entry = train_entry.get("engine")
        if isinstance(eng_entry, dict):
            eng_type = eng_entry.get("type", "")
            train_mods = [m for m in model.modules if m.train_id == train_id]
            if train_mods:
                cx = sum(m.centroid[0] for m in train_mods) / len(train_mods)
                cy = sum(m.centroid[1] for m in train_mods) / len(train_mods)
                untyped = [e for e in model.engines if not e.engine_type]
                if untyped:
                    best = min(untyped, key=lambda e: (e.center[0] - cx) ** 2 + (e.center[1] - cy) ** 2)
                    best.engine_type = eng_type
                    best.train_id = train_id
                    best.motherboard = motherboard


def _build_wingboards(model: CassetteModel) -> None:
    """Build wingboard rectangles at the boundary of E and G type tile modules.

    Wingboards are longer rectangular blocks placed at the outer edge of
    E-type and G-type modules (the first and last modules in TL/TH trains).
    Width is slightly smaller than the engine circle diameter.
    """
    if not model.engines:
        return

    # Engine radius for sizing
    avg_radius = sum(e.radius for e in model.engines) / max(len(model.engines), 1)
    wb_width = avg_radius * 2 * 0.8  # slightly smaller than engine circle diameter
    wb_length = avg_radius * 3.0     # longer rectangular block

    for train in model.trains:
        if not train.is_real:
            continue
        train_mods = [m for m in model.modules if m.train_id == train.id]
        if not train_mods:
            continue
        # Find E-type and G-type modules (codes starting with E or G)
        for mod in train_mods:
            if not mod.code.startswith(("E", "G")):
                continue
            # Place wingboard at the outer edge of the module
            cx, cy = mod.centroid
            # Determine outer direction: away from train centroid
            train_cx = sum(m.centroid[0] for m in train_mods) / len(train_mods)
            train_cy = sum(m.centroid[1] for m in train_mods) / len(train_mods)
            dx = cx - train_cx
            dy = cy - train_cy
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < 1e-6:
                continue
            # Offset position: move outward from train center past the module edge
            offset = 50.0  # offset beyond module boundary
            wb_cx = cx + (dx / dist) * offset
            wb_cy = cy + (dy / dist) * offset
            # Build rectangle perpendicular to the outward direction
            perp_x = -dy / dist
            perp_y = dx / dist
            half_l = wb_length / 2
            half_w = wb_width / 2
            p1 = (wb_cx + perp_x * half_l, wb_cy + perp_y * half_l)
            p2 = (wb_cx - perp_x * half_l, wb_cy - perp_y * half_l)
            p3 = (wb_cx - perp_x * half_l - (dx / dist) * wb_width,
                  wb_cy - perp_y * half_l - (dy / dist) * wb_width)
            p4 = (wb_cx + perp_x * half_l - (dx / dist) * wb_width,
                  wb_cy + perp_y * half_l - (dy / dist) * wb_width)
            model.wingboards.append(Wingboard(
                id=f"wb-{train.id}-{mod.code}",
                train_id=train.id,
                polygon=[p1, p2, p3, p4],
                centroid=(wb_cx, wb_cy),
                wingboard_name=mod.wingboard,
            ))
