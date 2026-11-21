#!/usr/bin/env python3
"""Reusable KiCad 10 pcbnew helpers for netlist parsing, board init, routing, and GND zones."""

from __future__ import annotations

import argparse
import heapq
import math
import os
import pathlib
import sys
import tempfile

KICAD_PYTHON = pathlib.Path(
    "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3"
)

try:
    import pcbnew
except ModuleNotFoundError:
    if KICAD_PYTHON.exists():
        os.execv(str(KICAD_PYTHON), [str(KICAD_PYTHON), *sys.argv])
    raise

FP_DIR = pathlib.Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints")


def parse_sexpr(text: str) -> list:
    """Parse a KiCad S-expression string into nested Python lists and strings."""
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch in ("(", ")"):
            tokens.append(ch)
            i += 1
        elif ch == '"':
            i += 1
            buf: list[str] = []
            while i < n:
                c = text[i]
                if c == "\\":
                    i += 1
                    if i < n:
                        esc = text[i]
                        buf.append({"n": "\n", "r": "\r", "t": "\t"}.get(esc, esc))
                        i += 1
                elif c == '"':
                    i += 1
                    break
                else:
                    buf.append(c)
                    i += 1
            tokens.append("".join(buf))
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in ("(", ")"):
                j += 1
            tokens.append(text[i:j])
            i = j

    stack: list[list] = [[]]
    for tok in tokens:
        if tok == "(":
            new_list: list = []
            stack[-1].append(new_list)
            stack.append(new_list)
        elif tok == ")":
            stack.pop()
        else:
            stack[-1].append(tok)
    return stack[0][0]


def _find_child(node: list, tag: str) -> list | None:
    for item in node[1:]:
        if isinstance(item, list) and item and item[0] == tag:
            return item
    return None


def _find_children(node: list, tag: str) -> list[list]:
    return [
        item for item in node[1:] if isinstance(item, list) and item and item[0] == tag
    ]


def parse_netlist(
    net_path: pathlib.Path, *, dnp_prefixes: tuple[str, ...] = ()
) -> tuple[dict[str, dict], list[dict]]:
    """Extract components (with fields & DNP flags) and nets from a KiCad .net file."""
    tree = parse_sexpr(net_path.read_text(encoding="utf-8"))
    comps_node = _find_child(tree, "components")
    nets_node = _find_child(tree, "nets")
    if comps_node is None or nets_node is None:
        raise ValueError(f"Missing components or nets section in {net_path}")

    components: dict[str, dict] = {}
    for comp in _find_children(comps_node, "comp"):
        ref_node = _find_child(comp, "ref")
        val_node = _find_child(comp, "value")
        fp_node = _find_child(comp, "footprint")
        ts_node = _find_child(comp, "tstamp") or _find_child(comp, "tstamps")
        if not (ref_node and val_node and fp_node):
            raise ValueError(f"Malformed component entry in {net_path}: {comp}")
        ref = ref_node[1]
        value = val_node[1]
        footprint = fp_node[1]
        tstamp = (
            ts_node[1] if ts_node else f"00000000-0000-0000-0000-{len(components):012d}"
        )

        fields: dict[str, str] = {}
        fields_node = _find_child(comp, "fields")
        if fields_node:
            for fld in _find_children(fields_node, "field"):
                name_n = _find_child(fld, "name")
                if name_n and len(name_n) >= 2:
                    fname = name_n[1]
                    fval = fld[2] if len(fld) >= 3 and isinstance(fld[2], str) else ""
                    fields[fname] = fval

        dnp = False
        exclude_from_bom = False
        exclude_from_pos = False
        for prop in _find_children(comp, "property"):
            pname = _find_child(prop, "name")
            pval = _find_child(prop, "value")
            if pname and len(pname) >= 2:
                key = pname[1]
                key_l = key.lower()
                if pval and len(pval) >= 2:
                    val = pval[1]
                    fields[key] = val
                    val_l = val.strip().lower()
                    if key_l == "dnp" and val_l in ("", "1", "true", "yes", "dnp"):
                        dnp = True
                    elif key_l == "exclude_from_bom" and val_l in (
                        "",
                        "1",
                        "true",
                        "yes",
                    ):
                        exclude_from_bom = True
                    elif key_l == "exclude_from_pos_files" and val_l in (
                        "",
                        "1",
                        "true",
                        "yes",
                    ):
                        exclude_from_pos = True
                else:
                    if key_l == "dnp":
                        dnp = True
                    elif key_l == "exclude_from_bom":
                        exclude_from_bom = True
                    elif key_l == "exclude_from_pos_files":
                        exclude_from_pos = True
        if _find_child(comp, "dnp") is not None:
            dnp = True
        if _find_child(comp, "exclude_from_bom") is not None:
            exclude_from_bom = True
        if _find_child(comp, "exclude_from_pos_files") is not None:
            exclude_from_pos = True
        if "DNP" in fields.get("Notes", "") or (
            dnp_prefixes and ref.startswith(dnp_prefixes)
        ):
            dnp = True

        components[ref] = {
            "ref": ref,
            "value": value,
            "footprint": footprint,
            "tstamp": tstamp,
            "fields": fields,
            "dnp": dnp,
            "exclude_from_bom": exclude_from_bom or dnp,
            "exclude_from_pos_files": exclude_from_pos or dnp,
        }

    nets: list[dict] = []
    for net_n in _find_children(nets_node, "net"):
        code_n = _find_child(net_n, "code")
        name_n = _find_child(net_n, "name")
        if not (code_n and name_n):
            continue
        nodes: list[tuple[str, str]] = []
        for nd in _find_children(net_n, "node"):
            r_n = _find_child(nd, "ref")
            p_n = _find_child(nd, "pin")
            if r_n and p_n:
                nodes.append((r_n[1], p_n[1]))
        nets.append({"code": int(code_n[1]), "name": name_n[1], "nodes": nodes})

    return components, nets


def create_base_board(
    out_path: pathlib.Path,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    *,
    title: str = "PROJECT PCB",
    revision: str = "Rev 1.0",
    date: str = "2026-11",
    company: str = "",
    track_width: float = 0.25,
    clearance: float = 0.20,
    via_diam: float = 0.60,
    via_drill: float = 0.30,
    edge_clearance: float = 0.40,
) -> pcbnew.BOARD:
    """Create a fresh KiCad 10 PCB via LoadBoard() shell with rectangular Edge.Cuts outline."""
    minimal_pcb = """(kicad_pcb
\t(version 20240108)
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
\t)
\t(setup
\t\t(pad_to_mask_clearance 0.05)
\t\t(allow_soldermask_bridges_in_footprints no)
\t\t(pcbplotparams
\t\t\t(layerselection 0x00010fc_ffffffff)
\t\t\t(plot_on_all_layers_selection 0x0000000_00000000)
\t\t\t(tent_vias yes)
\t\t)
\t)
\t(net 0 "")
)
"""
    with tempfile.NamedTemporaryFile("w", suffix=".kicad_pcb", delete=False) as tf:
        tf.write(minimal_pcb)
        tmp_path = tf.name
    try:
        board = pcbnew.LoadBoard(tmp_path)
    finally:
        pathlib.Path(tmp_path).unlink(missing_ok=True)

    board.SetFileName(str(out_path))
    tb = board.GetTitleBlock()
    tb.SetTitle(title)
    tb.SetRevision(revision)
    tb.SetDate(date)
    if company:
        tb.SetCompany(company)

    ds = board.GetDesignSettings()
    ds.SetGridOrigin(pcbnew.VECTOR2I(0, 0))
    ds.SetAuxOrigin(pcbnew.VECTOR2I(0, 0))
    ds.SetTrackWidthIndex(0)
    ds.m_TrackMinWidth = pcbnew.FromMM(0.127)
    ds.m_ViasMinSize = pcbnew.FromMM(0.45)
    ds.m_ViasMinDrill = pcbnew.FromMM(0.20)
    ds.m_CopperEdgeClearance = pcbnew.FromMM(edge_clearance)
    ds.m_SilkClearance = pcbnew.FromMM(0.15)
    ds.m_TentViasFront = True
    ds.m_TentViasBack = True

    netclass = ds.m_NetSettings.GetDefaultNetclass()
    netclass.SetClearance(pcbnew.FromMM(clearance))
    netclass.SetTrackWidth(pcbnew.FromMM(track_width))
    netclass.SetViaDiameter(pcbnew.FromMM(via_diam))
    netclass.SetViaDrill(pcbnew.FromMM(via_drill))

    edge_rect = pcbnew.PCB_SHAPE(board)
    edge_rect.SetShape(pcbnew.SHAPE_T_RECT)
    edge_rect.SetLayer(pcbnew.Edge_Cuts)
    edge_rect.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x0), pcbnew.FromMM(y0)))
    edge_rect.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
    edge_rect.SetWidth(pcbnew.FromMM(0.10))
    edge_rect.SetFilled(False)
    board.Add(edge_rect)

    return board


def get_footprint_field(fp: pcbnew.FOOTPRINT, field_name: str) -> str:
    """Return trimmed text of custom footprint field `field_name`, or empty string."""
    for fld in fp.GetFields():
        if fld.GetName() == field_name:
            return fld.GetText().strip()
    return ""


def populate_footprints(
    board: pcbnew.BOARD,
    components: dict[str, dict],
    placements: dict[str, tuple[float, float, float, bool]],
    fp_dir: pathlib.Path = FP_DIR,
) -> dict[str, pcbnew.FOOTPRINT]:
    """Load, add, position, flip (for B.Cu), orient, and configure fields on all footprints."""
    if set(placements) != set(components):
        raise ValueError(
            f"Placement mismatch: extra={set(placements) - set(components)}, "
            f"missing={set(components) - set(placements)}"
        )

    footprints: dict[str, pcbnew.FOOTPRINT] = {}
    for ref, (x, y, rot, is_back) in placements.items():
        comp = components[ref]
        lib, fp_name = comp["footprint"].split(":", 1)
        lib_path = str(fp_dir / f"{lib}.pretty")
        fp = pcbnew.FootprintLoad(lib_path, fp_name)
        if fp is None:
            raise RuntimeError(
                f"Failed to load footprint {comp['footprint']} from {lib_path}"
            )
        board.Add(fp)

        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        if is_back:
            fp.Flip(fp.GetPosition(), False)
        fp.SetOrientationDegrees(rot)
        fp.SetReference(ref)
        fp.SetValue(comp["value"])
        fp.SetPath(pcbnew.KIID_PATH(f"/{comp['tstamp']}"))

        for k, v in comp["fields"].items():
            if k.lower() not in ("dnp", "exclude_from_bom", "exclude_from_pos_files"):
                fp.SetField(k, v)
        for fld in fp.GetFields():
            fld.SetVisible(False)
        fp.Value().SetVisible(False)
        fp.Reference().SetVisible(True)

        is_fid = ref.strip().upper().startswith("FID")
        if comp["dnp"] or is_fid:
            fp.SetDNP(True)
            fp.SetExcludedFromBOM(True)
            fp.SetExcludedFromPosFiles(True)
        else:
            if comp.get("exclude_from_bom"):
                fp.SetExcludedFromBOM(True)
            if comp.get("exclude_from_pos_files"):
                fp.SetExcludedFromPosFiles(True)

        if is_fid:
            fab_layer = pcbnew.B_Fab if is_back else pcbnew.F_Fab
            fp.Reference().SetLayer(fab_layer)
            fp.Reference().SetVisible(False)
            fp.Value().SetLayer(fab_layer)
            fp.Value().SetVisible(False)

        footprints[ref] = fp

    return footprints


def add_fiducials(
    board: pcbnew.BOARD,
    fiducials: dict[str, tuple[float, float]],
    *,
    is_back: bool = True,
    fp_name: str = "Fiducial_1mm_Mask2mm",
    fp_dir: pathlib.Path = FP_DIR,
) -> dict[str, pcbnew.FOOTPRINT]:
    """Load and place optical fiducials (not in netlist) with DNP/BOM/Pos exclusions."""
    fids: dict[str, pcbnew.FOOTPRINT] = {}
    lib_path = str(fp_dir / "Fiducial.pretty")
    fab_layer = pcbnew.B_Fab if is_back else pcbnew.F_Fab
    for ref, (fx, fy) in fiducials.items():
        fp = pcbnew.FootprintLoad(lib_path, fp_name)
        if fp is None:
            raise RuntimeError(f"Failed to load Fiducial:{fp_name} from {lib_path}")
        board.Add(fp)
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(fx), pcbnew.FromMM(fy)))
        if is_back:
            fp.Flip(fp.GetPosition(), False)
        fp.SetOrientationDegrees(0.0)
        fp.SetReference(ref)
        fp.SetValue("Fiducial")
        fp.SetDNP(True)
        fp.SetExcludedFromBOM(True)
        fp.SetExcludedFromPosFiles(True)
        for fld in fp.GetFields():
            fld.SetVisible(False)
        fp.Reference().SetLayer(fab_layer)
        fp.Reference().SetVisible(False)
        fp.Value().SetLayer(fab_layer)
        fp.Value().SetVisible(False)
        for pad in fp.Pads():
            pad.SetNetCode(0)
        fids[ref] = fp
    return fids


def assign_nets(
    board: pcbnew.BOARD,
    footprints: dict[str, pcbnew.FOOTPRINT],
    nets: list[dict],
) -> tuple[dict[str, pcbnew.NETINFO_ITEM], dict[tuple[str, str], str]]:
    """Register board nets and assign every pad to its matching net."""
    net_items: dict[str, pcbnew.NETINFO_ITEM] = {}
    pad_to_net: dict[tuple[str, str], str] = {}

    for net_def in nets:
        name = net_def["name"]
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        net_items[name] = ni
        for ref, pin in net_def["nodes"]:
            pad_to_net[(ref, pin)] = name

    for ref, fp in footprints.items():
        for pad in fp.Pads():
            net_name = pad_to_net.get((ref, pad.GetNumber()))
            if net_name is not None:
                pad.SetNet(net_items[net_name])
            else:
                pad.SetNetCode(0)

    for ref, pin in pad_to_net:
        fp = footprints[ref]
        if not any(p.GetNumber() == pin for p in fp.Pads()):
            raise RuntimeError(
                f"Pad ({ref}, {pin}) missing from {fp.GetFPIDAsString()}"
            )

    return net_items, pad_to_net


def _rect_bbox(
    cx: float, cy: float, w: float, h: float, deg: float
) -> tuple[float, float, float, float]:
    rad = math.radians(deg)
    c = abs(math.cos(rad))
    s = abs(math.sin(rad))
    bw = w * c + h * s
    bh = w * s + h * c
    return (cx - bw * 0.5, cy - bh * 0.5, cx + bw * 0.5, cy + bh * 0.5)


def extract_pad_geometry(
    pad: pcbnew.PAD,
) -> tuple[float, float, float, float, float, float, set[int]]:
    """Return (cx, cy, x0, y0, x1, y1, copper_layers) in mm for a pad."""
    pos = pad.GetPosition()
    cx = pcbnew.ToMM(pos.x)
    cy = pcbnew.ToMM(pos.y)
    sz = pad.GetSize()
    x0, y0, x1, y1 = _rect_bbox(
        cx, cy, pcbnew.ToMM(sz.x), pcbnew.ToMM(sz.y), pad.GetOrientation().AsDegrees()
    )
    layers: set[int] = set()
    lset = pad.GetLayerSet()
    if lset.Contains(pcbnew.F_Cu):
        layers.add(0)
    if lset.Contains(pcbnew.B_Cu):
        layers.add(1)
    return cx, cy, x0, y0, x1, y1, layers


def extract_keepout_circles(
    footprints: dict[str, pcbnew.FOOTPRINT],
) -> list[tuple[int, float, float, float]]:
    """Extract F.Cu/B.Cu internal footprint keepout circles (e.g. WQP-PJ398SM jack)."""
    keepouts: list[tuple[int, float, float, float]] = []
    for fp in footprints.values():
        for zone in fp.Zones():
            lset = zone.GetLayerSet()
            lids: list[int] = []
            if lset.Contains(pcbnew.F_Cu):
                lids.append(0)
            if lset.Contains(pcbnew.B_Cu):
                lids.append(1)
            if not lids:
                continue
            bbox = zone.GetBoundingBox()
            x0, y0 = pcbnew.ToMM(bbox.GetLeft()), pcbnew.ToMM(bbox.GetTop())
            x1, y1 = pcbnew.ToMM(bbox.GetRight()), pcbnew.ToMM(bbox.GetBottom())
            cx, cy = (x0 + x1) * 0.5, (y0 + y1) * 0.5
            r = max(x1 - x0, y1 - y0) * 0.5
            for lid in lids:
                keepouts.append((lid, cx, cy, r))
    return keepouts


class GridRouter:
    """2-layer A* router with exact SMD via keepouts and free THT layer transitions."""

    def __init__(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        step: float = 0.25,
        edge_clearance: float = 0.40,
        track_width: float = 0.25,
        clearance: float = 0.20,
    ) -> None:
        self.x0 = x0
        self.y0 = y0
        self.step = step
        self.track_width = track_width
        self.clearance = clearance
        self.nx = round((x1 - x0) / step) + 1
        self.ny = round((y1 - y0) / step) + 1
        self.static_block = [bytearray(self.nx * self.ny), bytearray(self.nx * self.ny)]
        self.owner = [[-1] * (self.nx * self.ny), [-1] * (self.nx * self.ny)]
        self.pad_net = [[-1] * (self.nx * self.ny), [-1] * (self.nx * self.ny)]
        self.via_block = bytearray(self.nx * self.ny)
        self.smd_via_block = bytearray(self.nx * self.ny)
        self.tht_pad_grid: dict[tuple[int, int], int] = {}

        edge_cells = math.ceil((edge_clearance + track_width * 0.5) / step)
        for layer in (0, 1):
            for gy in range(self.ny):
                for gx in range(self.nx):
                    if (
                        gx < edge_cells
                        or gx >= self.nx - edge_cells
                        or gy < edge_cells
                        or gy >= self.ny - edge_cells
                    ):
                        self.static_block[layer][gy * self.nx + gx] = 1

    def to_grid(self, x: float, y: float) -> tuple[int, int]:
        return (
            max(0, min(self.nx - 1, round((x - self.x0) / self.step))),
            max(0, min(self.ny - 1, round((y - self.y0) / self.step))),
        )

    def to_mm(self, gx: int, gy: int) -> tuple[float, float]:
        return (self.x0 + gx * self.step, self.y0 + gy * self.step)

    def mark_static_circle(
        self, layer: int, cx: float, cy: float, radius: float, block_via: bool = False
    ) -> None:
        gx0 = max(0, math.floor((cx - radius - self.x0) / self.step))
        gx1 = min(self.nx - 1, math.ceil((cx + radius - self.x0) / self.step))
        gy0 = max(0, math.floor((cy - radius - self.y0) / self.step))
        gy1 = min(self.ny - 1, math.ceil((cy + radius - self.y0) / self.step))
        r2 = radius * radius
        for gy in range(gy0, gy1 + 1):
            dy2 = (self.y0 + gy * self.step - cy) ** 2
            for gx in range(gx0, gx1 + 1):
                if (self.x0 + gx * self.step - cx) ** 2 + dy2 <= r2:
                    idx = gy * self.nx + gx
                    self.static_block[layer][idx] = 1
                    if block_via:
                        self.via_block[idx] = 1

    def mark_static_rect(
        self,
        layer: int,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        margin: float = 0.0,
        block_via: bool = False,
    ) -> None:
        rx0, rx1 = min(x0, x1) - margin, max(x0, x1) + margin
        ry0, ry1 = min(y0, y1) - margin, max(y0, y1) + margin
        gx0 = max(0, math.floor((rx0 - self.x0) / self.step))
        gx1 = min(self.nx - 1, math.ceil((rx1 - self.x0) / self.step))
        gy0 = max(0, math.floor((ry0 - self.y0) / self.step))
        gy1 = min(self.ny - 1, math.ceil((ry1 - self.y0) / self.step))
        for gy in range(gy0, gy1 + 1):
            row = gy * self.nx
            for gx in range(gx0, gx1 + 1):
                idx = row + gx
                self.static_block[layer][idx] = 1
                if block_via:
                    self.via_block[idx] = 1

    def mark_pad_box(
        self,
        layer: int,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        margin: float,
        net_code: int,
    ) -> None:
        gx0 = max(0, math.floor((x0 - margin - self.x0) / self.step))
        gx1 = min(self.nx - 1, math.ceil((x1 + margin - self.x0) / self.step))
        gy0 = max(0, math.floor((y0 - margin - self.y0) / self.step))
        gy1 = min(self.ny - 1, math.ceil((y1 + margin - self.y0) / self.step))
        arr = self.pad_net[layer]
        for gy in range(gy0, gy1 + 1):
            row = gy * self.nx
            for gx in range(gx0, gx1 + 1):
                cur = arr[row + gx]
                if cur == -1:
                    arr[row + gx] = net_code
                elif cur != net_code:
                    arr[row + gx] = -2

    def mark_smd_via_block(
        self, x0: float, y0: float, x1: float, y1: float, margin: float = 0.02
    ) -> None:
        """Block exact grid coordinates inside an SMD pad from receiving vias (prevents VP-001)."""
        for gy in range(self.ny):
            py = self.y0 + gy * self.step
            if py < y0 - margin or py > y1 + margin:
                continue
            row = gy * self.nx
            for gx in range(self.nx):
                px = self.x0 + gx * self.step
                if x0 - margin <= px <= x1 + margin:
                    self.smd_via_block[row + gx] = 1

    def mark_via_obstacle(
        self, cx: float, cy: float, radius: float, net_code: int
    ) -> None:
        gx, gy = self.to_grid(cx, cy)
        idx = gy * self.nx + gx
        self.owner[0][idx] = net_code
        self.owner[1][idx] = net_code
        gx0 = max(0, math.floor((cx - radius - self.x0) / self.step))
        gx1 = min(self.nx - 1, math.ceil((cx + radius - self.x0) / self.step))
        gy0 = max(0, math.floor((cy - radius - self.y0) / self.step))
        gy1 = min(self.ny - 1, math.ceil((cy + radius - self.y0) / self.step))
        r2 = radius * radius
        for ny_i in range(gy0, gy1 + 1):
            dy2 = (self.y0 + ny_i * self.step - cy) ** 2
            for nx_i in range(gx0, gx1 + 1):
                if (self.x0 + nx_i * self.step - cx) ** 2 + dy2 <= r2:
                    nidx = ny_i * self.nx + nx_i
                    for layer in (0, 1):
                        if self.owner[layer][nidx] == -1:
                            self.owner[layer][nidx] = net_code
                        elif self.owner[layer][nidx] != net_code:
                            self.owner[layer][nidx] = -2
                    self.via_block[nidx] = 1

    def mark_segment(
        self,
        layer: int,
        ax: float,
        ay: float,
        bx: float,
        by: float,
        width: float,
        net_code: int,
    ) -> None:
        r = width * 0.5 + self.clearance + self.track_width * 0.5
        gx0 = max(0, math.floor((min(ax, bx) - r - self.x0) / self.step))
        gx1 = min(self.nx - 1, math.ceil((max(ax, bx) + r - self.x0) / self.step))
        gy0 = max(0, math.floor((min(ay, by) - r - self.y0) / self.step))
        gy1 = min(self.ny - 1, math.ceil((max(ay, by) + r - self.y0) / self.step))
        vx, vy = bx - ax, by - ay
        vlen2 = vx * vx + vy * vy
        r2 = r * r
        own = self.owner[layer]
        for gy in range(gy0, gy1 + 1):
            py = self.y0 + gy * self.step
            row = gy * self.nx
            for gx in range(gx0, gx1 + 1):
                px = self.x0 + gx * self.step
                if vlen2 == 0.0:
                    d2 = (px - ax) ** 2 + (py - ay) ** 2
                else:
                    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / vlen2))
                    d2 = (px - (ax + t * vx)) ** 2 + (py - (ay + t * vy)) ** 2
                if d2 <= r2:
                    idx = row + gx
                    if own[idx] == -1:
                        own[idx] = net_code
                    elif own[idx] != net_code:
                        own[idx] = -2

    def is_passable(self, layer: int, gx: int, gy: int, net_code: int) -> bool:
        if gx < 0 or gx >= self.nx or gy < 0 or gy >= self.ny:
            return False
        idx = gy * self.nx + gx
        if self.static_block[layer][idx]:
            return False
        own = self.owner[layer][idx]
        if own != -1 and own != net_code:
            return False
        pnet = self.pad_net[layer][idx]
        return not (pnet != -1 and pnet != net_code)

    def can_place_via(self, gx: int, gy: int, net_code: int) -> bool:
        idx = gy * self.nx + gx
        if self.via_block[idx] or self.smd_via_block[idx]:
            return False
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                nx_i, ny_i = gx + dx, gy + dy
                if nx_i < 0 or nx_i >= self.nx or ny_i < 0 or ny_i >= self.ny:
                    return False
                nidx = ny_i * self.nx + nx_i
                for layer in (0, 1):
                    if self.static_block[layer][nidx]:
                        return False
                    own = self.owner[layer][nidx]
                    if own != -1 and own != net_code:
                        return False
                    pnet = self.pad_net[layer][nidx]
                    if pnet != -1 and pnet != net_code:
                        return False
        return True

    def route(
        self,
        starts: list[tuple[int, int, int]],
        targets: set[tuple[int, int, int]],
        net_code: int,
        preferred_layer: int | None = None,
    ) -> list[tuple[int, int, int]] | None:
        target_coords = list(targets)

        def heuristic(gx: int, gy: int) -> float:
            best = 1e9
            for _, tx, ty in target_coords:
                dx, dy = abs(gx - tx), abs(gy - ty)
                d = max(dx, dy) + 0.414 * min(dx, dy)
                best = min(best, d)
            return best

        pq: list[tuple[float, float, int, int, int, int]] = []
        best_g: dict[tuple[int, int, int], float] = {}
        parent: dict[tuple[int, int, int], tuple[int, int, int] | None] = {}
        for s in starts:
            best_g[s] = 0.0
            parent[s] = None
            heapq.heappush(pq, (heuristic(s[1], s[2]), 0.0, s[0], s[1], s[2], -1))

        dirs = (
            (1, 0, 1.0),
            (-1, 0, 1.0),
            (0, 1, 1.0),
            (0, -1, 1.0),
            (1, 1, 1.414),
            (1, -1, 1.414),
            (-1, 1, 1.414),
            (-1, -1, 1.414),
        )
        while pq:
            _, cg, cl, cx, cy, cdir = heapq.heappop(pq)
            state = (cl, cx, cy)
            if cg > best_g.get(state, 1e18):
                continue
            if state in targets:
                path: list[tuple[int, int, int]] = []
                cur: tuple[int, int, int] | None = state
                while cur is not None:
                    path.append(cur)
                    cur = parent[cur]
                path.reverse()
                return path

            for d_i, (dx, dy, step_cost) in enumerate(dirs):
                nx_i, ny_i = cx + dx, cy + dy
                nstate = (cl, nx_i, ny_i)
                if nstate not in targets and not self.is_passable(
                    cl, nx_i, ny_i, net_code
                ):
                    continue
                if (
                    dx != 0
                    and dy != 0
                    and (
                        (
                            (cl, cx + dx, cy) not in targets
                            and not self.is_passable(cl, cx + dx, cy, net_code)
                        )
                        or (
                            (cl, cx, cy + dy) not in targets
                            and not self.is_passable(cl, cx, cy + dy, net_code)
                        )
                    )
                ):
                    continue
                bend = 0.25 if (cdir != -1 and cdir != d_i) else 0.0
                layer_pen = (
                    0.12
                    if (preferred_layer is not None and cl != preferred_layer)
                    else 0.0
                )
                ng = cg + step_cost + bend + layer_pen
                if ng < best_g.get(nstate, 1e18):
                    best_g[nstate] = ng
                    parent[nstate] = state
                    heapq.heappush(
                        pq, (ng + heuristic(nx_i, ny_i), ng, cl, nx_i, ny_i, d_i)
                    )

            nl = 1 - cl
            vstate = (nl, cx, cy)
            is_tht_pad = self.tht_pad_grid.get((cx, cy)) == net_code
            if is_tht_pad and (
                vstate in targets or self.is_passable(nl, cx, cy, net_code)
            ):
                if cg < best_g.get(vstate, 1e18):
                    best_g[vstate] = cg
                    parent[vstate] = state
                    heapq.heappush(pq, (cg + heuristic(cx, cy), cg, nl, cx, cy, -1))
            elif self.can_place_via(cx, cy, net_code) and (
                vstate in targets or self.is_passable(nl, cx, cy, net_code)
            ):
                ng = cg + 10.0
                if ng < best_g.get(vstate, 1e18):
                    best_g[vstate] = ng
                    parent[vstate] = state
                    heapq.heappush(pq, (ng + heuristic(cx, cy), ng, nl, cx, cy, -1))

        return None


def _merge_collinear_path(
    path: list[tuple[int, int, int]],
    junctions: set[tuple[int, int, int]] | None = None,
) -> list[tuple[int, int, int]]:
    """Collapse collinear grid steps on the same layer while preserving T-junction vertices."""
    if len(path) <= 2:
        return path
    out = [path[0]]
    for idx in range(1, len(path) - 1):
        p_prev = out[-1]
        p_cur = path[idx]
        p_next = path[idx + 1]
        if junctions and p_cur in junctions:
            out.append(p_cur)
            continue
        if p_prev[0] == p_cur[0] == p_next[0]:
            dx1, dy1 = p_cur[1] - p_prev[1], p_cur[2] - p_prev[2]
            dx2, dy2 = p_next[1] - p_cur[1], p_next[2] - p_cur[2]
            if dx1 * dy2 == dy1 * dx2 and (dx1 * dx2 + dy1 * dy2) > 0:
                continue
        out.append(p_cur)
    out.append(path[-1])
    return out


def add_track(
    board: pcbnew.BOARD,
    layer_id: int,
    ax: float,
    ay: float,
    bx: float,
    by: float,
    width: float,
    net_item: pcbnew.NETINFO_ITEM,
) -> pcbnew.PCB_TRACK:
    trk = pcbnew.PCB_TRACK(board)
    trk.SetLayer(layer_id)
    trk.SetWidth(pcbnew.FromMM(width))
    trk.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(ax), pcbnew.FromMM(ay)))
    trk.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(bx), pcbnew.FromMM(by)))
    trk.SetNet(net_item)
    board.Add(trk)
    return trk


def add_via(
    board: pcbnew.BOARD,
    cx: float,
    cy: float,
    net_item: pcbnew.NETINFO_ITEM,
    diam: float = 0.60,
    drill: float = 0.30,
) -> pcbnew.PCB_VIA:
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(cx), pcbnew.FromMM(cy)))
    via.SetWidth(pcbnew.FromMM(diam))
    via.SetDrill(pcbnew.FromMM(drill))
    via.SetViaType(pcbnew.VIATYPE_THROUGH)
    via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    via.SetNet(net_item)
    board.Add(via)
    return via


def pour_gnd_zones(
    board: pcbnew.BOARD,
    gnd_net: pcbnew.NETINFO_ITEM,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    edge_clearance: float = 0.40,
    clearance: float = 0.20,
) -> None:
    """Add F.Cu and B.Cu GND zones and rebuild connectivity before and after filling."""
    zx0, zy0 = x0 + edge_clearance, y0 + edge_clearance
    zx1, zy1 = x1 - edge_clearance, y1 - edge_clearance
    for layer_id in (pcbnew.F_Cu, pcbnew.B_Cu):
        zone = pcbnew.ZONE(board)
        zone.SetLayer(layer_id)
        zone.SetNet(gnd_net)
        zone.SetLocalClearance(pcbnew.FromMM(clearance))
        zone.SetMinThickness(pcbnew.FromMM(0.20))
        zone.SetThermalReliefGap(pcbnew.FromMM(0.25))
        zone.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.30))
        if hasattr(pcbnew, "ISLAND_REMOVAL_MODE_ALWAYS"):
            zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        outline = zone.Outline()
        outline.NewOutline()
        for px, py in ((zx0, zy0), (zx1, zy0), (zx1, zy1), (zx0, zy1)):
            outline.Append(pcbnew.VECTOR2I(pcbnew.FromMM(px), pcbnew.FromMM(py)))
        board.Add(zone)

    board.BuildConnectivity()
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    board.BuildConnectivity()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect a KiCad .net netlist for pcbnew layout."
    )
    parser.add_argument(
        "--netlist", type=pathlib.Path, required=True, help="Path to KiCad .net file"
    )
    args = parser.parse_args()

    components, nets = parse_netlist(args.netlist)
    dnp_refs = sorted(ref for ref, c in components.items() if c["dnp"])
    node_count = sum(len(n["nodes"]) for n in nets)
    print(f"Netlist: {args.netlist.name}")
    print(
        f"  Components: {len(components)} ({len(dnp_refs)} DNP: {', '.join(dnp_refs) if dnp_refs else 'none'})"
    )
    print(f"  Nets:       {len(nets)} ({node_count} pad connections)")


if __name__ == "__main__":
    main()
