#!/usr/bin/env python3
"""Normalize pt-unit panel SVGs to 1:1 mm Plain SVGs and run pixel-exact clearance audits."""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from typing import Any

PT_TO_MM = 25.4 / 72.0

_SVG_NUM_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_SVG_CMD_CHARS = frozenset("MmLlHhVvCcSsQqTtAaZz")
_NON_RENDERED_TAGS = frozenset(
    {
        "defs",
        "clipPath",
        "mask",
        "symbol",
        "pattern",
        "marker",
        "metadata",
        "title",
        "desc",
        "style",
    }
)
_GEOM_TAGS = frozenset({"path", "polygon", "polyline", "rect", "circle", "ellipse"})


class _SvgPathReader:
    """Cursor-based SVG path d-string tokenizer supporting compact arc flags."""

    def __init__(self, d: str) -> None:
        self.d = d
        self.pos = 0
        self.n = len(d)

    def skip_sep(self) -> None:
        while self.pos < self.n and self.d[self.pos] in " \t\r\n,":
            self.pos += 1

    def eof(self) -> bool:
        self.skip_sep()
        return self.pos >= self.n

    def peek_cmd(self) -> str | None:
        self.skip_sep()
        if self.pos < self.n and self.d[self.pos] in _SVG_CMD_CHARS:
            return self.d[self.pos]
        return None

    def read_cmd(self) -> str:
        self.skip_sep()
        ch = self.d[self.pos]
        self.pos += 1
        return ch

    def has_arg(self) -> bool:
        return not self.eof() and self.peek_cmd() is None

    def read_number(self) -> float:
        self.skip_sep()
        m = _SVG_NUM_RE.match(self.d, self.pos)
        if not m:
            raise ValueError(
                f"Expected SVG path number near pos {self.pos}: {self.d[self.pos : self.pos + 24]!r}"
            )
        self.pos = m.end()
        return float(m.group(0))

    def read_flag(self) -> int:
        self.skip_sep()
        if self.pos >= self.n or self.d[self.pos] not in ("0", "1"):
            raise ValueError(
                f"Expected SVG arc flag ('0' or '1') near pos {self.pos}: "
                f"{self.d[self.pos : self.pos + 24]!r}"
            )
        val = int(self.d[self.pos])
        self.pos += 1
        return val


def load_panel_spec(spec_path: pathlib.Path) -> dict[str, Any]:
    """Extract the machine-readable JSON geometry block from panel_svg_spec.md."""
    text = spec_path.read_text(encoding="utf-8")
    match = re.search(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
    if not match:
        raise RuntimeError(f"Could not locate JSON geometry block in {spec_path}")
    return json.loads(match.group(1))


def _fmt_mm(val: float) -> str:
    txt = f"{val:.4f}".rstrip("0").rstrip(".")
    return "0" if txt in ("", "-0") else txt


def _scale_path_d(d: str, scale: float) -> tuple[str, list[tuple[float, float]]]:
    """Scale every coordinate in an SVG path d-string by `scale`."""
    reader = _SvgPathReader(d)
    out: list[str] = []
    pts_seen: list[tuple[float, float]] = []

    cmd = ""
    cx = 0.0
    cy = 0.0
    sx = 0.0
    sy = 0.0

    while not reader.eof():
        if reader.peek_cmd() is not None:
            cmd = reader.read_cmd()
            if cmd in ("Z", "z"):
                out.append(cmd)
                cx, cy = sx, sy
                continue
        if not cmd:
            raise ValueError(
                f"Malformed SVG path data near pos {reader.pos}: {d[reader.pos : reader.pos + 24]!r}"
            )

        upper = cmd.upper()
        rel = cmd.islower()

        if upper in ("M", "L", "T"):
            first = True
            while reader.has_arg():
                x = reader.read_number() * scale
                y = reader.read_number() * scale
                if rel:
                    cx += x
                    cy += y
                else:
                    cx, cy = x, y
                if upper == "M" and first:
                    sx, sy = cx, cy
                    op = "m" if rel else "M"
                    first = False
                elif upper == "M":
                    op = "l" if rel else "L"
                else:
                    op = cmd
                pts_seen.append((cx, cy))
                out.append(f"{op}{_fmt_mm(x)} {_fmt_mm(y)}")
        elif upper == "H":
            while reader.has_arg():
                x = reader.read_number() * scale
                cx = cx + x if rel else x
                pts_seen.append((cx, cy))
                out.append(f"{cmd}{_fmt_mm(x)}")
        elif upper == "V":
            while reader.has_arg():
                y = reader.read_number() * scale
                cy = cy + y if rel else y
                pts_seen.append((cx, cy))
                out.append(f"{cmd}{_fmt_mm(y)}")
        elif upper == "C":
            while reader.has_arg():
                vals = [reader.read_number() * scale for _ in range(6)]
                if rel:
                    pts_seen.extend(
                        [
                            (cx + vals[0], cy + vals[1]),
                            (cx + vals[2], cy + vals[3]),
                            (cx + vals[4], cy + vals[5]),
                        ]
                    )
                    cx += vals[4]
                    cy += vals[5]
                else:
                    pts_seen.extend(
                        [(vals[0], vals[1]), (vals[2], vals[3]), (vals[4], vals[5])]
                    )
                    cx, cy = vals[4], vals[5]
                out.append(f"{cmd}" + " ".join(_fmt_mm(v) for v in vals))
        elif upper in ("S", "Q"):
            while reader.has_arg():
                vals = [reader.read_number() * scale for _ in range(4)]
                if rel:
                    pts_seen.extend(
                        [(cx + vals[0], cy + vals[1]), (cx + vals[2], cy + vals[3])]
                    )
                    cx += vals[2]
                    cy += vals[3]
                else:
                    pts_seen.extend([(vals[0], vals[1]), (vals[2], vals[3])])
                    cx, cy = vals[2], vals[3]
                out.append(f"{cmd}" + " ".join(_fmt_mm(v) for v in vals))
        elif upper == "A":
            while reader.has_arg():
                rx = reader.read_number() * scale
                ry = reader.read_number() * scale
                xrot = reader.read_number()
                large = reader.read_flag()
                sweep = reader.read_flag()
                x = reader.read_number() * scale
                y = reader.read_number() * scale
                if rel:
                    cx += x
                    cy += y
                else:
                    cx, cy = x, y
                pts_seen.append((cx, cy))
                out.append(
                    f"{cmd}{_fmt_mm(rx)} {_fmt_mm(ry)} {_fmt_mm(xrot)} "
                    f"{large} {sweep} {_fmt_mm(x)} {_fmt_mm(y)}"
                )
        else:
            raise ValueError(f"Unsupported SVG path command {cmd}")

    return " ".join(out), pts_seen


def _scale_points_attr(
    points_str: str, scale: float
) -> tuple[str, list[tuple[float, float]]]:
    nums = [
        float(v)
        for v in re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", points_str)
    ]
    if len(nums) % 2 != 0:
        raise ValueError(f"Odd coordinate count in points attribute: {points_str}")
    pts: list[tuple[float, float]] = []
    formatted: list[str] = []
    for k in range(0, len(nums), 2):
        x = nums[k] * scale
        y = nums[k + 1] * scale
        pts.append((x, y))
        formatted.append(f"{_fmt_mm(x)},{_fmt_mm(y)}")
    return " ".join(formatted), pts


def _is_registration_bbox(
    bbox: tuple[float, float, float, float], width_mm: float, height_mm: float
) -> bool:
    return (
        abs(bbox[0]) < 0.05
        and abs(bbox[1]) < 0.05
        and abs(bbox[2] - width_mm) < 0.05
        and abs(bbox[3] - height_mm) < 0.05
    )


def _parse_style(style_str: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in style_str.split(";"):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        k_clean = k.strip().lower()
        if k_clean:
            out[k_clean] = v.strip()
    return out


def _is_hidden(elem: ET.Element, style_map: dict[str, str]) -> bool:
    disp = elem.attrib.get("display", style_map.get("display", "")).strip().lower()
    vis = elem.attrib.get("visibility", style_map.get("visibility", "")).strip().lower()
    return disp == "none" or vis == "hidden"


def _iter_rendered_elements(elem: ET.Element) -> Iterator[ET.Element]:
    """Yield rendered SVG elements, pruning defs/clipPath/hidden subtrees."""
    tag = elem.tag.split("}")[-1]
    if tag in _NON_RENDERED_TAGS:
        return
    style_map = _parse_style(elem.attrib.get("style", ""))
    if _is_hidden(elem, style_map):
        return
    yield elem
    for child in elem:
        yield from _iter_rendered_elements(child)


def normalize_svg_to_mm(
    raw_svg: pathlib.Path,
    out_svg: pathlib.Path,
    fill_hex: str,
    width_mm: float,
    height_mm: float,
    *,
    scale: float = PT_TO_MM,
) -> dict[str, Any]:
    """Convert pt-viewBox SVG to a 1:1 mm Plain SVG and validate paths-only."""
    svg_ns = "http://www.w3.org/2000/svg"
    ET.register_namespace("", svg_ns)

    tree = ET.parse(raw_svg)
    root = tree.getroot()

    root.attrib["width"] = f"{width_mm:.2f}mm"
    root.attrib["height"] = f"{height_mm:.2f}mm"
    root.attrib["viewBox"] = f"0 0 {width_mm:.2f} {height_mm:.2f}"
    for k in list(root.attrib):
        if "xlink" in k:
            del root.attrib[k]

    text_count = 0
    stroked_count = 0
    element_count = 0
    reg_frame_bbox: tuple[float, float, float, float] | None = None

    for elem in _iter_rendered_elements(root):
        tag = elem.tag.split("}")[-1]
        if tag in ("text", "tspan", "textPath"):
            text_count += 1
        if "transform" in elem.attrib:
            raise RuntimeError(
                f"Unexpected transform attribute on <{tag}> in {raw_svg}: "
                f"{elem.attrib['transform']}"
            )

        style_map = _parse_style(elem.attrib.get("style", ""))
        fill_val = elem.attrib.get("fill", style_map.get("fill", "")).strip().lower()
        stroke_val = (
            elem.attrib.get("stroke", style_map.get("stroke", "none")).strip().lower()
        )

        bbox: tuple[float, float, float, float] | None = None
        if tag == "path" and "d" in elem.attrib:
            element_count += 1
            scaled_d, pts = _scale_path_d(elem.attrib["d"], scale)
            elem.attrib["d"] = scaled_d
            if pts:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                bbox = (min(xs), min(ys), max(xs), max(ys))
        elif tag in ("polygon", "polyline") and "points" in elem.attrib:
            element_count += 1
            scaled_pts, _ = _scale_points_attr(elem.attrib["points"], scale)
            elem.attrib["points"] = scaled_pts
        elif tag == "rect":
            element_count += 1
            for attr in ("x", "y", "width", "height", "rx", "ry"):
                if attr in elem.attrib:
                    elem.attrib[attr] = _fmt_mm(float(elem.attrib[attr]) * scale)
            rx = float(elem.attrib.get("x", "0"))
            ry = float(elem.attrib.get("y", "0"))
            rw = float(elem.attrib.get("width", "0"))
            rh = float(elem.attrib.get("height", "0"))
            bbox = (rx, ry, rx + rw, ry + rh)
        elif tag == "circle":
            element_count += 1
            for attr in ("cx", "cy", "r"):
                if attr in elem.attrib:
                    elem.attrib[attr] = _fmt_mm(float(elem.attrib[attr]) * scale)
        elif tag == "ellipse":
            element_count += 1
            for attr in ("cx", "cy", "rx", "ry"):
                if attr in elem.attrib:
                    elem.attrib[attr] = _fmt_mm(float(elem.attrib[attr]) * scale)

        is_reg = (tag in _GEOM_TAGS) and (
            elem.attrib.get("id") == "registration_frame"
            or (bbox is not None and _is_registration_bbox(bbox, width_mm, height_mm))
        )
        if is_reg:
            elem.attrib["id"] = "registration_frame"
            reg_frame_bbox = (
                bbox if bbox is not None else (0.0, 0.0, width_mm, height_mm)
            )
            if fill_val == "none":
                elem.attrib["fill"] = "none"
                elem.attrib["stroke"] = "#000000"
                elem.attrib["stroke-width"] = "0.05"
                for k in ("fill", "stroke", "stroke-width"):
                    style_map.pop(k, None)
            else:
                for k in (
                    "stroke",
                    "stroke-width",
                    "stroke-miterlimit",
                    "stroke-linecap",
                    "stroke-linejoin",
                ):
                    elem.attrib.pop(k, None)
                    style_map.pop(k, None)
                elem.attrib["fill"] = fill_hex
                style_map.pop("fill", None)
        else:
            if stroke_val not in ("none", ""):
                stroked_count += 1
            for k in (
                "stroke",
                "stroke-width",
                "stroke-miterlimit",
                "stroke-linecap",
                "stroke-linejoin",
            ):
                elem.attrib.pop(k, None)
                style_map.pop(k, None)
            if tag in _GEOM_TAGS:
                elem.attrib["fill"] = "none" if fill_val == "none" else fill_hex
                style_map.pop("fill", None)

        if "style" in elem.attrib:
            if style_map:
                elem.attrib["style"] = ";".join(
                    f"{k}:{v}" for k, v in style_map.items()
                )
            else:
                del elem.attrib["style"]

    if text_count > 0:
        raise RuntimeError(f"{raw_svg} still contains {text_count} live text nodes!")
    if stroked_count > 0:
        raise RuntimeError(
            f"{raw_svg} still contains {stroked_count} stroked elements!"
        )
    if reg_frame_bbox is None:
        raise RuntimeError(
            f"{raw_svg} is missing the 0..{width_mm} x 0..{height_mm} mm registration frame!"
        )

    for child in list(root):
        if child.tag.split("}")[-1] == "title":
            root.remove(child)

    out_svg.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(out_svg, encoding="utf-8", xml_declaration=True)
    return {
        "out_svg": str(out_svg),
        "elements": element_count,
        "text_nodes": text_count,
        "stroked_nodes": stroked_count,
        "registration_bbox_mm": [round(v, 5) for v in reg_frame_bbox],
    }


def _load_mask_bitmap(
    path: pathlib.Path,
    expected_w: int,
    expected_h: int,
    *,
    polarity: str = "auto",
):
    import numpy as np
    from PIL import Image

    img = Image.open(path)
    if img.size != (expected_w, expected_h):
        raise RuntimeError(
            f"Expected audit bitmap {expected_w}x{expected_h}, got {img.size} for {path}"
        )
    if "A" in img.getbands():
        rgba = np.asarray(img.convert("RGBA"))
        alpha = rgba[:, :, 3]
        if int(alpha.min()) < 250:
            return alpha > 40

    rgb = np.asarray(img.convert("RGB"))
    resolved = polarity
    if resolved == "auto":
        border = np.concatenate(
            [rgb[0, :, :], rgb[-1, :, :], rgb[:, 0, :], rgb[:, -1, :]], axis=0
        )
        resolved = (
            "dark-on-light" if float(np.median(border)) > 200.0 else "light-on-dark"
        )
    if resolved == "dark-on-light":
        return rgb.min(axis=2) < 215
    return rgb.max(axis=2) > 40


def _dilate_disk(mask, radius_px: int):
    """Fast binary dilation by circular disk using active-bbox integer-offset OR shifts."""
    import numpy as np

    h, w = mask.shape
    out = np.zeros_like(mask)
    ys_nz, xs_nz = np.nonzero(mask)
    if len(ys_nz) == 0:
        return out
    my0, my1 = int(ys_nz.min()), int(ys_nz.max()) + 1
    mx0, mx1 = int(xs_nz.min()), int(xs_nz.max()) + 1
    sub = mask[my0:my1, mx0:mx1]

    r2 = radius_px * radius_px
    for dy in range(-radius_px, radius_px + 1):
        dy_y0 = my0 + dy
        dy_y1 = my1 + dy
        if dy_y1 <= 0 or dy_y0 >= h:
            continue
        clip_top = max(0, -dy_y0)
        clip_bot = max(0, dy_y1 - h)
        sy0 = clip_top
        sy1 = (my1 - my0) - clip_bot
        ty0 = dy_y0 + clip_top
        ty1 = dy_y1 - clip_bot
        for dx in range(-radius_px, radius_px + 1):
            if dx * dx + dy * dy > r2:
                continue
            dx_x0 = mx0 + dx
            dx_x1 = mx1 + dx
            if dx_x1 <= 0 or dx_x0 >= w:
                continue
            clip_left = max(0, -dx_x0)
            clip_right = max(0, dx_x1 - w)
            sx0 = clip_left
            sx1 = (mx1 - mx0) - clip_right
            tx0 = dx_x0 + clip_left
            tx1 = dx_x1 - clip_right
            out[ty0:ty1, tx0:tx1] |= sub[sy0:sy1, sx0:sx1]
    return out


def _capsule_mask(
    yy,
    xx,
    x0: float,
    x1: float,
    y0: float,
    radius_mm: float,
):
    import numpy as np

    clamped_x = np.clip(xx, x0, x1)
    return (xx - clamped_x) ** 2 + (yy - y0) ** 2 <= radius_mm**2


def run_clearance_audit(
    spec: dict[str, Any],
    silks_png: pathlib.Path,
    mask_png: pathlib.Path,
    *,
    px_per_mm: float = 40.0,
    min_silk_mask_gap_mm: float = 0.20,
    edge_silk_inset_mm: float = 0.50,
    edge_mask_pullback_mm: float = 0.60,
    washer_radius_mm: float = 3.50,
    polarity: str = "auto",
    allow_empty: bool = False,
    check_pot_nut_keepout: bool = True,
) -> dict[str, Any]:
    """Run pixel-exact clearance checks across F.SilkS and F.Mask bitmaps."""
    import numpy as np

    canvas = spec["canvas"]
    width_mm = float(canvas["width_mm"])
    height_mm = float(canvas["height_mm"])
    expected_w = round(width_mm * px_per_mm)
    expected_h = round(height_mm * px_per_mm)

    silks_raw = _load_mask_bitmap(silks_png, expected_w, expected_h, polarity=polarity)
    mask_raw = _load_mask_bitmap(mask_png, expected_w, expected_h, polarity=polarity)

    h_px, w_px = silks_raw.shape
    xs_mm = (np.arange(w_px, dtype=np.float32) + 0.5) / px_per_mm
    ys_mm = (np.arange(h_px, dtype=np.float32) + 0.5) / px_per_mm
    yy, xx = np.meshgrid(ys_mm, xs_mm, indexing="ij")

    errors: list[str] = []
    silks_px = int(np.count_nonzero(silks_raw))
    mask_px = int(np.count_nonzero(mask_raw))
    metrics: dict[str, Any] = {
        "px_per_mm": px_per_mm,
        "silks_foreground_px": silks_px,
        "mask_foreground_px": mask_px,
    }
    if not allow_empty:
        if silks_px == 0:
            errors.append(
                "F.SilkS audit bitmap is empty (0 foreground pixels); check render/polarity."
            )
        if mask_px == 0:
            errors.append(
                "F.Mask audit bitmap is empty (0 foreground pixels); check render/polarity."
            )

    direct_overlap = int(np.count_nonzero(silks_raw & mask_raw))
    search_px = max(1, math.ceil(max(0.60, min_silk_mask_gap_mm) * px_per_mm) + 1)
    if direct_overlap > 0:
        min_gap_mm = 0.0
    else:
        lo, hi = 1, search_px - 1
        hit_rad: int | None = None
        while lo <= hi:
            mid = (lo + hi) // 2
            if bool(np.any(silks_raw & _dilate_disk(mask_raw, mid))):
                hit_rad = mid
                hi = mid - 1
            else:
                lo = mid + 1
        if hit_rad is not None:
            min_gap_mm = round((hit_rad - 1) / px_per_mm, 3)
        else:
            min_gap_mm = round((search_px - 1) / px_per_mm, 3)

    metrics["silk_to_mask_overlap_px"] = direct_overlap
    metrics["silk_to_mask_min_gap_mm"] = min_gap_mm
    if direct_overlap > 0 or min_gap_mm < min_silk_mask_gap_mm:
        errors.append(
            f"F.SilkS to F.Mask clearance too small: {min_gap_mm} mm "
            f"(direct overlap {direct_overlap} px, min {min_silk_mask_gap_mm} mm)"
        )

    edge_mask_zone = (
        (xx < edge_mask_pullback_mm)
        | (xx > width_mm - edge_mask_pullback_mm)
        | (yy < edge_mask_pullback_mm)
        | (yy > height_mm - edge_mask_pullback_mm)
    )
    edge_silk_zone = (
        (xx < edge_silk_inset_mm)
        | (xx > width_mm - edge_silk_inset_mm)
        | (yy < edge_silk_inset_mm)
        | (yy > height_mm - edge_silk_inset_mm)
    )
    mask_edge_hits = int(np.count_nonzero(mask_raw & edge_mask_zone))
    silk_edge_hits = int(np.count_nonzero(silks_raw & edge_silk_zone))
    metrics["mask_edge_pullback_violations_px"] = mask_edge_hits
    metrics["silk_edge_inset_violations_px"] = silk_edge_hits
    if mask_edge_hits:
        errors.append(
            f"F.Mask violates {edge_mask_pullback_mm:.2f} mm edge pullback ({mask_edge_hits} px)"
        )
    if silk_edge_hits:
        errors.append(
            f"F.SilkS violates {edge_silk_inset_mm:.2f} mm edge inset ({silk_edge_hits} px)"
        )

    for s in spec.get("mounting_slots", []):
        ref = s["ref"]
        hx = float(s["local_x"])
        hy = float(s["local_y"])
        sw = float(s["width_mm"])
        sh = float(s["height_mm"])
        x0 = hx - (sw - sh) / 2.0
        x1 = hx + (sw - sh) / 2.0
        washer_zone = _capsule_mask(yy, xx, x0, x1, hy, washer_radius_mm)
        m_hits = int(np.count_nonzero(mask_raw & washer_zone))
        s_hits = int(np.count_nonzero(silks_raw & washer_zone))
        metrics[f"{ref}_washer_mask_hits_px"] = m_hits
        metrics[f"{ref}_washer_silk_hits_px"] = s_hits
        if m_hits or s_hits:
            errors.append(
                f"{ref} M3 washer overlap: mask={m_hits} px, silk={s_hits} px"
            )

    for comp in spec.get("components", []):
        ref = comp["ref"]
        cx = float(comp["local_x"])
        cy = float(comp["local_y"])
        drill = float(comp["drill_mm"])
        keepout = float(comp["keepout_mm"])
        grounded = bool(comp.get("grounded", True))
        dist2 = (xx - cx) ** 2 + (yy - cy) ** 2

        if not grounded:
            npth_r = drill / 2.0 + 0.50
            bezel_r = keepout / 2.0
            npth_zone = dist2 <= npth_r**2
            bezel_zone = dist2 <= bezel_r**2
            m_hits = int(np.count_nonzero(mask_raw & npth_zone))
            s_hits = int(np.count_nonzero(silks_raw & bezel_zone))
            metrics[f"{ref}_npth_mask_hits_px"] = m_hits
            metrics[f"{ref}_bezel_silk_hits_px"] = s_hits
            if m_hits:
                errors.append(
                    f"{ref} F.Mask inside {npth_r:.2f} mm NPTH pullback ({m_hits} px)"
                )
            if s_hits:
                errors.append(
                    f"{ref} F.SilkS inside {bezel_r:.2f} mm bezel keepout ({s_hits} px)"
                )
        else:
            drill_zone = dist2 <= (drill / 2.0 + 0.25) ** 2
            m_hits = int(np.count_nonzero(mask_raw & drill_zone))
            s_hits = int(np.count_nonzero(silks_raw & drill_zone))
            if m_hits or s_hits:
                errors.append(
                    f"{ref} hole keepout overlap: mask={m_hits} px, silk={s_hits} px"
                )

            nut_kinds = (
                ("switch", "switch_submini", "jack", "pot")
                if check_pot_nut_keepout
                else ("switch", "switch_submini", "jack")
            )
            if comp.get("kind") in nut_kinds:
                nut_zone = dist2 <= (keepout / 2.0) ** 2
                nm_hits = int(np.count_nonzero(mask_raw & nut_zone))
                ns_hits = int(np.count_nonzero(silks_raw & nut_zone))
                metrics[f"{ref}_nut_mask_hits_px"] = nm_hits
                metrics[f"{ref}_nut_silk_hits_px"] = ns_hits
                if nm_hits or ns_hits:
                    errors.append(
                        f"{ref} nut keepout ({keepout} mm) overlap: "
                        f"mask={nm_hits} px, silk={ns_hits} px"
                    )

    if errors:
        raise RuntimeError("Clearance audit FAILED:\n  - " + "\n  - ".join(errors))
    return metrics


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Normalize panel SVGs to 1:1 mm Plain SVGs and run clearance audits."
    )
    parser.add_argument(
        "--spec-md",
        type=pathlib.Path,
        required=True,
        help="Path to panel_svg_spec.md generated by generate_eurorack_panel.py --spec-md.",
    )
    parser.add_argument(
        "--normalize-silks",
        nargs=2,
        type=pathlib.Path,
        metavar=("IN_SVG", "OUT_SVG"),
        default=None,
        help="Convert raw pt-unit F.SilkS SVG to 1:1 mm Plain SVG.",
    )
    parser.add_argument(
        "--normalize-mask",
        nargs=2,
        type=pathlib.Path,
        metavar=("IN_SVG", "OUT_SVG"),
        default=None,
        help="Convert raw pt-unit F.Mask SVG to 1:1 mm Plain SVG.",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=PT_TO_MM,
        help=f"Input SVG coordinate scale to mm (default: {PT_TO_MM:.6f} for pt->mm; use 1.0 if already mm).",
    )
    parser.add_argument(
        "--silks-fill",
        default="#000000",
        help="Fill hex color written into normalized F.SilkS SVG (default: #000000).",
    )
    parser.add_argument(
        "--mask-fill",
        default="#C89B3C",
        help="Fill hex color written into normalized F.Mask SVG (default: #C89B3C).",
    )
    parser.add_argument(
        "--audit-silks-png",
        type=pathlib.Path,
        default=None,
        help="Rendered F.SilkS mask PNG for morphological clearance audit.",
    )
    parser.add_argument(
        "--audit-mask-png",
        type=pathlib.Path,
        default=None,
        help="Rendered F.Mask mask PNG for morphological clearance audit.",
    )
    parser.add_argument(
        "--px-per-mm",
        type=float,
        default=40.0,
        help="Audit raster resolution in pixels/mm (default: 40.0 = 1016 ppi).",
    )
    parser.add_argument(
        "--min-silk-mask-gap",
        type=float,
        default=0.20,
        help="Minimum F.SilkS to F.Mask separation in mm (default: 0.20).",
    )
    parser.add_argument(
        "--edge-silk-inset",
        type=float,
        default=0.50,
        help="Minimum F.SilkS inset from Edge.Cuts in mm (default: 0.50).",
    )
    parser.add_argument(
        "--edge-mask-pullback",
        type=float,
        default=0.60,
        help="Minimum F.Mask pullback from Edge.Cuts in mm (default: 0.60).",
    )
    parser.add_argument(
        "--washer-radius",
        type=float,
        default=3.50,
        help="M3 washer keepout radius around mounting slots in mm (default: 3.50).",
    )
    parser.add_argument(
        "--polarity",
        choices=("auto", "light-on-dark", "dark-on-light"),
        default="auto",
        help="Bitmap foreground polarity for opaque audit PNGs (default: auto).",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow an audit PNG with zero foreground pixels without failing.",
    )
    parser.add_argument(
        "--skip-pot-nut-keepout",
        action="store_true",
        help="Skip nut/bezel keepout check for 'pot' components.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if (args.audit_silks_png is None) != (args.audit_mask_png is None):
        raise SystemExit(
            "ERROR: Pass both --audit-silks-png and --audit-mask-png together."
        )
    if (
        args.normalize_silks is None
        and args.normalize_mask is None
        and args.audit_silks_png is None
    ):
        raise SystemExit(
            "ERROR: Specify --normalize-silks, --normalize-mask, and/or --audit-*-png."
        )

    spec = load_panel_spec(args.spec_md)
    w_mm = float(spec["canvas"]["width_mm"])
    h_mm = float(spec["canvas"]["height_mm"])

    report: dict[str, Any] = {}
    if args.normalize_silks is not None:
        in_svg, out_svg = args.normalize_silks
        report["front_silkscreen"] = normalize_svg_to_mm(
            in_svg, out_svg, args.silks_fill, w_mm, h_mm, scale=args.scale
        )
    if args.normalize_mask is not None:
        in_svg, out_svg = args.normalize_mask
        report["front_soldermask"] = normalize_svg_to_mm(
            in_svg, out_svg, args.mask_fill, w_mm, h_mm, scale=args.scale
        )
    if args.audit_silks_png is not None and args.audit_mask_png is not None:
        report["clearance_audit"] = run_clearance_audit(
            spec,
            args.audit_silks_png,
            args.audit_mask_png,
            px_per_mm=args.px_per_mm,
            min_silk_mask_gap_mm=args.min_silk_mask_gap,
            edge_silk_inset_mm=args.edge_silk_inset,
            edge_mask_pullback_mm=args.edge_mask_pullback,
            washer_radius_mm=args.washer_radius,
            polarity=args.polarity,
            allow_empty=args.allow_empty,
            check_pot_nut_keepout=not args.skip_pot_nut_keepout,
        )

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
