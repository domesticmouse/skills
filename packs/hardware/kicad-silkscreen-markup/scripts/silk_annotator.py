#!/usr/bin/env python3
"""Silkscreen collision engine, exact KiCad text measurer, fab notes helper, and inspector CLI."""

from __future__ import annotations

import argparse
import math
import os
import pathlib
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
    """Tracks pad/mask keepouts, footprint silkscreen outlines, board margins, and placed silk."""

    def __init__(
        self,
        board: pcbnew.BOARD,
        footprints: dict[str, pcbnew.FOOTPRINT] | None = None,
        board_bounds: tuple[float, float, float, float] | None = None,
        edge_clearance: float = SILK_EDGE_CLEARANCE,
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
    step: float = 0.65,
    max_radius: float = 12.0,
    rotations: tuple[float, ...] = (0.0, 90.0),
) -> tuple[float, float, float] | None:
    """Place visible Reference + user-text Value on SilkS using a collision-free 2D offset grid.

    Keeps fp.Value() hidden on .Fab, accounts for B.SilkS mirroring so <REF> <VAL>
    always reads left-to-right, and reserves both bounding boxes in `grid`.
    Returns (pair_cx, pair_cy, deg) on success, or None if no valid slot was found.
    """
    if side is None:
        side = 1 if fp.IsFlipped() else 0
    silk_layer = pcbnew.B_SilkS if side == 1 else pcbnew.F_SilkS
    fab_layer = pcbnew.B_Fab if side == 1 else pcbnew.F_Fab
    mirrored = side == 1
    sign = -1.0 if side == 1 else 1.0

    fp.Value().SetLayer(fab_layer)
    fp.Value().SetVisible(False)

    if center is None:
        pos = fp.GetPosition()
        cx, cy = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
    else:
        cx, cy = center

    rw, rh = grid.measure_text(fp.GetReference(), height, thickness)
    vw, vh = grid.measure_text(val_text, height, thickness) if val_text else (0.0, 0.0)

    n = math.ceil(max_radius / step)
    offsets: list[tuple[float, float]] = []
    max_r2 = max_radius * max_radius + 1e-9
    for iy in range(-n, n + 1):
        dy = iy * step
        for ix in range(-n, n + 1):
            dx = ix * step
            if dx * dx + dy * dy <= max_r2:
                offsets.append((dx, dy))
    offsets.sort(key=lambda d: (d[0] * d[0] + d[1] * d[1], abs(d[1]), abs(d[0])))

    for dx, dy in offsets:
        tx, ty = cx + dx, cy + dy
        for deg in rotations:
            if deg not in (0.0, 90.0):
                raise ValueError(f"Unsupported rotation {deg}; expected 0.0 or 90.0")
            if not val_text:
                rw_r, rh_r = (rh, rw) if deg == 90.0 else (rw, rh)
                rbox = (
                    tx - rw_r * 0.5,
                    ty - rh_r * 0.5,
                    tx + rw_r * 0.5,
                    ty + rh_r * 0.5,
                )
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
                continue

            if deg == 0.0:
                ref_cx = tx - sign * (vw + gap) * 0.5
                ref_cy = ty
                val_cx = tx + sign * (rw + gap) * 0.5
                val_cy = ty
                rw_r, rh_r = rw, rh
                vw_r, vh_r = vw, vh
            else:
                ref_cx = tx
                ref_cy = ty + sign * (vw + gap) * 0.5
                val_cx = tx
                val_cy = ty - sign * (rw + gap) * 0.5
                rw_r, rh_r = rh, rw
                vw_r, vh_r = vh, vw

            rbox = (
                ref_cx - rw_r * 0.5,
                ref_cy - rh_r * 0.5,
                ref_cx + rw_r * 0.5,
                ref_cy + rh_r * 0.5,
            )
            vbox = (
                val_cx - vw_r * 0.5,
                val_cy - vh_r * 0.5,
                val_cx + vw_r * 0.5,
                val_cy + vh_r * 0.5,
            )
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
                    val_text,
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


def inspect_board_silk(pcb_path: pathlib.Path) -> None:
    """Inspect reference visibility, text counts, keepout/edge hits, and text collisions."""
    board = pcbnew.LoadBoard(str(pcb_path))
    grid = SilkGrid(board)
    footprints = list(board.GetFootprints())
    refs_visible = sum(
        1
        for fp in footprints
        if fp.Reference().IsVisible() and "Silk" in fp.Reference().GetLayerName()
    )
    vals_on_silk = sum(
        1
        for fp in footprints
        if fp.Value().IsVisible() and "Silk" in fp.Value().GetLayerName()
    )

    silk_items: dict[int, list[tuple[str, tuple[float, float, float, float]]]] = {
        0: [],
        1: [],
    }
    silk_layers = (pcbnew.F_SilkS, pcbnew.B_SilkS)
    for fp in footprints:
        for suffix, field in (("REF", fp.Reference()), ("VAL", fp.Value())):
            if field.IsVisible() and field.GetLayer() in silk_layers:
                side = 0 if field.GetLayer() == pcbnew.F_SilkS else 1
                silk_items[side].append(
                    (f"{fp.GetReference()}:{suffix}", _bbox_tuple(field))
                )
        for gi in fp.GraphicalItems():
            if (
                hasattr(gi, "GetText")
                and (not hasattr(gi, "IsVisible") or gi.IsVisible())
                and gi.GetLayer() in silk_layers
            ):
                side = 0 if gi.GetLayer() == pcbnew.F_SilkS else 1
                silk_items[side].append(
                    (f"{fp.GetReference()}:{gi.GetText()}", _bbox_tuple(gi))
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
    print(f"  Footprints:       {len(footprints)}")
    print(f"  Refs on SilkS:    {refs_visible}/{len(footprints)}")
    print(f"  Values on Silk:   {vals_on_silk}")
    print(
        f"  F.SilkS texts:    {len(silk_items[0])} | B.SilkS texts: {len(silk_items[1])}"
    )
    print(f"  Text overlaps:    {overlaps}")
    print(f"  Keepout/pad hits: {keepout_hits}")
    print(f"  Out-of-bounds:    {oob_hits}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect silkscreen markup on a KiCad .kicad_pcb."
    )
    parser.add_argument(
        "--inspect", type=pathlib.Path, required=True, help="Path to .kicad_pcb file"
    )
    args = parser.parse_args()
    inspect_board_silk(args.inspect)


if __name__ == "__main__":
    main()
