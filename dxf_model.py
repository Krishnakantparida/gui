"""
Parsing and geometric classification of cassette DXF layouts.

Domain model
------------
A cassette layout is made of:
  - LWPOLYLINE entities  -> the outline of a physical module footprint
  - HATCH entities       -> the filled/colored region inside a module
                            (the fill color groups modules into "trains",
                            i.e. differently colored readout chains)
  - MTEXT entities       -> text labels. Two kinds, distinguished by
                            ``dxf.color``:
                              * color == 250 -> a module label, formatted as
                                "<code>\n(<u>,<v>)" where <code> is e.g.
                                "M3", "E3", "W2", "G8" and (u,v) are the
                                module's (u,v) coordinates on a second line.
                                Some older cassettes omit the (u,v) line.
                              * color == 0   -> a train label, e.g. "TL1",
                                "TL2", "LD1", "HD1" -- the human-readable
                                name of a train, placed near the train's
                                engine(s).
  - CIRCLE entities on layer "ENGINES" -> the "engine" of a train. Engines
    are drawn in the same color as the train they belong to (a dark-red
    shade for the "red" trains, magenta for others). An engine is matched
    to a train by color.

A LWPOLYLINE is only counted as a "module" if a HATCH region is matched to
it (this filters out decorative/frame/outline-only geometry that isn't an
actual populated module footprint).

Shape classification is purely geometric (vertex count + interior angles),
because that's the only reliable general-purpose way to tell a hexagonal
(or partially-cut hexagonal) module apart from a tile module without any
extra metadata in the DXF:

  - "tile"        -> an even vertex count from 4 to 12, with ~all interior
                     angles close to 90 degrees. A plain rectangle is the
                     4-sided case; a rectangle with one or more rectangular
                     notches/steps cut into it (still an all-right-angle
                     outline) adds 2 vertices per notch, up to 12 -- every
                     corner, convex or concave, still measures ~90 degrees
                     as an unsigned interior angle, so no special-casing of
                     notch direction is needed.
  - "hex_full"    -> 6 vertices, ~all interior angles close to 120 degrees
                     and roughly equal edge lengths
  - "hex_partial" -> anything else, i.e. "part of" a hexagon -- this
                     deliberately covers footprints with 3, 4, 5, or 7+
                     vertices (corner-clipped, chamfered, or edge-cut
                     hexagons), not just the common 4-sided case

These thresholds are heuristics. They were tuned against synthetic sample
layouts (see generate_samples.py) since no real cassette DXF was available
at build time -- validate/tune against real files in cassette_layouts/.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import ezdxf
from ezdxf.colors import aci2rgb
from ezdxf.math import bulge_to_arc
from shapely.geometry import Point, Polygon

# ---------------------------------------------------------------------------
# Tunables (see module docstring)
# ---------------------------------------------------------------------------
TILE_ANGLE_CENTER = 90.0
TILE_ANGLE_TOLERANCE = 18.0
TILE_MIN_SIDES = 4
TILE_MAX_SIDES = 12

HEX_ANGLE_CENTER = 120.0
HEX_ANGLE_TOLERANCE = 16.0
HEX_EDGE_RATIO_MAX = 1.45

COLLINEAR_ANGLE_THRESHOLD = 165.0  # merge vertices whose corner is this straight
ARC_SAMPLES_PER_BULGE = 8

DEFAULT_COLOR_RGB = (148, 163, 184)  # slate-400, used when color can't be resolved

ENGINES_LAYER = "ENGINES"
MODULE_LABEL_COLOR = 250  # MTEXT dxf.color for module labels (code + (u,v))
TRAIN_LABEL_COLOR = 0      # MTEXT dxf.color for train names (TL1, LD1, ...)


@dataclass
class Train:
    """A readout train: a group of modules + engines sharing one fill color."""
    id: str                       # stable key, e.g. "aci:246"
    label: str                    # human name, e.g. "TL1" or "Train 1"; falls back to id
    color_key: str
    color_rgb: tuple[int, int, int]


@dataclass
class Module:
    id: str
    polygon: list[tuple[float, float]]  # cleaned, closed-implied vertex loop
    shape: str  # "hex_full" | "hex_partial" | "tile"
    train_id: str
    color_key: str
    color_rgb: tuple[int, int, int]
    code: str               # e.g. "M3", "E3", "W2", "G8"
    uv: tuple[int, int] | None  # (u, v) coordinates parsed from the label, if present
    label: str             # full original label text (may include the (u,v) line)
    centroid: tuple[float, float]


@dataclass
class Engine:
    id: str
    center: tuple[float, float]
    radius: float
    train_id: str
    color_key: str
    color_rgb: tuple[int, int, int]


@dataclass
class CassetteModel:
    name: str
    modules: list[Module] = field(default_factory=list)
    engines: list[Engine] = field(default_factory=list)
    trains: list[Train] = field(default_factory=list)
    bounds: tuple[float, float, float, float] = (0, 0, 1, 1)


@dataclass
class CassetteSummary:
    cassette_type: str  # "Pure silicon" | "Mixed"
    full_hex: int
    partial_hex: int
    tile: int
    trains: int
    engines: int


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def _flatten_lwpolyline(points_xyb: list[tuple[float, float, float]], closed: bool) -> list[tuple[float, float]]:
    """Flatten a LWPOLYLINE's (x, y, bulge) vertices into a plain point loop,
    replacing bulge segments with sampled arc points."""
    pts: list[tuple[float, float]] = []
    n = len(points_xyb)
    if n == 0:
        return pts

    segment_count = n if closed else n - 1
    for i in range(n):
        x, y, bulge = points_xyb[i]
        pts.append((x, y))
        if i >= segment_count:
            continue
        if abs(bulge) > 1e-9:
            nxt = points_xyb[(i + 1) % n]
            try:
                center, start_angle, end_angle, radius = bulge_to_arc((x, y), (nxt[0], nxt[1]), bulge)
            except Exception:
                continue
            sweep = end_angle - start_angle
            while sweep <= 0:
                sweep += 2 * math.pi
            for s in range(1, ARC_SAMPLES_PER_BULGE):
                t = start_angle + sweep * (s / ARC_SAMPLES_PER_BULGE)
                pts.append((center[0] + radius * math.cos(t), center[1] + radius * math.sin(t)))
    return pts


def _dedupe_points(points: list[tuple[float, float]], tol: float = 1e-6) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for p in points:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > tol:
            out.append(p)
    if len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= tol:
        out.pop()
    return out


def _interior_angle(p0, p1, p2) -> float:
    v1 = (p0[0] - p1[0], p0[1] - p1[1])
    v2 = (p2[0] - p1[0], p2[1] - p1[1])
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 < 1e-9 or n2 < 1e-9:
        return 180.0
    dot = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(math.acos(dot))


def _simplify_polygon(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Remove near-duplicate and near-collinear vertices so vertex count
    reflects the shape's actual corner count."""
    pts = _dedupe_points(points)
    if len(pts) < 4:
        return pts
    changed = True
    while changed and len(pts) > 3:
        changed = False
        n = len(pts)
        for i in range(n):
            p0, p1, p2 = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
            if _interior_angle(p0, p1, p2) >= COLLINEAR_ANGLE_THRESHOLD:
                pts.pop(i)
                changed = True
                break
    return pts


def _edge_lengths(points: list[tuple[float, float]]) -> list[float]:
    n = len(points)
    return [math.hypot(points[(i + 1) % n][0] - points[i][0], points[(i + 1) % n][1] - points[i][1]) for i in range(n)]


def classify_shape(points: list[tuple[float, float]]) -> str:
    pts = _simplify_polygon(points)
    n = len(pts)
    if n < 3:
        return "hex_partial"

    angles = [_interior_angle(pts[(i - 1) % n], pts[i], pts[(i + 1) % n]) for i in range(n)]

    if TILE_MIN_SIDES <= n <= TILE_MAX_SIDES and n % 2 == 0:
        if all(abs(a - TILE_ANGLE_CENTER) <= TILE_ANGLE_TOLERANCE for a in angles):
            return "tile"

    if n == 6:
        angles_ok = all(abs(a - HEX_ANGLE_CENTER) <= HEX_ANGLE_TOLERANCE for a in angles)
        lengths = _edge_lengths(pts)
        edge_ratio = max(lengths) / max(min(lengths), 1e-9)
        if angles_ok and edge_ratio <= HEX_EDGE_RATIO_MAX:
            return "hex_full"

    return "hex_partial"


def _centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    poly = Polygon(points)
    if not poly.is_valid or poly.area == 0:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return (sum(xs) / len(xs), sum(ys) / len(ys))
    c = poly.centroid
    return (c.x, c.y)


# ---------------------------------------------------------------------------
# Color resolution
# ---------------------------------------------------------------------------
def _resolve_color(entity, doc) -> tuple[str, tuple[int, int, int]]:
    """Return (stable_key, rgb) for an entity's effective color."""
    true_color = entity.dxf.get("true_color", None)
    if true_color is not None:
        rgb = ((true_color >> 16) & 0xFF, (true_color >> 8) & 0xFF, true_color & 0xFF)
        return f"true:{true_color}", rgb

    aci = entity.dxf.get("color", 256)
    if aci in (256, 0):  # BYLAYER / BYBLOCK -> resolve via layer
        layer_name = entity.dxf.get("layer", "0")
        layer = doc.layers.get(layer_name) if doc.layers.has_entry(layer_name) else None
        if layer is not None:
            layer_true_color = layer.dxf.get("true_color", None)
            if layer_true_color is not None:
                rgb = ((layer_true_color >> 16) & 0xFF, (layer_true_color >> 8) & 0xFF, layer_true_color & 0xFF)
                return f"layer_true:{layer_true_color}", rgb
            aci = layer.dxf.get("color", 7)
        else:
            aci = 7

    try:
        rgb = aci2rgb(abs(aci))
    except Exception:
        rgb = DEFAULT_COLOR_RGB
    return f"aci:{abs(aci)}", rgb


# ---------------------------------------------------------------------------
# Label parsing
# ---------------------------------------------------------------------------
def _parse_module_label(text: str) -> tuple[str, tuple[int, int] | None]:
    """Split a module MTEXT body into (code, (u,v) | None).

    The body is typically "M3\\n(3,2)" -- first line is the module code, the
    optional second line is "(u,v)". Some cassettes only have the code line.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    code = lines[0] if lines else text.strip()
    uv: tuple[int, int] | None = None
    for ln in lines[1:]:
        body = ln.strip("() ")
        parts = [p.strip() for p in body.split(",")]
        if len(parts) == 2:
            try:
                uv = (int(parts[0]), int(parts[1]))
                break
            except ValueError:
                continue
    return code, uv


# ---------------------------------------------------------------------------
# Train registry
# ---------------------------------------------------------------------------
class _TrainRegistry:
    """Collects trains by color_key, assigning sequential ids and labels."""

    def __init__(self) -> None:
        self._by_key: dict[str, Train] = {}
        self._order: list[str] = []

    def get_or_create(self, color_key: str, color_rgb: tuple[int, int, int]) -> Train:
        if color_key in self._by_key:
            return self._by_key[color_key]
        idx = len(self._by_key) + 1
        train = Train(
            id=color_key,
            label=f"Train {idx}",
            color_key=color_key,
            color_rgb=color_rgb,
        )
        self._by_key[color_key] = train
        self._order.append(color_key)
        return train

    def all(self) -> list[Train]:
        return [self._by_key[k] for k in self._order]

    def try_assign_label(self, color_key: str, label: str) -> None:
        train = self._by_key.get(color_key)
        if train is None:
            return
        # keep the first non-default label we see
        if train.label.startswith("Train "):
            train.label = label


# ---------------------------------------------------------------------------
# Main parse entrypoint
# ---------------------------------------------------------------------------
def load_cassette(filepath: str, name: str) -> CassetteModel:
    doc = ezdxf.readfile(filepath)
    msp = doc.modelspace()

    trains = _TrainRegistry()

    # --- collect candidate module outlines from LWPOLYLINE ---
    outlines = []
    for e in msp.query("LWPOLYLINE"):
        if not e.closed:
            continue
        raw = list(e.get_points("xyb"))
        pts = _flatten_lwpolyline(raw, closed=True)
        pts = _dedupe_points(pts)
        if len(pts) < 3:
            continue
        poly = Polygon(pts)
        if not poly.is_valid or poly.area <= 1e-6:
            continue
        outlines.append({"points": pts, "polygon": poly, "centroid": _centroid(pts)})

    # --- collect HATCH regions (color + a representative point) ---
    hatches = []
    for e in msp.query("HATCH"):
        color_key, color_rgb = _resolve_color(e, doc)
        # representative point: centroid of the first boundary path
        rep_point = None
        try:
            for path in e.paths:
                verts = None
                if hasattr(path, "vertices") and path.vertices:
                    verts = [(v[0], v[1]) for v in path.vertices]
                elif hasattr(path, "edges"):
                    verts = []
                    for edge in path.edges:
                        start = getattr(edge, "start", None)
                        if start is not None:
                            verts.append((start[0], start[1]))
                if verts and len(verts) >= 3:
                    rep_point = _centroid(verts)
                    break
        except Exception:
            rep_point = None
        if rep_point is None:
            continue
        hatches.append({"point": rep_point, "color_key": color_key, "color_rgb": color_rgb})

    # --- match each hatch to the outline that contains it ---
    outline_hatch: dict[int, dict] = {}
    for h in hatches:
        pt = Point(h["point"])
        best_idx = None
        best_dist = None
        for idx, o in enumerate(outlines):
            if o["polygon"].contains(pt) or o["polygon"].distance(pt) < 1e-6:
                # contained: pick the smallest containing polygon (nested shapes safety)
                dist = o["polygon"].area
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best_idx = idx
        if best_idx is None:
            # fall back to nearest centroid within a reasonable radius
            for idx, o in enumerate(outlines):
                dist = pt.distance(Point(o["centroid"]))
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best_idx = idx
        if best_idx is not None:
            outline_hatch[best_idx] = h
            trains.get_or_create(h["color_key"], h["color_rgb"])

    # --- collect MTEXT labels, split into module vs train labels ---
    module_labels: list[dict] = []
    train_label_points: list[dict] = []
    for e in msp.query("MTEXT"):
        insert = e.dxf.insert
        try:
            text = e.plain_text()
        except Exception:
            text = e.text
        text = text.strip()
        if not text:
            continue
        color = e.dxf.get("color", 256)
        point = (insert[0], insert[1])
        if color == TRAIN_LABEL_COLOR:
            train_label_points.append({"point": point, "text": text})
        else:
            # treat everything else as a candidate module label (the canonical
            # marker is color 250, but be lenient in case other cassettes vary)
            module_labels.append({"point": point, "text": text})

    # --- collect engines (CIRCLE on ENGINES layer) ---
    engine_entries: list[dict] = []
    for c in msp.query("CIRCLE"):
        layer = c.dxf.get("layer", "")
        if layer != ENGINES_LAYER:
            continue
        ctr = c.dxf.center
        color_key, color_rgb = _resolve_color(c, doc)
        engine_entries.append({
            "center": (ctr[0], ctr[1]),
            "radius": float(c.dxf.radius),
            "color_key": color_key,
            "color_rgb": color_rgb,
        })

    # Engines belong to the train whose color matches. If an engine's color
    # doesn't match any existing train, register a new train for it (this can
    # happen when an engine color has no hatched module, though in practice
    # every engine color also appears as a hatch color in the sample files).
    for eng in engine_entries:
        trains.get_or_create(eng["color_key"], eng["color_rgb"])

    # --- assign human-readable labels to trains ---
    # Each train-label MTEXT (e.g. "TL1", "LD3") sits near one of the trains.
    # We match labels to trains greedily: deduplicate the label texts, then for
    # each unique label find the nearest module whose train hasn't been named
    # yet. This avoids two labels collapsing onto the same train when they're
    # clustered near modules of one color.
    labeled_trains: set[str] = set()
    seen_texts: set[str] = set()
    for tl in train_label_points:
        if tl["text"] in seen_texts:
            continue
        seen_texts.add(tl["text"])
        pt = Point(tl["point"])
        best_idx = None
        best_dist = None
        for idx, o in enumerate(outlines):
            if idx not in outline_hatch:
                continue
            train_id = outline_hatch[idx]["color_key"]
            if train_id in labeled_trains:
                continue
            d = pt.distance(Point(o["centroid"]))
            if best_dist is None or d < best_dist:
                best_dist = d
                best_idx = idx
        if best_idx is not None:
            train_id = outline_hatch[best_idx]["color_key"]
            trains.try_assign_label(train_id, tl["text"])
            labeled_trains.add(train_id)
            continue
        # fall back to nearest unlabelled engine
        best_eng = None
        best_eng_d = None
        for eng in engine_entries:
            if eng["color_key"] in labeled_trains:
                continue
            d = pt.distance(Point(eng["center"]))
            if best_eng_d is None or d < best_eng_d:
                best_eng_d = d
                best_eng = eng
        if best_eng is not None:
            trains.try_assign_label(best_eng["color_key"], tl["text"])
            labeled_trains.add(best_eng["color_key"])

    # --- build modules: only outlines with a matched hatch count as modules ---
    modules: list[Module] = []
    for idx, o in enumerate(outlines):
        hatch = outline_hatch.get(idx)
        if hatch is None:
            continue
        shape = classify_shape(o["points"])
        train = trains.get_or_create(hatch["color_key"], hatch["color_rgb"])

        # find the module label whose insertion point falls inside this module
        label_text = ""
        code = ""
        uv: tuple[int, int] | None = None
        best_label_dist = None
        for lab in module_labels:
            pt = Point(lab["point"])
            if o["polygon"].contains(pt):
                label_text = lab["text"]
                code, uv = _parse_module_label(lab["text"])
                break
            dist = pt.distance(Point(o["centroid"]))
            if best_label_dist is None or dist < best_label_dist:
                if o["polygon"].distance(pt) < max(o["polygon"].length * 0.05, 1e-6):
                    best_label_dist = dist
                    label_text = lab["text"]
                    code, uv = _parse_module_label(lab["text"])

        modules.append(
            Module(
                id=f"module-{idx}",
                polygon=o["points"],
                shape=shape,
                train_id=train.id,
                color_key=hatch["color_key"],
                color_rgb=hatch["color_rgb"],
                code=code or f"Module {idx + 1}",
                uv=uv,
                label=label_text or f"Module {idx + 1}",
                centroid=o["centroid"],
            )
        )

    # --- build engines ---
    engines: list[Engine] = []
    for i, eng in enumerate(engine_entries):
        train = trains.get_or_create(eng["color_key"], eng["color_rgb"])
        engines.append(
            Engine(
                id=f"engine-{i}",
                center=eng["center"],
                radius=eng["radius"],
                train_id=train.id,
                color_key=eng["color_key"],
                color_rgb=eng["color_rgb"],
            )
        )

    all_x = [p[0] for m in modules for p in m.polygon] + [e.center[0] for e in engines]
    all_y = [p[1] for m in modules for p in m.polygon] + [e.center[1] for e in engines]
    if not all_x:
        all_x = [0, 1]
    if not all_y:
        all_y = [0, 1]
    bounds = (min(all_x), min(all_y), max(all_x), max(all_y))

    return CassetteModel(
        name=name,
        modules=modules,
        engines=engines,
        trains=trains.all(),
        bounds=bounds,
    )


def summarize(model: CassetteModel) -> CassetteSummary:
    full_hex = sum(1 for m in model.modules if m.shape == "hex_full")
    partial_hex = sum(1 for m in model.modules if m.shape == "hex_partial")
    tile = sum(1 for m in model.modules if m.shape == "tile")
    trains = len(model.trains)
    cassette_type = "Mixed" if tile > 0 else "Pure silicon"
    return CassetteSummary(
        cassette_type=cassette_type,
        full_hex=full_hex,
        partial_hex=partial_hex,
        tile=tile,
        trains=trains,
        engines=len(model.engines),
    )
