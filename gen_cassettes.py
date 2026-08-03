"""Generate sample cassette DXF + JSON files for the interactive viewer.

DXF structure:
  Layers: 0, ENGINES (circles), SHAPES (closed LWPOLYLINEs), TEXT (MTEXT)
  Each train's modules are closed polylines on SHAPES with a unique ACI color.
  Engine circles are on the ENGINES layer (all same ACI color).
  MTEXT labels on TEXT layer: module code + (u,v), and train label.

JSON structure:
  { cassette_half: { train_name: { module_code: {type, i_rot, trigLinks, daqLinks},
                                   "engine": {u, v, type},
                                   "wagon_west": str, "wagon_east": str,
                                   "wingboard": str, "motherboard": str } } }
"""

import json
import math
import ezdxf

HEX_RADIUS = 60.0
TILE_W = 100.0
TILE_H = 80.0
ENGINE_RADIUS = 40.0
SPACING_X = 400.0
SPACING_Y = 450.0


def hex_polygon(cx, cy, r=HEX_RADIUS):
    pts = []
    for i in range(6):
        angle = math.radians(60 * i + 30)
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return pts


def tile_polygon(cx, cy, w=TILE_W, h=TILE_H):
    return [
        (cx - w / 2, cy - h / 2),
        (cx + w / 2, cy - h / 2),
        (cx + w / 2, cy + h / 2),
        (cx - w / 2, cy + h / 2),
    ]


def uv_to_xy(u, v, origin_x, origin_y, dx=120, dy=90):
    return (origin_x + u * dx, origin_y + v * dy)


def add_train(msp, train_label, aci_color, modules_spec, origin_x, origin_y,
              is_hex=True, engine_uv=None, engine_type="EL10E0"):
    """Add a train's shapes, text, and engine to the modelspace.

    modules_spec: list of (code, u, v, shape_type) where shape_type is
    'hex' or 'tile'.
    """
    for code, u, v, shape_type in modules_spec:
        cx, cy = uv_to_xy(u, v, origin_x, origin_y)
        if shape_type == "hex":
            pts = hex_polygon(cx, cy)
        else:
            pts = tile_polygon(cx, cy)
        msp.add_lwpolyline(pts, dxfattribs={"layer": "SHAPES", "color": aci_color}, close=True)
        # Add a HATCH inside the outline so dxf_model.py matches it as a module.
        hatch = msp.add_hatch(color=aci_color, dxfattribs={"layer": "SHAPES"})
        hatch.paths.add_polyline_path(pts, is_closed=True)
        msp.add_mtext(
            f"{code}\n({u},{v})",
            dxfattribs={"layer": "TEXT", "color": 250, "insert": (cx, cy)},
        )
    msp.add_mtext(
        train_label,
        dxfattribs={"layer": "TEXT", "color": 0, "insert": (origin_x - 50, origin_y)},
    )
    if engine_uv is not None:
        eu, ev = engine_uv
        ex, ey = uv_to_xy(eu, ev, origin_x, origin_y)
        msp.add_circle(
            (ex, ey), radius=ENGINE_RADIUS,
            dxfattribs={"layer": "ENGINES", "color": 1},
        )


def build_cassette_18C_44C():
    doc = ezdxf.new("R2010")
    doc.layers.add("ENGINES", color=1)
    doc.layers.add("SHAPES", color=250)
    doc.layers.add("TEXT", color=250)
    msp = doc.modelspace()

    json_data = {"44C": {}, "18C": {}}

    # 44C half — TL3, TL2, TL1 (hex tile trains), LD2, LD1 (wagon trains)
    # TL3: 5 hex modules G8,E8,D8,B12,A6 at v=6
    tl3_mods = [("G8", 4, 6, "hex"), ("E8", 3, 6, "hex"), ("D8", 2, 6, "hex"),
                ("B12", 1, 6, "hex"), ("A6", 0, 6, "hex")]
    add_train(msp, "TL3", 32, tl3_mods, 1000, 200, is_hex=True)
    json_data["44C"]["TL3"] = {
        "G8": {"u": 4, "v": 6, "type": "TM-G8RM", "i_rot": 0, "trigLinks": 1, "daqLinks": 1},
        "E8": {"u": 3, "v": 6, "type": "TM-E8FM", "i_rot": 0, "trigLinks": 1, "daqLinks": 1},
        "D8": {"u": 2, "v": 6, "type": "TM-D8FM", "i_rot": 0, "trigLinks": 1, "daqLinks": 1},
        "B12": {"u": 1, "v": 6, "type": "TM-B2FC", "i_rot": 0, "trigLinks": 1, "daqLinks": 1},
        "A6": {"u": 0, "v": 6, "type": "TM-A6FC", "i_rot": 0, "trigLinks": 1, "daqLinks": 1},
        "engine": {"u": 4.5, "v": 6.5, "type": "EL10E0"},
        "wingboard": "WB-44C-TL3",
        "motherboard": "MB-44C-TL3",
    }

    tl2_mods = [("G8", 4, 7, "hex"), ("E8", 3, 7, "hex"), ("D8", 2, 7, "hex"),
                ("B12", 1, 7, "hex"), ("A5", 0, 7, "hex")]
    add_train(msp, "TL2", 42, tl2_mods, 1000, 650, is_hex=True)
    json_data["44C"]["TL2"] = {
        "G8": {"u": 4, "v": 7, "type": "TM-G8FM", "i_rot": 0, "trigLinks": 1, "daqLinks": 1},
        "E8": {"u": 3, "v": 7, "type": "TM-E8FM", "i_rot": 0, "trigLinks": 1, "daqLinks": 1},
        "D8": {"u": 2, "v": 7, "type": "TM-D8FM", "i_rot": 0, "trigLinks": 1, "daqLinks": 1},
        "B12": {"u": 1, "v": 7, "type": "TM-B2FC", "i_rot": 0, "trigLinks": 1, "daqLinks": 1},
        "A5": {"u": 0, "v": 7, "type": "TM-A5FC", "i_rot": 0, "trigLinks": 1, "daqLinks": 1},
        "engine": {"u": 4.5, "v": 7.5, "type": "EL10E0"},
        "wingboard": "WB-44C-TL2",
        "motherboard": "MB-44C-TL2",
    }

    tl1_mods = [("G8", 4, 8, "hex"), ("E8", 3, 8, "hex"), ("D8", 2, 8, "hex"),
                ("B12", 1, 8, "hex"), ("A6", 0, 8, "hex")]
    add_train(msp, "TL1", 82, tl1_mods, 1000, 1100, is_hex=True)
    json_data["44C"]["TL1"] = {
        "G8": {"u": 4, "v": 8, "type": "TM-G8LM", "i_rot": 0, "trigLinks": 1, "daqLinks": 1},
        "E8": {"u": 3, "v": 8, "type": "TM-E8FM", "i_rot": 0, "trigLinks": 1, "daqLinks": 1},
        "D8": {"u": 2, "v": 8, "type": "TM-D8FM", "i_rot": 0, "trigLinks": 1, "daqLinks": 1},
        "B12": {"u": 1, "v": 8, "type": "TM-B2FC", "i_rot": 0, "trigLinks": 1, "daqLinks": 1},
        "A6": {"u": 0, "v": 8, "type": "TM-A6FC", "i_rot": 0, "trigLinks": 1, "daqLinks": 1},
        "engine": {"u": 4.5, "v": 8.5, "type": "EL10E0"},
        "wingboard": "WB-44C-TL1",
        "motherboard": "MB-44C-TL1",
    }

    # LD2: wagon train — W1,W2 on west, E1,E2 on east, engine at center
    ld2_mods = [("W1", 4, 5, "hex"), ("W2", 3, 4, "hex"),
                ("E1", 5, 6, "hex"), ("E2", 6, 7, "hex")]
    add_train(msp, "LD2", 122, ld2_mods, 1000, 1600, is_hex=True,
              engine_uv=(4.5, 5.5), engine_type="EL10E0")
    json_data["44C"]["LD2"] = {
        "W1": {"u": 4, "v": 5, "type": "ML-F3T", "i_rot": 1, "trigLinks": 2, "daqLinks": 1},
        "W2": {"u": 3, "v": 4, "type": "ML-T3T", "i_rot": 1, "trigLinks": 2, "daqLinks": 1},
        "E1": {"u": 5, "v": 6, "type": "ML-F3T", "i_rot": 1, "trigLinks": 2, "daqLinks": 1},
        "E2": {"u": 6, "v": 7, "type": "ML-B3T", "i_rot": 1, "trigLinks": 2, "daqLinks": 1},
        "engine": {"u": 4.5, "v": 5.5, "type": "EL10E0"},
        "wagon_west": "WW11A1",
        "wagon_east": "WE11A1",
    }

    # LD1: wagon train — W1 on west, E1,E2,E3 on east
    ld1_mods = [("W1", 3, 5, "hex"), ("E1", 4, 6, "hex"),
                ("E2", 5, 7, "hex"), ("E3", 4, 7, "hex")]
    add_train(msp, "LD1", 152, ld1_mods, 1000, 2100, is_hex=True,
              engine_uv=(3.5, 5.5), engine_type="EL10E0")
    json_data["44C"]["LD1"] = {
        "W1": {"u": 3, "v": 5, "type": "ML-F3T", "i_rot": 1, "trigLinks": 2, "daqLinks": 1},
        "E1": {"u": 4, "v": 6, "type": "ML-F3T", "i_rot": 1, "trigLinks": 2, "daqLinks": 1},
        "E2": {"u": 5, "v": 7, "type": "ML-F3T", "i_rot": 1, "trigLinks": 2, "daqLinks": 1},
        "E3": {"u": 4, "v": 7, "type": "ML-F3T", "i_rot": 5, "trigLinks": 2, "daqLinks": 1},
        "engine": {"u": 3.5, "v": 5.5, "type": "EL10E0"},
        "wagon_west": "WW10A1",
        "wagon_east": "WE30A3",
    }

    # Extra engine circles (unlabeled — "Train 6" in DXF color grouping)
    for ey in [200, 650, 1100, 1600, 2100]:
        msp.add_circle((2600, ey), radius=ENGINE_RADIUS,
                      dxfattribs={"layer": "ENGINES", "color": 246})

    msp.add_mtext("Cassette 18C(44C)",
                  dxfattribs={"layer": "TEXT", "color": 8, "insert": (100, -50)})

    doc.saveas("cassette_layouts/Cassette_18C_44C.dxf")
    with open("cassette_layouts/Cassette_18C_44C.json", "w") as f:
        json.dump(json_data, f, indent=4)
    print("Generated Cassette_18C_44C.dxf + .json")


def build_cassette_7B_33B():
    doc = ezdxf.new("R2010")
    doc.layers.add("ENGINES", color=1)
    doc.layers.add("SHAPES", color=250)
    doc.layers.add("TEXT", color=250)
    msp = doc.modelspace()

    json_data = {"33B": {}, "7B": {}}

    # 33B half — HD1, HD2 (high-density wagon trains), LD3..LD5 (low-density wagon trains)
    # HD1: M1,M2,M3 with wagon_type, engine
    hd1_mods = [("M1", 5, 4, "hex"), ("M2", 4, 3, "hex"), ("M3", 3, 2, "hex")]
    add_train(msp, "HD1", 32, hd1_mods, 1000, 200, is_hex=True,
              engine_uv=(5.5, 4.5), engine_type="EH10H0")
    json_data["33B"]["HD1"] = {
        "M1": {"u": 5, "v": 4, "type": "MH-F2T", "i_rot": 4, "trigLinks": 4, "daqLinks": 1},
        "M2": {"u": 4, "v": 3, "type": "MH-F2T", "i_rot": 4, "trigLinks": 5, "daqLinks": 1},
        "M3": {"u": 3, "v": 2, "type": "MH-F2T", "i_rot": 4, "trigLinks": 5, "daqLinks": 2},
        "engine": {"u": 5.5, "v": 4.5, "type": "EH10H0"},
        "wagon_type": "WH30BT",
    }

    hd2_mods = [("M1", 5, 3, "hex"), ("M2", 4, 2, "hex")]
    add_train(msp, "HD2", 42, hd2_mods, 1000, 650, is_hex=True,
              engine_uv=(5.5, 3.5), engine_type="EH10H0")
    json_data["33B"]["HD2"] = {
        "M1": {"u": 5, "v": 3, "type": "MH-F2T", "i_rot": 4, "trigLinks": 5, "daqLinks": 1},
        "M2": {"u": 4, "v": 2, "type": "MH-F2T", "i_rot": 4, "trigLinks": 5, "daqLinks": 1},
        "engine": {"u": 5.5, "v": 3.5, "type": "EH10H0"},
        "wagon_type": "WH20AT",
    }

    # LD3: W1,W2,W3 west, E1-E4 east
    ld3_mods = [("W1", 10, 7, "hex"), ("W2", 11, 8, "hex"), ("W3", 12, 9, "hex"),
                ("E1", 9, 6, "hex"), ("E2", 8, 5, "hex"), ("E3", 7, 4, "hex"),
                ("E4", 6, 3, "hex")]
    add_train(msp, "LD3", 82, ld3_mods, 1000, 1100, is_hex=True,
              engine_uv=(9.5, 6.5), engine_type="EL10W0")
    json_data["33B"]["LD3"] = {
        "W1": {"u": 10, "v": 7, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "W2": {"u": 11, "v": 8, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "W3": {"u": 12, "v": 9, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "E1": {"u": 9, "v": 6, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "E2": {"u": 8, "v": 5, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "E3": {"u": 7, "v": 4, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "E4": {"u": 6, "v": 3, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "engine": {"u": 9.5, "v": 6.5, "type": "EL10W0"},
        "wagon_west": "WW30A1",
        "wagon_east": "WE40A1",
    }

    # LD2: W1,W2,W3 west, E1-E4 east
    ld2_mods = [("W1", 10, 8, "hex"), ("W2", 11, 9, "hex"), ("W3", 12, 10, "hex"),
                ("E1", 9, 7, "hex"), ("E2", 8, 6, "hex"), ("E3", 7, 5, "hex"),
                ("E4", 6, 4, "hex")]
    add_train(msp, "LD2", 122, ld2_mods, 1000, 1700, is_hex=True,
              engine_uv=(9.5, 7.5), engine_type="EL10W0")
    json_data["33B"]["LD2"] = {
        "W1": {"u": 10, "v": 8, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "W2": {"u": 11, "v": 9, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "W3": {"u": 12, "v": 10, "type": "ML-T3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "E1": {"u": 9, "v": 7, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "E2": {"u": 8, "v": 6, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "E3": {"u": 7, "v": 5, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "E4": {"u": 6, "v": 4, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "engine": {"u": 9.5, "v": 7.5, "type": "EL10W0"},
        "wagon_west": "WW21B1",
        "wagon_east": "WE40A1",
    }

    # LD1: W1,W2,W3 west, E1-E3 east
    ld1_mods = [("W1", 9, 8, "hex"), ("W2", 10, 9, "hex"), ("W3", 11, 10, "hex"),
                ("E1", 8, 7, "hex"), ("E2", 7, 6, "hex"), ("E3", 6, 5, "hex")]
    add_train(msp, "LD1", 152, ld1_mods, 1000, 2300, is_hex=True,
              engine_uv=(8.5, 7.5), engine_type="EL10W0")
    json_data["33B"]["LD1"] = {
        "W1": {"u": 9, "v": 8, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "W2": {"u": 10, "v": 9, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "W3": {"u": 11, "v": 10, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "E1": {"u": 8, "v": 7, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "E2": {"u": 7, "v": 6, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "E3": {"u": 6, "v": 5, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "engine": {"u": 8.5, "v": 7.5, "type": "EL10W0"},
        "wagon_west": "WW30A1",
        "wagon_east": "WE30A1",
    }

    # LD4: W1,W2,W3 west, E1,E2 east
    ld4_mods = [("W1", 10, 6, "hex"), ("W2", 11, 7, "hex"), ("W3", 12, 8, "hex"),
                ("E1", 9, 5, "hex"), ("E2", 8, 4, "hex")]
    add_train(msp, "LD4", 202, ld4_mods, 1000, 2900, is_hex=True,
              engine_uv=(9.5, 5.5), engine_type="EL10W0")
    json_data["33B"]["LD4"] = {
        "W1": {"u": 10, "v": 6, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "W2": {"u": 11, "v": 7, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "W3": {"u": 12, "v": 8, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "E1": {"u": 9, "v": 5, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "E2": {"u": 8, "v": 4, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "engine": {"u": 9.5, "v": 5.5, "type": "EL10W0"},
        "wagon_west": "WW30A1",
        "wagon_east": "WE20A1",
    }

    # LD5: W1,W2 west, E1,E2,E3 east
    ld5_mods = [("W1", 12, 7, "hex"), ("W2", 13, 8, "hex"),
                ("E1", 11, 6, "hex"), ("E2", 10, 5, "hex"), ("E3", 12, 6, "hex")]
    add_train(msp, "LD5", 222, ld5_mods, 1000, 3400, is_hex=True,
              engine_uv=(11.5, 6.5), engine_type="EL10W0")
    json_data["33B"]["LD5"] = {
        "W1": {"u": 12, "v": 7, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "W2": {"u": 13, "v": 8, "type": "ML-R3T", "i_rot": 5, "trigLinks": 2, "daqLinks": 1},
        "E1": {"u": 11, "v": 6, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "E2": {"u": 10, "v": 5, "type": "ML-F3T", "i_rot": 4, "trigLinks": 2, "daqLinks": 1},
        "E3": {"u": 12, "v": 6, "type": "ML-53T", "i_rot": 2, "trigLinks": 2, "daqLinks": 1},
        "engine": {"u": 11.5, "v": 6.5, "type": "EL10W0"},
        "wagon_west": "WW11A1",
        "wagon_east": "WE21C3",
    }

    # Extra engine circles (unlabeled — "Train 7", "Train 8" groups)
    for ey in [200, 650]:
        msp.add_circle((2600, ey), radius=ENGINE_RADIUS,
                      dxfattribs={"layer": "ENGINES", "color": 214})
    for ey in [1100, 1700, 2300, 2900, 3400]:
        msp.add_circle((2600, ey), radius=ENGINE_RADIUS,
                      dxfattribs={"layer": "ENGINES", "color": 246})

    msp.add_mtext("Cassette 7B(33B)",
                  dxfattribs={"layer": "TEXT", "color": 8, "insert": (100, -50)})

    doc.saveas("cassette_layouts/Cassette_7B_33B.dxf")
    with open("cassette_layouts/Cassette_7B_33B.json", "w") as f:
        json.dump(json_data, f, indent=4)
    print("Generated Cassette_7B_33B.dxf + .json")


if __name__ == "__main__":
    build_cassette_18C_44C()
    build_cassette_7B_33B()
    print("Done.")
