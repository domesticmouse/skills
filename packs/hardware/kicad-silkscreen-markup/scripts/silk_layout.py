#!/usr/bin/env python3
"""Declarative silk_layout.json round-trip CLI for iterative KiCad 10 silkscreen tuning."""

from __future__ import annotations

import argparse
import json
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

_SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from silk_annotator import (
    SilkGrid,
    _bbox_tuple,
    _configure_ref_field,
    _rect_perimeter_boxes,
    add_silk_dot,
    add_silk_rect,
    add_silk_seg,
    add_silk_text,
    add_standard_fab_notes,
    board_edge_bounds,
    box_edge_distance,
    compact_passive_value,
    footprint_bbox,
    get_fp_silkscreen_field,
    inspect_board_silk,
    is_fiducial_ref,
    is_mounting_hole,
    is_passive_ref,
    is_smd_footprint,
    place_ref_val_pair,
)

_SILK_LAYER_TO_NAME = {
    pcbnew.F_SilkS: "F.SilkS",
    pcbnew.B_SilkS: "B.SilkS",
}
_SUPPORTED_SHAPE_TYPES = (
    pcbnew.SHAPE_T_RECT,
    pcbnew.SHAPE_T_CIRCLE,
    pcbnew.SHAPE_T_SEGMENT,
)


def _parse_silk_layer(name: str) -> tuple[int, int, bool]:
    if name in ("F.SilkS", "F.Silkscreen"):
        return (0, pcbnew.F_SilkS, False)
    if name in ("B.SilkS", "B.Silkscreen"):
        return (1, pcbnew.B_SilkS, True)
    raise ValueError(f"Unsupported silkscreen layer: {name!r}")


def _ref_sort_key(ref: str) -> tuple[str, int, str]:
    match = re.match(r"^([A-Za-z_]+?)(\d+)$", ref)
    if match:
        return (match.group(1), int(match.group(2)), ref)
    return (ref, -1, ref)


def _norm_angle(deg: float) -> float:
    angle = round(deg % 360.0, 2)
    return 0.0 if angle in (0.0, 360.0) else angle


def _round_mm(nm_val: int, offset_mm: float = 0.0) -> float:
    val = round(pcbnew.ToMM(nm_val) - offset_mm, 3)
    return 0.0 if val == 0.0 else val


def resolve_board_origin_and_bounds(
    board: pcbnew.BOARD,
) -> tuple[float, float, tuple[float, float, float, float]]:
    """Return (origin_x, origin_y, (bx0, by0, bx1, by1)) in global KiCad mm."""
    bx0, by0, bx1, by1 = board_edge_bounds(board)
    aux = board.GetDesignSettings().GetAuxOrigin()
    if aux.x != 0 or aux.y != 0:
        ox, oy = pcbnew.ToMM(aux.x), pcbnew.ToMM(aux.y)
    else:
        ox, oy = bx0, by0
    return ox, oy, (bx0, by0, bx1, by1)


def _to_local_box(
    box: tuple[float, float, float, float], ox: float, oy: float
) -> tuple[float, float, float, float]:
    return (
        round(box[0] - ox, 2),
        round(box[1] - oy, 2),
        round(box[2] - ox, 2),
        round(box[3] - oy, 2),
    )


def _text_item_to_dict(
    item: pcbnew.PCB_TEXT | pcbnew.PCB_FIELD,
    ox: float,
    oy: float,
    *,
    include_text: bool,
) -> dict:
    ctr = item.GetBoundingBox().GetCenter()
    out: dict[str, object] = {"layer": _SILK_LAYER_TO_NAME[item.GetLayer()]}
    if include_text:
        out["text"] = item.GetText()
    out["x"] = _round_mm(ctr.x, ox)
    out["y"] = _round_mm(ctr.y, oy)
    out["deg"] = _norm_angle(float(item.GetTextAngleDegrees()))
    out["height"] = _round_mm(item.GetTextHeight())
    out["thickness"] = _round_mm(item.GetTextThickness())
    return out


def extract_silk_layout(board: pcbnew.BOARD) -> dict:
    """Extract all silkscreen items from `board` into board-local schema dict."""
    ox, oy, (bx0, by0, bx1, by1) = resolve_board_origin_and_bounds(board)
    bw = round(bx1 - bx0, 3)
    bh = round(by1 - by0, 3)

    qr_rects: list[dict] = []
    dots: list[dict] = []
    segments: list[dict] = []
    board_texts: list[dict] = []

    for d in board.GetDrawings():
        layer_id = d.GetLayer()
        layer_name = _SILK_LAYER_TO_NAME.get(layer_id)
        if layer_name is None:
            continue
        if isinstance(d, pcbnew.PCB_TEXT):
            if d.IsVisible():
                board_texts.append(_text_item_to_dict(d, ox, oy, include_text=True))
        elif isinstance(d, pcbnew.PCB_SHAPE):
            shape_t = d.GetShape()
            width = _round_mm(d.GetWidth())
            if shape_t == pcbnew.SHAPE_T_RECT:
                s, e = d.GetStart(), d.GetEnd()
                qr_rects.append(
                    {
                        "layer": layer_name,
                        "x0": _round_mm(s.x, ox),
                        "y0": _round_mm(s.y, oy),
                        "x1": _round_mm(e.x, ox),
                        "y1": _round_mm(e.y, oy),
                        "filled": bool(d.IsSolidFill()),
                        "width": width,
                    }
                )
            elif shape_t == pcbnew.SHAPE_T_CIRCLE:
                c = d.GetCenter()
                dots.append(
                    {
                        "layer": layer_name,
                        "x": _round_mm(c.x, ox),
                        "y": _round_mm(c.y, oy),
                        "radius": _round_mm(d.GetRadius()),
                        "filled": bool(d.IsSolidFill()),
                        "width": width,
                    }
                )
            elif shape_t == pcbnew.SHAPE_T_SEGMENT:
                s, e = d.GetStart(), d.GetEnd()
                segments.append(
                    {
                        "layer": layer_name,
                        "x0": _round_mm(s.x, ox),
                        "y0": _round_mm(s.y, oy),
                        "x1": _round_mm(e.x, ox),
                        "y1": _round_mm(e.y, oy),
                        "width": width,
                    }
                )
            else:
                shape_desc = (
                    d.GetShapeStr() if hasattr(d, "GetShapeStr") else str(shape_t)
                )
                print(
                    f"WARNING: Board silk shape {shape_desc} on {layer_name} is not "
                    "represented in silk_layout.json and will be preserved in place on --apply."
                )

    qr_rects.sort(key=lambda r: (r["layer"], r["x0"], r["y0"], r["x1"], r["y1"]))
    dots.sort(key=lambda d: (d["layer"], d["x"], d["y"], d["radius"]))
    segments.sort(key=lambda s: (s["layer"], s["x0"], s["y0"], s["x1"], s["y1"]))
    board_texts.sort(key=lambda t: (t["layer"], t["text"], t["x"], t["y"]))

    footprints_map: dict[str, dict] = {}
    for fp in sorted(
        board.GetFootprints(), key=lambda f: _ref_sort_key(f.GetReference())
    ):
        ref = fp.GetReference()
        if is_fiducial_ref(ref) or is_mounting_hole(fp):
            continue
        vf = fp.Value()
        if vf.IsVisible() and vf.GetLayer() in _SILK_LAYER_TO_NAME:
            print(
                f"WARNING: {ref} Value field is visible on silk; keep Value hidden on "
                ".Fab and move its silk text item instead."
            )
        rf = fp.Reference()
        ref_entry = (
            _text_item_to_dict(rf, ox, oy, include_text=False)
            if rf.IsVisible() and rf.GetLayer() in _SILK_LAYER_TO_NAME
            else None
        )
        texts = [
            _text_item_to_dict(gi, ox, oy, include_text=True)
            for gi in fp.GraphicalItems()
            if isinstance(gi, pcbnew.PCB_TEXT)
            and gi.IsVisible()
            and gi.GetLayer() in _SILK_LAYER_TO_NAME
        ]
        texts.sort(key=lambda t: (t["layer"], t["text"], t["x"], t["y"]))
        footprints_map[ref] = {"ref": ref_entry, "texts": texts}

    return {
        "version": 1,
        "coordinate_system": (
            f"board-local mm relative to origin=({round(ox, 3)}, {round(oy, 3)})"
        ),
        "board_origin_mm": [round(ox, 3), round(oy, 3)],
        "board_size_mm": [bw, bh],
        "qr_rects": qr_rects,
        "dots": dots,
        "segments": segments,
        "board_texts": board_texts,
        "footprints": footprints_map,
    }


def format_silk_layout_json(layout: dict) -> str:
    """Format silk_layout.json with compact single-line leaf items for crisp diffs."""
    lines: list[str] = [
        "{",
        f'  "version": {json.dumps(layout.get("version", 1))},',
    ]
    if "coordinate_system" in layout:
        lines.append(
            f'  "coordinate_system": {json.dumps(layout["coordinate_system"], ensure_ascii=False)},'
        )
    if "board_origin_mm" in layout:
        lines.append(f'  "board_origin_mm": {json.dumps(layout["board_origin_mm"])},')
    if "board_size_mm" in layout:
        lines.append(f'  "board_size_mm": {json.dumps(layout["board_size_mm"])},')
    for key in ("qr_rects", "dots", "segments", "board_texts"):
        items = layout.get(key, [])
        if not items:
            lines.append(f'  "{key}": [],')
            continue
        lines.append(f'  "{key}": [')
        for idx, item in enumerate(items):
            comma = "," if idx < len(items) - 1 else ""
            lines.append(f"    {json.dumps(item, ensure_ascii=False)}{comma}")
        lines.append("  ],")

    fps = layout.get("footprints", {})
    lines.append('  "footprints": {')
    fp_keys = sorted(fps, key=_ref_sort_key)
    for idx, ref in enumerate(fp_keys):
        entry = fps[ref]
        comma = "," if idx < len(fp_keys) - 1 else ""
        ref_key = json.dumps(ref, ensure_ascii=False)
        if entry == "auto":
            lines.append(f'    {ref_key}: "auto"{comma}')
            continue
        ref_s = json.dumps(entry.get("ref"), ensure_ascii=False)
        texts = entry.get("texts", [])
        if entry.get("ref") is None and len(texts) <= 1:
            texts_s = f"[{json.dumps(texts[0], ensure_ascii=False)}]" if texts else "[]"
            lines.append(f'    {ref_key}: {{"ref": null, "texts": {texts_s}}}{comma}')
        elif not texts:
            lines.append(f'    {ref_key}: {{"ref": {ref_s}, "texts": []}}{comma}')
        else:
            lines.append(f"    {ref_key}: {{")
            lines.append(f'      "ref": {ref_s},')
            lines.append('      "texts": [')
            for tidx, txt in enumerate(texts):
                tcomma = "," if tidx < len(texts) - 1 else ""
                lines.append(f"        {json.dumps(txt, ensure_ascii=False)}{tcomma}")
            lines.append("      ]")
            lines.append(f"    }}{comma}")
    lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def load_silk_layout(path: pathlib.Path) -> dict:
    """Load and minimally validate `silk_layout.json`."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("footprints"), dict):
        raise TypeError(f"Invalid silk layout file: {path}")
    return data


def _fmt_pos(item: dict) -> str:
    return f"({item['x']}, {item['y']}, {item['deg']}°)"


def summarize_silk_diff(old_layout: dict | None, new_layout: dict) -> list[str]:
    """Return human-readable summary lines describing changes between two layouts."""
    if old_layout is None:
        summary = (
            "Initialized layout: "
            f"{len(new_layout.get('footprints', {}))} footprints, "
            f"{len(new_layout.get('board_texts', []))} board_texts, "
            f"{len(new_layout.get('qr_rects', []))} qr_rects, "
            f"{len(new_layout.get('dots', []))} dots."
        )
        return [summary]

    changes: list[str] = []
    for key in ("qr_rects", "dots", "segments", "board_texts"):
        old_items = old_layout.get(key, [])
        new_items = new_layout.get(key, [])
        if old_items != new_items:
            changes.append(
                f"{key}: updated ({len(old_items)} -> {len(new_items)} items)"
            )

    old_fps = old_layout.get("footprints", {})
    new_fps = new_layout.get("footprints", {})
    for ref in sorted(set(old_fps) | set(new_fps), key=_ref_sort_key):
        if ref not in old_fps:
            changes.append(f"{ref}: added")
            continue
        if ref not in new_fps:
            changes.append(f"{ref}: removed")
            continue
        old_e, new_e = old_fps[ref], new_fps[ref]
        if old_e == new_e:
            continue
        if not isinstance(old_e, dict) or not isinstance(new_e, dict):
            changes.append(f"{ref}: updated ({old_e!r} -> {new_e!r})")
            continue
        parts: list[str] = []
        if old_e.get("ref") != new_e.get("ref"):
            or_d, nr_d = old_e.get("ref"), new_e.get("ref")
            if isinstance(or_d, dict) and isinstance(nr_d, dict):
                parts.append(f"REF {_fmt_pos(or_d)} -> {_fmt_pos(nr_d)}")
            else:
                parts.append(f"REF {or_d} -> {nr_d}")
        if old_e.get("texts") != new_e.get("texts"):
            ot_list, nt_list = old_e.get("texts", []), new_e.get("texts", [])
            if len(ot_list) == len(nt_list) == 1:
                ot, nt = ot_list[0], nt_list[0]
                if ot.get("text") == nt.get("text"):
                    parts.append(f"'{nt['text']}' {_fmt_pos(ot)} -> {_fmt_pos(nt)}")
                else:
                    parts.append(f"text '{ot.get('text')}' -> '{nt.get('text')}'")
            else:
                parts.append(f"texts ({len(ot_list)} -> {len(nt_list)} items)")
        changes.append(f"{ref}: {', '.join(parts) if parts else 'updated'}")
    return changes


def strip_board_silkscreen(board: pcbnew.BOARD) -> None:
    """Remove managed silkscreen text/shapes cleanly using Delete() (never Remove())."""
    for d in list(board.GetDrawings()):
        if d.GetLayer() not in _SILK_LAYER_TO_NAME:
            continue
        if isinstance(d, pcbnew.PCB_TEXT) or (
            isinstance(d, pcbnew.PCB_SHAPE) and d.GetShape() in _SUPPORTED_SHAPE_TYPES
        ):
            board.Delete(d)
    for fp in list(board.GetFootprints()):
        for gi in list(fp.GraphicalItems()):
            if isinstance(gi, pcbnew.PCB_TEXT) and gi.GetLayer() in _SILK_LAYER_TO_NAME:
                fp.Delete(gi)


def strip_board_fab_notes(board: pcbnew.BOARD) -> None:
    """Remove board-level B.Fab text notes cleanly using Delete() (never Remove())."""
    for d in list(board.GetDrawings()):
        if d.GetLayer() == pcbnew.B_Fab and isinstance(d, pcbnew.PCB_TEXT):
            board.Delete(d)


def _place_fixed_board_silk(
    board: pcbnew.BOARD,
    grid: SilkGrid,
    layout: dict,
    ox: float,
    oy: float,
) -> None:
    for rect in layout.get("qr_rects", []):
        side, layer_id, _ = _parse_silk_layer(rect["layer"])
        gx0, gy0 = ox + rect["x0"], oy + rect["y0"]
        gx1, gy1 = ox + rect["x1"], oy + rect["y1"]
        filled = bool(rect.get("filled", True))
        width = float(rect.get("width", 0.15))
        add_silk_rect(
            board,
            layer_id,
            gx0,
            gy0,
            gx1,
            gy1,
            filled=filled,
            width=width,
        )
        rx0, rx1 = min(gx0, gx1), max(gx0, gx1)
        ry0, ry1 = min(gy0, gy1), max(gy0, gy1)
        if filled:
            grid.reserve(side, rx0 - 0.15, ry0 - 0.15, rx1 + 0.15, ry1 + 0.15)
        else:
            for box in _rect_perimeter_boxes(rx0, ry0, rx1, ry1, width * 0.5 + 0.15):
                grid.reserve(side, *box)

    for dot in layout.get("dots", []):
        side, layer_id, _ = _parse_silk_layer(dot["layer"])
        gx, gy = ox + dot["x"], oy + dot["y"]
        r = float(dot.get("radius", 0.25))
        add_silk_dot(
            board,
            layer_id,
            gx,
            gy,
            radius=r,
            width=float(dot.get("width", 0.15)),
            filled=bool(dot.get("filled", True)),
        )
        grid.reserve(side, gx - r - 0.25, gy - r - 0.25, gx + r + 0.25, gy + r + 0.25)

    for seg in layout.get("segments", []):
        side, layer_id, _ = _parse_silk_layer(seg["layer"])
        gx0, gy0 = ox + seg["x0"], oy + seg["y0"]
        gx1, gy1 = ox + seg["x1"], oy + seg["y1"]
        add_silk_seg(
            board,
            layer_id,
            gx0,
            gy0,
            gx1,
            gy1,
            width=float(seg.get("width", 0.15)),
        )
        grid.reserve(
            side,
            min(gx0, gx1) - 0.15,
            min(gy0, gy1) - 0.15,
            max(gx0, gx1) + 0.15,
            max(gy0, gy1) + 0.15,
        )

    for item in layout.get("board_texts", []):
        side, layer_id, mirrored = _parse_silk_layer(item["layer"])
        gx, gy = ox + item["x"], oy + item["y"]
        txt = add_silk_text(
            board,
            layer_id,
            item["text"],
            gx,
            gy,
            deg=float(item.get("deg", 0.0)),
            height=float(item.get("height", 0.80)),
            thickness=float(item.get("thickness", 0.15)),
            mirrored=mirrored,
        )
        grid.reserve(side, *_bbox_tuple(txt))


def _place_pinned_footprints(
    footprints: dict[str, pcbnew.FOOTPRINT],
    grid: SilkGrid,
    layout: dict,
    ox: float,
    oy: float,
) -> set[str]:
    pinned_refs: set[str] = set()
    for ref, entry in layout.get("footprints", {}).items():
        if entry == "auto":
            continue
        fp = footprints.get(ref)
        if fp is None:
            print(f"WARNING: Skipping unknown ref {ref!r} in silk layout.")
            continue
        pinned_refs.add(ref)
        ref_cfg = entry.get("ref")
        if isinstance(ref_cfg, dict):
            side, layer_id, mirrored = _parse_silk_layer(ref_cfg["layer"])
            gx, gy = ox + ref_cfg["x"], oy + ref_cfg["y"]
            _configure_ref_field(
                fp.Reference(),
                layer_id,
                gx,
                gy,
                float(ref_cfg.get("deg", 0.0)),
                float(ref_cfg.get("height", 0.80)),
                float(ref_cfg.get("thickness", 0.15)),
                mirrored,
            )
            grid.reserve(side, *_bbox_tuple(fp.Reference()))
        for txt_cfg in entry.get("texts", []):
            side, layer_id, mirrored = _parse_silk_layer(txt_cfg["layer"])
            gx, gy = ox + txt_cfg["x"], oy + txt_cfg["y"]
            txt = add_silk_text(
                fp,
                layer_id,
                txt_cfg["text"],
                gx,
                gy,
                deg=float(txt_cfg.get("deg", 0.0)),
                height=float(txt_cfg.get("height", 0.80)),
                thickness=float(txt_cfg.get("thickness", 0.15)),
                mirrored=mirrored,
            )
            grid.reserve(side, *_bbox_tuple(txt))
    return pinned_refs


def _auto_place_remaining(
    grid: SilkGrid,
    footprints: dict[str, pcbnew.FOOTPRINT],
    pinned_refs: set[str],
) -> int:
    def _fp_sort_key(ref: str) -> tuple[int, float, float, str]:
        fp = footprints[ref]
        pos = fp.GetPosition()
        return (
            1 if is_passive_ref(ref) else 0,
            pcbnew.ToMM(pos.y),
            pcbnew.ToMM(pos.x),
            ref,
        )

    ordered_refs = sorted(
        (
            r
            for r, fp in footprints.items()
            if r not in pinned_refs
            and not is_fiducial_ref(r)
            and not is_mounting_hole(fp)
        ),
        key=_fp_sort_key,
    )
    failed: list[str] = []
    for ref in ordered_refs:
        fp = footprints[ref]
        _, val_str = get_fp_silkscreen_field(fp)
        if is_passive_ref(ref):
            val_str = compact_passive_value(val_str or fp.GetValue())
        max_ed = 3.5 if is_smd_footprint(fp) else 5.5
        res = place_ref_val_pair(
            grid,
            fp,
            val_str,
            gap=0.35,
            step=0.30,
            max_edge_distance=max_ed,
            val_only="auto",
        )
        if res is None:
            failed.append(ref)

    if failed:
        raise RuntimeError(
            "Silkscreen placement failed within local tether bounds for: "
            + ", ".join(failed)
        )
    return len(ordered_refs)


def apply_silk_layout(
    board: pcbnew.BOARD,
    layout: dict,
    *,
    add_fab_notes: bool = False,
) -> tuple[int, int]:
    """Strip managed silkscreen and stamp pinned + 'auto' entries from `layout`."""
    ox, oy, (bx0, by0, bx1, by1) = resolve_board_origin_and_bounds(board)
    if "board_origin_mm" in layout:
        ox = float(layout["board_origin_mm"][0])
        oy = float(layout["board_origin_mm"][1])

    footprints = {fp.GetReference(): fp for fp in board.GetFootprints()}
    strip_board_silkscreen(board)
    if add_fab_notes:
        strip_board_fab_notes(board)

    for fp in footprints.values():
        fab_layer = pcbnew.B_Fab if fp.IsFlipped() else pcbnew.F_Fab
        fp.Reference().SetLayer(fab_layer)
        fp.Reference().SetVisible(False)
        fp.Value().SetLayer(fab_layer)
        fp.Value().SetVisible(False)

    grid = SilkGrid(
        board,
        footprints,
        board_bounds=(bx0, by0, bx1, by1),
        block_smd_fab=True,
        block_tht_fab=True,
    )
    for d in board.GetDrawings():
        if d.GetLayer() in _SILK_LAYER_TO_NAME and isinstance(d, pcbnew.PCB_SHAPE):
            side = 0 if d.GetLayer() == pcbnew.F_SilkS else 1
            grid.reserve(side, *_bbox_tuple(d))

    _place_fixed_board_silk(board, grid, layout, ox, oy)
    pinned_refs = _place_pinned_footprints(footprints, grid, layout, ox, oy)
    auto_count = _auto_place_remaining(grid, footprints, pinned_refs)

    if add_fab_notes:
        add_standard_fab_notes(board, (bx0 + bx1) * 0.5, by1 + 5.0)

    return len(pinned_refs), auto_count


def _collect_all_silk_boxes(
    board: pcbnew.BOARD,
) -> list[tuple[str, int, tuple[float, float, float, float]]]:
    items: list[tuple[str, int, tuple[float, float, float, float]]] = []
    for d in board.GetDrawings():
        layer_id = d.GetLayer()
        if (
            layer_id in _SILK_LAYER_TO_NAME
            and isinstance(d, pcbnew.PCB_TEXT)
            and d.IsVisible()
        ):
            side = 0 if layer_id == pcbnew.F_SilkS else 1
            items.append((f"BOARD:{d.GetText()}", side, _bbox_tuple(d)))

    for fp in board.GetFootprints():
        ref = fp.GetReference()
        rf = fp.Reference()
        if rf.IsVisible() and rf.GetLayer() in _SILK_LAYER_TO_NAME:
            side = 0 if rf.GetLayer() == pcbnew.F_SilkS else 1
            items.append((f"{ref}:REF", side, _bbox_tuple(rf)))
        for gi in fp.GraphicalItems():
            if (
                isinstance(gi, pcbnew.PCB_TEXT)
                and gi.IsVisible()
                and gi.GetLayer() in _SILK_LAYER_TO_NAME
            ):
                side = 0 if gi.GetLayer() == pcbnew.F_SilkS else 1
                items.append((f"{ref}:{gi.GetText()}", side, _bbox_tuple(gi)))
    return items


def _print_all_silk_overview(
    pcb_path: pathlib.Path,
    board: pcbnew.BOARD,
    layout: dict,
    ox: float,
    oy: float,
) -> None:
    print(
        f"Silkscreen overview for {pcb_path.name} "
        f"(board-local mm relative to ({ox:.3f}, {oy:.3f})):"
    )
    for key in ("qr_rects", "dots", "segments", "board_texts"):
        items = layout.get(key, [])
        if items:
            print(f"  {key} ({len(items)}):")
            for item in items:
                print(f"    {json.dumps(item, ensure_ascii=False)}")

    fps_by_ref = {fp.GetReference(): fp for fp in board.GetFootprints()}
    for side_label, want_flipped in (("F.Cu", False), ("B.Cu", True)):
        group_refs = [
            ref
            for ref in sorted(layout.get("footprints", {}), key=_ref_sort_key)
            if ref in fps_by_ref and fps_by_ref[ref].IsFlipped() == want_flipped
        ]
        print(f"\n  Footprints on {side_label} ({len(group_refs)}):")
        for ref in group_refs:
            fp = fps_by_ref[ref]
            pos = fp.GetPosition()
            px, py = _round_mm(pos.x, ox), _round_mm(pos.y, oy)
            entry = layout["footprints"][ref]
            ref_d = entry.get("ref")
            ref_s = (
                f"({ref_d['x']:6.2f},{ref_d['y']:6.2f},{ref_d['deg']:3.0f}°)"
                if ref_d
                else "(hidden)          "
            )
            txt_s = ", ".join(
                f"{t['text']}@({t['x']:.2f},{t['y']:.2f},{t['deg']:.0f}°)"
                for t in entry.get("texts", [])
            )
            print(f"    {ref:<6} part=({px:5.2f},{py:5.2f})  REF={ref_s}  TXT={txt_s}")


def _print_ref_neighborhood(
    board: pcbnew.BOARD,
    fp: pcbnew.FOOTPRINT,
    all_silk: list[tuple[str, int, tuple[float, float, float, float]]],
    ox: float,
    oy: float,
) -> None:
    ref = fp.GetReference()
    pos = fp.GetPosition()
    lx, ly = _round_mm(pos.x, ox), _round_mm(pos.y, oy)
    rot = _norm_angle(float(fp.GetOrientationDegrees()))
    side_str = "B.Cu" if fp.IsFlipped() else "F.Cu"
    fp_box = footprint_bbox(fp)
    lbox = _to_local_box(fp_box, ox, oy)
    print(
        f"{ref} ({side_str}) origin=({lx:.2f}, {ly:.2f}) rot={rot:.1f}° "
        f"bbox=({lbox[0]:.2f}..{lbox[2]:.2f}, {lbox[1]:.2f}..{lbox[3]:.2f})"
    )

    label_sides: set[int] = {1 if fp.IsFlipped() else 0}
    rf = fp.Reference()
    if rf.IsVisible() and rf.GetLayer() in _SILK_LAYER_TO_NAME:
        rd = _text_item_to_dict(rf, ox, oy, include_text=False)
        rbox = _to_local_box(_bbox_tuple(rf), ox, oy)
        label_sides.add(0 if rf.GetLayer() == pcbnew.F_SilkS else 1)
        print(
            f"  REF  {rd['layer']:<7} ({rd['x']:.3f}, {rd['y']:.3f}) "
            f"deg={rd['deg']:.1f} h={rd['height']:.2f} "
            f"bbox=({rbox[0]:.2f}..{rbox[2]:.2f}, {rbox[1]:.2f}..{rbox[3]:.2f})"
        )
    else:
        print("  REF  (hidden on .Fab)")

    texts_found = [
        gi
        for gi in fp.GraphicalItems()
        if isinstance(gi, pcbnew.PCB_TEXT)
        and gi.IsVisible()
        and gi.GetLayer() in _SILK_LAYER_TO_NAME
    ]
    for gi in texts_found:
        td = _text_item_to_dict(gi, ox, oy, include_text=True)
        tbox = _to_local_box(_bbox_tuple(gi), ox, oy)
        label_sides.add(0 if gi.GetLayer() == pcbnew.F_SilkS else 1)
        print(
            f"  TEXT {td['layer']:<7} {td['text']!r:<12} ({td['x']:.3f}, {td['y']:.3f}) "
            f"deg={td['deg']:.1f} h={td['height']:.2f} "
            f"bbox=({tbox[0]:.2f}..{tbox[2]:.2f}, {tbox[1]:.2f}..{tbox[3]:.2f})"
        )

    nearby_fps: list[tuple[float, str, str, tuple[float, float, float, float]]] = []
    for other in board.GetFootprints():
        oref = other.GetReference()
        if oref == ref or is_fiducial_ref(oref):
            continue
        obox = footprint_bbox(other)
        dist = box_edge_distance(fp_box, obox)
        if dist <= 5.0:
            oside = "B.Cu" if other.IsFlipped() else "F.Cu"
            nearby_fps.append((dist, oref, oside, _to_local_box(obox, ox, oy)))
    nearby_fps.sort(key=lambda x: (x[0], _ref_sort_key(x[1])))
    if nearby_fps:
        print("  Nearby footprints (<= 5.0 mm):")
        for dist, oref, oside, olbox in nearby_fps:
            print(
                f"    {oref:<6} ({oside}) d={dist:.2f} mm  "
                f"bbox=({olbox[0]:.2f}..{olbox[2]:.2f}, {olbox[1]:.2f}..{olbox[3]:.2f})"
            )

    nearby_labels: list[tuple[float, str, str, tuple[float, float, float, float]]] = []
    for lname, lside, lbox_g in all_silk:
        if lside not in label_sides or lname.startswith(f"{ref}:"):
            continue
        dist = box_edge_distance(fp_box, lbox_g)
        if dist <= 5.0:
            sname = "F.SilkS" if lside == 0 else "B.SilkS"
            nearby_labels.append((dist, lname, sname, _to_local_box(lbox_g, ox, oy)))
    nearby_labels.sort(key=lambda x: (x[0], x[1]))
    if nearby_labels:
        print("  Nearby silkscreen labels (<= 5.0 mm):")
        for dist, lname, sname, llbox in nearby_labels:
            print(
                f"    {lname:<16} ({sname}) d={dist:.2f} mm  "
                f"bbox=({llbox[0]:.2f}..{llbox[2]:.2f}, {llbox[1]:.2f}..{llbox[3]:.2f})"
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Extract, restamp, inspect, and verify silk_layout.json on a KiCad PCB."
    )
    parser.add_argument(
        "--pcb", type=pathlib.Path, required=True, help="Target .kicad_pcb file."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--extract",
        action="store_true",
        help="Extract silkscreen positions from PCB into --layout JSON.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Restamp --layout JSON onto PCB in place (~1 s).",
    )
    mode.add_argument(
        "--show",
        nargs="*",
        metavar="REF",
        default=None,
        help="Show all silkscreen items, or local details/neighbors for REF...",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="Run strict silkscreen collision/keepout/tether inspection.",
    )
    parser.add_argument(
        "--layout",
        type=pathlib.Path,
        default=pathlib.Path("silk_layout.json"),
        help="Path to silkscreen layout JSON (default: silk_layout.json).",
    )
    parser.add_argument(
        "--restamp-fab-notes",
        action="store_true",
        help="With --apply, strip and restamp standard B.Fab notes below bottom edge.",
    )
    parser.add_argument(
        "--no-fab-notes",
        action="store_true",
        help="Deprecated no-op; existing B.Fab notes are now preserved by default.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.pcb.exists():
        print(f"ERROR: Missing PCB file: {args.pcb}")
        return 1

    if args.check:
        return 0 if inspect_board_silk(args.pcb) else 1

    board = pcbnew.LoadBoard(str(args.pcb))
    if args.extract:
        new_layout = extract_silk_layout(board)
        old_layout = load_silk_layout(args.layout) if args.layout.exists() else None
        changes = summarize_silk_diff(old_layout, new_layout)
        args.layout.parent.mkdir(parents=True, exist_ok=True)
        args.layout.write_text(format_silk_layout_json(new_layout), encoding="utf-8")
        print(f"Synced silkscreen from {args.pcb.name} -> {args.layout}")
        if changes:
            for line in changes:
                print(f"  - {line}")
        else:
            print("  - No changes.")
        inspect_board_silk(args.pcb)
        return 0

    if args.apply:
        if not args.layout.exists():
            print(f"ERROR: Missing silk layout file: {args.layout}")
            return 1
        layout = load_silk_layout(args.layout)
        pinned, auto = apply_silk_layout(
            board,
            layout,
            add_fab_notes=args.restamp_fab_notes and not args.no_fab_notes,
        )
        board.Save(str(args.pcb))
        print(
            f"Updated silkscreen in {args.pcb.name}: {pinned} pinned, {auto} auto-placed."
        )
        ok = inspect_board_silk(args.pcb)
        return 0 if ok else 1

    if args.show is not None:
        ox, oy, _ = resolve_board_origin_and_bounds(board)
        if not args.show:
            _print_all_silk_overview(
                args.pcb, board, extract_silk_layout(board), ox, oy
            )
            return 0
        by_upper = {fp.GetReference().upper(): fp for fp in board.GetFootprints()}
        all_silk = _collect_all_silk_boxes(board)
        rc = 0
        for idx, req in enumerate(args.show):
            fp = by_upper.get(req.strip().upper())
            if fp is None:
                print(f"ERROR: Unknown footprint reference {req!r}")
                rc = 1
                continue
            if idx > 0:
                print()
            _print_ref_neighborhood(board, fp, all_silk, ox, oy)
        return rc

    return 1


if __name__ == "__main__":
    sys.exit(main())
