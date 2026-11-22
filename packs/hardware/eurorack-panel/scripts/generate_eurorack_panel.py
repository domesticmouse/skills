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

  # 2. Generate a standard front panel PCB, run DRC, and export Gerbers:
  python3 .agents/skills/eurorack-panel/scripts/generate_eurorack_panel.py \
      --main-pcb BufferedMult.kicad_pcb \
      --output BufferedMult_Panel.kicad_pcb \
      --title "BUF MULT" \
      --subtitle "1:3 / 1:6" \
      --gerber-dir production/panel \
      --zip production/BufferedMult_Panel.zip \
      --drc

  # 3. Generate a blank-front panel + Markdown/JSON SVG specification:
  python3 .agents/skills/eurorack-panel/scripts/generate_eurorack_panel.py \
      --main-pcb envelope_follower.kicad_pcb \
      --output envelope_follower_panel.kicad_pcb \
      --blank-front \
      --title "ENVELOPE FOLLOWER + SKEW LIMITER" \
      --version "Rev 1.0" \
      --url "github.com/domesticmouse/EnvelopeFollowerWithSkewLimiter" \
      --spec-md panel_svg_spec.md \
      --drc
"""

from __future__ import annotations

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
        "kind": "switch_submini",
        "pattern": re.compile(
            r"Dailywell_2M|2MS1|2M1|Sub[-_]?Mini|10-48", re.IGNORECASE
        ),
        "default_offset": (0.0, 0.0),
        "drill_mm": 5.2,
        "pad_mm": 7.2,
        "keepout_mm": 8.2,
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


def _sexpr_escape(value: str) -> str:
    """Escape backslashes and double quotes for KiCad S-expression strings."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _sexpr_unescape(value: str) -> str:
    """Unescape KiCad S-expression string escapes (`\\"` and `\\\\`)."""
    return re.sub(r'\\(["\\])', r"\1", value)


def _extract_sexpr_block(text: str, start_idx: int) -> str:
    """Return the balanced S-expression substring starting at `(` index `start_idx`."""
    depth = 0
    in_quote = False
    escape = False
    end_idx = len(text)
    for idx in range(start_idx, len(text)):
        ch = text[idx]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_quote:
            escape = True
            continue
        if ch == '"':
            in_quote = not in_quote
            continue
        if in_quote:
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end_idx = idx + 1
                break
    return text[start_idx:end_idx]


def _extract_title_block(text: str) -> dict[str, str]:
    """Extract title/rev/date fields from a KiCad PCB `(title_block ...)` section."""
    m = re.search(r"\(title_block\b", text)
    if not m:
        return {}
    block = _extract_sexpr_block(text, m.start())
    return {
        key: _sexpr_unescape(val).strip()
        for key, val in re.findall(r'\((title|rev|date)\s+"((?:[^"\\]|\\.)*)"\)', block)
    }


def compute_panel_geometry(
    bbox: dict[str, float], hp: int, panel_w: float
) -> dict[str, float]:
    """Compute global/local panel bounds and main-PCB overhang geometry."""
    pcb_w = round(bbox["max_x"] - bbox["min_x"], 4)
    pcb_h = round(bbox["max_y"] - bbox["min_y"], 4)
    overhang_x = round((panel_w - pcb_w) / 2.0, 4)
    overhang_y = round((PANEL_HEIGHT_3U_MM - pcb_h) / 2.0, 4)
    panel_x0 = round(bbox["min_x"] - overhang_x, 4)
    panel_x1 = round(panel_x0 + panel_w, 4)
    panel_y0 = round(bbox["min_y"] - overhang_y, 4)
    panel_y1 = round(panel_y0 + PANEL_HEIGHT_3U_MM, 4)
    center_x = round((panel_x0 + panel_x1) / 2.0, 4)
    return {
        "hp": float(hp),
        "panel_w": round(panel_w, 4),
        "panel_h": PANEL_HEIGHT_3U_MM,
        "pcb_w": pcb_w,
        "pcb_h": pcb_h,
        "overhang_x": overhang_x,
        "overhang_y": overhang_y,
        "panel_x0": panel_x0,
        "panel_x1": panel_x1,
        "panel_y0": panel_y0,
        "panel_y1": panel_y1,
        "center_x": center_x,
    }


def compute_mount_slots(
    hp: int, panel_w: float, panel_x0: float, panel_y0: float
) -> list[dict]:
    """Return Doepfer M3 oval mounting slots in panel-local and global coordinates."""
    left_slot_offset = round(panel_w / 2.0, 2) if hp <= 2 else MOUNT_X_LOCAL_MM
    raw_slots = [
        ("H1", left_slot_offset, MOUNT_TOP_Y_LOCAL_MM),
        ("H2", left_slot_offset, MOUNT_BOT_Y_LOCAL_MM),
    ]
    if hp >= 10:
        right_slot_offset = round(MOUNT_X_LOCAL_MM + (hp - 3) * 5.08, 2)
        raw_slots.extend(
            [
                ("H3", right_slot_offset, MOUNT_TOP_Y_LOCAL_MM),
                ("H4", right_slot_offset, MOUNT_BOT_Y_LOCAL_MM),
            ]
        )
    return [
        {
            "ref": ref,
            "local_x": round(lx, 4),
            "local_y": round(ly, 4),
            "global_x": round(panel_x0 + lx, 4),
            "global_y": round(panel_y0 + ly, 4),
            "width_mm": MOUNT_SLOT_W_MM,
            "height_mm": MOUNT_SLOT_H_MM,
        }
        for ref, lx, ly in raw_slots
    ]


def parse_main_pcb(
    pcb_path: pathlib.Path,
) -> tuple[dict[str, float], list[dict], dict[str, str]]:
    """Extract outline, panel-mounted parts, and title-block metadata from `.kicad_pcb`."""
    text = pcb_path.read_text(encoding="utf-8")
    pcb_meta = _extract_title_block(text)

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

    jacks: list[dict] = []
    for fp_start in re.finditer(r'(?m)^[ \t]+\(footprint\s+"((?:[^"\\]|\\.)+)"', text):
        fp_lib = _sexpr_unescape(fp_start.group(1))
        spec = next(
            (s for s in PANEL_COMPONENT_SPECS if s["pattern"].search(fp_lib)),
            None,
        )
        if spec is None:
            continue

        chunk = _extract_sexpr_block(text, text.find("(", fp_start.start()))
        at_m = re.search(r"\(at\s+([\d.-]+)\s+([\d.-]+)(?:\s+([\d.-]+))?\)", chunk)
        ref_m = re.search(r'\(property\s+"Reference"\s+"((?:[^"\\]|\\.)+)"', chunk)
        val_m = re.search(r'\(property\s+"Value"\s+"((?:[^"\\]|\\.)+)"', chunk)
        if not (at_m and ref_m and val_m):
            continue

        fp_x = float(at_m.group(1))
        fp_y = float(at_m.group(2))
        rot = float(at_m.group(3)) if at_m.group(3) else 0.0
        ref = _sexpr_unescape(ref_m.group(1))
        val = _sexpr_unescape(val_m.group(1))

        # Auto-detect bushing/shaft circle from footprint body, fallback to spec default_offset
        circle_m = re.search(r"\(fp_circle\s+\(center\s+([\d.-]+)\s+([\d.-]+)\)", chunk)
        def_cx, def_cy = spec["default_offset"]
        cx = float(circle_m.group(1)) if circle_m else def_cx
        cy = float(circle_m.group(2)) if circle_m else def_cy
        dx, dy = rotate_offset(cx, cy, rot)

        def _prop(name: str, body: str = chunk) -> str:
            pm = re.search(
                rf'\(property\s+"{re.escape(name)}"\s+"((?:[^"\\]|\\.)*)"', body
            )
            return _sexpr_unescape(pm.group(1)).strip() if pm else ""

        silk = _prop("Silkscreen") or None
        jacks.append(
            {
                "ref": ref,
                "value": val,
                "label": derive_panel_label(ref, val, silk),
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
                "mpn": _prop("MPN"),
                "manufacturer": _prop("Manufacturer"),
                "description": _prop("Description"),
                "notes": _prop("Notes"),
            }
        )

    jacks.sort(key=lambda j: (j["bushing_y"], j["bushing_x"]))
    if not jacks:
        raise ValueError(
            f"No panel-mounted component footprints (jacks, pots, switches, LEDs) found in {pcb_path}"
        )

    return bbox, jacks, pcb_meta


def print_inspection_report(
    pcb_path: pathlib.Path,
    bbox: dict[str, float],
    jacks: list[dict],
    hp: int,
    panel_w: float,
) -> None:
    """Print a mechanical alignment & coordinate report for the main PCB and panel."""
    geom = compute_panel_geometry(bbox, hp, panel_w)
    pcb_w = geom["pcb_w"]
    pcb_h = geom["pcb_h"]
    overhang_y = geom["overhang_y"]
    panel_x0 = geom["panel_x0"]
    panel_y0 = geom["panel_y0"]

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
        f"{'Ref':<5} {'Value':<10} {'Label':<10} {'FP Origin (X, Y)':<20} "
        f"{'Bushing Global (X, Y)':<23} {'Panel-Local (X, Y)':<20} {'Drill'}"
    )
    print("-" * 99)
    for j in jacks:
        lx = round(j["bushing_x"] - panel_x0, 2)
        ly = round(j["bushing_y"] - panel_y0, 2)
        drill_mm = j.get("drill_mm", JACK_DRILL_MM)
        lbl = clean_label(j.get("label", j["value"]))
        print(
            f"{j['ref']:<5} {j['value']:<10} {lbl:<10} "
            f"({j['fp_x']:6.2f}, {j['fp_y']:6.2f})     "
            f"({j['bushing_x']:6.2f}, {j['bushing_y']:6.2f})        "
            f"({lx:6.2f}, {ly:6.2f})     {drill_mm:.2f} mm"
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

    kind_meta = {
        "jack": (
            f"Eurorack_Panel:JackHole_3.5mm_Thonkiconn_{drill_mm:g}mm",
            "eurorack panel hole thonkiconn 3.5mm",
        ),
        "pot": (
            f"Eurorack_Panel:PotHole_9mm_Vertical_{drill_mm:g}mm",
            "eurorack panel hole pot 9mm vertical",
        ),
        "switch_submini": (
            f"Eurorack_Panel:SwitchHole_SubMini_{drill_mm:g}mm",
            "eurorack panel hole switch submini toggle",
        ),
        "switch": (
            f"Eurorack_Panel:SwitchHole_Mini_{drill_mm:g}mm",
            "eurorack panel hole switch toggle",
        ),
        "led_3mm": (
            f"Eurorack_Panel:LEDHole_3mm_{drill_mm:g}mm_NPTH",
            "eurorack panel hole led 3mm npth",
        ),
        "led_5mm": (
            f"Eurorack_Panel:LEDHole_5mm_{drill_mm:g}mm_NPTH",
            "eurorack panel hole led 5mm npth",
        ),
    }
    fp_name, fp_tags = kind_meta.get(
        jack.get("kind", "jack"),
        (
            f"Eurorack_Panel:JackHole_3.5mm_Thonkiconn_{drill_mm:g}mm",
            "eurorack panel hole thonkiconn 3.5mm",
        ),
    )

    return f"""\t(footprint "{fp_name}"
\t\t(layer "F.Cu")
\t\t(uuid "{det_uuid(ns, f"fp_{ref}")}")
\t\t(at {bx:g} {by:g})
\t\t(descr "{descr}")
\t\t(tags "{fp_tags}")
\t\t(attr board_only exclude_from_pos_files exclude_from_bom)
\t\t(property "Reference" "{_sexpr_escape(ref)}"
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
\t\t(property "Value" "{_sexpr_escape(val)}"
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


def derive_panel_label(ref: str, val: str, silk: str | None) -> str:
    """Derive a concise front-panel label from Silkscreen property or Value."""
    if silk:
        s = silk.strip()
        if s.upper() == f"{ref.strip()}{val.strip()}".upper():
            return clean_label(val)
        tokens = s.split()
        if tokens and tokens[0].upper() == ref.upper():
            tokens = tokens[1:]
        val_tokens = val.strip().split()
        if (
            val_tokens
            and len(tokens) > len(val_tokens)
            and [t.upper() for t in tokens[-len(val_tokens) :]]
            == [t.upper() for t in val_tokens]
        ):
            tokens = tokens[: -len(val_tokens)]
        if tokens:
            return clean_label(" ".join(tokens))
    return clean_label(val)


def _rect_clearance(
    rect: tuple[float, float, float, float],
    circles: list[tuple[float, float, float]],
    obs_rects: list[tuple[float, float, float, float]],
    panel_w: float,
    panel_h: float,
    edge_margin: float = 1.0,
) -> float:
    """Return signed minimum clearance (mm) from rect to edges and obstacles."""
    x0, y0, x1, y1 = rect
    best = min(
        x0 - edge_margin,
        (panel_w - edge_margin) - x1,
        y0 - edge_margin,
        (panel_h - edge_margin) - y1,
    )
    for cx, cy, r in circles:
        nx = min(max(cx, x0), x1)
        ny = min(max(cy, y0), y1)
        d = math.hypot(cx - nx, cy - ny) - r
        best = min(best, d)
    for ox0, oy0, ox1, oy1 in obs_rects:
        dx = max(ox0 - x1, x0 - ox1, 0.0)
        dy = max(oy0 - y1, y0 - oy1, 0.0)
        if dx > 0.0 or dy > 0.0:
            d = math.hypot(dx, dy)
        else:
            d = -min(x1 - ox0, ox1 - x0, y1 - oy0, oy1 - y0)
        best = min(best, d)
    return round(best, 4)


def _wrap_text_lines(
    text: str,
    max_chars: int,
    max_lines: int = 3,
    delims: tuple[str, ...] = (" ", "/", "+"),
) -> list[str]:
    """Wrap text into balanced lines up to `max_chars` without breaking words needlessly."""
    clean = " ".join(text.split())
    if not clean:
        return []
    if len(clean) <= max_chars or max_lines <= 1:
        return [clean]

    # Try balanced 2-line split first across preferred delimiters
    mid = len(clean) / 2.0
    best_pair: tuple[float, list[str]] | None = None
    for delim in delims:
        for idx, ch in enumerate(clean):
            if ch != delim or idx == 0 or idx >= len(clean) - 1:
                continue
            if delim == " ":
                left = clean[:idx].strip()
                right = clean[idx + 1 :].strip()
            elif delim == "/":
                left = clean[: idx + 1].strip()
                right = clean[idx + 1 :].strip()
            else:
                left = clean[:idx].strip()
                right = clean[idx:].strip()
            if left and right and len(left) <= max_chars and len(right) <= max_chars:
                score = abs(len(left) - len(right)) + 0.01 * abs(idx - mid)
                if best_pair is None or score < best_pair[0]:
                    best_pair = (score, [left, right])
        if best_pair is not None:
            return best_pair[1]

    # Greedy wrap fallback up to max_lines
    lines: list[str] = []
    rem = clean
    while rem and len(lines) < max_lines - 1:
        if len(rem) <= max_chars:
            break
        split_at = -1
        for delim in delims:
            upper = max_chars if delim == "/" else max_chars + 1
            pos = rem.rfind(delim, 1, upper)
            if pos > 0:
                split_at = pos + (1 if delim == "/" else 0)
                break
        if split_at <= 0:
            split_at = max_chars
        head = rem[:split_at].strip()
        rem = rem[split_at:].strip()
        if head:
            lines.append(head)
    if rem:
        lines.append(rem)
    return lines


def _estimate_text_box(
    lines: list[str],
    font_size: float,
    thickness: float,
    rot_deg: float,
    line_pitch: float,
) -> tuple[float, float]:
    """Return conservative bounding (width_mm, height_mm) for KiCad stroke text."""
    max_len = max((len(line) for line in lines), default=1)
    w_unrot = max_len * font_size * 0.92 + thickness + 0.6
    h_unrot = max(0, len(lines) - 1) * line_pitch + font_size * 1.25 + thickness + 0.6
    if round(rot_deg) % 180 == 90:
        return round(h_unrot, 4), round(w_unrot, 4)
    return round(w_unrot, 4), round(h_unrot, 4)


def _scan_rect_positions(
    bw: float,
    bh: float,
    circles: list[tuple[float, float, float]],
    obs_rects: list[tuple[float, float, float, float]],
    panel_w: float,
    panel_h: float,
    xs: list[float],
    ys: list[float],
) -> tuple[float, float, float] | None:
    """Evaluate candidate center (x, y) coordinates and return (clearance, cx, cy)."""
    best: tuple[float, float, float] | None = None
    hw, hh = bw / 2.0, bh / 2.0
    for cx in xs:
        if cx - hw < 0.5 or cx + hw > panel_w - 0.5:
            continue
        for cy in ys:
            if cy - hh < 0.5 or cy + hh > panel_h - 0.5:
                continue
            clr = _rect_clearance(
                (cx - hw, cy - hh, cx + hw, cy + hh),
                circles,
                obs_rects,
                panel_w,
                panel_h,
            )
            if best is None or clr > best[0]:
                best = (clr, round(cx, 3), round(cy, 3))
    return best


def _line_positions(
    cx: float, cy: float, count: int, rot_deg: float, line_pitch: float
) -> list[tuple[float, float]]:
    """Compute per-line KiCad anchor coordinates for a centered multi-line block."""
    if round(rot_deg) % 180 == 90:
        return [
            (round(cx + (i - (count - 1) / 2.0) * line_pitch, 3), round(cy, 3))
            for i in range(count)
        ]
    return [
        (round(cx, 3), round(cy + (i - (count - 1) / 2.0) * line_pitch, 3))
        for i in range(count)
    ]


def _make_frange(start: float, stop: float, step: float) -> list[float]:
    """Generate rounded inclusive floating-point grid coordinates."""
    if stop < start:
        return []
    vals: list[float] = []
    cur = start
    while cur <= stop + 1e-6:
        vals.append(round(cur, 3))
        cur += step
    return vals


def _place_qr_placeholder(
    circles: list[tuple[float, float, float]],
    obs_rects: list[tuple[float, float, float, float]],
    panel_w: float,
    panel_h: float,
) -> tuple[float, float, float]:
    """Select collision-free panel-local center for the 5.0 x 5.0 mm JLCPCB QR blank."""
    qr_half = 2.575  # 5.0 mm square + 0.15 mm stroke half-width
    priority = [
        (round(panel_w - 7.5, 2), round(panel_h - 7.5, 2)),
        (round(panel_w / 2.0, 2), round(panel_h - 7.5, 2)),
        (round(panel_w / 2.0, 2), round(panel_h - 9.0, 2)),
        (round(panel_w - 7.5, 2), 9.5),
        (round(panel_w / 2.0, 2), 9.5),
        (round(panel_w / 2.0, 2), round(panel_h / 2.0, 2)),
    ]
    best: tuple[float, float, float] | None = None
    for cx, cy in priority:
        clr = _rect_clearance(
            (cx - qr_half, cy - qr_half, cx + qr_half, cy + qr_half),
            circles,
            obs_rects,
            panel_w,
            panel_h,
        )
        if clr >= 1.5:
            return clr, cx, cy
        if best is None or clr > best[0]:
            best = (clr, cx, cy)

    xs = _make_frange(1.0 + qr_half, panel_w - 1.0 - qr_half, 1.0)
    ys = _make_frange(1.0 + qr_half, panel_h - 1.0 - qr_half, 1.0)
    grid_best = _scan_rect_positions(
        qr_half * 2.0, qr_half * 2.0, circles, obs_rects, panel_w, panel_h, xs, ys
    )
    if grid_best is not None and (best is None or grid_best[0] > best[0]):
        best = grid_best
    assert best is not None
    return best


def _place_title_block_silk(
    circles: list[tuple[float, float, float]],
    obs_rects: list[tuple[float, float, float, float]],
    panel_w: float,
    panel_h: float,
    hp: int,
    title: str,
    version: str,
) -> dict:
    """Find collision-free placement on B.SilkS for module name + version/HP."""
    ver_clean = version.strip()
    meta_full = f"{hp}HP  {ver_clean}" if ver_clean else f"{hp}HP"
    configs = [
        (1.0, 0.9, 0.16, 1.85),
        (0.85, 0.8, 0.15, 1.65),
        (0.8, 0.8, 0.15, 1.5),
    ]
    best_choice: dict | None = None

    for title_sz, meta_sz, thick, pitch in configs:
        max_chars_h = max(4, int((panel_w - 2.6) / (title_sz * 0.92)))
        t_lines = _wrap_text_lines(title, max_chars_h, max_lines=3)
        if len(meta_full) <= max_chars_h or not ver_clean:
            m_lines = [meta_full]
        else:
            m_lines = [f"{hp}HP", ver_clean]
        lines = [(ln, title_sz, thick) for ln in t_lines] + [
            (ml, meta_sz, thick) for ml in m_lines
        ]
        bw, bh = _estimate_text_box(
            [ln for ln, _, _ in lines], max(title_sz, meta_sz), thick, 0.0, pitch
        )
        if bw <= panel_w - 2.0:
            center_x = [round(panel_w / 2.0, 3)]
            top_ys = _make_frange(
                max(1.2 + bh / 2.0, 5.0), min(24.0, panel_h - 1.2 - bh / 2.0), 0.5
            )
            bot_ys = _make_frange(
                max(1.2 + bh / 2.0, panel_h - 24.0), panel_h - 1.2 - bh / 2.0, 0.5
            )
            top_best = _scan_rect_positions(
                bw, bh, circles, obs_rects, panel_w, panel_h, center_x, top_ys
            )
            bot_best = _scan_rect_positions(
                bw, bh, circles, obs_rects, panel_w, panel_h, center_x, bot_ys
            )
            for cand in (top_best, bot_best):
                if cand is not None and cand[0] >= 1.0:
                    return {
                        "clearance": cand[0],
                        "cx": cand[1],
                        "cy": cand[2],
                        "bw": bw,
                        "bh": bh,
                        "rot": 0.0,
                        "line_pitch": pitch,
                        "lines": lines,
                    }
            full_xs = _make_frange(1.2 + bw / 2.0, panel_w - 1.2 - bw / 2.0, 1.0)
            full_ys = _make_frange(1.2 + bh / 2.0, panel_h - 1.2 - bh / 2.0, 1.0)
            grid_best = _scan_rect_positions(
                bw, bh, circles, obs_rects, panel_w, panel_h, full_xs, full_ys
            )
            for cand in (top_best, bot_best, grid_best):
                if cand is not None and (
                    best_choice is None or cand[0] > best_choice["clearance"]
                ):
                    best_choice = {
                        "clearance": cand[0],
                        "cx": cand[1],
                        "cy": cand[2],
                        "bw": bw,
                        "bh": bh,
                        "rot": 0.0,
                        "line_pitch": pitch,
                        "lines": lines,
                    }
            if best_choice is not None and best_choice["clearance"] >= 0.8:
                return best_choice

    # Narrow-panel fallback: try 90 deg vertical along clear side corridors
    for title_sz, meta_sz, thick, pitch in configs[1:]:
        t_lines = _wrap_text_lines(title, 34, max_lines=2)
        lines = [(ln, title_sz, thick) for ln in t_lines] + [
            (meta_full, meta_sz, thick)
        ]
        bw, bh = _estimate_text_box(
            [ln for ln, _, _ in lines], max(title_sz, meta_sz), thick, 90.0, pitch
        )
        xs = ([round(panel_w / 2.0, 3)] if bw <= panel_w - 1.0 else []) + _make_frange(
            1.2 + bw / 2.0, panel_w - 1.2 - bw / 2.0, 0.5
        )
        ys = _make_frange(1.2 + bh / 2.0, panel_h - 1.2 - bh / 2.0, 1.0)
        cand = _scan_rect_positions(
            bw, bh, circles, obs_rects, panel_w, panel_h, xs, ys
        )
        if cand is not None and (
            best_choice is None or cand[0] > best_choice["clearance"]
        ):
            best_choice = {
                "clearance": cand[0],
                "cx": cand[1],
                "cy": cand[2],
                "bw": bw,
                "bh": bh,
                "rot": 90.0,
                "line_pitch": pitch,
                "lines": lines,
            }
            if cand[0] >= 0.8:
                return best_choice

    if best_choice is None or best_choice["clearance"] < 0.0:
        compact_line = " ".join(part for part in (title.strip(), meta_full) if part)
        compact_lines = [(compact_line, 0.8, 0.15)]
        bw, bh = _estimate_text_box([compact_line], 0.8, 0.15, 90.0, 1.5)
        xs = [round(panel_w / 2.0, 3)] + _make_frange(
            1.0 + bw / 2.0, panel_w - 1.0 - bw / 2.0, 0.25
        )
        ys = _make_frange(1.2 + bh / 2.0, panel_h - 1.2 - bh / 2.0, 1.0)
        cand = _scan_rect_positions(
            bw, bh, circles, obs_rects, panel_w, panel_h, xs, ys
        )
        if cand is not None and (
            best_choice is None or cand[0] > best_choice["clearance"]
        ):
            best_choice = {
                "clearance": cand[0],
                "cx": cand[1],
                "cy": cand[2],
                "bw": bw,
                "bh": bh,
                "rot": 90.0,
                "line_pitch": 1.5,
                "lines": compact_lines,
            }
        elif best_choice is None:
            best_choice = {
                "clearance": -99.0,
                "cx": round(panel_w / 2.0, 3),
                "cy": round(panel_h / 2.0, 3),
                "bw": bw,
                "bh": bh,
                "rot": 90.0,
                "line_pitch": 1.5,
                "lines": compact_lines,
            }

    return best_choice


def _place_url_silk(
    circles: list[tuple[float, float, float]],
    obs_rects: list[tuple[float, float, float, float]],
    panel_w: float,
    panel_h: float,
    url: str,
) -> dict | None:
    """Find collision-free placement on B.SilkS for project/GitHub URL."""
    clean_url = url.strip()
    if not clean_url:
        return None

    best_choice: dict | None = None
    attempts = [
        ([clean_url], 0.85, 0.15, 1.5, 0.0, 0.8),
        ([clean_url], 0.85, 0.15, 1.5, 90.0, 0.5),
        (
            _wrap_text_lines(clean_url, 32, max_lines=2, delims=("/", "-", " ")),
            0.8,
            0.15,
            1.45,
            0.0,
            0.5,
        ),
        (
            _wrap_text_lines(clean_url, 36, max_lines=2, delims=("/", "-", " ")),
            0.8,
            0.15,
            1.45,
            90.0,
            0.5,
        ),
        (
            _wrap_text_lines(clean_url, 22, max_lines=3, delims=("/", "-", " ")),
            0.8,
            0.15,
            1.45,
            0.0,
            0.2,
        ),
        (
            _wrap_text_lines(clean_url, 36, max_lines=3, delims=("/", "-", " ")),
            0.8,
            0.15,
            1.45,
            90.0,
            0.2,
        ),
    ]
    for raw_lines, font_sz, thick, pitch, rot, accept_clr in attempts:
        if not raw_lines:
            continue
        bw, bh = _estimate_text_box(raw_lines, font_sz, thick, rot, pitch)
        if bw > panel_w - 2.0 or bh > panel_h - 2.0:
            continue
        if rot == 0.0:
            xs = [round(panel_w / 2.0, 3)] + _make_frange(
                1.2 + bw / 2.0, panel_w - 1.2 - bw / 2.0, 1.0
            )
            ys = _make_frange(1.2 + bh / 2.0, panel_h - 1.2 - bh / 2.0, 0.5)
        else:
            xs = [round(panel_w / 2.0, 3)] + _make_frange(
                1.2 + bw / 2.0, panel_w - 1.2 - bw / 2.0, 0.5
            )
            ys = _make_frange(1.2 + bh / 2.0, panel_h - 1.2 - bh / 2.0, 1.0)
        cand = _scan_rect_positions(
            bw, bh, circles, obs_rects, panel_w, panel_h, xs, ys
        )
        if cand is None:
            continue
        choice = {
            "clearance": cand[0],
            "cx": cand[1],
            "cy": cand[2],
            "bw": bw,
            "bh": bh,
            "rot": rot,
            "line_pitch": pitch,
            "lines": [(ln, font_sz, thick) for ln in raw_lines],
        }
        if cand[0] >= accept_clr:
            return choice
        if best_choice is None or cand[0] > best_choice["clearance"]:
            best_choice = choice

    if best_choice is None:
        bw, bh = _estimate_text_box([clean_url], 0.8, 0.15, 90.0, 1.45)
        best_choice = {
            "clearance": -99.0,
            "cx": round(panel_w / 2.0, 3),
            "cy": round(panel_h / 2.0, 3),
            "bw": bw,
            "bh": bh,
            "rot": 90.0,
            "line_pitch": 1.45,
            "lines": [(clean_url, 0.8, 0.15)],
        }
    return best_choice


def plan_rear_silkscreen(
    panel_w: float,
    panel_h: float,
    panel_x0: float,
    panel_y0: float,
    mount_slots: list[dict],
    jacks: list[dict],
    hp: int,
    title: str,
    version: str,
    url: str,
) -> dict:
    """Plan collision-free B.SilkS items (QR blank, title/version, URL) in panel-local coords."""
    circles: list[tuple[float, float, float]] = [
        (
            round(j["bushing_x"] - panel_x0, 4),
            round(j["bushing_y"] - panel_y0, 4),
            (j["pad_mm"] if j.get("grounded", True) else j["drill_mm"]) / 2.0 + 0.65,
        )
        for j in jacks
    ]
    obs_rects: list[tuple[float, float, float, float]] = [
        (
            s["local_x"] - s["width_mm"] / 2.0 - 0.65,
            s["local_y"] - s["height_mm"] / 2.0 - 0.65,
            s["local_x"] + s["width_mm"] / 2.0 + 0.65,
            s["local_y"] + s["height_mm"] / 2.0 + 0.65,
        )
        for s in mount_slots
    ]

    def _inflate(
        cx: float, cy: float, bw: float, bh: float
    ) -> tuple[float, float, float, float]:
        return (
            round(cx - bw / 2.0 - 0.5, 4),
            round(cy - bh / 2.0 - 0.5, 4),
            round(cx + bw / 2.0 + 0.5, 4),
            round(cy + bh / 2.0 + 0.5, 4),
        )

    qr_clr, qr_lx, qr_ly = _place_qr_placeholder(circles, obs_rects, panel_w, panel_h)
    if qr_clr < 0.2:
        print(
            f"Warning: Rear JLCPCB QR placeholder clearance is tight ({qr_clr:.2f} mm).",
            file=sys.stderr,
        )
    obs_rects.append(_inflate(qr_lx, qr_ly, 5.15, 5.15))

    tb_pick = _place_title_block_silk(
        circles, obs_rects, panel_w, panel_h, hp, title, version
    )
    if tb_pick["clearance"] < 0.2:
        print(
            f"Warning: Rear module title/version clearance is tight ({tb_pick['clearance']:.2f} mm).",
            file=sys.stderr,
        )
    obs_rects.append(
        _inflate(tb_pick["cx"], tb_pick["cy"], tb_pick["bw"], tb_pick["bh"])
    )

    url_pick = _place_url_silk(circles, obs_rects, panel_w, panel_h, url)
    if url_pick is not None and url_pick["clearance"] < 0.2:
        print(
            f"Warning: Rear URL clearance is tight ({url_pick['clearance']:.2f} mm).",
            file=sys.stderr,
        )

    def _serialize_text_item(name: str, pick: dict) -> dict:
        coords = _line_positions(
            pick["cx"], pick["cy"], len(pick["lines"]), pick["rot"], pick["line_pitch"]
        )
        entries = []
        for idx, (text_val, fsz, th) in enumerate(pick["lines"]):
            lx, ly = coords[idx]
            entries.append(
                {
                    "id": f"{name}_{idx}",
                    "text": text_val,
                    "local_x": lx,
                    "local_y": ly,
                    "global_x": round(panel_x0 + lx, 4),
                    "global_y": round(panel_y0 + ly, 4),
                    "rot": pick["rot"],
                    "font_size_mm": fsz,
                    "thickness_mm": th,
                }
            )
        return {
            "kind": name,
            "local_center": [pick["cx"], pick["cy"]],
            "global_center": [
                round(panel_x0 + pick["cx"], 4),
                round(panel_y0 + pick["cy"], 4),
            ],
            "box_size_mm": [pick["bw"], pick["bh"]],
            "rot_deg": pick["rot"],
            "clearance_mm": pick["clearance"],
            "entries": entries,
        }

    items: list[dict] = [
        {
            "kind": "qr_placeholder",
            "size_mm": [5.0, 5.0],
            "local_center": [qr_lx, qr_ly],
            "global_center": [round(panel_x0 + qr_lx, 4), round(panel_y0 + qr_ly, 4)],
            "local_bounds_mm": {
                "x0": round(qr_lx - 2.5, 4),
                "y0": round(qr_ly - 2.5, 4),
                "x1": round(qr_lx + 2.5, 4),
                "y1": round(qr_ly + 2.5, 4),
            },
            "clearance_mm": qr_clr,
        },
        _serialize_text_item("title_version", tb_pick),
    ]
    if url_pick is not None:
        items.append(_serialize_text_item("url", url_pick))

    return {"items": items}


def build_panel_sexpr(
    bbox: dict[str, float],
    jacks: list[dict],
    hp: int,
    panel_w: float,
    title: str,
    subtitle: str,
    ns: str = "BufferedMult_Panel",
    cascade_arrow: bool | None = None,
    blank_front: bool = False,
    version: str = "",
    url: str = "",
    rear_plan: dict | None = None,
) -> str:
    """Build the complete KiCad 10 `.kicad_pcb` S-expression for the front panel."""
    geom = compute_panel_geometry(bbox, hp, panel_w)
    panel_x0 = geom["panel_x0"]
    panel_x1 = geom["panel_x1"]
    panel_y0 = geom["panel_y0"]
    panel_y1 = geom["panel_y1"]
    center_x = geom["center_x"]

    mount_slots = compute_mount_slots(hp, panel_w, panel_x0, panel_y0)
    if rear_plan is None:
        rear_plan = plan_rear_silkscreen(
            panel_w=panel_w,
            panel_h=PANEL_HEIGHT_3U_MM,
            panel_x0=panel_x0,
            panel_y0=panel_y0,
            mount_slots=mount_slots,
            jacks=jacks,
            hp=hp,
            title=title,
            version=version,
            url=url,
        )

    footprints_str = "\n".join(
        [
            *(
                format_mount_slot_footprint(
                    ns, slot["ref"], slot["global_x"], slot["global_y"]
                )
                for slot in mount_slots
            ),
            *(format_jack_footprint(ns, j, panel_x0, panel_y0) for j in jacks),
        ]
    )

    tb_lines = [f'\t\t(title "{_sexpr_escape(title)}")']
    if version.strip():
        tb_lines.append(f'\t\t(rev "{_sexpr_escape(version.strip())}")')
    if url.strip():
        tb_lines.append(f'\t\t(comment 1 "{_sexpr_escape(url.strip())}")')
    title_block_sexpr = "\t(title_block\n" + "\n".join(tb_lines) + "\n\t)"

    front_silk_sexpr = ""
    if not blank_front:
        rows: list[list[dict]] = []
        for j in jacks:
            if not rows or abs(j["bushing_y"] - rows[-1][0]["bushing_y"]) > 1.0:
                rows.append([j])
            else:
                rows[-1].append(j)

        jack_graphics: list[str] = []
        row_label_ys: list[float] = []
        has_wide_intergroup_gap = any(
            (rows[i + 1][0]["bushing_y"] - rows[i][0]["bushing_y"]) > 20.0
            for i in range(len(rows) - 1)
        )
        for row_idx, row in enumerate(rows):
            row_y = row[0]["bushing_y"]
            if has_wide_intergroup_gap:
                lbl_y = (
                    round(row_y - 7.28, 2)
                    if row_idx % 2 == 0
                    else round(row_y + 7.32, 2)
                )
            else:
                lbl_y = round(row_y + 7.2, 2)
            row_label_ys.append(lbl_y)

            for j in row:
                jx = j["bushing_x"]
                lbl = clean_label(j.get("label", j["value"]))
                ref_id = j["ref"].lower()
                tokens = lbl.upper().split()
                is_input = (
                    bool(tokens)
                    and (tokens[0] in ("IN", "INPUT") or tokens[-1] in ("IN", "INPUT"))
                    and "OUT" not in tokens
                    and "OUTPUT" not in tokens
                )
                if is_input:
                    badge_hw = max(3.6, round(len(lbl) * 0.65 + 0.9, 2))
                    jack_graphics.append(
                        f"""\t(gr_rect
\t\t(start {jx - badge_hw:g} {lbl_y - 1.45:g})
\t\t(end {jx + badge_hw:g} {lbl_y + 1.45:g})
\t\t(stroke
\t\t\t(width 0.25)
\t\t\t(type solid)
\t\t)
\t\t(fill no)
\t\t(layer "F.SilkS")
\t\t(uuid "{det_uuid(ns, f"badge_{ref_id}")}")
\t)
\t(gr_text "{_sexpr_escape(lbl)}"
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
                        f"""\t(gr_text "{_sexpr_escape(lbl)}"
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

        draw_cascade = (
            cascade_arrow if cascade_arrow is not None else ("MULT" in title.upper())
        )
        cascade_graphics = ""
        if (
            draw_cascade
            and len(rows) >= 3
            and (row_label_ys[2] - row_label_ys[1]) > 18.0
        ):
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

        footer_sexpr = ""
        if subtitle.strip():
            footer_sexpr = f"""
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
\t(gr_text "{_sexpr_escape(subtitle)}"
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
\t)"""

        jack_graphics_str = "\n".join(jack_graphics)
        front_silk_sexpr = f"""
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
\t(gr_text "{_sexpr_escape(title)}"
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
{jack_graphics_str}{cascade_graphics}{footer_sexpr}"""

    rear_silk_parts: list[str] = []
    for item in rear_plan["items"]:
        if item["kind"] == "qr_placeholder":
            gx, gy = item["global_center"]
            rear_silk_parts.append(
                f"""\t(gr_rect
\t\t(start {gx - 2.5:g} {gy - 2.5:g})
\t\t(end {gx + 2.5:g} {gy + 2.5:g})
\t\t(stroke
\t\t\t(width 0.15)
\t\t\t(type solid)
\t\t)
\t\t(fill yes)
\t\t(layer "B.SilkS")
\t\t(uuid "{det_uuid(ns, "jlc_qr_placeholder")}")
\t)"""
            )
        else:
            for entry in item["entries"]:
                rear_silk_parts.append(
                    f"""\t(gr_text "{_sexpr_escape(entry["text"])}"
\t\t(at {entry["global_x"]:g} {entry["global_y"]:g} {entry["rot"]:g})
\t\t(layer "B.SilkS")
\t\t(uuid "{det_uuid(ns, f"rear_{entry['id']}")}")
\t\t(effects
\t\t\t(font
\t\t\t\t(size {entry["font_size_mm"]:g} {entry["font_size_mm"]:g})
\t\t\t\t(thickness {entry["thickness_mm"]:g})
\t\t\t)
\t\t\t(justify mirror)
\t\t)
\t)"""
                )
    rear_silk_sexpr = "\n".join(rear_silk_parts)

    return f"""(kicad_pcb
\t(version 20260206)
\t(generator "pcbnew")
\t(generator_version "10.0")
\t(general
\t\t(thickness 1.6)
\t\t(legacy_teardrops no)
\t)
\t(paper "A4")
{title_block_sexpr}
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
\t){front_silk_sexpr}
{rear_silk_sexpr}
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


def _compute_panel_spacing(
    comp_entries: list[dict], panel_w: float
) -> tuple[dict, dict[str, float]]:
    """Compute per-group control pitches, open margins, and max pot knob diameters."""
    pots = [c for c in comp_entries if c["kind"] == "pot"]
    max_knob_by_ref: dict[str, float] = {}
    for pot in pots:
        edge_max = 2.0 * (min(pot["local_x"], panel_w - pot["local_x"]) - 1.0)
        pot_limits = [
            math.hypot(pot["local_x"] - op["local_x"], pot["local_y"] - op["local_y"])
            - 1.5
            for op in pots
            if op["ref"] != pot["ref"]
        ]
        other_limits = [
            2.0
            * (
                math.hypot(
                    pot["local_x"] - oc["local_x"], pot["local_y"] - oc["local_y"]
                )
                - oc["keepout_mm"] / 2.0
                - 1.0
            )
            for oc in comp_entries
            if oc["kind"] != "pot"
        ]
        raw_max = max(0.0, min([edge_max, *pot_limits, *other_limits]))
        max_knob_by_ref[pot["ref"]] = round(math.floor(raw_max * 2.0) / 2.0, 1)

    rows: list[list[dict]] = []
    for c in sorted(comp_entries, key=lambda x: (x["local_y"], x["local_x"])):
        if not rows or abs(c["local_y"] - rows[-1][0]["local_y"]) > 1.0:
            rows.append([c])
        else:
            rows[-1].append(c)

    row_ys = [round(sum(c["local_y"] for c in row) / len(row), 2) for row in rows]
    row_summary = []
    for idx, row in enumerate(rows):
        ry = row_ys[idx]
        xs = sorted(c["local_x"] for c in row)
        gap_below = round(row_ys[idx + 1] - ry, 2) if idx + 1 < len(rows) else None
        h_pitches = (
            [round(xs[i + 1] - xs[i], 2) for i in range(len(xs) - 1)]
            if len(xs) > 1
            else []
        )
        row_summary.append(
            {
                "row": idx + 1,
                "local_y_mm": ry,
                "refs": [c["ref"] for c in row],
                "x_positions_mm": xs,
                "left_margin_mm": round(min(xs), 2),
                "right_margin_mm": round(panel_w - max(xs), 2),
                "horizontal_pitches_mm": h_pitches,
                "vertical_pitch_to_next_mm": gap_below,
            }
        )

    group_summary: dict[str, dict] = {}
    for kind in sorted({c["kind"] for c in comp_entries}):
        grp = [c for c in comp_entries if c["kind"] == kind]
        xs = sorted({c["local_x"] for c in grp})
        ys = sorted({c["local_y"] for c in grp})
        v_pitches = sorted({round(ys[i + 1] - ys[i], 2) for i in range(len(ys) - 1)})
        h_pitches = sorted({round(xs[i + 1] - xs[i], 2) for i in range(len(xs) - 1)})
        entry: dict = {
            "count": len(grp),
            "x_positions_mm": xs,
            "y_positions_mm": ys,
            "horizontal_pitches_mm": h_pitches,
            "vertical_pitches_mm": v_pitches,
        }
        if kind == "pot":
            entry["shaft_sweep_deg"] = 300.0
            entry["shaft_sweep_note"] = (
                "Standard Alpha 9mm pot sweep is 300 deg (+/-150 deg around 12 o'clock)."
            )
            entry["max_knob_diameter_mm"] = (
                min(max_knob_by_ref.values()) if max_knob_by_ref else None
            )
        group_summary[kind] = entry

    return {
        "groups": group_summary,
        "rows": row_summary,
        "side_clearance_from_center_mm": round(panel_w / 2.0, 2),
    }, max_knob_by_ref


def build_panel_spec_markdown(
    main_pcb_path: pathlib.Path,
    output_pcb_path: pathlib.Path | None,
    bbox: dict[str, float],
    jacks: list[dict],
    hp: int,
    panel_w: float,
    title: str,
    version: str,
    url: str,
    blank_front: bool,
    rear_plan: dict,
) -> str:
    """Build a structured Markdown + JSON specification for front-panel SVG crafting."""
    geom = compute_panel_geometry(bbox, hp, panel_w)
    panel_x0 = geom["panel_x0"]
    panel_y0 = geom["panel_y0"]
    panel_x1 = geom["panel_x1"]
    panel_y1 = geom["panel_y1"]
    mount_slots = compute_mount_slots(hp, panel_w, panel_x0, panel_y0)

    def _md_esc(text: str) -> str:
        return text.replace("|", "\\|").replace("\n", " ").strip()

    comp_entries: list[dict] = []
    for j in jacks:
        lx = round(j["bushing_x"] - panel_x0, 2)
        ly = round(j["bushing_y"] - panel_y0, 2)
        grounded = bool(j.get("grounded", True))
        comp_entries.append(
            {
                "ref": j["ref"],
                "kind": j["kind"],
                "label": clean_label(j.get("label", j["value"])),
                "value": j["value"],
                "local_x": lx,
                "local_y": ly,
                "global_x": round(j["bushing_x"], 2),
                "global_y": round(j["bushing_y"], 2),
                "drill_mm": j["drill_mm"],
                "pad_mm": j["pad_mm"],
                "keepout_mm": j["keepout_mm"],
                "grounded": grounded,
                "hole_type": "PTH GND" if grounded else "NPTH",
                "front_mask": (
                    f"Tented (`B.Mask` {j['pad_mm']:g} mm)"
                    if grounded
                    else f"Open `*.Mask` ({j['drill_mm']:g} mm)"
                ),
                "mpn": j.get("mpn", ""),
                "manufacturer": j.get("manufacturer", ""),
                "notes": j.get("notes") or j.get("description") or "",
            }
        )

    spacing, max_knob_by_ref = _compute_panel_spacing(comp_entries, panel_w)
    for c in comp_entries:
        c["max_knob_mm"] = max_knob_by_ref.get(c["ref"])

    target_pcb_display = (
        f"`{output_pcb_path.name}`"
        if output_pcb_path is not None
        else "*(inspect-only)*"
    )
    front_mode = (
        "Blank (`0` `F.SilkS` primitives; ready for custom SVG import)"
        if blank_front
        else "Standard auto-labeled `F.SilkS`"
    )

    lines: list[str] = [
        f"# Eurorack Front-Panel Specification — {title}",
        "",
        "## 1. Overview & Metadata",
        "",
        "| Field | Value |",
        "| :--- | :--- |",
        f"| **Module Name** | `{_md_esc(title)}` |",
        f"| **Version** | `{_md_esc(version or 'N/A')}` |",
        f"| **GitHub / Project URL** | `{_md_esc(url or 'N/A')}` |",
        f"| **Format** | `{hp} HP × 3U` (`{panel_w:.2f} × {PANEL_HEIGHT_3U_MM:.2f} mm`, `1.6 mm` FR4) |",
        f"| **Source Main PCB** | `{main_pcb_path.name}` (`{geom['pcb_w']:.2f} × {geom['pcb_h']:.2f} mm`) |",
        f"| **Target Panel PCB** | {target_pcb_display} |",
        f"| **Front Face Mode** | {front_mode} |",
        "",
        "## 2. SVG Canvas & Coordinate System",
        "",
        "Use a **1:1 millimeter** SVG canvas matching KiCad's panel-local coordinate system (`(0, 0)` at top-left, `+X` right, `+Y` down, `1 SVG user unit = 1.00 mm`):",
        "",
        "```xml",
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{panel_w:.2f}mm" height="{PANEL_HEIGHT_3U_MM:.2f}mm" viewBox="0 0 {panel_w:.2f} {PANEL_HEIGHT_3U_MM:.2f}">',
        "```",
        "",
        f"- **KiCad Global Origin Mapping:** SVG `(0.00, 0.00)` maps to KiCad global `({panel_x0:.2f}, {panel_y0:.2f}) mm` -> bottom-right `({panel_x1:.2f}, {panel_y1:.2f}) mm`.",
        f"- **Main PCB Overhang:** `{geom['overhang_y']:.2f} mm` vertical rail overhang (top & bottom); `{geom['overhang_x']:.2f} mm` horizontal overhang.",
        f"- **Safe Artwork Bounds (`0.50 mm` edge inset):** `X = 0.50 .. {panel_w - 0.50:.2f} mm`, `Y = 0.50 .. {PANEL_HEIGHT_3U_MM - 0.50:.2f} mm`.",
        f"- **Eurorack Rail-Lip & Washer Keepouts:** Top `Y = 0.00 .. 6.50 mm`, Bottom `Y = {PANEL_HEIGHT_3U_MM - 6.50:.2f} .. {PANEL_HEIGHT_3U_MM:.2f} mm`.",
        "",
        "## 3. Mounting Slots (`NPTH` Oval)",
        "",
        "| Ref | SVG Center `(X, Y)` mm | KiCad Global `(X, Y)` mm | Slot `W × H` mm | `X` Span mm | `Y` Span mm | Washer Keepout |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]

    for s in mount_slots:
        x_lo = round(s["local_x"] - s["width_mm"] / 2.0, 2)
        x_hi = round(s["local_x"] + s["width_mm"] / 2.0, 2)
        y_lo = round(s["local_y"] - s["height_mm"] / 2.0, 2)
        y_hi = round(s["local_y"] + s["height_mm"] / 2.0, 2)
        lines.append(
            f"| **{s['ref']}** | `({s['local_x']:.2f}, {s['local_y']:.2f})` | "
            f"`({s['global_x']:.2f}, {s['global_y']:.2f})` | "
            f"`{s['width_mm']:.2f} × {s['height_mm']:.2f}` | "
            f"`{x_lo:.2f}..{x_hi:.2f}` | `{y_lo:.2f}..{y_hi:.2f}` | "
            "`~7.0 mm` M3 washer (`Y ± 3.5 mm`) |"
        )

    lines.extend(
        [
            "",
            "## 4. Front-Panel Component Cutouts & Keepouts",
            "",
            "| Ref | Kind | Label | Value | SVG Center `(X, Y)` mm | KiCad Global `(X, Y)` mm | Drill Ø mm | Hole Type & Front Mask | Nut / Bezel Keepout Ø mm | Max Knob Ø mm | Notes / Behavior |",
            "| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :--- | :---: | :---: | :--- |",
        ]
    )
    for c in comp_entries:
        knob_str = (
            f"`<= {c['max_knob_mm']:.1f}`" if c["max_knob_mm"] is not None else "—"
        )
        note_str = _md_esc(c["notes"]) if c["notes"] else "—"
        lines.append(
            f"| **{c['ref']}** | `{c['kind']}` | `{_md_esc(c['label'])}` | `{_md_esc(c['value'])}` | "
            f"`({c['local_x']:.2f}, {c['local_y']:.2f})` | `({c['global_x']:.2f}, {c['global_y']:.2f})` | "
            f"`{c['drill_mm']:.2f}` | {c['hole_type']} — {c['front_mask']} | "
            f"`{c['keepout_mm']:.1f}` | {knob_str} | {note_str} |"
        )

    lines.extend(["", "## 5. Inter-Control Spacing & Open Regions", ""])
    for kind, g in spacing["groups"].items():
        vp = ", ".join(f"`{v:.2f} mm`" for v in g["vertical_pitches_mm"]) or "—"
        hp_list = ", ".join(f"`{h:.2f} mm`" for h in g["horizontal_pitches_mm"]) or "—"
        xs_str = ", ".join(f"`{x:.2f}`" for x in g["x_positions_mm"])
        ys_str = ", ".join(f"`{y:.2f}`" for y in g["y_positions_mm"])
        extra = ""
        if kind == "pot":
            extra = (
                f" — Max knob Ø `{g['max_knob_diameter_mm']:.1f} mm`; "
                f"{g['shaft_sweep_note']}"
            )
        lines.append(
            f"- **`{kind}` (`×{g['count']}`):** X = {xs_str} mm; Y = {ys_str} mm; "
            f"H-pitch = {hp_list}; V-pitch = {vp}{extra}"
        )

    lines.append("")
    lines.append("**Row Band Summary (Top to Bottom):**")
    for r in spacing["rows"]:
        next_gap = (
            f" (next row `+{r['vertical_pitch_to_next_mm']:.2f} mm`)"
            if r["vertical_pitch_to_next_mm"] is not None
            else ""
        )
        lines.append(
            f"- Row {r['row']} (`Y = {r['local_y_mm']:.2f} mm`): "
            f"{', '.join(r['refs'])} — left margin `{r['left_margin_mm']:.2f} mm`, "
            f"right margin `{r['right_margin_mm']:.2f} mm`{next_gap}"
        )

    lines.extend(
        [
            "",
            "## 6. Target Front-Face SVG Layers & Fabrication Rules (`F.SilkS` & `F.Mask`)",
            "",
            "Export **two aligned Plain SVGs** sharing the exact `viewBox` canvas above:",
            "1. **`front_silkscreen.svg` → `F.SilkS`**: Labels, dial ticks, polarity markers, borders, and legends.",
            "2. **`front_soldermask.svg` → `F.Mask`**: Solder-mask openings for decorative metallic accents.",
            "",
            "### PCB Fabrication & KiCad Rules",
            "- **Exposed Copper vs. Bare FR4 (`F.Mask`):** The panel includes a solid `F.Cu` `GND` pour. Any `F.Mask` opening over the pour exposes **bare copper (ENIG gold or HASL silver)**. Because `F.Cu` pulls back `0.40–0.50 mm` from `Edge.Cuts` and around NPTH holes (`H1`, `H2`, `LED`s), avoid placing `F.Mask` artwork within **`0.60 mm`** of `Edge.Cuts` or within **`drill/2 + 0.50 mm`** of NPTH holes unless bare FR4 is intentional.",
            "- **Zero `F.SilkS` / `F.Mask` Overlap:** Maintain **`>= 0.20 mm`** clearance between `F.SilkS` and `F.Mask` shapes (plus `>= 0.20 mm` outside exposed hole pads/slots) so fab houses do not clip ink and KiCad DRC reports zero `silk_over_copper` errors.",
            "- **Convert Text & Strokes to Paths:** Before saving Plain SVG, convert all fonts and strokes to filled outlines (`Object to Path` and `Stroke to Path`) so KiCad renders exact geometry without font substitution.",
            "- **JLCPCB Minimums:** `F.SilkS` minimum stroke `>= 0.15 mm` (`0.18–0.25 mm` recommended), minimum text height `>= 0.80 mm` (`1.0 mm+` recommended); `F.Mask` minimum opening/bridge `>= 0.20 mm`.",
            f"- **Exact Registration in KiCad 10 (`File → Import → Graphics...`):** Include a `0.05 mm` registration rectangle from `(0, 0)` to `({panel_w:.2f}, {PANEL_HEIGHT_3U_MM:.2f})` in both SVGs so KiCad does not shift the bounding box on import. Import at **Scale `1.0`** onto `F.SilkS` / `F.Mask`, anchor at panel origin `({panel_x0:.2f}, {panel_y0:.2f})` (or `(0, 0)` with aux origin active), **Ungroup**, and delete the temporary outer registration rectangle.",
            "",
            "## 7. Back-Face Silkscreen Layout (`B.SilkS`)",
            "",
            "All rear markings are mirrored (`(justify mirror)`) for right-reading inspection from the back and automatically kept clear of `B.Mask` pads, mounting slots, and panel edges (`Min Clearance mm` / `clearance_mm` reports net margin beyond the built-in `1.0 mm` edge, `0.65 mm` pad/slot, and `0.50 mm` inter-item keepout buffers):",
            "",
            "| Element | Content / Size | Panel-Local `(X, Y)` mm | KiCad Global `(X, Y)` mm | Rot (deg) | Min Clearance mm |",
            "| :--- | :--- | :---: | :---: | :---: | :---: |",
        ]
    )

    for item in rear_plan["items"]:
        if item["kind"] == "qr_placeholder":
            lx, ly = item["local_center"]
            gx, gy = item["global_center"]
            lines.append(
                f"| **JLCPCB QR Blank** | `5.00 × 5.00 mm` filled `gr_rect` | "
                f"`({lx:.2f}, {ly:.2f})` | `({gx:.2f}, {gy:.2f})` | `0` | `{item['clearance_mm']:.2f}` |"
            )
        else:
            content = " / ".join(_md_esc(e["text"]) for e in item["entries"])
            lx, ly = item["local_center"]
            gx, gy = item["global_center"]
            label = (
                "Module Name & Version"
                if item["kind"] == "title_version"
                else "Project URL"
            )
            lines.append(
                f"| **{label}** | `{content}` | "
                f"`({lx:.2f}, {ly:.2f})` | `({gx:.2f}, {gy:.2f})` | "
                f"`{item['rot_deg']:g}` | `{item['clearance_mm']:.2f}` |"
            )

    payload = {
        "metadata": {
            "module_name": title,
            "version": version,
            "url": url,
            "hp": hp,
            "blank_front": blank_front,
            "source_pcb": main_pcb_path.name,
            "target_panel_pcb": output_pcb_path.name if output_pcb_path else None,
        },
        "canvas": {
            "units": "mm",
            "width_mm": round(panel_w, 2),
            "height_mm": PANEL_HEIGHT_3U_MM,
            "viewBox": f"0 0 {panel_w:.2f} {PANEL_HEIGHT_3U_MM:.2f}",
            "origin": "top-left (+X right, +Y down)",
            "kicad_global_origin_mm": [round(panel_x0, 2), round(panel_y0, 2)],
            "kicad_global_end_mm": [round(panel_x1, 2), round(panel_y1, 2)],
            "main_pcb_size_mm": [round(geom["pcb_w"], 2), round(geom["pcb_h"], 2)],
            "overhang_mm": {
                "x": round(geom["overhang_x"], 2),
                "y": round(geom["overhang_y"], 2),
            },
            "safe_artwork_bounds_mm": {
                "x_min": 0.5,
                "y_min": 0.5,
                "x_max": round(panel_w - 0.5, 2),
                "y_max": round(PANEL_HEIGHT_3U_MM - 0.5, 2),
            },
            "rail_keepout_y_mm": {
                "top": [0.0, 6.5],
                "bottom": [round(PANEL_HEIGHT_3U_MM - 6.5, 2), PANEL_HEIGHT_3U_MM],
            },
        },
        "mounting_slots": mount_slots,
        "components": comp_entries,
        "spacing": spacing,
        "fabrication_rules": {
            "target_layers": ["F.SilkS", "F.Mask"],
            "min_silk_stroke_mm": 0.15,
            "min_silk_text_height_mm": 0.8,
            "min_mask_opening_mm": 0.2,
            "min_silk_to_mask_clearance_mm": 0.2,
            "copper_edge_pullback_mm": 0.6,
            "paths_only_svg": True,
            "registration_frame_mm": [0.0, 0.0, round(panel_w, 2), PANEL_HEIGHT_3U_MM],
        },
        "back_silkscreen": rear_plan["items"],
    }

    lines.extend(
        [
            "",
            "## 8. Machine-Readable Geometry (`JSON`)",
            "",
            "```json",
            json.dumps(payload, indent=2),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


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
            "--severity-all",
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
    all_violations = data.get("violations", [])
    lib_issues = [v for v in all_violations if v.get("type") == "lib_footprint_issues"]
    non_lib = [v for v in all_violations if v.get("type") != "lib_footprint_issues"]
    unconnected = data.get("unconnected_items", [])
    if lib_issues:
        print(
            f"  DRC Note: filtered {len(lib_issues)} lib_footprint_issues warning(s) "
            "(inline panel footprints)."
        )
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
        default=None,
        help="Module title (defaults to main PCB title_block title or filename).",
    )
    parser.add_argument(
        "--subtitle",
        type=str,
        default="",
        help="Bottom front-silkscreen module subtitle (ignored with --blank-front).",
    )
    parser.add_argument(
        "--version",
        type=str,
        default=None,
        help="Module revision/version string for back silkscreen & title_block (defaults to main PCB rev).",
    )
    parser.add_argument(
        "--url",
        type=str,
        default="",
        help="GitHub or project URL placed on back silkscreen (B.SilkS).",
    )
    parser.add_argument(
        "--blank-front",
        action="store_true",
        help="Generate a blank front face with zero F.SilkS primitives for custom SVG artwork.",
    )
    parser.add_argument(
        "--spec-md",
        type=pathlib.Path,
        default=None,
        help="Export a Markdown (+ JSON) mechanical & SVG dimension specification to this path.",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Print mechanical alignment and coordinate table without writing a `.kicad_pcb`.",
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
    parser.add_argument(
        "-l",
        "--label",
        action="append",
        default=[],
        metavar="REF=TEXT",
        help="Override panel silkscreen label for a component reference (e.g. D4=ENV).",
    )
    parser.add_argument(
        "--drill",
        action="append",
        default=[],
        metavar="REF=MM",
        help="Override panel cutout drill diameter in mm for a reference (e.g. SW1=5.0).",
    )
    return parser.parse_args()


def _apply_label_overrides(jacks: list[dict], specs: list[str]) -> None:
    """Apply --label REF=TEXT overrides to parsed panel components."""
    overrides: dict[str, str] = {}
    for spec in specs:
        if "=" not in spec:
            raise ValueError(f"Invalid --label format {spec!r}; expected REF=TEXT")
        ref_key, lbl_text = spec.split("=", 1)
        overrides[ref_key.strip().upper()] = lbl_text.strip()
    matched_refs = {j["ref"].upper() for j in jacks}
    for ref_u in overrides:
        if ref_u not in matched_refs:
            print(
                f"Warning: --label target {ref_u!r} not found among panel-mounted components.",
                file=sys.stderr,
            )
    for j in jacks:
        ref_u = j["ref"].upper()
        if ref_u in overrides:
            j["label"] = overrides[ref_u]


def _apply_drill_overrides(jacks: list[dict], specs: list[str]) -> None:
    """Apply --drill REF=MM overrides and scale pad diameters consistently."""
    overrides: dict[str, float] = {}
    for spec in specs:
        if "=" not in spec:
            raise ValueError(f"Invalid --drill format {spec!r}; expected REF=MM")
        ref_key, drill_str = spec.split("=", 1)
        try:
            drill_val = float(drill_str.strip())
        except ValueError as exc:
            raise ValueError(
                f"Invalid drill diameter {drill_str!r} in --drill {spec!r}"
            ) from exc
        if not math.isfinite(drill_val) or drill_val <= 0:
            raise ValueError(f"Drill diameter must be > 0 in --drill {spec!r}")
        overrides[ref_key.strip().upper()] = drill_val
    matched_refs = {j["ref"].upper() for j in jacks}
    for ref_u in overrides:
        if ref_u not in matched_refs:
            print(
                f"Warning: --drill target {ref_u!r} not found among panel-mounted components.",
                file=sys.stderr,
            )
    for j in jacks:
        ref_u = j["ref"].upper()
        if ref_u in overrides:
            new_drill = overrides[ref_u]
            old_drill = j["drill_mm"]
            delta = new_drill - old_drill
            j["drill_mm"] = new_drill
            if j.get("grounded", True):
                j["pad_mm"] = round(
                    max(new_drill + 2.0, j["pad_mm"] + delta),
                    2,
                )
                j["keepout_mm"] = round(max(j["pad_mm"], j["keepout_mm"] + delta), 2)
            else:
                j["pad_mm"] = new_drill
                j["keepout_mm"] = round(
                    max(new_drill + 0.8, j["keepout_mm"] + delta), 2
                )


def main() -> None:
    args = parse_args()
    bbox, jacks, pcb_meta = parse_main_pcb(args.main_pcb)

    if args.label:
        _apply_label_overrides(jacks, args.label)
    if args.drill:
        _apply_drill_overrides(jacks, args.drill)

    pcb_w = bbox["max_x"] - bbox["min_x"]
    hp, panel_w = infer_hp_and_width(pcb_w, args.hp)
    if args.inspect and args.spec_md is None:
        print_inspection_report(args.main_pcb, bbox, jacks, hp, panel_w)
        return

    title = (
        args.title
        if args.title is not None
        else (pcb_meta.get("title") or args.main_pcb.stem)
    )
    version = args.version if args.version is not None else pcb_meta.get("rev", "")

    geom = compute_panel_geometry(bbox, hp, panel_w)
    mount_slots = compute_mount_slots(hp, panel_w, geom["panel_x0"], geom["panel_y0"])
    rear_plan = plan_rear_silkscreen(
        panel_w=panel_w,
        panel_h=PANEL_HEIGHT_3U_MM,
        panel_x0=geom["panel_x0"],
        panel_y0=geom["panel_y0"],
        mount_slots=mount_slots,
        jacks=jacks,
        hp=hp,
        title=title,
        version=version,
        url=args.url,
    )

    if args.spec_md is not None:
        spec_md = build_panel_spec_markdown(
            main_pcb_path=args.main_pcb,
            output_pcb_path=None if args.inspect else args.output,
            bbox=bbox,
            jacks=jacks,
            hp=hp,
            panel_w=panel_w,
            title=title,
            version=version,
            url=args.url,
            blank_front=args.blank_front,
            rear_plan=rear_plan,
        )
        args.spec_md.parent.mkdir(parents=True, exist_ok=True)
        args.spec_md.write_text(spec_md, encoding="utf-8")
        print(f"Exported panel specification to {args.spec_md}")

    if args.inspect:
        print_inspection_report(args.main_pcb, bbox, jacks, hp, panel_w)
        return

    sexpr = build_panel_sexpr(
        bbox=bbox,
        jacks=jacks,
        hp=hp,
        panel_w=panel_w,
        title=title,
        subtitle=args.subtitle,
        ns=args.output.stem,
        cascade_arrow=args.cascade_arrow,
        blank_front=args.blank_front,
        version=version,
        url=args.url,
        rear_plan=rear_plan,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(sexpr, encoding="utf-8")
    refill_zones_with_kicad(args.output)
    print(
        f"Generated {args.output} ({hp}HP / {panel_w:.1f}x{PANEL_HEIGHT_3U_MM:.1f}mm, "
        f"{len(jacks)} panel cutouts)."
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
