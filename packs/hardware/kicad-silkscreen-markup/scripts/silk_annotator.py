#!/usr/bin/env python3
"""Silkscreen collision engine, exact KiCad text measurer, fab notes helper, and inspector CLI."""

from __future__ import annotations

import argparse
import math
import os
import pathlib
import re
import sys

KICAD_PYTHON = pathlib.Path(
    "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3"
)

try:
    import pcbnew
except ModuleNotFoundError:
    if KICAD_PYTHON.exists():
        os.execv(str(KICAD_PYTHON), [str(KICAD_PYTHON), *sys.argv])
    raise

SILK_HEIGHT = 0.80
SILK_THICKNESS = 0.15
SILK_EDGE_CLEARANCE = 0.45
MAX_SMD_TETHER_MM = 3.5
MAX_THT_TETHER_MM = 6.0
MAX_PAIR_SPLIT_MM = 1.2
DENSE_THRESHOLD_PER_CM2 = 1.0


def is_fiducial_ref(ref: str) -> bool:
    """Return True if the reference designator belongs to a fiducial marker."""
    return ref.strip().upper().startswith("FID")


def is_mounting_hole(fp: pcbnew.FOOTPRINT) -> bool:
    """Return True for NPTH/no-pad mechanical mounting holes (H*/MH*)."""
    ref = fp.GetReference().strip().upper()
    if not re.match(r"^M?H\d+$", ref):
        return False
    return all(pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH for pad in fp.Pads())


def is_passive_ref(ref: str) -> bool:
    """Return True for fixed resistors/capacitors (R*/C*), excluding potentiometers (RV*)."""
    return bool(re.match(r"^[RC]\d+$", ref.strip().upper()))


def compact_passive_value(val_text: str) -> str:
    """Extract the concise primary value token for passives (e.g., '100k 0.1%' -> '100k')."""
    tokens = val_text.strip().split()
    return tokens[0] if tokens else ""


def is_smd_footprint(fp: pcbnew.FOOTPRINT) -> bool:
    """Return True if the footprint contains SMD pads."""
    return any(pad.GetAttribute() == pcbnew.PAD_ATTRIB_SMD for pad in fp.Pads())


def footprint_bbox(fp: pcbnew.FOOTPRINT) -> tuple[float, float, float, float]:
    """Return tight (x0, y0, x1, y1) mm bbox across pads and non-text Fab/SilkS graphics."""
    xs: list[float] = []
    ys: list[float] = []
    for pad in fp.Pads():
        _, _, x0, y0, x1, y1, _ = extract_pad_geometry(pad)
        xs.extend((x0, x1))
        ys.extend((y0, y1))
    body_layers = (pcbnew.F_Fab, pcbnew.B_Fab, pcbnew.F_SilkS, pcbnew.B_SilkS)
    for gi in fp.GraphicalItems():
        if hasattr(gi, "GetText") or gi.GetLayer() not in body_layers:
            continue
        bb = gi.GetBoundingBox()
        xs.extend((pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetRight())))
        ys.extend((pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetBottom())))
    if xs and ys:
        return (min(xs), min(ys), max(xs), max(ys))
    pos = fp.GetPosition()
    cx, cy = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
    return (cx - 0.5, cy - 0.5, cx + 0.5, cy + 0.5)


def box_edge_distance(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    """Return Euclidean distance in mm between two axis-aligned boxes (0 if overlapping)."""
    dx = max(a[0] - b[2], 0.0, b[0] - a[2])
    dy = max(a[1] - b[3], 0.0, b[1] - a[3])
    return math.hypot(dx, dy)


def extract_pad_geometry(
    pad: pcbnew.PAD,
) -> tuple[float, float, float, float, float, float, set[int]]:
    """Return (cx, cy, x0, y0, x1, y1, copper_layers) in mm for a pad."""
    pos = pad.GetPosition()
    cx, cy = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
    sz = pad.GetSize()
    w, h = pcbnew.ToMM(sz.x), pcbnew.ToMM(sz.y)
    rad = math.radians(pad.GetOrientation().AsDegrees())
    c, s = abs(math.cos(rad)), abs(math.sin(rad))
    bw, bh = w * c + h * s, w * s + h * c
    layers: set[int] = set()
    lset = pad.GetLayerSet()
    if lset.Contains(pcbnew.F_Cu):
        layers.add(0)
    if lset.Contains(pcbnew.B_Cu):
        layers.add(1)
    return cx, cy, cx - bw * 0.5, cy - bh * 0.5, cx + bw * 0.5, cy + bh * 0.5, layers


class SilkGrid:
    """Tracks pad/mask keepouts, footprint outlines, SMD .Fab bodies, board margins, and placed silk."""

    def __init__(
        self,
        board: pcbnew.BOARD,
        footprints: dict[str, pcbnew.FOOTPRINT] | None = None,
        board_bounds: tuple[float, float, float, float] | None = None,
        edge_clearance: float = SILK_EDGE_CLEARANCE,
        block_smd_fab: bool = True,
    ) -> None:
        self.board = board
        self.edge_clearance = edge_clearance
        self._text_cache: dict[tuple[str, float, float], tuple[float, float]] = {}
        self.placed: list[list[tuple[float, float, float, float]]] = [[], []]
        self.keepout: list[list[tuple[float, float, float, float]]] = [[], []]

        if board_bounds is None:
            ebb = board.GetBoardEdgesBoundingBox()
            self.board_x0 = pcbnew.ToMM(ebb.GetLeft())
            self.board_y0 = pcbnew.ToMM(ebb.GetTop())
            self.board_x1 = pcbnew.ToMM(ebb.GetRight())
            self.board_y1 = pcbnew.ToMM(ebb.GetBottom())
        else:
            self.board_x0, self.board_y0, self.board_x1, self.board_y1 = board_bounds

        fp_list = (
            list(footprints.values())
            if footprints is not None
            else list(board.GetFootprints())
        )
        self.footprints = fp_list
        pad_pad = 0.25
        silk_pad = 0.20
        for fp in fp_list:
            for pad in fp.Pads():
                _, _, x0, y0, x1, y1, layers = extract_pad_geometry(pad)
                lset = pad.GetLayerSet()
                if 0 in layers or lset.Contains(pcbnew.F_Mask):
                    self.keepout[0].append(
                        (x0 - pad_pad, y0 - pad_pad, x1 + pad_pad, y1 + pad_pad)
                    )
                if 1 in layers or lset.Contains(pcbnew.B_Mask):
                    self.keepout[1].append(
                        (x0 - pad_pad, y0 - pad_pad, x1 + pad_pad, y1 + pad_pad)
                    )
            for gi in fp.GraphicalItems():
                if hasattr(gi, "GetText"):
                    continue
                layer_id = gi.GetLayer()
                if layer_id not in (pcbnew.F_SilkS, pcbnew.B_SilkS):
                    continue
                side = 0 if layer_id == pcbnew.F_SilkS else 1
                bb = gi.GetBoundingBox()
                self.keepout[side].append(
                    (
                        pcbnew.ToMM(bb.GetLeft()) - silk_pad,
                        pcbnew.ToMM(bb.GetTop()) - silk_pad,
                        pcbnew.ToMM(bb.GetRight()) + silk_pad,
                        pcbnew.ToMM(bb.GetBottom()) + silk_pad,
                    )
                )
            if block_smd_fab:
                fp_side = 1 if fp.IsFlipped() else 0
                if is_fiducial_ref(fp.GetReference()):
                    pos = fp.GetPosition()
                    fx, fy = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
                    self.keepout[fp_side].append(
                        (fx - 1.25, fy - 1.25, fx + 1.25, fy + 1.25)
                    )
                elif is_smd_footprint(fp):
                    fp_fab_layer = pcbnew.B_Fab if fp_side == 1 else pcbnew.F_Fab
                    fab_xs: list[float] = []
                    fab_ys: list[float] = []
                    for gi in fp.GraphicalItems():
                        if hasattr(gi, "GetText"):
                            continue
                        if gi.GetLayer() == fp_fab_layer:
                            bb = gi.GetBoundingBox()
                            fab_xs.extend(
                                (pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetRight()))
                            )
                            fab_ys.extend(
                                (pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetBottom()))
                            )
                    if fab_xs and fab_ys:
                        self.keepout[fp_side].append(
                            (
                                min(fab_xs) - 0.05,
                                min(fab_ys) - 0.05,
                                max(fab_xs) + 0.05,
                                max(fab_ys) + 0.05,
                            )
                        )

    def is_dense(
        self, side: int, threshold_per_cm2: float = DENSE_THRESHOLD_PER_CM2
    ) -> bool:
        """Return True when footprint density on `side` warrants value-only passive labels."""
        width = max(0.0, self.board_x1 - self.board_x0)
        height = max(0.0, self.board_y1 - self.board_y0)
        count = 0
        for fp in self.footprints:
            if is_fiducial_ref(fp.GetReference()) or is_mounting_hole(fp):
                continue
            fp_side = 1 if fp.IsFlipped() else 0
            if fp_side == side or not is_smd_footprint(fp):
                count += 1
        area_cm2 = (width * height) / 100.0
        if area_cm2 <= 0.0:
            return count >= 35
        return (count / area_cm2) >= threshold_per_cm2 or count >= 35

    def measure_text(
        self, text: str, height: float = SILK_HEIGHT, thickness: float = SILK_THICKNESS
    ) -> tuple[float, float]:
        """Return exact KiCad stroke-font (width, height) in mm + 0.06 mm padding."""
        key = (text, height, thickness)
        cached = self._text_cache.get(key)
        if cached is not None:
            return cached
        txt = pcbnew.PCB_TEXT(self.board)
        txt.SetText(text)
        txt.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(height), pcbnew.FromMM(height)))
        txt.SetTextThickness(pcbnew.FromMM(thickness))
        txt.SetTextAngleDegrees(0.0)
        bb = txt.GetBoundingBox()
        dims = (pcbnew.ToMM(bb.GetWidth()) + 0.06, pcbnew.ToMM(bb.GetHeight()) + 0.06)
        self._text_cache[key] = dims
        return dims

    def box_ok(
        self,
        side: int,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        check_placed: bool = True,
    ) -> bool:
        if (
            x0 < self.board_x0 + self.edge_clearance
            or x1 > self.board_x1 - self.edge_clearance
            or y0 < self.board_y0 + self.edge_clearance
            or y1 > self.board_y1 - self.edge_clearance
        ):
            return False
        for kx0, ky0, kx1, ky1 in self.keepout[side]:
            if not (x1 <= kx0 or x0 >= kx1 or y1 <= ky0 or y0 >= ky1):
                return False
        if check_placed:
            margin = 0.20
            for px0, py0, px1, py1 in self.placed[side]:
                if not (
                    x1 + margin <= px0
                    or x0 - margin >= px1
                    or y1 + margin <= py0
                    or y0 - margin >= py1
                ):
                    return False
        return True

    def reserve(self, side: int, x0: float, y0: float, x1: float, y1: float) -> None:
        self.placed[side].append((x0, y0, x1, y1))


def add_silk_text(
    parent: pcbnew.BOARD | pcbnew.FOOTPRINT,
    layer_id: int,
    text: str,
    cx: float,
    cy: float,
    deg: float = 0.0,
    height: float = SILK_HEIGHT,
    thickness: float = SILK_THICKNESS,
    mirrored: bool = False,
) -> pcbnew.PCB_TEXT:
    """Create and add centered silkscreen or fab stroke text."""
    txt = pcbnew.PCB_TEXT(parent)
    txt.SetText(text)
    txt.SetLayer(layer_id)
    txt.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(cx), pcbnew.FromMM(cy)))
    txt.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(height), pcbnew.FromMM(height)))
    txt.SetTextThickness(pcbnew.FromMM(thickness))
    txt.SetTextAngleDegrees(deg)
    txt.SetMirrored(mirrored)
    txt.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    txt.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
    parent.Add(txt)
    return txt


def add_silk_rect(
    board: pcbnew.BOARD,
    layer_id: int,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    filled: bool = True,
    width: float = 0.15,
) -> None:
    """Draw a silkscreen rectangle (e.g. JLCPCB QR placeholder or stripe)."""
    shp = pcbnew.PCB_SHAPE(board)
    shp.SetShape(pcbnew.SHAPE_T_RECT)
    shp.SetLayer(layer_id)
    shp.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x0), pcbnew.FromMM(y0)))
    shp.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
    shp.SetWidth(pcbnew.FromMM(width))
    shp.SetFilled(filled)
    board.Add(shp)


def add_silk_dot(
    board: pcbnew.BOARD, layer_id: int, cx: float, cy: float, radius: float = 0.25
) -> None:
    """Draw a filled circular silkscreen dot (e.g. Pin-1 marker)."""
    shp = pcbnew.PCB_SHAPE(board)
    shp.SetShape(pcbnew.SHAPE_T_CIRCLE)
    shp.SetLayer(layer_id)
    shp.SetCenter(pcbnew.VECTOR2I(pcbnew.FromMM(cx), pcbnew.FromMM(cy)))
    shp.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(cx + radius), pcbnew.FromMM(cy)))
    shp.SetWidth(pcbnew.FromMM(0.15))
    shp.SetFilled(True)
    board.Add(shp)


def add_silk_seg(
    board: pcbnew.BOARD,
    layer_id: int,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    width: float = 0.25,
) -> None:
    """Draw a silkscreen line segment (e.g. diode cathode bar)."""
    shp = pcbnew.PCB_SHAPE(board)
    shp.SetShape(pcbnew.SHAPE_T_SEGMENT)
    shp.SetLayer(layer_id)
    shp.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x0), pcbnew.FromMM(y0)))
    shp.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
    shp.SetWidth(pcbnew.FromMM(width))
    board.Add(shp)


_add_silk_text = add_silk_text
_add_silk_rect = add_silk_rect
_add_silk_dot = add_silk_dot
_add_silk_seg = add_silk_seg


def _configure_ref_field(
    ref_field: pcbnew.PCB_FIELD,
    layer_id: int,
    cx: float,
    cy: float,
    deg: float,
    height: float,
    thickness: float,
    mirrored: bool,
) -> None:
    ref_field.SetLayer(layer_id)
    ref_field.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(cx), pcbnew.FromMM(cy)))
    ref_field.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(height), pcbnew.FromMM(height)))
    ref_field.SetTextThickness(pcbnew.FromMM(thickness))
    ref_field.SetTextAngleDegrees(deg)
    ref_field.SetMirrored(mirrored)
    ref_field.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    ref_field.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
    ref_field.SetVisible(True)


def _resolve_fp_side_and_center(
    fp: pcbnew.FOOTPRINT,
    side: int | None,
    center: tuple[float, float] | None,
) -> tuple[int, int, int, bool, float, float, float]:
    if side is None:
        side = 1 if fp.IsFlipped() else 0
    silk_layer = pcbnew.B_SilkS if side == 1 else pcbnew.F_SilkS
    fab_layer = pcbnew.B_Fab if side == 1 else pcbnew.F_Fab
    mirrored = side == 1
    sign = -1.0 if side == 1 else 1.0
    if center is None:
        pos = fp.GetPosition()
        cx, cy = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
    else:
        cx, cy = center
    return side, silk_layer, fab_layer, mirrored, sign, cx, cy


def _make_box(
    cx: float, cy: float, w: float, h: float, deg: float
) -> tuple[float, float, float, float]:
    rw, rh = (h, w) if deg == 90.0 else (w, h)
    return (cx - rw * 0.5, cy - rh * 0.5, cx + rw * 0.5, cy + rh * 0.5)


def _candidate_grid_points(
    cx: float,
    cy: float,
    fp_box: tuple[float, float, float, float],
    limit: float,
    step: float,
    pad_margin: float,
) -> list[tuple[float, float]]:
    x_min = min(cx, fp_box[0]) - limit - pad_margin
    x_max = max(cx, fp_box[2]) + limit + pad_margin
    y_min = min(cy, fp_box[1]) - limit - pad_margin
    y_max = max(cy, fp_box[3]) + limit + pad_margin
    ix0 = math.floor((x_min - cx) / step)
    ix1 = math.ceil((x_max - cx) / step)
    iy0 = math.floor((y_min - cy) / step)
    iy1 = math.ceil((y_max - cy) / step)
    return [
        (ix * step, iy * step)
        for iy in range(iy0, iy1 + 1)
        for ix in range(ix0, ix1 + 1)
    ]


def place_val_only(
    grid: SilkGrid,
    fp: pcbnew.FOOTPRINT,
    val_text: str,
    *,
    side: int | None = None,
    center: tuple[float, float] | None = None,
    height: float = SILK_HEIGHT,
    thickness: float = SILK_THICKNESS,
    step: float = 0.30,
    max_edge_distance: float | None = None,
    compact: bool = True,
    rotations: tuple[float, ...] = (0.0, 90.0),
) -> tuple[float, float, float] | None:
    """Place a single concise value token on SilkS within local tether distance, hiding Ref & Value on .Fab."""
    side, silk_layer, fab_layer, mirrored, _, cx, cy = _resolve_fp_side_and_center(
        fp, side, center
    )
    fp.Reference().SetLayer(fab_layer)
    fp.Reference().SetVisible(False)
    fp.Value().SetLayer(fab_layer)
    fp.Value().SetVisible(False)

    val_clean = val_text.strip()
    if is_fiducial_ref(fp.GetReference()) or not val_clean:
        return None

    label = (
        compact_passive_value(val_clean)
        if compact and is_passive_ref(fp.GetReference())
        else val_clean
    )
    if not label:
        return None

    fp_box = footprint_bbox(fp)
    limit = (
        max_edge_distance
        if max_edge_distance is not None
        else (MAX_SMD_TETHER_MM if is_smd_footprint(fp) else MAX_THT_TETHER_MM)
    )
    vw, vh = grid.measure_text(label, height, thickness)
    pad_margin = max(vw, vh) * 0.5 + 0.2

    candidates: list[
        tuple[
            float,
            float,
            float,
            float,
            int,
            float,
            float,
            float,
            tuple[float, float, float, float],
        ]
    ] = []
    for dx, dy in _candidate_grid_points(cx, cy, fp_box, limit, step, pad_margin):
        tx, ty = cx + dx, cy + dy
        dist2 = dx * dx + dy * dy
        for deg_idx, deg in enumerate(rotations):
            if deg not in (0.0, 90.0):
                raise ValueError(f"Unsupported rotation {deg}; expected 0.0 or 90.0")
            vbox = _make_box(tx, ty, vw, vh, deg)
            ed = box_edge_distance(fp_box, vbox)
            if ed <= limit:
                candidates.append(
                    (round(ed, 4), dist2, abs(dy), abs(dx), deg_idx, tx, ty, deg, vbox)
                )

    candidates.sort()
    for _, _, _, _, _, tx, ty, deg, vbox in candidates:
        if grid.box_ok(side, *vbox):
            add_silk_text(
                fp,
                silk_layer,
                label,
                tx,
                ty,
                deg,
                height,
                thickness,
                mirrored,
            )
            grid.reserve(side, *vbox)
            return (tx, ty, deg)

    return None


def place_ref_val_pair(
    grid: SilkGrid,
    fp: pcbnew.FOOTPRINT,
    val_text: str,
    *,
    side: int | None = None,
    center: tuple[float, float] | None = None,
    height: float = SILK_HEIGHT,
    thickness: float = SILK_THICKNESS,
    gap: float = 0.35,
    step: float = 0.50,
    max_radius: float = 6.0,
    max_edge_distance: float | None = None,
    val_only: bool | str = "auto",
    compact_passives: bool = True,
    allow_stacked: bool = True,
    rotations: tuple[float, ...] = (0.0, 90.0),
) -> tuple[float, float, float] | None:
    """Place local Reference + Value (or value-only for passives on dense boards) on SilkS.

    Keeps fp.Value() hidden on .Fab, accounts for B.SilkS mirroring so <REF> <VAL>
    always reads left-to-right, and strictly enforces local tether bounds without
    board-wide drift. Returns (cx, cy, deg) on success, or None if no local slot fits.
    """
    side, silk_layer, fab_layer, mirrored, sign, cx, cy = _resolve_fp_side_and_center(
        fp, side, center
    )
    fp.Value().SetLayer(fab_layer)
    fp.Value().SetVisible(False)

    ref_str = fp.GetReference()
    if is_fiducial_ref(ref_str):
        fp.Reference().SetLayer(fab_layer)
        fp.Reference().SetVisible(False)
        return (cx, cy, 0.0)

    is_passive = is_passive_ref(ref_str)
    val_clean = val_text.strip()
    base_limit = (
        max_edge_distance
        if max_edge_distance is not None
        else (MAX_SMD_TETHER_MM if is_smd_footprint(fp) else MAX_THT_TETHER_MM)
    )
    limit = min(base_limit, max_radius) if max_edge_distance is None else base_limit

    if val_only is True or (
        val_only == "auto" and is_passive and bool(val_clean) and grid.is_dense(side)
    ):
        return place_val_only(
            grid,
            fp,
            val_clean,
            side=side,
            center=(cx, cy),
            height=height,
            thickness=thickness,
            step=min(step, 0.35),
            max_edge_distance=limit,
            compact=compact_passives,
            rotations=rotations,
        )

    fp_box = footprint_bbox(fp)

    rw, rh = grid.measure_text(ref_str, height, thickness)
    vw, vh = (
        grid.measure_text(val_clean, height, thickness) if val_clean else (0.0, 0.0)
    )
    pad_margin = max(rw + vw + gap, rh + vh + gap) * 0.5 + 0.2

    grid_pts = _candidate_grid_points(cx, cy, fp_box, limit, step, pad_margin)

    if not val_clean:
        ref_candidates: list[
            tuple[
                float,
                float,
                float,
                float,
                int,
                float,
                float,
                float,
                tuple[float, float, float, float],
            ]
        ] = []
        for dx, dy in grid_pts:
            tx, ty = cx + dx, cy + dy
            dist2 = dx * dx + dy * dy
            for deg_idx, deg in enumerate(rotations):
                if deg not in (0.0, 90.0):
                    raise ValueError(
                        f"Unsupported rotation {deg}; expected 0.0 or 90.0"
                    )
                rbox = _make_box(tx, ty, rw, rh, deg)
                ed = box_edge_distance(fp_box, rbox)
                if ed <= limit:
                    ref_candidates.append(
                        (
                            round(ed, 4),
                            dist2,
                            abs(dy),
                            abs(dx),
                            deg_idx,
                            tx,
                            ty,
                            deg,
                            rbox,
                        )
                    )
        ref_candidates.sort()
        for _, _, _, _, _, tx, ty, deg, rbox in ref_candidates:
            if grid.box_ok(side, *rbox):
                _configure_ref_field(
                    fp.Reference(),
                    silk_layer,
                    tx,
                    ty,
                    deg,
                    height,
                    thickness,
                    mirrored,
                )
                grid.reserve(side, *rbox)
                return (tx, ty, deg)
        return None

    pair_candidates: list[
        tuple[
            float,
            float,
            int,
            int,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            tuple[float, float, float, float],
            tuple[float, float, float, float],
        ]
    ] = []
    styles = (0, 1) if allow_stacked else (0,)
    for dx, dy in grid_pts:
        tx, ty = cx + dx, cy + dy
        dist2 = dx * dx + dy * dy
        for deg_idx, deg in enumerate(rotations):
            if deg not in (0.0, 90.0):
                raise ValueError(f"Unsupported rotation {deg}; expected 0.0 or 90.0")
            for style_idx in styles:
                if style_idx == 0:
                    if deg == 0.0:
                        ref_cx, ref_cy = tx - sign * (vw + gap) * 0.5, ty
                        val_cx, val_cy = tx + sign * (rw + gap) * 0.5, ty
                    else:
                        ref_cx, ref_cy = tx, ty + sign * (vw + gap) * 0.5
                        val_cx, val_cy = tx, ty - sign * (rw + gap) * 0.5
                else:
                    if deg == 0.0:
                        ref_cx, ref_cy = tx, ty - (vh + gap) * 0.5
                        val_cx, val_cy = tx, ty + (rh + gap) * 0.5
                    else:
                        ref_cx, ref_cy = tx - (vh + gap) * 0.5, ty
                        val_cx, val_cy = tx + (rh + gap) * 0.5, ty

                rbox = _make_box(ref_cx, ref_cy, rw, rh, deg)
                vbox = _make_box(val_cx, val_cy, vw, vh, deg)
                ed = max(
                    box_edge_distance(fp_box, rbox),
                    box_edge_distance(fp_box, vbox),
                )
                if ed <= limit:
                    pair_candidates.append(
                        (
                            round(ed, 4),
                            dist2,
                            style_idx,
                            deg_idx,
                            abs(dy),
                            abs(dx),
                            tx,
                            ty,
                            deg,
                            ref_cx,
                            ref_cy,
                            val_cx,
                            val_cy,
                            rbox,
                            vbox,
                        )
                    )

    pair_candidates.sort()
    for (
        _,
        _,
        _,
        _,
        _,
        _,
        tx,
        ty,
        deg,
        ref_cx,
        ref_cy,
        val_cx,
        val_cy,
        rbox,
        vbox,
    ) in pair_candidates:
        if grid.box_ok(side, *rbox) and grid.box_ok(side, *vbox):
            _configure_ref_field(
                fp.Reference(),
                silk_layer,
                ref_cx,
                ref_cy,
                deg,
                height,
                thickness,
                mirrored,
            )
            add_silk_text(
                fp,
                silk_layer,
                val_clean,
                val_cx,
                val_cy,
                deg,
                height,
                thickness,
                mirrored,
            )
            grid.reserve(side, *rbox)
            grid.reserve(side, *vbox)
            return (tx, ty, deg)

    if val_only == "auto" and is_passive:
        return place_val_only(
            grid,
            fp,
            val_clean,
            side=side,
            center=(cx, cy),
            height=height,
            thickness=thickness,
            step=min(step, 0.35),
            max_edge_distance=limit,
            compact=compact_passives,
            rotations=rotations,
        )

    return None


def add_standard_fab_notes(board: pcbnew.BOARD, cx: float, y_start: float) -> None:
    """Place complete B.Fab fabrication notes satisfying analyze_pcb.py fab_notes_completeness."""
    lines = [
        "FAB NOTES: 2L FR4 | THICKNESS: 1.6mm | 1oz CU",
        "FINISH: ENIG / HASL-LF | IPC-6012 CLASS 2",
        "SOLDER MASK: BLACK | SILK: WHITE | MIN TR/SP: 0.127mm",
        "DRILL TOL: +/-0.08mm | NO EDGE CUT",
    ]
    for idx, line in enumerate(lines):
        add_silk_text(
            board, pcbnew.B_Fab, line, cx, y_start + idx * 2.2, 0.0, 0.80, 0.15, True
        )


def _bbox_tuple(item: pcbnew.BOARD_ITEM) -> tuple[float, float, float, float]:
    bb = item.GetBoundingBox()
    return (
        pcbnew.ToMM(bb.GetLeft()),
        pcbnew.ToMM(bb.GetTop()),
        pcbnew.ToMM(bb.GetRight()),
        pcbnew.ToMM(bb.GetBottom()),
    )


def inspect_board_silk(
    pcb_path: pathlib.Path,
    *,
    max_smd_tether: float = MAX_SMD_TETHER_MM,
    max_tht_tether: float = MAX_THT_TETHER_MM,
    max_pair_split: float = MAX_PAIR_SPLIT_MM,
) -> bool:
    """Inspect silkscreen labels, collisions, keepouts, tether drift, and split pairs."""
    board = pcbnew.LoadBoard(str(pcb_path))
    grid = SilkGrid(board)
    footprints = list(board.GetFootprints())
    non_fid = [
        fp
        for fp in footprints
        if not is_fiducial_ref(fp.GetReference()) and not is_mounting_hole(fp)
    ]

    refs_visible = 0
    vals_on_silk = 0
    labeled = 0
    unlabeled = 0
    val_only_passives = 0
    tether_violations = 0
    split_pair_violations = 0

    silk_items: dict[int, list[tuple[str, tuple[float, float, float, float]]]] = {
        0: [],
        1: [],
    }
    silk_layers = (pcbnew.F_SilkS, pcbnew.B_SilkS)

    for fp in footprints:
        ref = fp.GetReference()
        is_fid = is_fiducial_ref(ref)
        fp_box = footprint_bbox(fp)
        limit = max_smd_tether if is_smd_footprint(fp) else max_tht_tether

        has_ref = False
        ref_side = -1
        ref_box: tuple[float, float, float, float] | None = None
        fp_texts: list[tuple[str, int, tuple[float, float, float, float]]] = []
        user_texts: list[tuple[str, int, tuple[float, float, float, float]]] = []

        ref_field = fp.Reference()
        if ref_field.IsVisible() and ref_field.GetLayer() in silk_layers:
            has_ref = True
            ref_side = 0 if ref_field.GetLayer() == pcbnew.F_SilkS else 1
            ref_box = _bbox_tuple(ref_field)
            silk_items[ref_side].append((f"{ref}:REF", ref_box))
            fp_texts.append(("REF", ref_side, ref_box))

        val_field = fp.Value()
        if val_field.IsVisible() and val_field.GetLayer() in silk_layers:
            vals_on_silk += 1
            vside = 0 if val_field.GetLayer() == pcbnew.F_SilkS else 1
            vbox = _bbox_tuple(val_field)
            silk_items[vside].append((f"{ref}:VAL", vbox))
            fp_texts.append(("VAL", vside, vbox))

        for gi in fp.GraphicalItems():
            if (
                hasattr(gi, "GetText")
                and (not hasattr(gi, "IsVisible") or gi.IsVisible())
                and gi.GetLayer() in silk_layers
            ):
                gside = 0 if gi.GetLayer() == pcbnew.F_SilkS else 1
                gbox = _bbox_tuple(gi)
                gtext = gi.GetText()
                silk_items[gside].append((f"{ref}:{gtext}", gbox))
                fp_texts.append((gtext, gside, gbox))
                user_texts.append((gtext, gside, gbox))

        if is_fid:
            if fp_texts:
                print(f"  WARNING: Fiducial {ref} has visible silkscreen text")
            continue
        if is_mounting_hole(fp):
            continue

        if has_ref:
            refs_visible += 1
        if has_ref or user_texts:
            labeled += 1
            if is_passive_ref(ref) and not has_ref and user_texts:
                val_only_passives += 1
        else:
            unlabeled += 1
            pos = fp.GetPosition()
            print(
                f"  UNLABELED: {ref} at "
                f"({pcbnew.ToMM(pos.x):.2f}, {pcbnew.ToMM(pos.y):.2f})"
            )

        for lbl, tside, tbox in fp_texts:
            ed = box_edge_distance(fp_box, tbox)
            if ed > limit:
                tether_violations += 1
                print(
                    f"  TETHER DRIFT side={tside}: {ref}:{lbl} is {ed:.2f} mm "
                    f"from {ref} (max {limit:.1f} mm)"
                )

        if has_ref and ref_box is not None and user_texts:
            polarity_tokens = {"+", "-", "1", "K", "A"}
            same_side_uts = [
                ut_box
                for ut_text, ut_side, ut_box in user_texts
                if ut_side == ref_side and ut_text.strip().upper() not in polarity_tokens
            ]
            if same_side_uts:
                pair_gap = min(
                    box_edge_distance(ref_box, ut_box) for ut_box in same_side_uts
                )
                if pair_gap > max_pair_split:
                    split_pair_violations += 1
                    print(
                        f"  SPLIT PAIR side={ref_side}: {ref} REF and VAL separated "
                        f"by {pair_gap:.2f} mm (max {max_pair_split:.1f} mm)"
                    )

    for dr in board.GetDrawings():
        if (
            hasattr(dr, "GetText")
            and (not hasattr(dr, "IsVisible") or dr.IsVisible())
            and dr.GetLayer() in silk_layers
        ):
            side = 0 if dr.GetLayer() == pcbnew.F_SilkS else 1
            silk_items[side].append((f"BOARD:{dr.GetText()}", _bbox_tuple(dr)))

    overlaps = 0
    keepout_hits = 0
    oob_hits = 0
    has_edges = grid.board_x1 > grid.board_x0 and grid.board_y1 > grid.board_y0

    for side in (0, 1):
        items = silk_items[side]
        for i in range(len(items)):
            n1, b1 = items[i]
            for j in range(i + 1, len(items)):
                n2, b2 = items[j]
                if not (
                    b1[2] <= b2[0] or b2[2] <= b1[0] or b1[3] <= b2[1] or b2[3] <= b1[1]
                ):
                    overlaps += 1
                    print(f"  OVERLAP side={side}: {n1} {b1} vs {n2} {b2}")

        for name, (x0, y0, x1, y1) in items:
            for kx0, ky0, kx1, ky1 in grid.keepout[side]:
                if not (x1 <= kx0 or x0 >= kx1 or y1 <= ky0 or y0 >= ky1):
                    keepout_hits += 1
                    print(
                        f"  KEEPOUT HIT side={side}: {name} {(x0, y0, x1, y1)} "
                        f"vs {(kx0, ky0, kx1, ky1)}"
                    )
                    break
            if has_edges and (
                x0 < grid.board_x0 + grid.edge_clearance
                or x1 > grid.board_x1 - grid.edge_clearance
                or y0 < grid.board_y0 + grid.edge_clearance
                or y1 > grid.board_y1 - grid.edge_clearance
            ):
                oob_hits += 1
                print(f"  OUT OF BOUNDS side={side}: {name} {(x0, y0, x1, y1)}")

    print(f"Silkscreen Inspection: {pcb_path.name}")
    print(f"  Footprints:         {len(footprints)} ({len(non_fid)} non-fiducial)")
    print(
        f"  Labeled on SilkS:   {labeled}/{len(non_fid)} "
        f"({refs_visible} with REF, {val_only_passives} value-only passives)"
    )
    print(f"  Unlabeled parts:    {unlabeled}")
    print(f"  Raw Values on Silk: {vals_on_silk}")
    print(
        f"  F.SilkS texts:      {len(silk_items[0])} | B.SilkS texts: {len(silk_items[1])}"
    )
    print(f"  Text overlaps:      {overlaps}")
    print(f"  Keepout/pad hits:   {keepout_hits}")
    print(f"  Out-of-bounds:      {oob_hits}")
    print(f"  Tether drift hits:  {tether_violations}")
    print(f"  Split pair hits:    {split_pair_violations}")

    failures: list[str] = []
    if unlabeled:
        failures.append(f"{unlabeled} unlabeled")
    if vals_on_silk:
        failures.append(f"{vals_on_silk} raw values on silk")
    if overlaps:
        failures.append(f"{overlaps} overlaps")
    if keepout_hits:
        failures.append(f"{keepout_hits} keepout hits")
    if oob_hits:
        failures.append(f"{oob_hits} out-of-bounds")
    if tether_violations:
        failures.append(f"{tether_violations} tether drift")
    if split_pair_violations:
        failures.append(f"{split_pair_violations} split pairs")

    if failures:
        print(f"  RESULT: FAIL ({', '.join(failures)})")
        return False
    print("  RESULT: PASS")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect silkscreen markup on a KiCad .kicad_pcb."
    )
    parser.add_argument(
        "--inspect", type=pathlib.Path, required=True, help="Path to .kicad_pcb file"
    )
    parser.add_argument(
        "--max-smd-tether",
        type=float,
        default=MAX_SMD_TETHER_MM,
        help=f"Max mm from SMD footprint edge to its silkscreen text (default: {MAX_SMD_TETHER_MM})",
    )
    parser.add_argument(
        "--max-tht-tether",
        type=float,
        default=MAX_THT_TETHER_MM,
        help=f"Max mm from THT footprint edge to its silkscreen text (default: {MAX_THT_TETHER_MM})",
    )
    parser.add_argument(
        "--max-pair-split",
        type=float,
        default=MAX_PAIR_SPLIT_MM,
        help=f"Max mm between REF and VAL texts in a pair (default: {MAX_PAIR_SPLIT_MM})",
    )
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Always exit 0 even when silkscreen inspection finds violations.",
    )
    args = parser.parse_args()
    ok = inspect_board_silk(
        args.inspect,
        max_smd_tether=args.max_smd_tether,
        max_tht_tether=args.max_tht_tether,
        max_pair_split=args.max_pair_split,
    )
    if not ok and not args.no_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
