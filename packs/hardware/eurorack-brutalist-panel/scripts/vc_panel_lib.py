"""Reusable VectorCraft batch builders for Dark Techno / Brutalist Eurorack panels."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

MM_TO_PT = 72.0 / 25.4
PT_TO_MM = 25.4 / 72.0

# Visual palette (draw 01_F_Mask_Gold and 02_F_SilkS_White in Preview Hex;
# _audit_*.png renders on a black background, and audit_panel_svgs.py remaps
# fills to Fab Hex during 1:1 mm normalization).
COLOR_FR4_BG = "#141518"
COLOR_FR4_RIM = "#2a2d34"
COLOR_DRILL_FILL = "#07080a"
COLOR_DRILL_RIM = "#383c46"
COLOR_MASK_GOLD = "#D8B154"
COLOR_MASK_FAB_GOLD = "#C89B3C"
COLOR_SILK_PREVIEW = "#F4F5F7"
COLOR_SILK_FAB = "#000000"
COLOR_BLACK = "#000000"

# Audit bitmap resolution (40 px/mm = 1016 ppi)
AUDIT_PPI = 1016.0
AUDIT_PX_PER_MM = AUDIT_PPI / 25.4


def pt(mm: float) -> float:
    """Convert millimeters to typographic points."""
    return round(mm * MM_TO_PT, 6)


def load_panel_spec(spec_path: Path) -> dict[str, Any]:
    """Extract the machine-readable JSON geometry block from panel_svg_spec.md."""
    text = spec_path.read_text(encoding="utf-8")
    match = re.search(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
    if not match:
        raise RuntimeError(f"Could not locate JSON geometry block in {spec_path}")
    return json.loads(match.group(1))


class StepBuilder:
    """Builds vectorcraft-cli --commands steps while tracking 0-based step indices."""

    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []

    def add(self, command: str, params: dict[str, Any] | None = None) -> int:
        idx = len(self.steps)
        step: dict[str, Any] = {"command": command}
        if params is not None:
            step["params"] = params
        self.steps.append(step)
        return idx

    def new_layer(self, name: str, color: str | None = None) -> str:
        params: dict[str, Any] = {"name": name, "top": True}
        if color:
            params["color"] = color
        idx = self.add("layer.new", params)
        return f"${idx}.id"

    def set_current_layer(self, layer_ref: str) -> None:
        self.add("layer.setCurrent", {"id": layer_ref})

    def set_layer_visible(self, layer_ref: str, visible: bool) -> None:
        self.add("layer.setProps", {"id": layer_ref, "visible": visible})

    def rect_fill(
        self,
        x_mm: float,
        y_mm: float,
        w_mm: float,
        h_mm: float,
        color: str,
        radius_mm: float = 0.0,
        rotation_deg: float = 0.0,
    ) -> str:
        params: dict[str, Any] = {
            "x": pt(x_mm),
            "y": pt(y_mm),
            "width": pt(w_mm),
            "height": pt(h_mm),
        }
        if radius_mm > 0.0:
            params["radius"] = pt(radius_mm)
        if rotation_deg != 0.0:
            params["rotation"] = rotation_deg
        idx = self.add("shape.rectangle", params)
        self.add("paint.setFill", {"color": color})
        self.add("paint.setStroke", {"none": True})
        return f"${idx}.id"

    def rect_stroke_outlined(
        self,
        x_mm: float,
        y_mm: float,
        w_mm: float,
        h_mm: float,
        stroke_mm: float,
        color: str,
        align: str = "center",
        join: str = "miter",
        radius_mm: float = 0.0,
    ) -> str:
        params: dict[str, Any] = {
            "x": pt(x_mm),
            "y": pt(y_mm),
            "width": pt(w_mm),
            "height": pt(h_mm),
        }
        if radius_mm > 0.0:
            params["radius"] = pt(radius_mm)
        self.add("shape.rectangle", params)
        self.add("paint.setFill", {"none": True})
        self.add("paint.setStroke", {"color": color})
        self.add(
            "stroke.set",
            {"weight": pt(stroke_mm), "align": align, "join": join},
        )
        out_idx = self.add("object.path.outlineStroke")
        return f"${out_idx}.ids[0]"

    def circle_fill(self, cx_mm: float, cy_mm: float, d_mm: float, color: str) -> str:
        r_mm = d_mm / 2.0
        idx = self.add(
            "shape.ellipse",
            {
                "x": pt(cx_mm - r_mm),
                "y": pt(cy_mm - r_mm),
                "width": pt(d_mm),
                "height": pt(d_mm),
            },
        )
        self.add("paint.setFill", {"color": color})
        self.add("paint.setStroke", {"none": True})
        return f"${idx}.id"

    def circle_stroke_keepout(
        self,
        cx_mm: float,
        cy_mm: float,
        d_mm: float,
        color: str,
        stroke_mm: float = 0.14,
        dash_mm: tuple[float, float] | None = (0.45, 0.35),
        opacity: int = 85,
    ) -> str:
        r_mm = d_mm / 2.0
        idx = self.add(
            "shape.ellipse",
            {
                "x": pt(cx_mm - r_mm),
                "y": pt(cy_mm - r_mm),
                "width": pt(d_mm),
                "height": pt(d_mm),
            },
        )
        self.add("paint.setFill", {"none": True})
        self.add("paint.setStroke", {"color": color})
        stroke_params: dict[str, Any] = {"weight": pt(stroke_mm)}
        if dash_mm is not None:
            stroke_params["dash"] = [pt(dash_mm[0]), pt(dash_mm[1])]
        self.add("stroke.set", stroke_params)
        self.add("transparency.set", {"opacity": opacity})
        return f"${idx}.id"

    def rect_stroke_keepout(
        self,
        x_mm: float,
        y_mm: float,
        w_mm: float,
        h_mm: float,
        color: str,
        stroke_mm: float = 0.14,
        dash_mm: tuple[float, float] | None = (0.50, 0.35),
        radius_mm: float = 0.0,
        opacity: int = 80,
    ) -> str:
        params: dict[str, Any] = {
            "x": pt(x_mm),
            "y": pt(y_mm),
            "width": pt(w_mm),
            "height": pt(h_mm),
        }
        if radius_mm > 0.0:
            params["radius"] = pt(radius_mm)
        idx = self.add("shape.rectangle", params)
        self.add("paint.setFill", {"none": True})
        self.add("paint.setStroke", {"color": color})
        stroke_params: dict[str, Any] = {"weight": pt(stroke_mm)}
        if dash_mm is not None:
            stroke_params["dash"] = [pt(dash_mm[0]), pt(dash_mm[1])]
        self.add("stroke.set", stroke_params)
        self.add("transparency.set", {"opacity": opacity})
        return f"${idx}.id"

    def polygon_fill(self, points_mm: list[tuple[float, float]], color: str) -> str:
        anchors = [{"x": pt(x), "y": pt(y)} for x, y in points_mm]
        idx = self.add("path.create", {"anchors": anchors, "closed": True})
        self.add("paint.setFill", {"color": color})
        self.add("paint.setStroke", {"none": True})
        return f"${idx}.id"

    def polygon_stroke_outlined(
        self,
        points_mm: list[tuple[float, float]],
        stroke_mm: float,
        color: str,
        closed: bool = True,
        align: str = "center",
        join: str = "miter",
        cap: str = "butt",
    ) -> str:
        anchors = [{"x": pt(x), "y": pt(y)} for x, y in points_mm]
        self.add("path.create", {"anchors": anchors, "closed": closed})
        self.add("paint.setFill", {"none": True})
        self.add("paint.setStroke", {"color": color})
        self.add(
            "stroke.set",
            {
                "weight": pt(stroke_mm),
                "align": align,
                "join": join,
                "cap": cap,
            },
        )
        out_idx = self.add("object.path.outlineStroke")
        return f"${out_idx}.ids[0]"

    def line_stroke_outlined(
        self,
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        stroke_mm: float,
        color: str,
        cap: str = "butt",
    ) -> str:
        self.add(
            "shape.line",
            {
                "x1": pt(x1_mm),
                "y1": pt(y1_mm),
                "x2": pt(x2_mm),
                "y2": pt(y2_mm),
            },
        )
        self.add("paint.setFill", {"none": True})
        self.add("paint.setStroke", {"color": color})
        self.add("stroke.set", {"weight": pt(stroke_mm), "cap": cap})
        out_idx = self.add("object.path.outlineStroke")
        return f"${out_idx}.ids[0]"

    def text_outlined(
        self,
        x_mm: float,
        y_baseline_mm: float,
        text: str,
        font: str,
        style: str,
        size_mm: float,
        color: str,
        justify: str = "center",
        tracking: int | None = None,
    ) -> str:
        idx = self.add(
            "text.create",
            {
                "x": pt(x_mm),
                "y": pt(y_baseline_mm),
                "text": text,
                "font": font,
                "style": style,
                "size": pt(size_mm),
                "color": color,
                "justify": justify,
            },
        )
        if tracking is not None:
            self.add("text.setStyle", {"id": f"${idx}.id", "tracking": tracking})
        out_idx = self.add("type.createOutlines")
        return f"${out_idx}.ids[0]"

    def minus_front(self, back_id: str, front_id: str) -> str:
        idx = self.add(
            "object.pathfinder.minusFront",
            {"ids": [back_id, front_id]},
        )
        return f"${idx}.ids[0]"

    def write_commands(self, path: Path) -> Path:
        """Write accumulated batch steps as UTF-8 JSON, creating parent dirs."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.steps, indent=2) + "\n", encoding="utf-8")
        return path


def chamfer_rect_points(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    tl: float = 0.0,
    tr: float = 0.0,
    br: float = 0.0,
    bl: float = 0.0,
) -> list[tuple[float, float]]:
    """Return clockwise polygon vertices for a chamfered rectangle."""
    w = x1 - x0
    h = y1 - y0
    if w <= 0.0 or h <= 0.0:
        raise ValueError(
            f"Rectangle bounds must have positive size: ({x0}, {y0}) -> ({x1}, {y1})"
        )
    if min(tl, tr, br, bl) < 0.0:
        raise ValueError("Chamfer sizes must be non-negative")
    if tl + tr > w or bl + br > w or tl + bl > h or tr + br > h:
        raise ValueError(
            f"Chamfers exceed rectangle dimensions ({w}x{h}): "
            f"tl={tl}, tr={tr}, br={br}, bl={bl}"
        )

    pts: list[tuple[float, float]] = []
    if tl > 0.0:
        pts.extend([(x0, y0 + tl), (x0 + tl, y0)])
    else:
        pts.append((x0, y0))
    if tr > 0.0:
        pts.extend([(x1 - tr, y0), (x1, y0 + tr)])
    else:
        pts.append((x1, y0))
    if br > 0.0:
        pts.extend([(x1, y1 - br), (x1 - br, y1)])
    else:
        pts.append((x1, y1))
    if bl > 0.0:
        pts.extend([(x0 + bl, y1), (x0, y1 - bl)])
    else:
        pts.append((x0, y1))

    deduped: list[tuple[float, float]] = []
    for p in pts:
        if not deduped or p != deduped[-1]:
            deduped.append(p)
    if len(deduped) > 1 and deduped[-1] == deduped[0]:
        deduped.pop()
    return deduped


def regular_polygon_points(
    cx: float, cy: float, radius: float, sides: int, rot_deg: float = 0.0
) -> list[tuple[float, float]]:
    """Return vertices for a regular polygon centered at (cx, cy)."""
    if sides < 3:
        raise ValueError(f"Regular polygon requires at least 3 sides, got {sides}")
    if radius <= 0.0:
        raise ValueError(f"Regular polygon radius must be positive, got {radius}")
    pts: list[tuple[float, float]] = []
    for k in range(sides):
        ang = math.radians(rot_deg + k * (360.0 / sides))
        pts.append((cx + radius * math.cos(ang), cy + radius * math.sin(ang)))
    return pts


def init_panel_document(
    sb: StepBuilder, spec: dict[str, Any], title: str
) -> dict[str, str]:
    """Create a 1:1 mm VectorCraft document and standard 5-layer stack."""
    canvas = spec["canvas"]
    width_mm = float(canvas["width_mm"])
    height_mm = float(canvas["height_mm"])

    sb.add(
        "file.new",
        {
            "title": title,
            "width": f"{width_mm} mm",
            "height": f"{height_mm} mm",
            "units": "Millimeters",
            "alignNewObjectsToPixelGrid": False,
            "colorMode": "rgb",
            "rasterEffectsPpi": 300,
        },
    )
    return {
        "mockup": sb.new_layer("00_Board_Mockup", "#3f444e"),
        "mask": sb.new_layer("01_F_Mask_Gold", "#d8b154"),
        "silks": sb.new_layer("02_F_SilkS_White", "#ffffff"),
        "reg": sb.new_layer("03_Registration_Frame", "#00ff88"),
        "keepout": sb.new_layer("04_Hardware_Keepouts", "#00d4ff"),
    }


def populate_mockup_layer(
    sb: StepBuilder, lyr_mockup: str, spec: dict[str, Any]
) -> None:
    """Populate the Matte Black FR4 background and drilled hole cutouts."""
    canvas = spec["canvas"]
    width_mm = float(canvas["width_mm"])
    height_mm = float(canvas["height_mm"])

    sb.set_current_layer(lyr_mockup)
    sb.rect_fill(0.0, 0.0, width_mm, height_mm, COLOR_FR4_BG)
    sb.rect_stroke_outlined(
        0.0, 0.0, width_mm, height_mm, 0.18, COLOR_FR4_RIM, align="inside"
    )

    for slot in spec.get("mounting_slots", []):
        sw, sh = float(slot["width_mm"]), float(slot["height_mm"])
        sx = float(slot["local_x"]) - sw / 2.0
        sy = float(slot["local_y"]) - sh / 2.0
        sb.rect_fill(sx, sy, sw, sh, COLOR_DRILL_FILL, radius_mm=sh / 2.0)
        sb.rect_stroke_outlined(
            sx,
            sy,
            sw,
            sh,
            0.14,
            COLOR_DRILL_RIM,
            align="outside",
            radius_mm=sh / 2.0,
        )

    for comp in spec.get("components", []):
        cx = float(comp["local_x"])
        cy = float(comp["local_y"])
        drill = float(comp["drill_mm"])
        is_led = str(comp.get("kind", "")).startswith("led")
        sb.circle_fill(cx, cy, drill, COLOR_DRILL_FILL)
        rim_col = "#2f5a3f" if is_led else COLOR_DRILL_RIM
        sb.circle_stroke_keepout(
            cx, cy, drill + 0.16, rim_col, stroke_mm=0.14, dash_mm=None, opacity=95
        )
        if is_led:
            sb.circle_fill(cx, cy, max(1.0, drill - 1.0), "#1c3322")


def populate_registration_layer(
    sb: StepBuilder, lyr_reg: str, spec: dict[str, Any]
) -> None:
    """Add an inside-aligned 0.05 mm registration rectangle matching Edge.Cuts."""
    canvas = spec["canvas"]
    width_mm = float(canvas["width_mm"])
    height_mm = float(canvas["height_mm"])

    sb.set_current_layer(lyr_reg)
    sb.rect_stroke_outlined(
        0.0,
        0.0,
        width_mm,
        height_mm,
        0.05,
        COLOR_SILK_PREVIEW,
        align="inside",
        join="miter",
    )


def populate_keepout_layer(
    sb: StepBuilder, lyr_keepout: str, spec: dict[str, Any]
) -> None:
    """Draw rail, M3 washer, F.Cu pullback, nut, and max-knob keepout overlays."""
    canvas = spec["canvas"]
    width_mm = float(canvas["width_mm"])
    height_mm = float(canvas["height_mm"])
    pullback_mm = float(
        spec.get("fabrication_rules", {}).get("copper_edge_pullback_mm", 0.60)
    )

    sb.set_current_layer(lyr_keepout)

    for band in canvas.get("rail_keepout_y_mm", {}).values():
        y0, y1 = float(band[0]), float(band[1])
        sb.rect_stroke_keepout(
            0.0,
            y0,
            width_mm,
            y1 - y0,
            "#ff33aa",
            stroke_mm=0.14,
            dash_mm=(0.7, 0.4),
            opacity=80,
        )

    for slot in spec.get("mounting_slots", []):
        hx = float(slot["local_x"])
        hy = float(slot["local_y"])
        sw = float(slot["width_mm"])
        sh = float(slot["height_mm"])
        washer_d = 7.0
        sweep_w = (sw - sh) + washer_d
        sb.rect_stroke_keepout(
            hx - sweep_w / 2.0,
            hy - washer_d / 2.0,
            sweep_w,
            washer_d,
            "#ff33aa",
            stroke_mm=0.15,
            dash_mm=(0.45, 0.30),
            radius_mm=washer_d / 2.0,
            opacity=90,
        )

    sb.rect_stroke_keepout(
        pullback_mm,
        pullback_mm,
        width_mm - 2.0 * pullback_mm,
        height_mm - 2.0 * pullback_mm,
        "#44ff66",
        stroke_mm=0.13,
        dash_mm=(0.60, 0.40),
        opacity=75,
    )

    for comp in spec.get("components", []):
        cx = float(comp["local_x"])
        cy = float(comp["local_y"])
        drill = float(comp["drill_mm"])
        keepout = float(comp["keepout_mm"])
        if not comp.get("grounded", True):
            npth_d = drill + 1.0
            sb.circle_stroke_keepout(
                cx,
                cy,
                npth_d,
                "#44ff66",
                stroke_mm=0.14,
                dash_mm=(0.35, 0.25),
                opacity=85,
            )
        sb.circle_stroke_keepout(
            cx, cy, keepout, "#ffaa00", stroke_mm=0.14, dash_mm=(0.45, 0.30), opacity=85
        )
        if comp.get("max_knob_mm"):
            sb.circle_stroke_keepout(
                cx,
                cy,
                float(comp["max_knob_mm"]),
                "#00d4ff",
                stroke_mm=0.15,
                dash_mm=(0.60, 0.35),
                opacity=85,
            )


def append_standard_exports(
    sb: StepBuilder,
    layers: dict[str, str],
    out_dir: Path,
    vc_stem: str = "panel",
) -> None:
    """Append standard VectorCraft, preview PNG, raw SVG, and 40 px/mm audit exports."""
    lyr_mockup = layers["mockup"]
    lyr_mask = layers["mask"]
    lyr_silks = layers["silks"]
    lyr_reg = layers["reg"]
    lyr_keepout = layers["keepout"]

    sb.set_layer_visible(lyr_mockup, True)
    sb.set_layer_visible(lyr_mask, True)
    sb.set_layer_visible(lyr_silks, True)
    sb.set_layer_visible(lyr_reg, False)
    sb.set_layer_visible(lyr_keepout, False)
    sb.add(
        "document.export",
        {
            "path": str(out_dir / f"{vc_stem}.vectorcraft"),
            "format": "vectorcraft",
            "pdfCompatible": True,
        },
    )
    sb.add(
        "document.export",
        {
            "path": str(out_dir / "preview_clean.png"),
            "format": "png",
            "ppi": 600,
            "background": "transparent",
        },
    )

    sb.set_layer_visible(lyr_keepout, True)
    sb.add(
        "document.export",
        {
            "path": str(out_dir / "preview_keepouts.png"),
            "format": "png",
            "ppi": 600,
            "background": "transparent",
        },
    )

    sb.set_layer_visible(lyr_mockup, False)
    sb.set_layer_visible(lyr_mask, False)
    sb.set_layer_visible(lyr_keepout, False)
    sb.set_layer_visible(lyr_silks, True)
    sb.set_layer_visible(lyr_reg, True)
    sb.add(
        "document.export",
        {
            "path": str(out_dir / "front_silkscreen.raw.svg"),
            "format": "svg",
            "decimals": 5,
            "outlineText": True,
            "hiddenLayers": False,
        },
    )

    sb.set_layer_visible(lyr_silks, False)
    sb.set_layer_visible(lyr_mask, True)
    sb.add(
        "document.export",
        {
            "path": str(out_dir / "front_soldermask.raw.svg"),
            "format": "svg",
            "decimals": 5,
            "outlineText": True,
            "hiddenLayers": False,
        },
    )

    sb.set_layer_visible(lyr_reg, False)
    sb.set_layer_visible(lyr_mask, False)
    sb.set_layer_visible(lyr_silks, True)
    sb.add(
        "document.export",
        {
            "path": str(out_dir / "_audit_silks.png"),
            "format": "png",
            "ppi": AUDIT_PPI,
            "background": "black",
            "antiAlias": "none",
        },
    )

    sb.set_layer_visible(lyr_silks, False)
    sb.set_layer_visible(lyr_mask, True)
    sb.add(
        "document.export",
        {
            "path": str(out_dir / "_audit_mask.png"),
            "format": "png",
            "ppi": AUDIT_PPI,
            "background": "black",
            "antiAlias": "none",
        },
    )
