#!/usr/bin/env python3
"""Import 1:1 mm Plain SVGs (F.SilkS and/or F.Mask) into a KiCad 10 panel PCB."""

from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterator

KICAD_PYTHON = pathlib.Path(
    "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3"
)

try:
    import pcbnew
except ModuleNotFoundError:
    if KICAD_PYTHON.exists():
        os.execv(str(KICAD_PYTHON), [str(KICAD_PYTHON), *sys.argv])
    raise

BEZIER_TOL_MM = 0.002
BEZIER_MAX_DEPTH = 10

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


_MASK_COLOR_MAP = {
    "black": "Black",
    "matte-black": "Black",
    "green": "Green",
    "white": "White",
    "red": "Red",
    "blue": "Blue",
    "yellow": "Yellow",
    "purple": "Purple",
}
_SILK_COLOR_MAP = {
    "white": "White",
    "black": "Black",
}
_FINISH_MAP = {
    "enig": "ENIG",
    "hasl": "HASL lead free",
}


def _build_stackup_block(
    indent: str, mask_color: str, silk_color: str, finish: str
) -> str:
    return (
        f"{indent}(stackup\n"
        f'{indent}\t(layer "F.SilkS"\n'
        f'{indent}\t\t(type "Top Silk Screen")\n'
        f'{indent}\t\t(color "{silk_color}")\n'
        f"{indent}\t)\n"
        f'{indent}\t(layer "F.Paste"\n'
        f'{indent}\t\t(type "Top Solder Paste")\n'
        f"{indent}\t)\n"
        f'{indent}\t(layer "F.Mask"\n'
        f'{indent}\t\t(type "Top Solder Mask")\n'
        f'{indent}\t\t(color "{mask_color}")\n'
        f"{indent}\t\t(thickness 0.01)\n"
        f"{indent}\t)\n"
        f'{indent}\t(layer "F.Cu"\n'
        f'{indent}\t\t(type "copper")\n'
        f"{indent}\t\t(thickness 0.035)\n"
        f"{indent}\t)\n"
        f'{indent}\t(layer "dielectric 1"\n'
        f'{indent}\t\t(type "core")\n'
        f"{indent}\t\t(thickness 1.51)\n"
        f'{indent}\t\t(material "FR4")\n'
        f"{indent}\t\t(epsilon_r 4.5)\n"
        f"{indent}\t\t(loss_tangent 0.02)\n"
        f"{indent}\t)\n"
        f'{indent}\t(layer "B.Cu"\n'
        f'{indent}\t\t(type "copper")\n'
        f"{indent}\t\t(thickness 0.035)\n"
        f"{indent}\t)\n"
        f'{indent}\t(layer "B.Mask"\n'
        f'{indent}\t\t(type "Bottom Solder Mask")\n'
        f'{indent}\t\t(color "{mask_color}")\n'
        f"{indent}\t\t(thickness 0.01)\n"
        f"{indent}\t)\n"
        f'{indent}\t(layer "B.Paste"\n'
        f'{indent}\t\t(type "Bottom Solder Paste")\n'
        f"{indent}\t)\n"
        f'{indent}\t(layer "B.SilkS"\n'
        f'{indent}\t\t(type "Bottom Silk Screen")\n'
        f'{indent}\t\t(color "{silk_color}")\n'
        f"{indent}\t)\n"
        f'{indent}\t(copper_finish "{finish}")\n'
        f"{indent}\t(dielectric_constraints no)\n"
        f"{indent})\n"
    )


def _point_line_distance(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    dx = bx - ax
    dy = by - ay
    seg_len = math.hypot(dx, dy)
    if seg_len < 1e-9:
        return math.hypot(px - ax, py - ay)
    return abs(dx * (ay - py) - (ax - px) * dy) / seg_len


def _flatten_cubic(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    tol: float = BEZIER_TOL_MM,
    depth: int = 0,
) -> list[tuple[float, float]]:
    d1 = _point_line_distance(p1[0], p1[1], p0[0], p0[1], p3[0], p3[1])
    d2 = _point_line_distance(p2[0], p2[1], p0[0], p0[1], p3[0], p3[1])
    if (d1 <= tol and d2 <= tol) or depth >= BEZIER_MAX_DEPTH:
        return [p3]

    m01 = ((p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5)
    m12 = ((p1[0] + p2[0]) * 0.5, (p1[1] + p2[1]) * 0.5)
    m23 = ((p2[0] + p3[0]) * 0.5, (p2[1] + p3[1]) * 0.5)
    m012 = ((m01[0] + m12[0]) * 0.5, (m01[1] + m12[1]) * 0.5)
    m123 = ((m12[0] + m23[0]) * 0.5, (m12[1] + m23[1]) * 0.5)
    mid = ((m012[0] + m123[0]) * 0.5, (m012[1] + m123[1]) * 0.5)

    left = _flatten_cubic(p0, m01, m012, mid, tol, depth + 1)
    right = _flatten_cubic(mid, m123, m23, p3, tol, depth + 1)
    return left + right


def _flatten_quad(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    tol: float = BEZIER_TOL_MM,
) -> list[tuple[float, float]]:
    c1 = (p0[0] + (2.0 / 3.0) * (p1[0] - p0[0]), p0[1] + (2.0 / 3.0) * (p1[1] - p0[1]))
    c2 = (p2[0] + (2.0 / 3.0) * (p1[0] - p2[0]), p2[1] + (2.0 / 3.0) * (p1[1] - p2[1]))
    return _flatten_cubic(p0, c1, c2, p2, tol)


def _vec_angle(ux: float, uy: float, vx: float, vy: float) -> float:
    dot = ux * vx + uy * vy
    mag = math.hypot(ux, uy) * math.hypot(vx, vy)
    cos_v = max(-1.0, min(1.0, dot / mag)) if mag > 1e-18 else 1.0
    ang = math.acos(cos_v)
    return -ang if (ux * vy - uy * vx) < 0.0 else ang


def _flatten_arc(
    x0: float,
    y0: float,
    rx: float,
    ry: float,
    xrot_deg: float,
    large_arc: int,
    sweep: int,
    x1: float,
    y1: float,
    tol: float = BEZIER_TOL_MM,
) -> list[tuple[float, float]]:
    """Flatten an SVG elliptical arc (W3C F.6.5/F.6.6) into polyline points."""
    if math.hypot(x1 - x0, y1 - y0) < 1e-9:
        return []
    rx = abs(rx)
    ry = abs(ry)
    if rx < 1e-9 or ry < 1e-9:
        return [(x1, y1)]

    phi = math.radians(xrot_deg)
    cos_phi = math.cos(phi)
    sin_phi = math.sin(phi)
    dx2 = (x0 - x1) * 0.5
    dy2 = (y0 - y1) * 0.5
    x1p = cos_phi * dx2 + sin_phi * dy2
    y1p = -sin_phi * dx2 + cos_phi * dy2

    rx2 = rx * rx
    ry2 = ry * ry
    x1p2 = x1p * x1p
    y1p2 = y1p * y1p
    lam = x1p2 / rx2 + y1p2 / ry2
    if lam > 1.0:
        s_lam = math.sqrt(lam)
        rx *= s_lam
        ry *= s_lam
        rx2 = rx * rx
        ry2 = ry * ry

    num = max(0.0, rx2 * ry2 - rx2 * y1p2 - ry2 * x1p2)
    den = rx2 * y1p2 + ry2 * x1p2
    factor = math.sqrt(num / den) if den > 1e-18 else 0.0
    sign = -1.0 if bool(large_arc) == bool(sweep) else 1.0
    cxp = sign * factor * (rx * y1p / ry)
    cyp = sign * factor * (-ry * x1p / rx)

    cx = cos_phi * cxp - sin_phi * cyp + (x0 + x1) * 0.5
    cy = sin_phi * cxp + cos_phi * cyp + (y0 + y1) * 0.5

    vx0 = (x1p - cxp) / rx
    vy0 = (y1p - cyp) / ry
    vx1 = (-x1p - cxp) / rx
    vy1 = (-y1p - cyp) / ry

    theta1 = _vec_angle(1.0, 0.0, vx0, vy0)
    dtheta = _vec_angle(vx0, vy0, vx1, vy1)
    if not sweep and dtheta > 0.0:
        dtheta -= 2.0 * math.pi
    elif sweep and dtheta < 0.0:
        dtheta += 2.0 * math.pi

    r_max = max(rx, ry)
    max_step = (
        2.0 * math.acos(max(-1.0, 1.0 - tol / r_max)) if r_max > tol else math.pi / 4.0
    )
    max_step = max(1e-3, min(max_step, math.pi / 8.0))
    steps = max(8, math.ceil(abs(dtheta) / max_step))

    pts: list[tuple[float, float]] = []
    for k in range(1, steps):
        ang = theta1 + dtheta * (k / steps)
        ca = math.cos(ang)
        sa = math.sin(ang)
        px = cx + cos_phi * rx * ca - sin_phi * ry * sa
        py = cy + sin_phi * rx * ca + cos_phi * ry * sa
        pts.append((px, py))
    pts.append((x1, y1))
    return pts


def _clean_subpath(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not pts:
        return []
    cleaned: list[tuple[float, float]] = [pts[0]]
    for x, y in pts[1:]:
        if math.hypot(x - cleaned[-1][0], y - cleaned[-1][1]) >= 1e-5:
            cleaned.append((x, y))
    if (
        len(cleaned) >= 2
        and math.hypot(cleaned[-1][0] - cleaned[0][0], cleaned[-1][1] - cleaned[0][1])
        < 1e-5
    ):
        cleaned.pop()
    return cleaned if len(cleaned) >= 3 else []


def _parse_path_d(d: str) -> list[list[tuple[float, float]]]:
    """Parse an SVG path d-string into closed polygon subpaths (in mm)."""
    reader = _SvgPathReader(d)
    subpaths: list[list[tuple[float, float]]] = []
    cur_pts: list[tuple[float, float]] = []

    cmd = ""
    prev_cmd = ""
    cx = 0.0
    cy = 0.0
    sx = 0.0
    sy = 0.0
    last_ctrl: tuple[float, float] | None = None

    def finish_subpath() -> None:
        nonlocal cur_pts
        cleaned = _clean_subpath(cur_pts)
        if cleaned:
            subpaths.append(cleaned)
        cur_pts = []

    while not reader.eof():
        if reader.peek_cmd() is not None:
            cmd = reader.read_cmd()
            if cmd in ("Z", "z"):
                finish_subpath()
                cx, cy = sx, sy
                prev_cmd = cmd
                last_ctrl = None
                continue
        if not cmd:
            raise ValueError(
                f"Malformed SVG path near pos {reader.pos}: {d[reader.pos : reader.pos + 24]!r}"
            )

        upper = cmd.upper()
        rel = cmd.islower()

        if upper == "M":
            first = True
            while reader.has_arg():
                x = reader.read_number()
                y = reader.read_number()
                if rel:
                    cx += x
                    cy += y
                else:
                    cx, cy = x, y
                if first:
                    finish_subpath()
                    sx, sy = cx, cy
                    cur_pts = [(cx, cy)]
                    first = False
                else:
                    cur_pts.append((cx, cy))
                prev_cmd = "L" if not first else "M"
            last_ctrl = None
        elif upper == "L":
            while reader.has_arg():
                x = reader.read_number()
                y = reader.read_number()
                cx, cy = (cx + x, cy + y) if rel else (x, y)
                cur_pts.append((cx, cy))
                prev_cmd = cmd
            last_ctrl = None
        elif upper == "H":
            while reader.has_arg():
                x = reader.read_number()
                cx = cx + x if rel else x
                cur_pts.append((cx, cy))
                prev_cmd = cmd
            last_ctrl = None
        elif upper == "V":
            while reader.has_arg():
                y = reader.read_number()
                cy = cy + y if rel else y
                cur_pts.append((cx, cy))
                prev_cmd = cmd
            last_ctrl = None
        elif upper == "C":
            while reader.has_arg():
                x1, y1, x2, y2, x3, y3 = (reader.read_number() for _ in range(6))
                if rel:
                    p1 = (cx + x1, cy + y1)
                    p2 = (cx + x2, cy + y2)
                    p3 = (cx + x3, cy + y3)
                else:
                    p1 = (x1, y1)
                    p2 = (x2, y2)
                    p3 = (x3, y3)
                cur_pts.extend(_flatten_cubic((cx, cy), p1, p2, p3))
                cx, cy = p3
                last_ctrl = p2
                prev_cmd = cmd
        elif upper == "S":
            while reader.has_arg():
                x2, y2, x3, y3 = (reader.read_number() for _ in range(4))
                if prev_cmd.upper() in ("C", "S") and last_ctrl is not None:
                    p1 = (2.0 * cx - last_ctrl[0], 2.0 * cy - last_ctrl[1])
                else:
                    p1 = (cx, cy)
                p2 = (cx + x2, cy + y2) if rel else (x2, y2)
                p3 = (cx + x3, cy + y3) if rel else (x3, y3)
                cur_pts.extend(_flatten_cubic((cx, cy), p1, p2, p3))
                cx, cy = p3
                last_ctrl = p2
                prev_cmd = cmd
        elif upper == "Q":
            while reader.has_arg():
                x1, y1, x2, y2 = (reader.read_number() for _ in range(4))
                p1 = (cx + x1, cy + y1) if rel else (x1, y1)
                p2 = (cx + x2, cy + y2) if rel else (x2, y2)
                cur_pts.extend(_flatten_quad((cx, cy), p1, p2))
                cx, cy = p2
                last_ctrl = p1
                prev_cmd = cmd
        elif upper == "T":
            while reader.has_arg():
                x2, y2 = reader.read_number(), reader.read_number()
                if prev_cmd.upper() in ("Q", "T") and last_ctrl is not None:
                    p1 = (2.0 * cx - last_ctrl[0], 2.0 * cy - last_ctrl[1])
                else:
                    p1 = (cx, cy)
                p2 = (cx + x2, cy + y2) if rel else (x2, y2)
                cur_pts.extend(_flatten_quad((cx, cy), p1, p2))
                cx, cy = p2
                last_ctrl = p1
                prev_cmd = cmd
        elif upper == "A":
            while reader.has_arg():
                rx = reader.read_number()
                ry = reader.read_number()
                xrot = reader.read_number()
                large = reader.read_flag()
                sweep = reader.read_flag()
                x = reader.read_number()
                y = reader.read_number()
                nx, ny = (cx + x, cy + y) if rel else (x, y)
                cur_pts.extend(_flatten_arc(cx, cy, rx, ry, xrot, large, sweep, nx, ny))
                cx, cy = nx, ny
                last_ctrl = None
                prev_cmd = cmd
        else:
            raise ValueError(f"Unsupported SVG path command: {cmd}")

    finish_subpath()
    return subpaths


def _parse_points_attr(points_str: str) -> list[tuple[float, float]]:
    nums = [
        float(v)
        for v in re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", points_str)
    ]
    if len(nums) % 2 != 0:
        raise ValueError(f"Odd coordinate count in points attribute: {points_str}")
    pts = [(nums[k], nums[k + 1]) for k in range(0, len(nums), 2)]
    return _clean_subpath(pts)


def _ellipse_points(
    cx: float, cy: float, rx: float, ry: float, segments: int = 64
) -> list[tuple[float, float]]:
    pts = [
        (
            cx + rx * math.cos(2.0 * math.pi * k / segments),
            cy + ry * math.sin(2.0 * math.pi * k / segments),
        )
        for k in range(segments)
    ]
    return _clean_subpath(pts)


def _rect_points(
    x: float,
    y: float,
    w: float,
    h: float,
    rx_raw: float | None,
    ry_raw: float | None,
    corner_segments: int = 16,
) -> list[tuple[float, float]]:
    if rx_raw is None and ry_raw is None:
        return _clean_subpath([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])
    rx = rx_raw if rx_raw is not None else float(ry_raw or 0.0)
    ry = ry_raw if ry_raw is not None else rx
    rx = min(max(0.0, rx), w * 0.5)
    ry = min(max(0.0, ry), h * 0.5)
    if rx <= 1e-6 or ry <= 1e-6:
        return _clean_subpath([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])

    corners = (
        (x + w - rx, y + ry, -math.pi * 0.5, 0.0),
        (x + w - rx, y + h - ry, 0.0, math.pi * 0.5),
        (x + rx, y + h - ry, math.pi * 0.5, math.pi),
        (x + rx, y + ry, math.pi, math.pi * 1.5),
    )
    pts: list[tuple[float, float]] = []
    for cx, cy, a0, a1 in corners:
        for k in range(corner_segments + 1):
            ang = a0 + (a1 - a0) * (k / corner_segments)
            pts.append((cx + rx * math.cos(ang), cy + ry * math.sin(ang)))
    return _clean_subpath(pts)


def _signed_area(pts: list[tuple[float, float]]) -> float:
    area = 0.0
    n = len(pts)
    for idx in range(n):
        x0, y0 = pts[idx]
        x1, y1 = pts[(idx + 1) % n]
        area += x0 * y1 - x1 * y0
    return 0.5 * area


def _point_in_poly(pt: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    px, py = pt
    inside = False
    n = len(poly)
    for idx in range(n):
        x0, y0 = poly[idx]
        x1, y1 = poly[(idx + 1) % n]
        if (y0 > py) != (y1 > py):
            x_int = (x1 - x0) * (py - y0) / (y1 - y0) + x0
            if px < x_int:
                inside = not inside
    return inside


def _subpath_polyset(
    pts: list[tuple[float, float]], ox_mm: float, oy_mm: float
) -> pcbnew.SHAPE_POLY_SET:
    ps = pcbnew.SHAPE_POLY_SET()
    ps.NewOutline()
    for x, y in pts:
        ps.Append(pcbnew.FromMM(x + ox_mm), pcbnew.FromMM(y + oy_mm))
    return ps


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


def _iter_svg_elements(
    elem: ET.Element,
    svg_path: pathlib.Path,
    *,
    fill: str = "",
    fill_rule: str = "nonzero",
    visible: bool = True,
) -> Iterator[tuple[ET.Element, str]]:
    """Yield rendered (element, fill_rule) pairs, pruning defs/hidden/registration_frame."""
    if elem.attrib.get("id") == "registration_frame":
        return
    tag = elem.tag.split("}")[-1]
    if tag in _NON_RENDERED_TAGS:
        return

    style_map = _parse_style(elem.attrib.get("style", ""))
    disp = elem.attrib.get("display", style_map.get("display", "")).strip().lower()
    if disp == "none":
        return
    if "transform" in elem.attrib:
        raise ValueError(
            f"Unsupported SVG transform attribute in {svg_path}: "
            f"{elem.attrib['transform']!r}; flatten transforms to Plain SVG first."
        )

    vis = elem.attrib.get("visibility", style_map.get("visibility", "")).strip().lower()
    cur_visible = False if vis == "hidden" else (True if vis == "visible" else visible)

    op = elem.attrib.get("opacity", style_map.get("opacity", "")).strip()
    fop = elem.attrib.get("fill-opacity", style_map.get("fill-opacity", "")).strip()
    if op in ("0", "0.0") or fop in ("0", "0.0"):
        return

    cur_fill = elem.attrib.get("fill", style_map.get("fill", fill)).strip().lower()
    cur_rule = (
        elem.attrib.get("fill-rule", style_map.get("fill-rule", fill_rule))
        .strip()
        .lower()
        or "nonzero"
    )
    if cur_visible and cur_fill != "none":
        yield (elem, cur_rule)
    for child in elem:
        yield from _iter_svg_elements(
            child,
            svg_path,
            fill=cur_fill,
            fill_rule=cur_rule,
            visible=cur_visible,
        )


def _parse_svg_shapes(
    svg_path: pathlib.Path,
) -> list[tuple[str, list[list[tuple[float, float]]]]]:
    """Parse an SVG into (fill_rule, subpaths_mm) entries without requiring pcbnew."""
    root = ET.parse(svg_path).getroot()
    shapes: list[tuple[str, list[list[tuple[float, float]]]]] = []

    for elem, fill_rule in _iter_svg_elements(root, svg_path):
        tag = elem.tag.split("}")[-1]
        subpaths: list[list[tuple[float, float]]] = []
        if tag == "rect":
            x = float(elem.attrib.get("x", "0"))
            y = float(elem.attrib.get("y", "0"))
            w = float(elem.attrib["width"])
            h = float(elem.attrib["height"])
            rx = float(elem.attrib["rx"]) if "rx" in elem.attrib else None
            ry = float(elem.attrib["ry"]) if "ry" in elem.attrib else None
            pts = _rect_points(x, y, w, h, rx, ry)
            if pts:
                subpaths = [pts]
        elif tag == "polygon":
            pts = _parse_points_attr(elem.attrib["points"])
            if pts:
                subpaths = [pts]
        elif tag == "circle":
            cx = float(elem.attrib.get("cx", "0"))
            cy = float(elem.attrib.get("cy", "0"))
            r = float(elem.attrib["r"])
            pts = _ellipse_points(cx, cy, r, r)
            if pts:
                subpaths = [pts]
        elif tag == "ellipse":
            cx = float(elem.attrib.get("cx", "0"))
            cy = float(elem.attrib.get("cy", "0"))
            rx = float(elem.attrib["rx"])
            ry = float(elem.attrib["ry"])
            pts = _ellipse_points(cx, cy, rx, ry)
            if pts:
                subpaths = [pts]
        elif tag == "path" and "d" in elem.attrib:
            subpaths = _parse_path_d(elem.attrib["d"])
        else:
            continue

        if subpaths:
            shapes.append((fill_rule, subpaths))

    return shapes


def _shapes_to_polysets(
    shapes: list[tuple[str, list[list[tuple[float, float]]]]],
    ox_mm: float,
    oy_mm: float,
) -> list[pcbnew.SHAPE_POLY_SET]:
    """Convert parsed (fill_rule, subpaths) entries into fractured SHAPE_POLY_SETs."""
    polysets: list[pcbnew.SHAPE_POLY_SET] = []

    for fill_rule, subpaths in shapes:
        if not subpaths:
            continue
        if fill_rule == "evenodd" or len(subpaths) == 1:
            combined = _subpath_polyset(subpaths[0], ox_mm, oy_mm)
            for sp in subpaths[1:]:
                combined.BooleanXor(_subpath_polyset(sp, ox_mm, oy_mm))
        else:
            ordered = sorted(
                subpaths, key=lambda sp: abs(_signed_area(sp)), reverse=True
            )
            combined = pcbnew.SHAPE_POLY_SET()
            placed: list[tuple[list[tuple[float, float]], int]] = []
            for sp in ordered:
                area = _signed_area(sp)
                if abs(area) < 1e-10:
                    continue
                sign = 1 if area >= 0.0 else -1
                w = sum(psign for psp, psign in placed if _point_in_poly(sp[0], psp))
                ps = _subpath_polyset(sp, ox_mm, oy_mm)
                if w != 0 and (w + sign) == 0:
                    combined.BooleanSubtract(ps)
                else:
                    combined.BooleanAdd(ps)
                placed.append((sp, sign))

        combined.Fracture()
        if combined.OutlineCount() > 0:
            polysets.append(combined)

    return polysets


def _extract_svg_polysets(
    svg_path: pathlib.Path, ox_mm: float, oy_mm: float
) -> list[pcbnew.SHAPE_POLY_SET]:
    """Parse SVG primitives into fractured SHAPE_POLY_SET objects in board coordinates."""
    return _shapes_to_polysets(_parse_svg_shapes(svg_path), ox_mm, oy_mm)


def _resolve_origin_mm(
    board: pcbnew.BOARD, explicit_origin: tuple[float, float] | None
) -> tuple[float, float]:
    """Resolve panel top-left origin in mm from override, AuxOrigin, or Edge.Cuts."""
    if explicit_origin is not None:
        return explicit_origin
    aux = board.GetDesignSettings().GetAuxOrigin()
    if aux.x != 0 or aux.y != 0:
        return (pcbnew.ToMM(aux.x), pcbnew.ToMM(aux.y))
    xs: list[int] = []
    ys: list[int] = []
    for d in board.GetDrawings():
        if d.GetLayer() == pcbnew.Edge_Cuts and not hasattr(d, "GetText"):
            bb = d.GetBoundingBox()
            hw = d.GetWidth() // 2 if hasattr(d, "GetWidth") else 0
            xs.append(bb.GetLeft() + hw)
            ys.append(bb.GetTop() + hw)
    if xs and ys:
        return (pcbnew.ToMM(min(xs)), pcbnew.ToMM(min(ys)))
    ebb = board.GetBoardEdgesBoundingBox()
    return (pcbnew.ToMM(ebb.GetLeft()), pcbnew.ToMM(ebb.GetTop()))


def _ensure_stackup(
    pcb_path: pathlib.Path, mask_color: str, silk_color: str, finish: str
) -> bool:
    """Insert KiCad stackup block into setup section if absent."""
    text = pcb_path.read_text(encoding="utf-8")
    if "(stackup" in text:
        return False
    m = re.search(r"^([ \t]*)\(pad_to_mask_clearance\b", text, re.MULTILINE)
    if m:
        indent = m.group(1)
        block = _build_stackup_block(indent, mask_color, silk_color, finish)
        pcb_path.write_text(
            text[: m.start()] + block + text[m.start() :], encoding="utf-8"
        )
        return True
    m_setup = re.search(r"^([ \t]*)\(setup\b[^\n]*\n", text, re.MULTILINE)
    if m_setup:
        indent = m_setup.group(1) + "\t"
        block = _build_stackup_block(indent, mask_color, silk_color, finish)
        pcb_path.write_text(
            text[: m_setup.end()] + block + text[m_setup.end() :], encoding="utf-8"
        )
        return True
    raise RuntimeError(f"Could not locate (setup ...) block in {pcb_path}")


def import_panel_svgs(
    pcb_path: pathlib.Path,
    *,
    silks_svg: pathlib.Path | None = None,
    mask_svg: pathlib.Path | None = None,
    origin_mm: tuple[float, float] | None = None,
    inject_stackup: bool = True,
    mask_color: str = "Black",
    silk_color: str = "White",
    finish: str = "ENIG",
) -> dict[str, int | list[float]]:
    """Import F.SilkS and/or F.Mask Plain SVGs into a KiCad panel PCB idempotently."""
    if silks_svg is None and mask_svg is None:
        raise ValueError("Specify at least one of --silks-svg or --mask-svg")

    raw_targets: list[tuple[str, int, pathlib.Path]] = []
    if silks_svg is not None:
        raw_targets.append(("F.SilkS", pcbnew.F_SilkS, silks_svg))
    if mask_svg is not None:
        raw_targets.append(("F.Mask", pcbnew.F_Mask, mask_svg))

    parsed_targets: list[
        tuple[str, int, list[tuple[str, list[list[tuple[float, float]]]]]]
    ] = []
    for label, layer_id, svg_path in raw_targets:
        if not svg_path.exists():
            raise FileNotFoundError(f"Missing SVG file for {label}: {svg_path}")
        parsed_targets.append((label, layer_id, _parse_svg_shapes(svg_path)))

    stackup_added = (
        _ensure_stackup(pcb_path, mask_color, silk_color, finish)
        if inject_stackup
        else False
    )
    board = pcbnew.LoadBoard(str(pcb_path))
    ox_mm, oy_mm = _resolve_origin_mm(board, origin_mm)

    target_layers = {layer_id: label for label, layer_id, _ in parsed_targets}
    removed = {"F.SilkS": 0, "F.Mask": 0}
    for drawing in list(board.GetDrawings()):
        layer = drawing.GetLayer()
        if layer in target_layers:
            label = target_layers[layer]
            board.Delete(drawing)
            removed[label] += 1

    added = {"F.SilkS": 0, "F.Mask": 0}
    for label, layer_id, shapes in parsed_targets:
        polysets = _shapes_to_polysets(shapes, ox_mm, oy_mm)
        for ps in polysets:
            for idx in range(ps.OutlineCount()):
                single_ps = pcbnew.SHAPE_POLY_SET()
                single_ps.AddOutline(ps.Outline(idx))
                shape = pcbnew.PCB_SHAPE(board)
                shape.SetShape(pcbnew.SHAPE_T_POLY)
                shape.SetLayer(layer_id)
                shape.SetFilled(True)
                shape.SetWidth(0)
                shape.SetPolyShape(single_ps)
                board.Add(shape)
                added[label] += 1

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())

    b_silks_count = sum(
        1 for d in board.GetDrawings() if d.GetLayer() == pcbnew.B_SilkS
    )
    pcbnew.SaveBoard(str(pcb_path), board)

    return {
        "origin_mm": [round(ox_mm, 4), round(oy_mm, 4)],
        "stackup_added": int(stackup_added),
        "removed_f_silks": removed["F.SilkS"],
        "removed_f_mask": removed["F.Mask"],
        "added_f_silks": added["F.SilkS"],
        "added_f_mask": added["F.Mask"],
        "preserved_b_silks": b_silks_count,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Import 1:1 mm F.SilkS and/or F.Mask Plain SVGs into a KiCad panel PCB."
    )
    parser.add_argument(
        "--pcb", type=pathlib.Path, required=True, help="Target panel .kicad_pcb path."
    )
    parser.add_argument(
        "--silks-svg",
        type=pathlib.Path,
        default=None,
        help="1:1 mm Plain SVG for F.SilkS.",
    )
    parser.add_argument(
        "--mask-svg",
        type=pathlib.Path,
        default=None,
        help="1:1 mm Plain SVG for F.Mask.",
    )
    parser.add_argument(
        "--origin",
        nargs=2,
        type=float,
        metavar=("X_MM", "Y_MM"),
        default=None,
        help="Override panel top-left KiCad global origin in mm (default: AuxOrigin or Edge.Cuts).",
    )
    parser.add_argument(
        "--no-stackup",
        action="store_true",
        help="Do not inject a default (stackup ...) block if absent.",
    )
    parser.add_argument(
        "--mask-color",
        choices=sorted(_MASK_COLOR_MAP),
        default="matte-black",
        help="Solder mask color for injected stackup (default: matte-black).",
    )
    parser.add_argument(
        "--silk-color",
        choices=sorted(_SILK_COLOR_MAP),
        default="white",
        help="Silkscreen color for injected stackup (default: white).",
    )
    parser.add_argument(
        "--finish",
        choices=sorted(_FINISH_MAP),
        default="enig",
        help="Surface finish for injected stackup (default: enig).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.silks_svg is None and args.mask_svg is None:
        raise SystemExit("ERROR: Pass at least one of --silks-svg or --mask-svg.")
    if not args.pcb.exists():
        raise SystemExit(f"ERROR: Missing PCB file: {args.pcb}")

    stats = import_panel_svgs(
        args.pcb,
        silks_svg=args.silks_svg,
        mask_svg=args.mask_svg,
        origin_mm=(args.origin[0], args.origin[1]) if args.origin else None,
        inject_stackup=not args.no_stackup,
        mask_color=_MASK_COLOR_MAP[args.mask_color],
        silk_color=_SILK_COLOR_MAP[args.silk_color],
        finish=_FINISH_MAP[args.finish],
    )
    print(f"KiCad SVG import complete: {json.dumps(stats)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
