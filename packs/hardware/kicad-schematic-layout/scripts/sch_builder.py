#!/usr/bin/env python3
"""KiCad 10 schematic builder and netlist/ERC verification helpers."""

from __future__ import annotations

import builtins
import json
import os
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_KICAD_CLI = Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")
DEFAULT_SYMBOL_DIR = Path(
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"
)

_UUID_NAMESPACE = uuid.UUID("a4b8f19c-2e6d-4c5a-9b1e-7c3d9012ef01")
_GRID_MM = 1.27


def _default_symbol_dir() -> Path:
    """Resolve the KiCad 10 symbol library directory from env vars or macOS default."""
    for var in ("KICAD10_SYMBOL_DIR", "KICAD_SYMBOL_DIR"):
        val = os.environ.get(var)
        if val:
            return Path(val)
    return DEFAULT_SYMBOL_DIR


def _default_kicad_cli() -> Path:
    """Resolve the `kicad-cli` executable path."""
    return DEFAULT_KICAD_CLI if DEFAULT_KICAD_CLI.exists() else Path("kicad-cli")


class Quoted(str):
    """String marker indicating an S-expression atom that must be double-quoted."""


@dataclass(frozen=True)
class PinDef:
    """Pin definition extracted from a KiCad 10 symbol library."""

    number: str
    name: str
    x: float
    y: float
    angle: float
    unit: int
    pin_type: str


@dataclass(frozen=True)
class PlacedSymbol:
    """Record of a placed symbol instance on the schematic canvas."""

    ref: str
    lib_id: str
    x: float
    y: float
    angle: int
    mirror: str | None
    unit: int
    pins: dict[str, tuple[float, float]]
    pin_numbers_by_name: dict[str, list[str]]


@dataclass
class PartMetadata:
    """Component metadata sourced from SKiDL or a KiCad netlist."""

    ref: str
    lib_id: str
    value: str
    footprint: str
    fields: dict[str, str] = field(default_factory=dict)
    dnp: bool = False
    exclude_from_bom: bool = False
    exclude_from_pos_files: bool = False


def _det_uuid(key: str) -> str:
    """Return a deterministic UUIDv5 string for stable schematic diffs."""
    return str(uuid.uuid5(_UUID_NAMESPACE, key))


def _snap_grid(val: float, grid: float = _GRID_MM) -> float:
    """Round a coordinate to 4 decimal places; assert it sits cleanly on the 1.27 mm grid."""
    snapped = round(round(val / grid) * grid, 4)
    if abs(val - snapped) > 1e-3:
        raise ValueError(
            f"Coordinate {val} is not on the {grid} mm schematic grid (nearest {snapped})"
        )
    return snapped


def _parse_sexp(text: str) -> list[Any]:
    """Parse a KiCad S-expression preserving Quoted vs bare tokens."""
    stack: list[list[Any]] = [[]]
    token: list[str] = []
    in_quote = False
    quote_buf: list[str] = []
    i = 0
    n = len(text)

    def flush_token() -> None:
        if token:
            raw = "".join(token)
            token.clear()
            stack[-1].append(raw)

    while i < n:
        ch = text[i]
        if in_quote:
            if ch == "\\" and i + 1 < n:
                nxt = text[i + 1]
                if nxt in ('"', "\\"):
                    quote_buf.append(nxt)
                elif nxt == "n":
                    quote_buf.append("\n")
                elif nxt == "r":
                    quote_buf.append("\r")
                elif nxt == "t":
                    quote_buf.append("\t")
                else:
                    quote_buf.append(ch + nxt)
                i += 2
                continue
            if ch == '"':
                in_quote = False
                stack[-1].append(Quoted("".join(quote_buf)))
                quote_buf.clear()
                i += 1
                continue
            quote_buf.append(ch)
            i += 1
            continue

        if ch == '"':
            flush_token()
            in_quote = True
            quote_buf.clear()
        elif ch == "(":
            flush_token()
            new_list: list[Any] = []
            stack[-1].append(new_list)
            stack.append(new_list)
        elif ch == ")":
            flush_token()
            if len(stack) > 1:
                stack.pop()
        elif ch.isspace():
            flush_token()
        else:
            token.append(ch)
        i += 1

    flush_token()
    return stack[0]


def _escape_quoted(s: str) -> str:
    """Escape a string for double-quoted KiCad S-expression output."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_atom(atom: Any) -> str:
    """Serialize an S-expression atom."""
    if isinstance(atom, Quoted):
        return f'"{_escape_quoted(atom)}"'
    return str(atom)


def _format_sexp(node: Any, indent: int = 0) -> str:
    """Format an S-expression tree cleanly in KiCad style."""
    if not isinstance(node, list):
        return _format_atom(node)

    has_sublist = any(isinstance(c, list) for c in node)
    if not has_sublist:
        return "(" + " ".join(_format_atom(c) for c in node) + ")"

    tag = node[0] if node else ""
    inline_prefix: list[str] = []
    idx = 0
    while idx < len(node) and not isinstance(node[idx], list):
        inline_prefix.append(_format_atom(node[idx]))
        idx += 1

    pad = "  " * (indent + 1)
    lines = ["(" + " ".join(inline_prefix)]
    for child in node[idx:]:
        lines.append(pad + _format_sexp(child, indent + 1))
    if tag in (
        "effects",
        "font",
        "stroke",
        "fill",
        "pts",
        "instances",
        "project",
        "path",
    ):
        return lines[0] + " " + " ".join(c.strip() for c in lines[1:]) + ")"
    return "\n".join(lines) + ")"


def _find_child(node: list[Any], tag: str) -> list[Any] | None:
    """Return the first child list starting with `tag`."""
    for item in node[1:]:
        if isinstance(item, list) and item and item[0] == tag:
            return item
    return None


def _find_children(node: list[Any], tag: str) -> list[list[Any]]:
    """Return all child lists starting with `tag`."""
    return [
        item for item in node[1:] if isinstance(item, list) and item and item[0] == tag
    ]


def _extract_raw_symbol_sexp(lib_path: Path, sym_name: str) -> list[Any]:
    """Extract and parse a top-level `(symbol "<sym_name>" ...)` from a `.kicad_sym` file."""
    text = lib_path.read_text(encoding="utf-8")
    target = f'(symbol "{sym_name}"'
    pos = 0
    idx = -1
    while True:
        found = text.find(target, pos)
        if found == -1:
            break
        # Must be top-level symbol inside kicad_symbol_lib (depth 1)
        if found > 0 and text[found - 1] in ("\t", "\n", " "):
            idx = found
            break
        pos = found + len(target)
    if idx == -1:
        raise KeyError(f"Symbol {sym_name!r} not found in {lib_path}")

    depth = 0
    in_quote = False
    i = idx
    n = len(text)
    while i < n:
        ch = text[i]
        if in_quote:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == '"':
                in_quote = False
        else:
            if ch == '"':
                in_quote = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    parsed = _parse_sexp(text[idx : i + 1])
                    return parsed[0]
        i += 1
    raise ValueError(f"Unterminated symbol S-expression for {sym_name!r} in {lib_path}")


def _rename_subsymbol(sub: list[Any], old_prefix: str, new_prefix: str) -> list[Any]:
    """Return a deep copy of a child unit symbol with renamed `<sym>_u_s` identifier."""
    out: list[Any] = []
    for i, item in enumerate(sub):
        if i == 1 and isinstance(item, str) and item.startswith(old_prefix):
            out.append(Quoted(new_prefix + item[len(old_prefix) :]))
        else:
            out.append(_deep_copy_sexp(item))
    return out


def _deep_copy_sexp(node: Any) -> Any:
    """Deep copy a parsed S-expression tree preserving Quoted markers."""
    if isinstance(node, list):
        return [_deep_copy_sexp(x) for x in node]
    if isinstance(node, Quoted):
        return Quoted(node)
    return node


def load_kicad10_symbol(
    lib_name: str,
    sym_name: str,
    symbol_dir: Path | None = None,
) -> tuple[list[Any], dict[int, list[PinDef]]]:
    """Load a KiCad 10 symbol, flattening `(extends ...)` chains, and extract its pins."""
    sym_root = symbol_dir or _default_symbol_dir()
    lib_path = sym_root / f"{lib_name}.kicad_sym"
    if not lib_path.exists():
        raise FileNotFoundError(f"KiCad symbol library not found: {lib_path}")

    def resolve_chain(name: str) -> list[Any]:
        node = _extract_raw_symbol_sexp(lib_path, name)
        ext = _find_child(node, "extends")
        if not ext:
            return node
        parent_name = str(ext[1])
        parent_node = resolve_chain(parent_name)

        header_tags_order: list[str] = []
        headers: dict[str, list[Any]] = {}
        props_order: list[str] = []
        props: dict[str, list[Any]] = {}
        subsym_order: list[str] = []
        subsyms: dict[str, list[Any]] = {}
        embedded_fonts: list[Any] | None = None

        for src_name, src in ((parent_name, parent_node), (name, node)):
            for child in src[2:]:
                if not isinstance(child, list) or not child:
                    continue
                tag = child[0]
                if tag == "extends":
                    continue
                if tag == "property":
                    pname = str(child[1])
                    if pname not in props:
                        props_order.append(pname)
                    props[pname] = _deep_copy_sexp(child)
                elif tag == "symbol":
                    renamed = _rename_subsymbol(child, f"{src_name}_", f"{name}_")
                    sub_key = str(renamed[1]) if len(renamed) > 1 else ""
                    if sub_key not in subsyms:
                        subsym_order.append(sub_key)
                    subsyms[sub_key] = renamed
                elif tag == "embedded_fonts":
                    embedded_fonts = _deep_copy_sexp(child)
                else:
                    if tag not in headers:
                        header_tags_order.append(tag)
                    headers[tag] = _deep_copy_sexp(child)

        merged: list[Any] = ["symbol", Quoted(name)]
        for tag in header_tags_order:
            merged.append(headers[tag])
        for pname in props_order:
            merged.append(props[pname])
        for sub_key in subsym_order:
            merged.append(subsyms[sub_key])
        if embedded_fonts is not None:
            merged.append(embedded_fonts)
        return merged

    flat = resolve_chain(sym_name)
    flat[1] = Quoted(f"{lib_name}:{sym_name}")

    pins_by_unit: dict[int, list[PinDef]] = {}
    unit_pattern = re.compile(r"_(\d+)_(\d+)$")
    for sub in _find_children(flat, "symbol"):
        sub_name = str(sub[1])
        m = unit_pattern.search(sub_name)
        if not m:
            continue
        unit_idx = int(m.group(1))
        style_idx = int(m.group(2))
        if style_idx not in (0, 1):
            continue
        for pin_node in _find_children(sub, "pin"):
            pin_type = str(pin_node[1])
            at_node = _find_child(pin_node, "at")
            name_node = _find_child(pin_node, "name")
            num_node = _find_child(pin_node, "number")
            if not at_node or not name_node or not num_node:
                continue
            pdef = PinDef(
                number=str(num_node[1]),
                name=str(name_node[1]),
                x=float(at_node[1]),
                y=float(at_node[2]),
                angle=float(at_node[3]),
                unit=unit_idx,
                pin_type=pin_type,
            )
            pins_by_unit.setdefault(unit_idx, []).append(pdef)

    return flat, pins_by_unit


def pin_world(
    sx: float,
    sy: float,
    angle: int,
    mirror: str | None,
    px: float,
    py: float,
) -> tuple[float, float]:
    """Transform a symbol-local pin coordinate (Y-up) into sheet coordinates (Y-down)."""
    if angle != 0 and mirror is not None:
        raise ValueError(
            "Do not combine non-zero angle with mirror; use pure angle or pure mirror"
        )
    if angle not in (0, 90, 180, 270):
        raise ValueError(
            f"Unsupported symbol angle {angle}; expected 0, 90, 180, or 270"
        )
    if mirror not in (None, "x", "y"):
        raise ValueError(f"Unsupported mirror {mirror!r}; expected None, 'x', or 'y'")

    if mirror == "x":
        rx, ry = px, -py
    elif mirror == "y":
        rx, ry = -px, py
    elif angle == 0:
        rx, ry = px, py
    elif angle == 90:
        rx, ry = -py, px
    elif angle == 180:
        rx, ry = -px, -py
    else:  # 270
        rx, ry = py, -px

    return round(sx + rx, 4), round(sy - ry, 4)


def load_skidl_parts_metadata() -> dict[str, PartMetadata]:
    """Extract component metadata from the active `builtins.default_circuit`."""
    meta: dict[str, PartMetadata] = {}
    circuit = getattr(builtins, "default_circuit", None)
    if circuit is None:
        return meta

    for part in circuit.parts:
        lib_path = str(getattr(part, "lib", ""))
        lib_name = Path(lib_path).stem if lib_path else ""
        if not lib_name:
            lib_name = str(getattr(part, "lib_name", ""))
        sym_name = str(getattr(part, "name", ""))
        lib_id = f"{lib_name}:{sym_name}" if lib_name else sym_name
        fields = {
            str(k): str(v)
            for k, v in getattr(part, "fields", {}).items()
            if v not in (None, "")
        }
        meta[part.ref] = PartMetadata(
            ref=part.ref,
            lib_id=lib_id,
            value=part.value_to_str(),
            footprint=str(getattr(part, "footprint", "")),
            fields=fields,
            dnp=bool(getattr(part, "dnp", False)),
            exclude_from_bom=bool(getattr(part, "exclude_from_bom", False)),
            exclude_from_pos_files=bool(getattr(part, "exclude_from_pos_files", False)),
        )
    return meta


_RESERVED_PROP_NAMES = frozenset(
    {"reference", "value", "footprint", "datasheet", "description"}
)
_TRUTHY_PROP_VALUES = frozenset({"", "1", "true", "yes"})


def load_netlist_parts_metadata(net_path: Path) -> dict[str, PartMetadata]:
    """Extract component metadata directly from a KiCad `.net` S-expression netlist."""
    tree = _parse_sexp(net_path.read_text(encoding="utf-8"))[0]
    comps = _find_child(tree, "components")
    meta: dict[str, PartMetadata] = {}
    if not comps:
        return meta

    for comp in _find_children(comps, "comp"):
        ref_n = _find_child(comp, "ref")
        val_n = _find_child(comp, "value")
        fp_n = _find_child(comp, "footprint")
        ls_n = _find_child(comp, "libsource")
        if not ref_n or not val_n:
            continue
        ref = str(ref_n[1])
        value = str(val_n[1])
        footprint = str(fp_n[1]) if fp_n else ""
        lib_id = ""
        if ls_n:
            lib_n = _find_child(ls_n, "lib")
            part_n = _find_child(ls_n, "part")
            if lib_n and part_n:
                lib_name = Path(str(lib_n[1])).stem
                lib_id = f"{lib_name}:{part_n[1]}"
        fields: dict[str, str] = {}
        fields_n = _find_child(comp, "fields")
        if fields_n:
            for f_n in _find_children(fields_n, "field"):
                name_n = _find_child(f_n, "name")
                if (
                    name_n
                    and len(name_n) >= 2
                    and len(f_n) > 2
                    and isinstance(f_n[2], str)
                    and f_n[2] != ""
                ):
                    fname = str(name_n[1])
                    if fname.lower() not in _RESERVED_PROP_NAMES:
                        fields[fname] = str(f_n[2])

        prop_nodes = list(_find_children(comp, "property"))
        props_n = _find_child(comp, "properties")
        if props_n:
            prop_nodes.extend(_find_children(props_n, "property"))

        dnp = _find_child(comp, "dnp") is not None
        ex_bom = _find_child(comp, "exclude_from_bom") is not None
        ex_pos = _find_child(comp, "exclude_from_pos_files") is not None
        for p_n in prop_nodes:
            pn = _find_child(p_n, "name")
            if not pn or len(pn) < 2:
                continue
            key_l = str(pn[1]).lower()
            pv = _find_child(p_n, "value")
            if pv and len(pv) >= 2:
                val_l = str(pv[1]).strip().lower()
                if key_l == "dnp" and val_l in (_TRUTHY_PROP_VALUES | {"dnp"}):
                    dnp = True
                elif key_l == "exclude_from_bom" and val_l in _TRUTHY_PROP_VALUES:
                    ex_bom = True
                elif key_l == "exclude_from_pos_files" and val_l in _TRUTHY_PROP_VALUES:
                    ex_pos = True
            else:
                if key_l == "dnp":
                    dnp = True
                elif key_l == "exclude_from_bom":
                    ex_bom = True
                elif key_l == "exclude_from_pos_files":
                    ex_pos = True

        meta[ref] = PartMetadata(
            ref=ref,
            lib_id=lib_id,
            value=value,
            footprint=footprint,
            fields=fields,
            dnp=dnp,
            exclude_from_bom=ex_bom,
            exclude_from_pos_files=ex_pos,
        )
    return meta


def _pt_key(pt: tuple[float, float]) -> tuple[int, int]:
    """Quantize a coordinate to 0.001 mm integer units for exact topological comparisons."""
    return (round(pt[0] * 1000), round(pt[1] * 1000))


def _make_effects(
    *,
    size: float = 1.27,
    bold: bool = False,
    justify: str | None = None,
    hide: bool = False,
) -> list[Any]:
    """Build a KiCad `(effects ...)` S-expression without emitting `(justify center)`."""
    font: list[Any] = ["font", ["size", f"{size:g}", f"{size:g}"]]
    if bold:
        font.append(["bold", "yes"])
    effects: list[Any] = ["effects", font]
    j_tokens = [tok for tok in (justify or "").split() if tok != "center"]
    if j_tokens:
        effects.append(["justify", *j_tokens])
    if hide:
        effects.append(["hide", "yes"])
    return effects


def _flip_justify(justify: str, flip_lr: bool) -> str:
    """Swap `left <-> right` justification tokens when symbol rotation/mirroring inverts them."""
    if not flip_lr:
        return justify
    return " ".join(
        "right" if t == "left" else "left" if t == "right" else t
        for t in justify.split()
    )


def _prop_sexp(
    name: str,
    val: str,
    x: float,
    y: float,
    *,
    angle: int = 0,
    size: float = 1.27,
    justify: str | None = None,
    hide: bool = False,
) -> list[Any]:
    """Build a KiCad schematic `(property ...)` S-expression."""
    effects = _make_effects(size=size, justify=justify, hide=hide)
    return [
        "property",
        Quoted(name),
        Quoted(val),
        ["at", f"{x:g}", f"{y:g}", str(angle)],
        effects,
    ]


class SchematicBuilder:
    """Declarative KiCad 10 single-sheet schematic builder with exact pin & junction math."""

    def __init__(
        self,
        project_name: str,
        parts_meta: dict[str, PartMetadata],
        *,
        paper: str = "A3",
        title: str = "",
        date: str = "",
        rev: str = "",
        company: str = "",
        comments: dict[int, str] | None = None,
        symbol_dir: Path | None = None,
    ) -> None:
        self.project_name = project_name
        self.parts_meta = parts_meta
        self.paper = paper
        self.title = title
        self.date = date
        self.rev = rev
        self.company = company
        self.comments = comments or {}
        self.symbol_dir = symbol_dir or _default_symbol_dir()
        self.root_uuid = _det_uuid(f"root:{project_name}")

        self._lib_symbols: dict[str, tuple[list[Any], dict[int, list[PinDef]]]] = {}
        self._symbol_nodes: list[list[Any]] = []
        self._placed: dict[tuple[str, int], PlacedSymbol] = {}
        self._wires: list[tuple[tuple[float, float], tuple[float, float]]] = []
        self._no_connects: list[tuple[float, float]] = []
        self._no_connect_keys: set[tuple[int, int]] = set()
        self._texts: list[list[Any]] = []
        self._pwr_idx = 0
        self._flg_idx = 0
        self._pin_points: set[tuple[int, int]] = set()

    def _ensure_symbol(self, lib_id: str) -> tuple[list[Any], dict[int, list[PinDef]]]:
        """Load and cache a KiCad 10 symbol definition."""
        if lib_id not in self._lib_symbols:
            lib_name, sym_name = lib_id.split(":", 1)
            self._lib_symbols[lib_id] = load_kicad10_symbol(
                lib_name, sym_name, self.symbol_dir
            )
        return self._lib_symbols[lib_id]

    def _unit_pins(self, lib_id: str, unit: int) -> list[PinDef]:
        """Return all pins active for a given symbol unit (unit 0 shared + unit N)."""
        _, by_unit = self._ensure_symbol(lib_id)
        return [*by_unit.get(0, []), *by_unit.get(unit, [])]

    def place(
        self,
        ref: str,
        x: float,
        y: float,
        *,
        angle: int = 0,
        mirror: str | None = None,
        unit: int = 1,
        ref_offset: tuple[float, float] = (2.54, -1.27),
        val_offset: tuple[float, float] = (2.54, 1.27),
        ref_justify: str = "left",
        val_justify: str = "left",
        hide_ref: bool = False,
        hide_val: bool = False,
        ref_size: float = 1.27,
        val_size: float = 1.27,
        prop_angle: int | None = None,
    ) -> PlacedSymbol:
        """Place a component (or specific unit of a multi-unit IC) at sheet `(x, y)`."""
        if ref not in self.parts_meta:
            raise KeyError(f"Component {ref!r} missing from parts metadata")
        if (ref, unit) in self._placed:
            raise ValueError(f"Symbol {ref!r} unit {unit} has already been placed")
        meta = self.parts_meta[ref]
        sx = _snap_grid(x)
        sy = _snap_grid(y)
        lib_sym, _ = self._ensure_symbol(meta.lib_id)
        unit_pins = self._unit_pins(meta.lib_id, unit)

        pin_coords: dict[str, tuple[float, float]] = {}
        by_name: dict[str, list[str]] = {}
        pin_sexps: list[list[Any]] = []
        for p in unit_pins:
            wx, wy = pin_world(sx, sy, angle, mirror, p.x, p.y)
            pin_coords[p.number] = (wx, wy)
            if p.name:
                by_name.setdefault(p.name, []).append(p.number)
            self._pin_points.add(_pt_key((wx, wy)))
            pin_sexps.append(
                [
                    "pin",
                    Quoted(p.number),
                    ["uuid", _det_uuid(f"pin:{ref}:{unit}:{p.number}")],
                ]
            )

        sym_uuid = _det_uuid(f"sym:{ref}:{unit}")
        datasheet = "~"
        description = ""
        for pr in _find_children(lib_sym, "property"):
            if str(pr[1]) == "Datasheet":
                datasheet = str(pr[2])
            elif str(pr[1]) == "Description":
                description = str(pr[2])

        rx, ry = round(sx + ref_offset[0], 4), round(sy + ref_offset[1], 4)
        vx, vy = round(sx + val_offset[0], 4), round(sy + val_offset[1], 4)
        text_ang = (angle % 180) if prop_angle is None else prop_angle
        flip_lr = (
            ((angle in (90, 180)) or (mirror == "y")) if prop_angle is None else False
        )

        node: list[Any] = [
            "symbol",
            ["lib_id", Quoted(meta.lib_id)],
            ["at", f"{sx:g}", f"{sy:g}", str(angle)],
        ]
        if mirror is not None:
            node.append(["mirror", mirror])
        node.extend(
            [
                ["unit", str(unit)],
                ["exclude_from_sim", "no"],
                ["in_bom", "no" if meta.exclude_from_bom else "yes"],
                ["on_board", "no" if meta.exclude_from_pos_files else "yes"],
                ["dnp", "yes" if meta.dnp else "no"],
                ["uuid", sym_uuid],
                _prop_sexp(
                    "Reference",
                    ref,
                    rx,
                    ry,
                    angle=text_ang,
                    size=ref_size,
                    justify=_flip_justify(ref_justify, flip_lr),
                    hide=hide_ref,
                ),
                _prop_sexp(
                    "Value",
                    meta.value,
                    vx,
                    vy,
                    angle=text_ang,
                    size=val_size,
                    justify=_flip_justify(val_justify, flip_lr),
                    hide=hide_val,
                ),
                _prop_sexp("Footprint", meta.footprint, sx, sy, hide=True),
                _prop_sexp("Datasheet", datasheet, sx, sy, hide=True),
                _prop_sexp("Description", description, sx, sy, hide=True),
            ]
        )
        for fk, fv in meta.fields.items():
            if fk.lower() not in _RESERVED_PROP_NAMES:
                node.append(_prop_sexp(fk, fv, sx, sy, hide=True))
        node.extend(pin_sexps)
        node.append(
            [
                "instances",
                [
                    "project",
                    Quoted(self.project_name),
                    [
                        "path",
                        Quoted(f"/{self.root_uuid}"),
                        ["reference", Quoted(ref)],
                        ["unit", str(unit)],
                    ],
                ],
            ]
        )

        self._symbol_nodes.append(node)
        placed = PlacedSymbol(
            ref=ref,
            lib_id=meta.lib_id,
            x=sx,
            y=sy,
            angle=angle,
            mirror=mirror,
            unit=unit,
            pins=pin_coords,
            pin_numbers_by_name=by_name,
        )
        self._placed[(ref, unit)] = placed
        return placed

    def pin(
        self, ref: str, pin_id: int | str, unit: int | None = None
    ) -> tuple[float, float]:
        """Return exact sheet `(x, y)` for a placed symbol's pin number or pin name."""
        pid = str(pin_id)
        candidates = (
            [self._placed[(ref, unit)]]
            if unit is not None
            else [pl for (r, _), pl in self._placed.items() if r == ref]
        )
        if not candidates:
            raise KeyError(f"Symbol {ref!r} (unit={unit}) has not been placed")

        for pl in candidates:
            if pid in pl.pins:
                return pl.pins[pid]
            if pid in pl.pin_numbers_by_name:
                nums = pl.pin_numbers_by_name[pid]
                if len(nums) == 1:
                    return pl.pins[nums[0]]
                raise KeyError(f"Ambiguous pin name {pid!r} on {ref}: matches {nums}")
        raise KeyError(f"Pin {pid!r} not found on {ref!r} (unit={unit})")

    def power(
        self,
        rail: str,
        x: float,
        y: float,
        *,
        angle: int = 0,
        val_offset: tuple[float, float] | None = None,
        val_justify: str = "center",
        pwr_flag: bool = False,
    ) -> tuple[float, float]:
        """Place a `power:<rail>` symbol at `(x, y)` (optionally attaching `power:PWR_FLAG`)."""
        if angle not in (0, 90, 180, 270):
            raise ValueError(
                f"Unsupported power symbol angle {angle}; expected 0, 90, 180, or 270"
            )
        lib_id = f"power:{rail}"
        self._ensure_symbol(lib_id)
        sx = _snap_grid(x)
        sy = _snap_grid(y)
        self._pwr_idx += 1
        ref = f"#PWR{self._pwr_idx:03d}"
        sym_uuid = _det_uuid(f"pwr:{ref}:{sx}:{sy}")
        self._pin_points.add(_pt_key((sx, sy)))

        if val_offset is None:
            if angle == 0:
                val_offset = (0.0, 3.81) if rail == "GND" else (0.0, -3.81)
            elif angle == 180:
                val_offset = (0.0, -3.81) if rail == "GND" else (0.0, 3.81)
            elif angle == 90:
                val_offset = (3.81, 0.0) if rail == "GND" else (-3.81, 0.0)
            else:  # 270
                val_offset = (-3.81, 0.0) if rail == "GND" else (3.81, 0.0)
        vx, vy = round(sx + val_offset[0], 4), round(sy + val_offset[1], 4)
        text_ang = angle % 180
        mapped_justify = _flip_justify(val_justify, angle in (90, 180))

        node: list[Any] = [
            "symbol",
            ["lib_id", Quoted(lib_id)],
            ["at", f"{sx:g}", f"{sy:g}", str(angle)],
            ["unit", "1"],
            ["exclude_from_sim", "yes"],
            ["in_bom", "no"],
            ["on_board", "no"],
            ["dnp", "no"],
            ["fields_autoplaced", "yes"],
            ["uuid", sym_uuid],
            _prop_sexp("Reference", ref, sx, sy, hide=True),
            _prop_sexp(
                "Value",
                rail,
                vx,
                vy,
                angle=text_ang,
                justify=mapped_justify,
            ),
            _prop_sexp("Footprint", "", sx, sy, hide=True),
            _prop_sexp("Datasheet", "", sx, sy, hide=True),
            _prop_sexp("Description", "", sx, sy, hide=True),
            ["pin", Quoted("1"), ["uuid", _det_uuid(f"pwr_pin:{ref}")]],
            [
                "instances",
                [
                    "project",
                    Quoted(self.project_name),
                    [
                        "path",
                        Quoted(f"/{self.root_uuid}"),
                        ["reference", Quoted(ref)],
                        ["unit", "1"],
                    ],
                ],
            ],
        ]
        self._symbol_nodes.append(node)

        if pwr_flag:
            self._ensure_symbol("power:PWR_FLAG")
            self._flg_idx += 1
            fref = f"#FLG{self._flg_idx:02d}"
            fuuid = _det_uuid(f"flg:{fref}:{sx}:{sy}")
            fnode: list[Any] = [
                "symbol",
                ["lib_id", Quoted("power:PWR_FLAG")],
                ["at", f"{sx:g}", f"{sy:g}", str(angle)],
                ["unit", "1"],
                ["exclude_from_sim", "yes"],
                ["in_bom", "no"],
                ["on_board", "no"],
                ["dnp", "no"],
                ["fields_autoplaced", "yes"],
                ["uuid", fuuid],
                _prop_sexp("Reference", fref, sx, sy, hide=True),
                _prop_sexp("Value", "PWR_FLAG", sx, sy, hide=True),
                _prop_sexp("Footprint", "", sx, sy, hide=True),
                _prop_sexp("Datasheet", "", sx, sy, hide=True),
                _prop_sexp("Description", "", sx, sy, hide=True),
                ["pin", Quoted("1"), ["uuid", _det_uuid(f"flg_pin:{fref}")]],
                [
                    "instances",
                    [
                        "project",
                        Quoted(self.project_name),
                        [
                            "path",
                            Quoted(f"/{self.root_uuid}"),
                            ["reference", Quoted(fref)],
                            ["unit", "1"],
                        ],
                    ],
                ],
            ]
            self._symbol_nodes.append(fnode)

        return (sx, sy)

    def wire(self, *points: tuple[float, float]) -> None:
        """Add orthogonal wire segments connecting consecutive `(x, y)` points."""
        if len(points) < 2:
            raise ValueError("wire() requires at least 2 points")
        for idx in range(len(points) - 1):
            p1, p2 = points[idx], points[idx + 1]
            x1, y1 = round(p1[0], 4), round(p1[1], 4)
            x2, y2 = round(p2[0], 4), round(p2[1], 4)
            if _pt_key((x1, y1)) == _pt_key((x2, y2)):
                continue
            if abs(x1 - x2) > 1e-3 and abs(y1 - y2) > 1e-3:
                raise ValueError(
                    f"Non-orthogonal wire segment {(x1, y1)} -> {(x2, y2)}"
                )
            self._wires.append(((x1, y1), (x2, y2)))

    def wire_hv(self, p1: tuple[float, float], p2: tuple[float, float]) -> None:
        """Route horizontally from `p1` to `(p2.x, p1.y)`, then vertically to `p2`."""
        self.wire(p1, (p2[0], p1[1]), p2)

    def wire_vh(self, p1: tuple[float, float], p2: tuple[float, float]) -> None:
        """Route vertically from `p1` to `(p1.x, p2.y)`, then horizontally to `p2`."""
        self.wire(p1, (p1[0], p2[1]), p2)

    def no_connect(self, pt: tuple[float, float]) -> None:
        """Place an ERC no-connect marker at `pt` (deduplicated)."""
        rx, ry = round(pt[0], 4), round(pt[1], 4)
        key = _pt_key((rx, ry))
        if key not in self._no_connect_keys:
            self._no_connect_keys.add(key)
            self._no_connects.append((rx, ry))

    def text(
        self,
        content: str,
        x: float,
        y: float,
        *,
        size: float = 1.524,
        bold: bool = False,
        justify: str = "left",
        angle: int = 0,
    ) -> None:
        """Add free-form schematic label text."""
        effects = _make_effects(size=size, bold=bold, justify=justify)
        self._texts.append(
            [
                "text",
                Quoted(content),
                ["exclude_from_sim", "no"],
                ["at", f"{round(x, 4):g}", f"{round(y, 4):g}", str(angle)],
                effects,
                ["uuid", _det_uuid(f"txt:{content}:{x}:{y}:{len(self._texts)}")],
            ]
        )

    def label(
        self,
        name: str,
        x: float,
        y: float,
        *,
        angle: int = 0,
        size: float = 1.27,
        justify: str = "left",
    ) -> tuple[float, float]:
        """Place a KiCad net `(label ...)` on the grid at `(x, y)`."""
        if angle not in (0, 90, 180, 270):
            raise ValueError(
                f"Unsupported label angle {angle}; expected 0, 90, 180, or 270"
            )
        sx = _snap_grid(x)
        sy = _snap_grid(y)
        effects = _make_effects(size=size, justify=justify)
        self._texts.append(
            [
                "label",
                Quoted(name),
                ["at", f"{sx:g}", f"{sy:g}", str(angle)],
                ["fields_autoplaced", "yes"],
                effects,
                ["uuid", _det_uuid(f"lbl:{name}:{sx}:{sy}:{len(self._texts)}")],
            ]
        )
        return (sx, sy)

    def _compute_junctions(self) -> list[tuple[float, float]]:
        """Compute exact KiCad junction dots at every T-intersection and >=3-way node."""
        endpoint_counts: dict[tuple[int, int], int] = {}
        coord_by_key: dict[tuple[int, int], tuple[float, float]] = {}

        seen_segs: set[tuple[tuple[int, int], tuple[int, int]]] = set()
        segs: list[tuple[tuple[int, int], tuple[int, int]]] = []
        for p1, p2 in self._wires:
            k1, k2 = _pt_key(p1), _pt_key(p2)
            if k1 == k2:
                continue
            canon = (min(k1, k2), max(k1, k2))
            if canon in seen_segs:
                continue
            seen_segs.add(canon)
            segs.append((k1, k2))
            coord_by_key[k1] = p1
            coord_by_key[k2] = p2
            endpoint_counts[k1] = endpoint_counts.get(k1, 0) + 1
            endpoint_counts[k2] = endpoint_counts.get(k2, 0) + 1

        junction_keys: set[tuple[int, int]] = set()
        for k, cnt in endpoint_counts.items():
            if cnt + (1 if k in self._pin_points else 0) >= 3:
                junction_keys.add(k)

        test_points = set(endpoint_counts.keys()) | self._pin_points
        for k1, k2 in segs:
            x1, y1 = k1
            x2, y2 = k2
            if x1 == x2:
                ymin, ymax = (y1, y2) if y1 < y2 else (y2, y1)
                for pt in test_points:
                    if pt[0] == x1 and ymin < pt[1] < ymax:
                        junction_keys.add(pt)
                        coord_by_key.setdefault(pt, (pt[0] / 1000.0, pt[1] / 1000.0))
            elif y1 == y2:
                xmin, xmax = (x1, x2) if x1 < x2 else (x2, x1)
                for pt in test_points:
                    if pt[1] == y1 and xmin < pt[0] < xmax:
                        junction_keys.add(pt)
                        coord_by_key.setdefault(pt, (pt[0] / 1000.0, pt[1] / 1000.0))

        return sorted(
            (coord_by_key[k] for k in junction_keys), key=lambda c: (c[1], c[0])
        )

    def to_sexp_str(self) -> str:
        """Render the complete KiCad 10 `.kicad_sch` S-expression string."""
        tb_entries: list[Any] = []
        if self.title:
            tb_entries.append(["title", Quoted(self.title)])
        if self.date:
            tb_entries.append(["date", Quoted(self.date)])
        if self.rev:
            tb_entries.append(["rev", Quoted(self.rev)])
        if self.company:
            tb_entries.append(["company", Quoted(self.company)])
        for cnum in sorted(self.comments):
            tb_entries.append(["comment", str(cnum), Quoted(self.comments[cnum])])

        lib_sym_list: list[Any] = ["lib_symbols"]
        for lib_id in sorted(self._lib_symbols):
            lib_sym_list.append(self._lib_symbols[lib_id][0])

        root: list[Any] = [
            "kicad_sch",
            ["version", "20251024"],
            ["generator", Quoted("eeschema")],
            ["generator_version", Quoted("10.0")],
            ["uuid", self.root_uuid],
            ["paper", Quoted(self.paper)],
        ]
        if tb_entries:
            root.append(["title_block", *tb_entries])
        root.append(lib_sym_list)

        for jx, jy in self._compute_junctions():
            root.append(
                [
                    "junction",
                    ["at", f"{jx:g}", f"{jy:g}"],
                    ["diameter", "0"],
                    ["color", "0", "0", "0", "0"],
                    ["uuid", _det_uuid(f"junc:{jx}:{jy}")],
                ]
            )

        for nx, ny in self._no_connects:
            root.append(
                [
                    "no_connect",
                    ["at", f"{nx:g}", f"{ny:g}"],
                    ["uuid", _det_uuid(f"nc:{nx}:{ny}")],
                ]
            )

        seen_wires: set[tuple[tuple[int, int], tuple[int, int]]] = set()
        for p1, p2 in self._wires:
            k1, k2 = _pt_key(p1), _pt_key(p2)
            canon = (min(k1, k2), max(k1, k2))
            if canon in seen_wires:
                continue
            seen_wires.add(canon)
            root.append(
                [
                    "wire",
                    [
                        "pts",
                        ["xy", f"{p1[0]:g}", f"{p1[1]:g}"],
                        ["xy", f"{p2[0]:g}", f"{p2[1]:g}"],
                    ],
                    ["stroke", ["width", "0"], ["type", "default"]],
                    ["uuid", _det_uuid(f"wire:{p1[0]}:{p1[1]}:{p2[0]}:{p2[1]}")],
                ]
            )

        root.extend(self._texts)
        root.extend(self._symbol_nodes)
        root.append(["sheet_instances", ["path", Quoted("/"), ["page", Quoted("1")]]])
        root.append(["embedded_fonts", "no"])
        return _format_sexp(root) + "\n"

    def write(self, path: str | Path) -> Path:
        """Write the `.kicad_sch` file to disk."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.to_sexp_str(), encoding="utf-8")
        return out


def _is_unconnected_net(name: str) -> bool:
    """Return True if a netlist net name represents an unconnected/NC stub."""
    stripped = name.lstrip("/")
    return stripped in ("", "NC", "~") or stripped.startswith(
        ("unconnected-", "unconnected_")
    )


def _parse_netlist_graph(
    net_path: Path,
) -> tuple[
    dict[str, tuple[str, str]],
    dict[frozenset[tuple[str, str]], str],
    dict[tuple[str, str], str],
]:
    """Parse a KiCad netlist into `(comps, multi_pin_nets, single_pin_nets)`."""
    tree = _parse_sexp(net_path.read_text(encoding="utf-8"))[0]
    comps: dict[str, tuple[str, str]] = {}
    comps_node = _find_child(tree, "components")
    if comps_node:
        for comp in _find_children(comps_node, "comp"):
            ref_n = _find_child(comp, "ref")
            val_n = _find_child(comp, "value")
            fp_n = _find_child(comp, "footprint")
            if not ref_n or not val_n:
                continue
            ref = str(ref_n[1])
            if ref.startswith("#"):
                continue
            comps[ref] = (str(val_n[1]), str(fp_n[1]) if fp_n else "")

    multi_nets: dict[frozenset[tuple[str, str]], str] = {}
    single_nets: dict[tuple[str, str], str] = {}
    nets_node = _find_child(tree, "nets")
    if nets_node:
        for net in _find_children(nets_node, "net"):
            name_n = _find_child(net, "name")
            name = str(name_n[1]) if name_n and len(name_n) >= 2 else ""
            raw_pins: set[tuple[str, str]] = set()
            for nd in _find_children(net, "node"):
                ref_n = _find_child(nd, "ref")
                pin_n = _find_child(nd, "pin")
                if not ref_n or not pin_n or len(ref_n) < 2 or len(pin_n) < 2:
                    continue
                ref = str(ref_n[1])
                if ref.startswith("#"):
                    continue
                raw_pins.add((ref, str(pin_n[1])))

            if len(raw_pins) >= 2:
                multi_nets[frozenset(raw_pins)] = name
            elif len(raw_pins) == 1 and not _is_unconnected_net(name):
                pin_key = next(iter(raw_pins))
                single_nets[pin_key] = name.lstrip("/")
    return comps, multi_nets, single_nets


def verify_schematic(
    sch_path: str | Path,
    expected_net_path: str | Path,
    *,
    kicad_cli: str | Path | None = None,
) -> dict[str, Any]:
    """Run KiCad 10 ERC and verify 100% component & net equivalence against `expected_net_path`."""
    sch = Path(sch_path).resolve()
    exp_net = Path(expected_net_path).resolve()
    cli = Path(kicad_cli) if kicad_cli else _default_kicad_cli()

    env = os.environ.copy()
    env.setdefault("XDG_DATA_HOME", "/tmp/xdg_data")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        erc_json = tmp / "erc.json"
        sch_net = tmp / "exported.net"

        erc_res = subprocess.run(
            [
                str(cli),
                "sch",
                "erc",
                "--severity-all",
                "--format",
                "json",
                "-o",
                str(erc_json),
                str(sch),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        if erc_res.returncode != 0:
            raise RuntimeError(
                f"kicad-cli sch erc failed (rc={erc_res.returncode}): {erc_res.stderr}"
            )

        erc_data = json.loads(erc_json.read_text(encoding="utf-8"))
        violations = [
            v for s in erc_data.get("sheets", []) for v in s.get("violations", [])
        ]
        errors = [v for v in violations if v.get("severity") == "error"]
        warnings = [v for v in violations if v.get("severity") != "error"]
        lib_warns = [
            w
            for w in warnings
            if w.get("type") in ("lib_symbol_issues", "footprint_link_issues")
        ]
        other_warns = [
            w
            for w in warnings
            if w.get("type") not in ("lib_symbol_issues", "footprint_link_issues")
        ]
        if errors or other_warns:
            lines = [
                f"  [ERROR] {e.get('type')}: {e.get('description')}" for e in errors
            ] + [
                f"  [WARN] {w.get('type')}: {w.get('description')}" for w in other_warns
            ]
            raise RuntimeError(
                f"KiCad ERC reported {len(errors)} error(s) and "
                f"{len(other_warns)} warning(s):\n" + "\n".join(lines)
            )

        net_res = subprocess.run(
            [
                str(cli),
                "sch",
                "export",
                "netlist",
                "--format",
                "kicadsexpr",
                "-o",
                str(sch_net),
                str(sch),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        if net_res.returncode != 0:
            raise RuntimeError(f"kicad-cli sch export netlist failed: {net_res.stderr}")

        exp_comps, exp_multi, exp_single = _parse_netlist_graph(exp_net)
        got_comps, got_multi, got_single = _parse_netlist_graph(sch_net)

        if exp_comps != got_comps:
            missing = sorted(set(exp_comps) - set(got_comps))
            extra = sorted(set(got_comps) - set(exp_comps))
            diff = {
                r: (exp_comps[r], got_comps[r])
                for r in sorted(set(exp_comps) & set(got_comps))
                if exp_comps[r] != got_comps[r]
            }
            raise RuntimeError(
                f"Component mismatch vs {exp_net.name}: "
                f"missing={missing}, extra={extra}, diff={diff}"
            )

        exp_set = set(exp_multi.keys())
        got_set = set(got_multi.keys())
        if exp_set != got_set or exp_single != got_single:
            missing_nets = [
                (exp_multi[k], sorted(k))
                for k in sorted(exp_set - got_set, key=lambda x: exp_multi[x])
            ]
            extra_nets = [
                (got_multi[k], sorted(k))
                for k in sorted(got_set - exp_set, key=lambda x: got_multi[x])
            ]
            single_missing = {
                k: v for k, v in exp_single.items() if k not in got_single
            }
            single_extra = {k: v for k, v in got_single.items() if k not in exp_single}
            single_diff = {
                k: (exp_single[k], got_single[k])
                for k in sorted(set(exp_single) & set(got_single))
                if exp_single[k] != got_single[k]
            }
            raise RuntimeError(
                f"Netlist connectivity mismatch vs {exp_net.name}!\n"
                f"  Expected multi-pin nets not matched ({len(missing_nets)}): {missing_nets}\n"
                f"  Schematic multi-pin nets unexpected ({len(extra_nets)}): {extra_nets}\n"
                f"  Single-pin nets missing={single_missing}, extra={single_extra}, "
                f"diff={single_diff}"
            )

        summary = {
            "schematic": sch.name,
            "netlist": exp_net.name,
            "components": len(got_comps),
            "multi_pin_nets": len(got_multi),
            "single_pin_nets": len(got_single),
            "total_nets": len(got_multi) + len(got_single),
            "lib_notices": len(lib_warns),
        }
        print(
            f"Verified {sch.name}: 0 ERC errors (0 warnings, "
            f"{len(lib_warns)} unconfigured-lib notices), "
            f"{len(got_comps)} components & {summary['total_nets']} nets "
            f"({len(got_multi)} multi-pin + {len(got_single)} single-pin) "
            f"match {exp_net.name} 100%."
        )
        return summary
