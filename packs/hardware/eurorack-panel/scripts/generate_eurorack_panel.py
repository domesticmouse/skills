#!/usr/bin/env python3
"""
Inspect a KiCad Eurorack main PCB and generate a mated 3U Eurorack Front Panel
(`.kicad_pcb`), complete with M3 mounting slots, grounded bushing cutouts,
silkscreen labels/input badges, filled copper shield planes, DRC verification,
and Gerber/Drill exports.

Usage:
  # 1. Inspect panel-mounted components & coordinates from a main PCB:
  python3 .agents/skills/eurorack-panel/scripts/generate_eurorack_panel.py \
      --main-pcb BufferedMult.kicad_pcb --inspect

  # 2. Generate the front panel PCB, run DRC, and export Gerbers + 3D renders:
  python3 .agents/skills/eurorack-panel/scripts/generate_eurorack_panel.py \
      --main-pcb BufferedMult.kicad_pcb \
      --output BufferedMult_Panel.kicad_pcb \
      --title "BUF MULT" \
      --subtitle "1:3 / 1:6" \
      --gerber-dir production/panel \
      --zip production/BufferedMult_Panel.zip \
      --drc
"""

import argparse
import json
import math
import pathlib
import re
import subprocess
import sys
import uuid
import zipfile

# Standard Doepfer A-100 3U height and HP widths (mm)
PANEL_HEIGHT_3U_MM = 128.5
DOEPFER_HP_WIDTHS_MM: dict[int, float] = {
    1: 5.00,
    2: 9.80,
    3: 15.00,
    4: 20.00,
    6: 30.00,
    8: 40.30,
    10: 50.50,
    12: 60.60,
    14: 70.80,
    16: 80.90,
    20: 101.30,
    24: 121.60,
    28: 141.90,
    42: 213.00,
}

# Default hole & nut/bezel dimensions by panel-mounted component type (mm)
JACK_DRILL_MM = 6.2
JACK_PAD_MM = 8.6
JACK_NUT_DIA_MM = 9.5

PANEL_COMPONENT_SPECS: list[dict] = [
    {
        "kind": "jack",
        "pattern": re.compile(
            r"WQP-PJ398SM|PJ301M|Thonkiconn|Jack_3\.5mm", re.IGNORECASE
        ),
        "default_offset": (0.0, 6.48),
        "drill_mm": JACK_DRILL_MM,
        "pad_mm": JACK_PAD_MM,
        "keepout_mm": JACK_NUT_DIA_MM,
        "grounded": True,
    },
    {
        "kind": "pot",
        "pattern": re.compile(
            r"Potentiometer.*Vertical|RK09K|RV09AF|RD901F", re.IGNORECASE
        ),
        "default_offset": (2.5, -7.0),
        "drill_mm": 7.2,
        "pad_mm": 9.6,
        "keepout_mm": 11.0,
        "grounded": True,
    },
    {
        "kind": "switch",
        "pattern": re.compile(
            r"SW_CuK_JS202011JCQN|SW_Toggle|100-SP1|Dailywell", re.IGNORECASE
        ),
        "default_offset": (0.0, 0.0),
        "drill_mm": 6.2,
        "pad_mm": 8.2,
        "keepout_mm": 9.0,
        "grounded": True,
    },
    {
        "kind": "led_5mm",
        "pattern": re.compile(r"LED_D5\.0mm", re.IGNORECASE),
        "default_offset": (1.27, 0.0),
        "drill_mm": 5.2,
        "pad_mm": 5.2,
        "keepout_mm": 6.0,
        "grounded": False,
    },
    {
        "kind": "led_3mm",
        "pattern": re.compile(r"LED_D3\.0mm", re.IGNORECASE),
        "default_offset": (1.27, 0.0),
        "drill_mm": 3.2,
        "pad_mm": 3.2,
        "keepout_mm": 4.0,
        "grounded": False,
    },
]

# M3 Eurorack mounting slot dimensions (mm)
MOUNT_SLOT_W_MM = 5.5
MOUNT_SLOT_H_MM = 3.2
MOUNT_X_LOCAL_MM = 7.5
MOUNT_TOP_Y_LOCAL_MM = 3.0
MOUNT_BOT_Y_LOCAL_MM = 125.5

KICAD_CLI = pathlib.Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")
KICAD_PYTHON = pathlib.Path(
    "/Applications/KiCad/KiCad.app/Contents/Frameworks/"
    "Python.framework/Versions/Current/bin/python3"
)


def det_uuid(namespace: str, name: str) -> str:
    """Return a deterministic UUIDv5 string for reproducible KiCad file generation."""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{namespace}:{name}"))


def infer_hp_and_width(
    pcb_width_mm: float, explicit_hp: int | None
) -> tuple[int, float]:
    """Infer HP count and standard Doepfer panel width (mm) from main PCB width."""
    if explicit_hp is not None:
        width = DOEPFER_HP_WIDTHS_MM.get(
            explicit_hp, round(explicit_hp * 5.08 - 0.3, 2)
        )
        return explicit_hp, width

    approx_hp = max(1, round(pcb_width_mm / 5.08))
    width = DOEPFER_HP_WIDTHS_MM.get(approx_hp, round(approx_hp * 5.08 - 0.3, 2))
    return approx_hp, width


def rotate_offset(cx: float, cy: float, rot_deg: float) -> tuple[float, float]:
    """Rotate a footprint-local offset (cx, cy) by KiCad's CCW rotation angle (deg)."""
    rad = math.radians(rot_deg)
    dx = cx * math.cos(rad) + cy * math.sin(rad)
    dy = -cx * math.sin(rad) + cy * math.cos(rad)
    return round(dx, 4), round(dy, 4)


def parse_main_pcb(pcb_path: pathlib.Path) -> tuple[dict[str, float], list[dict]]:
    """Extract PCB outline and panel-mounted part coords from a `.kicad_pcb` file."""
    text = pcb_path.read_text(encoding="utf-8")

    rect_match = re.search(
        r"\(gr_rect\s+\(start\s+([\d.-]+)\s+([\d.-]+)\)\s+\(end\s+([\d.-]+)\s+([\d.-]+)\)"
        r'(?:(?!\(gr_rect).)*?\(layer\s+"Edge\.Cuts"\)',
        text,
        re.DOTALL,
    )
    if rect_match:
        x1, y1, x2, y2 = (float(rect_match.group(i)) for i in range(1, 5))
        bbox = {
            "min_x": min(x1, x2),
            "min_y": min(y1, y2),
            "max_x": max(x1, x2),
            "max_y": max(y1, y2),
        }
    else:
        line_matches = re.findall(
            r"\(gr_line\s+\(start\s+([\d.-]+)\s+([\d.-]+)\)\s+\(end\s+([\d.-]+)\s+([\d.-]+)\)"
            r'(?:(?!\(gr_line).)*?\(layer\s+"Edge\.Cuts"\)',
            text,
            re.DOTALL,
        )
        if not line_matches:
            raise ValueError(
                f"Could not find Edge.Cuts gr_rect or gr_line in {pcb_path}"
            )
        xs = [float(m[0]) for m in line_matches] + [float(m[2]) for m in line_matches]
        ys = [float(m[1]) for m in line_matches] + [float(m[3]) for m in line_matches]
        bbox = {
            "min_x": min(xs),
            "min_y": min(ys),
            "max_x": max(xs),
            "max_y": max(ys),
        }

    jacks = []
    fp_pattern = re.compile(
        r'\(footprint\s+"([^"]+)"'
        r".*?\(at\s+([\d.-]+)\s+([\d.-]+)(?:\s+([\d.-]+))?\)"
        r'.*?\(property\s+"Reference"\s+"([^"]+)"'
        r'.*?\(property\s+"Value"\s+"([^"]+)"'
        r"(.*?)(?=\n\t\(footprint|\n\t\(gr_|\n\t\(segment|\n\t\(via|\n\t\(zone|\Z)",
        re.DOTALL,
    )
    for match in fp_pattern.finditer(text):
        fp_lib = match.group(1)
        spec = next(
            (s for s in PANEL_COMPONENT_SPECS if s["pattern"].search(fp_lib)),
            None,
        )
        if spec is None:
            continue

        fp_x = float(match.group(2))
        fp_y = float(match.group(3))
        rot = float(match.group(4)) if match.group(4) else 0.0
        ref = match.group(5)
        val = match.group(6)
        body = match.group(7)

        # Auto-detect bushing/shaft circle from footprint body, fallback to spec default_offset
        circle_m = re.search(r"\(fp_circle\s+\(center\s+([\d.-]+)\s+([\d.-]+)\)", body)
        def_cx, def_cy = spec["default_offset"]
        cx = float(circle_m.group(1)) if circle_m else def_cx
        cy = float(circle_m.group(2)) if circle_m else def_cy
        dx, dy = rotate_offset(cx, cy, rot)

        jacks.append(
            {
                "ref": ref,
                "value": val,
                "kind": spec["kind"],
                "footprint": fp_lib,
                "fp_x": fp_x,
                "fp_y": fp_y,
                "rot": rot,
                "offset_x": dx,
                "offset_y": dy,
                "bushing_x": round(fp_x + dx, 4),
                "bushing_y": round(fp_y + dy, 4),
                "drill_mm": spec["drill_mm"],
                "pad_mm": spec["pad_mm"],
                "keepout_mm": spec["keepout_mm"],
                "grounded": spec["grounded"],
            }
        )

    jacks.sort(key=lambda j: (j["bushing_y"], j["bushing_x"]))
    if not jacks:
        raise ValueError(
            f"No panel-mounted component footprints (jacks, pots, switches, LEDs) found in {pcb_path}"
        )

    return bbox, jacks


def print_inspection_report(
    pcb_path: pathlib.Path,
    bbox: dict[str, float],
    jacks: list[dict],
    hp: int,
    panel_w: float,
) -> None:
    """Print a mechanical alignment & coordinate report for the main PCB and panel."""
    pcb_w = round(bbox["max_x"] - bbox["min_x"], 2)
    pcb_h = round(bbox["max_y"] - bbox["min_y"], 2)
    overhang_y = round((PANEL_HEIGHT_3U_MM - pcb_h) / 2.0, 2)
    panel_x0 = round(bbox["min_x"] - (panel_w - pcb_w) / 2.0, 2)
    panel_y0 = round(bbox["min_y"] - overhang_y, 2)

    print(f"=== Eurorack Panel Mechanical Report for {pcb_path.name} ===")
    print(
        f"Main PCB Outline   : {pcb_w:.2f} x {pcb_h:.2f} mm "
        f"(X: {bbox['min_x']:.2f}..{bbox['max_x']:.2f}, "
        f"Y: {bbox['min_y']:.2f}..{bbox['max_y']:.2f})"
    )
    print(
        f"Target Front Panel : {hp}HP x 3U "
        f"({panel_w:.2f} x {PANEL_HEIGHT_3U_MM:.2f} mm), "
        f"Vertical rail overhang = {overhang_y:.2f} mm top/bottom"
    )
    print(
        f"Panel Origin (0,0) : Global ({panel_x0:.2f}, {panel_y0:.2f}) mm "
        f"-> ({panel_x0 + panel_w:.2f}, {panel_y0 + PANEL_HEIGHT_3U_MM:.2f}) mm\n"
    )
    print(
        f"{'Ref':<5} {'Value':<10} {'FP Origin (X, Y)':<20} "
        f"{'Bushing Global (X, Y)':<23} {'Panel-Local (X, Y)':<20} {'Drill'}"
    )
    print("-" * 88)
    for j in jacks:
        lx = round(j["bushing_x"] - panel_x0, 2)
        ly = round(j["bushing_y"] - panel_y0, 2)
        drill_mm = j.get("drill_mm", JACK_DRILL_MM)
        print(
            f"{j['ref']:<5} {j['value']:<10} "
            f"({j['fp_x']:6.2f}, {j['fp_y']:6.2f})     "
            f"({j['bushing_x']:6.2f}, {j['bushing_y']:6.2f})        "
            f"({lx:6.2f}, {ly:6.2f})     {drill_mm:.1f} mm"
        )


def format_jack_footprint(
    ns: str, jack: dict, panel_origin_x: float, panel_origin_y: float
) -> str:
    """Create an embedded KiCad 10 footprint for a panel-mounted component cutout."""
    ref = jack["ref"]
    val = jack["value"]
    bx = jack["bushing_x"]
    by = jack["bushing_y"]
    lx = round(bx - panel_origin_x, 2)
    ly = round(by - panel_origin_y, 2)
    drill_mm = jack.get("drill_mm", JACK_DRILL_MM)
    pad_mm = jack.get("pad_mm", JACK_PAD_MM)
    keepout_mm = jack.get("keepout_mm", JACK_NUT_DIA_MM)
    grounded = jack.get("grounded", True)
    nut_r = keepout_mm / 2.0
    pad_r = pad_mm / 2.0
    crtyd_r = round(max(pad_r, nut_r) + 0.15, 2)

    descr = (
        f"Eurorack panel cutout ({drill_mm:g}mm drill, "
        f"panel-local {lx:.2f}, {ly:.2f}mm)"
    )
    if grounded:
        pad_sexpr = f"""\t\t(pad "1" thru_hole circle
\t\t\t(at 0 0)
\t\t\t(size {pad_mm:g} {pad_mm:g})
\t\t\t(drill {drill_mm:g})
\t\t\t(layers "*.Cu" "B.Mask")
\t\t\t(remove_unused_layers no)
\t\t\t(net "GND")
\t\t\t(pintype "passive")
\t\t\t(uuid "{det_uuid(ns, f"fp_{ref}_pad1")}")
\t\t)"""
    else:
        pad_sexpr = f"""\t\t(pad "" np_thru_hole circle
\t\t\t(at 0 0)
\t\t\t(size {drill_mm:g} {drill_mm:g})
\t\t\t(drill {drill_mm:g})
\t\t\t(layers "*.Cu" "*.Mask")
\t\t\t(uuid "{det_uuid(ns, f"fp_{ref}_pad1")}")
\t\t)"""

    return f"""\t(footprint "Eurorack_Panel:JackHole_3.5mm_Thonkiconn_{drill_mm:g}mm"
\t\t(layer "F.Cu")
\t\t(uuid "{det_uuid(ns, f"fp_{ref}")}")
\t\t(at {bx:g} {by:g})
\t\t(descr "{descr}")
\t\t(tags "eurorack panel hole thonkiconn 3.5mm")
\t\t(attr board_only exclude_from_pos_files exclude_from_bom)
\t\t(property "Reference" "{ref}"
\t\t\t(at 0 0 0)
\t\t\t(layer "F.Fab")
\t\t\t(hide yes)
\t\t\t(uuid "{det_uuid(ns, f"fp_{ref}_ref")}")
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1 1)
\t\t\t\t\t(thickness 0.15)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Value" "{val}"
\t\t\t(at 0 0 0)
\t\t\t(layer "F.Fab")
\t\t\t(hide yes)
\t\t\t(uuid "{det_uuid(ns, f"fp_{ref}_val")}")
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1 1)
\t\t\t\t\t(thickness 0.15)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(fp_circle
\t\t\t(center 0 0)
\t\t\t(end {nut_r:g} 0)
\t\t\t(stroke
\t\t\t\t(width 0.1)
\t\t\t\t(type dash)
\t\t\t)
\t\t\t(fill no)
\t\t\t(layer "Dwgs.User")
\t\t\t(uuid "{det_uuid(ns, f"fp_{ref}_dwgs_nut")}")
\t\t)
\t\t(fp_circle
\t\t\t(center 0 0)
\t\t\t(end {pad_r:g} 0)
\t\t\t(stroke
\t\t\t\t(width 0.1)
\t\t\t\t(type solid)
\t\t\t)
\t\t\t(fill no)
\t\t\t(layer "F.Fab")
\t\t\t(uuid "{det_uuid(ns, f"fp_{ref}_fab_nut")}")
\t\t)
\t\t(fp_circle
\t\t\t(center 0 0)
\t\t\t(end {crtyd_r:g} 0)
\t\t\t(stroke
\t\t\t\t(width 0.05)
\t\t\t\t(type solid)
\t\t\t)
\t\t\t(fill no)
\t\t\t(layer "F.CrtYd")
\t\t\t(uuid "{det_uuid(ns, f"fp_{ref}_crtyd")}")
\t\t)
{pad_sexpr}
\t)"""


def format_mount_slot_footprint(ns: str, ref: str, x: float, y: float) -> str:
    """Create an embedded KiCad 10 footprint for an M3 Eurorack oval mounting slot."""
    hw = MOUNT_SLOT_W_MM / 2.0 + 0.25
    hh = MOUNT_SLOT_H_MM / 2.0 + 0.25
    descr = (
        f"Eurorack M3 oval mounting slot ({MOUNT_SLOT_H_MM}x{MOUNT_SLOT_W_MM}mm NPTH)"
    )
    return f"""\t(footprint "Eurorack_Panel:MountingSlot_M3_3.2x5.5mm_NPTH"
\t\t(layer "F.Cu")
\t\t(uuid "{det_uuid(ns, f"fp_{ref}")}")
\t\t(at {x:g} {y:g})
\t\t(descr "{descr}")
\t\t(tags "eurorack m3 mounting slot npth")
\t\t(attr board_only exclude_from_pos_files exclude_from_bom)
\t\t(property "Reference" "{ref}"
\t\t\t(at 0 0 0)
\t\t\t(layer "F.Fab")
\t\t\t(hide yes)
\t\t\t(uuid "{det_uuid(ns, f"fp_{ref}_ref")}")
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1 1)
\t\t\t\t\t(thickness 0.15)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Value" "M3_SLOT"
\t\t\t(at 0 0 0)
\t\t\t(layer "F.Fab")
\t\t\t(hide yes)
\t\t\t(uuid "{det_uuid(ns, f"fp_{ref}_val")}")
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1 1)
\t\t\t\t\t(thickness 0.15)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(fp_rect
\t\t\t(start {-hw:g} {-hh:g})
\t\t\t(end {hw:g} {hh:g})
\t\t\t(stroke
\t\t\t\t(width 0.05)
\t\t\t\t(type solid)
\t\t\t)
\t\t\t(fill no)
\t\t\t(layer "F.CrtYd")
\t\t\t(uuid "{det_uuid(ns, f"fp_{ref}_crtyd")}")
\t\t)
\t\t(pad "" np_thru_hole oval
\t\t\t(at 0 0)
\t\t\t(size {MOUNT_SLOT_W_MM:g} {MOUNT_SLOT_H_MM:g})
\t\t\t(drill oval {MOUNT_SLOT_W_MM:g} {MOUNT_SLOT_H_MM:g})
\t\t\t(layers "*.Cu" "*.Mask")
\t\t\t(uuid "{det_uuid(ns, f"fp_{ref}_pad")}")
\t\t)
\t)"""


def clean_label(raw_value: str) -> str:
    """Format a net/component value like `IN_1` or `OUT_1A` into `IN 1` or `OUT 1A`."""
    return raw_value.replace("_", " ").strip()


def build_panel_sexpr(
    bbox: dict[str, float],
    jacks: list[dict],
    hp: int,
    panel_w: float,
    title: str,
    subtitle: str,
    ns: str = "BufferedMult_Panel",
    cascade_arrow: bool | None = None,
) -> str:
    """Build the complete KiCad 10 `.kicad_pcb` S-expression for the front panel."""
    pcb_w = bbox["max_x"] - bbox["min_x"]
    pcb_h = bbox["max_y"] - bbox["min_y"]
    overhang_x = (panel_w - pcb_w) / 2.0
    overhang_y = (PANEL_HEIGHT_3U_MM - pcb_h) / 2.0

    panel_x0 = round(bbox["min_x"] - overhang_x, 4)
    panel_x1 = round(panel_x0 + panel_w, 4)
    panel_y0 = round(bbox["min_y"] - overhang_y, 4)
    panel_y1 = round(panel_y0 + PANEL_HEIGHT_3U_MM, 4)
    center_x = round((panel_x0 + panel_x1) / 2.0, 4)

    # Mounting slots (centered for 1-2HP, 7.5mm from left edge for >=3HP, 2nd pair for >=10HP)
    left_slot_offset = round(panel_w / 2.0, 2) if hp <= 2 else MOUNT_X_LOCAL_MM
    mount_slots = [
        ("H1", round(panel_x0 + left_slot_offset, 4), panel_y0 + MOUNT_TOP_Y_LOCAL_MM),
        ("H2", round(panel_x0 + left_slot_offset, 4), panel_y0 + MOUNT_BOT_Y_LOCAL_MM),
    ]
    if hp >= 10:
        right_slot_x = round(panel_x0 + MOUNT_X_LOCAL_MM + (hp - 3) * 5.08, 2)
        mount_slots.extend(
            [
                ("H3", right_slot_x, panel_y0 + MOUNT_TOP_Y_LOCAL_MM),
                ("H4", right_slot_x, panel_y0 + MOUNT_BOT_Y_LOCAL_MM),
            ]
        )

    footprints_str = "\n".join(
        [
            *(
                format_mount_slot_footprint(ns, ref, mx, my)
                for ref, mx, my in mount_slots
            ),
            *(format_jack_footprint(ns, j, panel_x0, panel_y0) for j in jacks),
        ]
    )

    # Group jacks into horizontal rows (within 1.0 mm Y tolerance)
    rows: list[list[dict]] = []
    for j in jacks:
        if not rows or abs(j["bushing_y"] - rows[-1][0]["bushing_y"]) > 1.0:
            rows.append([j])
        else:
            rows[-1].append(j)

    # Generate silkscreen labels and input frames for each jack
    jack_graphics: list[str] = []
    row_label_ys: list[float] = []
    has_wide_intergroup_gap = any(
        (rows[i + 1][0]["bushing_y"] - rows[i][0]["bushing_y"]) > 20.0
        for i in range(len(rows) - 1)
    )
    for row_idx, row in enumerate(rows):
        row_y = row[0]["bushing_y"]
        if has_wide_intergroup_gap:
            # Alternate labels above for odd rows (0, 2) and below for even rows (1, 3)
            lbl_y = (
                round(row_y - 7.28, 2) if row_idx % 2 == 0 else round(row_y + 7.32, 2)
            )
        else:
            # Uniform row grid (e.g. 6 rows @ 14.4mm): place labels at the inter-row midpoint below each row
            lbl_y = round(row_y + 7.2, 2)
        row_label_ys.append(lbl_y)

        for j in row:
            jx = j["bushing_x"]
            lbl = clean_label(j["value"])
            ref_id = j["ref"].lower()
            is_input = lbl.upper().startswith("IN")

            if is_input:
                jack_graphics.append(
                    f"""\t(gr_rect
\t\t(start {jx - 3.6:g} {lbl_y - 1.45:g})
\t\t(end {jx + 3.6:g} {lbl_y + 1.45:g})
\t\t(stroke
\t\t\t(width 0.25)
\t\t\t(type solid)
\t\t)
\t\t(fill no)
\t\t(layer "F.SilkS")
\t\t(uuid "{det_uuid(ns, f"badge_{ref_id}")}")
\t)
\t(gr_text "{lbl}"
\t\t(at {jx:g} {lbl_y:g} 0)
\t\t(layer "F.SilkS")
\t\t(uuid "{det_uuid(ns, f"lbl_{ref_id}")}")
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1.2 1.2)
\t\t\t\t(thickness 0.22)
\t\t\t\t(bold yes)
\t\t\t)
\t\t)
\t)"""
                )
            else:
                jack_graphics.append(
                    f"""\t(gr_text "{lbl}"
\t\t(at {jx:g} {lbl_y:g} 0)
\t\t(layer "F.SilkS")
\t\t(uuid "{det_uuid(ns, f"lbl_{ref_id}")}")
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1.2 1.2)
\t\t\t\t(thickness 0.2)
\t\t\t)
\t\t)
\t)"""
                )

    # If there is a central gap between Row 2 and Row 3, draw the cascade arrow when enabled
    draw_cascade = (
        cascade_arrow if cascade_arrow is not None else ("MULT" in title.upper())
    )
    cascade_graphics = ""
    if draw_cascade and len(rows) >= 3 and (row_label_ys[2] - row_label_ys[1]) > 18.0:
        col1_x = rows[0][0]["bushing_x"]
        col2_x = rows[0][-1]["bushing_x"]
        r2_lbl_y = row_label_ys[1]
        r3_lbl_y = row_label_ys[2]
        mid_norm_y = round((r2_lbl_y + r3_lbl_y) / 2.0, 2)
        cascade_graphics = f"""
\t(gr_line
\t\t(start {col1_x:g} {r2_lbl_y + 3.0:g})
\t\t(end {col1_x:g} {r3_lbl_y - 3.2:g})
\t\t(stroke
\t\t\t(width 0.25)
\t\t\t(type dash)
\t\t)
\t\t(layer "F.SilkS")
\t\t(uuid "{det_uuid(ns, "norm_cascade_line")}")
\t)
\t(gr_line
\t\t(start {col1_x - 1.1:g} {r3_lbl_y - 4.5:g})
\t\t(end {col1_x:g} {r3_lbl_y - 3.0:g})
\t\t(stroke
\t\t\t(width 0.25)
\t\t\t(type solid)
\t\t)
\t\t(layer "F.SilkS")
\t\t(uuid "{det_uuid(ns, "norm_arrow_l")}")
\t)
\t(gr_line
\t\t(start {col1_x + 1.1:g} {r3_lbl_y - 4.5:g})
\t\t(end {col1_x:g} {r3_lbl_y - 3.0:g})
\t\t(stroke
\t\t\t(width 0.25)
\t\t\t(type solid)
\t\t)
\t\t(layer "F.SilkS")
\t\t(uuid "{det_uuid(ns, "norm_arrow_r")}")
\t)
\t(gr_text "NORM"
\t\t(at {col2_x - 1.5:g} {mid_norm_y - 1.2:g} 0)
\t\t(layer "F.SilkS")
\t\t(uuid "{det_uuid(ns, "lbl_norm_1")}")
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1.1 1.1)
\t\t\t\t(thickness 0.18)
\t\t\t)
\t\t)
\t)
\t(gr_text "1 -> 2"
\t\t(at {col2_x - 1.5:g} {mid_norm_y + 1.2:g} 0)
\t\t(layer "F.SilkS")
\t\t(uuid "{det_uuid(ns, "lbl_norm_2")}")
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1.1 1.1)
\t\t\t\t(thickness 0.18)
\t\t\t)
\t\t)
\t)"""

    jack_graphics_str = "\n".join(jack_graphics)
    rear_title_y = (
        round(panel_y1 - 26.0, 2)
        if not has_wide_intergroup_gap
        else round(panel_y0 + 16.0, 2)
    )
    rear_jlc_y = (
        round(panel_y1 - 22.0, 2)
        if not has_wide_intergroup_gap
        else round((panel_y0 + panel_y1) / 2.0 - 1.25, 2)
    )

    return f"""(kicad_pcb
\t(version 20260206)
\t(generator "pcbnew")
\t(generator_version "10.0")
\t(general
\t\t(thickness 1.6)
\t\t(legacy_teardrops no)
\t)
\t(paper "A4")
\t(layers
\t\t(0 "F.Cu" signal)
\t\t(2 "B.Cu" signal)
\t\t(9 "F.Adhes" user "F.Adhesive")
\t\t(11 "B.Adhes" user "B.Adhesive")
\t\t(13 "F.Paste" user)
\t\t(15 "B.Paste" user)
\t\t(5 "F.SilkS" user "F.Silkscreen")
\t\t(7 "B.SilkS" user "B.Silkscreen")
\t\t(1 "F.Mask" user)
\t\t(3 "B.Mask" user)
\t\t(17 "Dwgs.User" user "User.Drawings")
\t\t(19 "Cmts.User" user "User.Comments")
\t\t(21 "Eco1.User" user "User.Eco1")
\t\t(23 "Eco2.User" user "User.Eco2")
\t\t(25 "Edge.Cuts" user)
\t\t(27 "Margin" user)
\t\t(31 "F.CrtYd" user "F.Courtyard")
\t\t(29 "B.CrtYd" user "B.Courtyard")
\t\t(35 "F.Fab" user)
\t\t(33 "B.Fab" user)
\t\t(39 "User.1" user)
\t\t(41 "User.2" user)
\t\t(43 "User.3" user)
\t\t(45 "User.4" user)
\t)
\t(setup
\t\t(pad_to_mask_clearance 0)
\t\t(allow_soldermask_bridges_in_footprints no)
\t\t(grid_origin {panel_x0:g} {panel_y0:g})
\t\t(aux_axis_origin {panel_x0:g} {panel_y0:g})
\t\t(tenting
\t\t\t(front yes)
\t\t\t(back yes)
\t\t)
\t\t(covering
\t\t\t(front yes)
\t\t\t(back yes)
\t\t)
\t\t(plugging
\t\t\t(front yes)
\t\t\t(back yes)
\t\t)
\t\t(capping no)
\t\t(filling no)
\t\t(pcbplotparams
\t\t\t(layerselection 0x00000000_00000000_55555555_5755f5ff)
\t\t\t(plot_on_all_layers_selection 0x00000000_00000000_00000000_00000000)
\t\t\t(disableapertmacros no)
\t\t\t(usegerberextensions no)
\t\t\t(usegerberattributes yes)
\t\t\t(usegerberadvancedattributes yes)
\t\t\t(creategerberjobfile yes)
\t\t\t(dashed_line_dash_ratio 12)
\t\t\t(dashed_line_gap_ratio 3)
\t\t\t(svgprecision 4)
\t\t\t(plotframeref no)
\t\t\t(mode 1)
\t\t\t(useauxorigin no)
\t\t\t(pdf_front_fp_property_popups yes)
\t\t\t(pdf_back_fp_property_popups yes)
\t\t\t(pdf_metadata yes)
\t\t\t(pdf_single_document no)
\t\t\t(dxfpolygonmode yes)
\t\t\t(dxfimperialunits yes)
\t\t\t(dxfusepcbnewfont yes)
\t\t\t(psnegative no)
\t\t\t(psa4output no)
\t\t\t(plot_black_and_white yes)
\t\t\t(sketchpadsonfab no)
\t\t\t(plotpadnumbers no)
\t\t\t(hidednponfab no)
\t\t\t(sketchdnponfab yes)
\t\t\t(crossoutdnponfab yes)
\t\t\t(subtractmaskfromsilk no)
\t\t\t(outputformat 1)
\t\t\t(mirror no)
\t\t\t(drillshape 1)
\t\t\t(scaleselection 1)
\t\t\t(outputdirectory "production/panel/")
\t\t)
\t)
{footprints_str}
\t(gr_rect
\t\t(start {panel_x0:g} {panel_y0:g})
\t\t(end {panel_x1:g} {panel_y1:g})
\t\t(stroke
\t\t\t(width 0.05)
\t\t\t(type solid)
\t\t)
\t\t(fill no)
\t\t(locked yes)
\t\t(layer "Edge.Cuts")
\t\t(uuid "{det_uuid(ns, "edge_cuts_rect")}")
\t)
\t(gr_rect
\t\t(start {bbox["min_x"]:g} {bbox["min_y"]:g})
\t\t(end {bbox["max_x"]:g} {bbox["max_y"]:g})
\t\t(stroke
\t\t\t(width 0.12)
\t\t\t(type dash)
\t\t)
\t\t(fill no)
\t\t(layer "B.Fab")
\t\t(uuid "{det_uuid(ns, "main_pcb_outline_ref")}")
\t)
\t(gr_line
\t\t(start {panel_x0 + 2.0:g} {panel_y0 + 13.0:g})
\t\t(end {panel_x1 - 2.0:g} {panel_y0 + 13.0:g})
\t\t(stroke
\t\t\t(width 0.25)
\t\t\t(type solid)
\t\t)
\t\t(layer "F.SilkS")
\t\t(uuid "{det_uuid(ns, "header_line_top")}")
\t)
\t(gr_text "{title}"
\t\t(at {center_x:g} {panel_y0 + 10.25:g} 0)
\t\t(layer "F.SilkS")
\t\t(uuid "{det_uuid(ns, "title_buf_mult")}")
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1.8 1.8)
\t\t\t\t(thickness 0.3)
\t\t\t\t(bold yes)
\t\t\t)
\t\t)
\t)
{jack_graphics_str}{cascade_graphics}
\t(gr_line
\t\t(start {panel_x0 + 2.0:g} {panel_y1 - 19.5:g})
\t\t(end {panel_x1 - 2.0:g} {panel_y1 - 19.5:g})
\t\t(stroke
\t\t\t(width 0.25)
\t\t\t(type solid)
\t\t)
\t\t(layer "F.SilkS")
\t\t(uuid "{det_uuid(ns, "footer_line_bot")}")
\t)
\t(gr_text "{subtitle}"
\t\t(at {center_x:g} {panel_y1 - 16.0:g} 0)
\t\t(layer "F.SilkS")
\t\t(uuid "{det_uuid(ns, "footer_subtitle")}")
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1.3 1.3)
\t\t\t\t(thickness 0.22)
\t\t\t\t(bold yes)
\t\t\t)
\t\t)
\t)
\t(gr_text "JLCJLCJLCJLC"
\t\t(at {center_x:g} {rear_jlc_y:g} 0)
\t\t(layer "B.SilkS")
\t\t(uuid "{det_uuid(ns, "jlc_order_placeholder")}")
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1.0 1.0)
\t\t\t\t(thickness 0.15)
\t\t\t)
\t\t\t(justify mirror)
\t\t)
\t)
\t(gr_text "{title} {hp}HP"
\t\t(at {center_x:g} {rear_title_y:g} 0)
\t\t(layer "B.SilkS")
\t\t(uuid "{det_uuid(ns, "rear_panel_title")}")
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1.0 1.0)
\t\t\t\t(thickness 0.15)
\t\t\t)
\t\t\t(justify mirror)
\t\t)
\t)
\t(zone
\t\t(net "GND")
\t\t(layer "F.Cu")
\t\t(uuid "{det_uuid(ns, "zone_f_cu")}")
\t\t(hatch edge 0.5)
\t\t(priority 1)
\t\t(connect_pads yes
\t\t\t(clearance 0.4)
\t\t)
\t\t(min_thickness 0.25)
\t\t(fill yes
\t\t\t(thermal_gap 0.5)
\t\t\t(thermal_bridge_width 0.5)
\t\t\t(island_removal_mode 0)
\t\t)
\t\t(polygon
\t\t\t(pts
\t\t\t\t(xy {panel_x0:g} {panel_y0:g})
\t\t\t\t(xy {panel_x1:g} {panel_y0:g})
\t\t\t\t(xy {panel_x1:g} {panel_y1:g})
\t\t\t\t(xy {panel_x0:g} {panel_y1:g})
\t\t\t)
\t\t)
\t)
\t(zone
\t\t(net "GND")
\t\t(layer "B.Cu")
\t\t(uuid "{det_uuid(ns, "zone_b_cu")}")
\t\t(hatch edge 0.5)
\t\t(priority 1)
\t\t(connect_pads yes
\t\t\t(clearance 0.4)
\t\t)
\t\t(min_thickness 0.25)
\t\t(fill yes
\t\t\t(thermal_gap 0.5)
\t\t\t(thermal_bridge_width 0.5)
\t\t\t(island_removal_mode 0)
\t\t)
\t\t(polygon
\t\t\t(pts
\t\t\t\t(xy {panel_x0:g} {panel_y0:g})
\t\t\t\t(xy {panel_x1:g} {panel_y0:g})
\t\t\t\t(xy {panel_x1:g} {panel_y1:g})
\t\t\t\t(xy {panel_x0:g} {panel_y1:g})
\t\t\t)
\t\t)
\t)
\t(embedded_fonts no)
)
"""


def refill_zones_with_kicad(pcb_path: pathlib.Path) -> None:
    """Refill all copper zones in-place using KiCad 10's Python `pcbnew` API."""
    if not KICAD_PYTHON.exists():
        print(
            "Warning: KiCad Python runtime not found; skipping zone fill.",
            file=sys.stderr,
        )
        return

    fill_code = (
        "import pcbnew; "
        f"b = pcbnew.LoadBoard({str(pcb_path)!r}); "
        "pcbnew.ZONE_FILLER(b).Fill(b.Zones()); "
        f"pcbnew.SaveBoard({str(pcb_path)!r}, b)"
    )
    subprocess.run(
        [str(KICAD_PYTHON), "-c", fill_code],
        check=True,
        stderr=subprocess.DEVNULL,
    )


def run_drc_check(pcb_path: pathlib.Path) -> tuple[int, int]:
    """Run `kicad-cli pcb drc` and return (violation_count, unconnected_count)."""
    drc_json = pathlib.Path("/tmp") / f"{pcb_path.stem}_drc.json"
    subprocess.run(
        [
            str(KICAD_CLI),
            "pcb",
            "drc",
            "--refill-zones",
            "--format",
            "json",
            "--output",
            str(drc_json),
            str(pcb_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    data = json.loads(drc_json.read_text(encoding="utf-8"))
    non_lib = [
        v for v in data.get("violations", []) if v.get("type") != "lib_footprint_issues"
    ]
    unconnected = data.get("unconnected_items", [])
    for v in non_lib:
        print(f"  DRC Violation: [{v.get('severity')}] {v.get('description')}")
    for u in unconnected:
        print(f"  DRC Unconnected: {u.get('description')}")
    return len(non_lib), len(unconnected)


def export_gerbers_and_drills(
    pcb_path: pathlib.Path,
    gerber_dir: pathlib.Path,
    zip_path: pathlib.Path | None = None,
) -> None:
    """Export Gerbers and Excellon drill files via `kicad-cli` and optionally zip."""
    gerber_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(KICAD_CLI),
            "pcb",
            "export",
            "gerbers",
            "--layers",
            "F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts",
            "--output",
            f"{gerber_dir}/",
            str(pcb_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            str(KICAD_CLI),
            "pcb",
            "export",
            "drill",
            "--format",
            "excellon",
            "--excellon-separate-th",
            "--generate-map",
            "--map-format",
            "gerberx2",
            "--output",
            f"{gerber_dir}/",
            str(pcb_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if zip_path is not None:
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in sorted(gerber_dir.iterdir()):
                if item.is_file():
                    zf.write(item, arcname=item.name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect a KiCad Eurorack PCB and generate a mated 3U front panel."
    )
    parser.add_argument(
        "--main-pcb",
        type=pathlib.Path,
        default=pathlib.Path("BufferedMult.kicad_pcb"),
        help="Path to the main circuit `.kicad_pcb` file.",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path("BufferedMult_Panel.kicad_pcb"),
        help="Output path for the generated front panel `.kicad_pcb` file.",
    )
    parser.add_argument(
        "--hp",
        type=int,
        default=None,
        help="Module width in HP (auto-detected from main PCB width if omitted).",
    )
    parser.add_argument(
        "--title",
        type=str,
        default="BUF MULT",
        help="Top silkscreen module title.",
    )
    parser.add_argument(
        "--subtitle",
        type=str,
        default="1:3 / 1:6",
        help="Bottom silkscreen module subtitle.",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Print mechanical alignment and coordinate table without writing files.",
    )
    parser.add_argument(
        "--drc",
        action="store_true",
        help="Run `kicad-cli pcb drc` after generating the panel.",
    )
    parser.add_argument(
        "--gerber-dir",
        type=pathlib.Path,
        default=None,
        help="Directory to export Gerber and Excellon drill files into.",
    )
    parser.add_argument(
        "--zip",
        type=pathlib.Path,
        default=None,
        help="Path to write zipped Gerber/drill archive (requires --gerber-dir).",
    )
    parser.add_argument(
        "--cascade-arrow",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Draw normalled cascade arrow between row groups (default: auto when title contains MULT).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bbox, jacks = parse_main_pcb(args.main_pcb)
    pcb_w = bbox["max_x"] - bbox["min_x"]
    hp, panel_w = infer_hp_and_width(pcb_w, args.hp)

    if args.inspect:
        print_inspection_report(args.main_pcb, bbox, jacks, hp, panel_w)
        return

    sexpr = build_panel_sexpr(
        bbox=bbox,
        jacks=jacks,
        hp=hp,
        panel_w=panel_w,
        title=args.title,
        subtitle=args.subtitle,
        ns=args.output.stem,
        cascade_arrow=args.cascade_arrow,
    )
    args.output.write_text(sexpr, encoding="utf-8")
    refill_zones_with_kicad(args.output)
    print(
        f"Generated {args.output} ({hp}HP / {panel_w:.1f}x{PANEL_HEIGHT_3U_MM:.1f}mm, "
        f"{len(jacks)} jack cutouts)."
    )

    if args.drc:
        v_cnt, u_cnt = run_drc_check(args.output)
        print(f"DRC Summary: {v_cnt} violations, {u_cnt} unconnected items.")
        if v_cnt > 0 or u_cnt > 0:
            sys.exit(1)

    if args.gerber_dir is not None:
        export_gerbers_and_drills(args.output, args.gerber_dir, args.zip)
        print(f"Exported Gerbers & Drills to {args.gerber_dir}")
        if args.zip is not None:
            print(f"Packaged fabrication archive at {args.zip}")


if __name__ == "__main__":
    main()
