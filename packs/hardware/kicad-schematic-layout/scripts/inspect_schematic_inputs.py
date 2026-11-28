#!/usr/bin/env python3
"""Inspect KiCad .net netlists / KiCad 10 .kicad_sym pinouts and verify .kicad_sch outputs."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

try:
    import sch_builder as sb
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sch_builder as sb


def _collect_graphic_coords(node: list[Any], xs: list[float], ys: list[float]) -> None:
    """Collect graphic coordinates from a symbol unit child node for bbox estimation."""
    for item in node[1:]:
        if not isinstance(item, list) or not item:
            continue
        if item[0] == "pts":
            for pt in sb._find_children(item, "xy"):
                xs.append(float(pt[1]))
                ys.append(float(pt[2]))
        elif item[0] in ("start", "end", "center"):
            xs.append(float(item[1]))
            ys.append(float(item[2]))


def _resolve_extends_chain(lib_path: Path, sym_name: str) -> list[str]:
    """Return the `(extends ...)` inheritance chain for `sym_name`."""
    chain: list[str] = []
    node = sb._extract_raw_symbol_sexp(lib_path, sym_name)
    while True:
        ext = sb._find_child(node, "extends")
        if not ext:
            break
        parent = str(ext[1])
        chain.append(parent)
        node = sb._extract_raw_symbol_sexp(lib_path, parent)
    return chain


def _inspect_symbol(lib_name: str, sym_name: str, symbol_dir: Path) -> bool:
    """Print resolved extends chain, pins, and graphic bounding box for a KiCad 10 symbol."""
    lib_path = symbol_dir / f"{lib_name}.kicad_sym"
    if not lib_path.exists():
        print(f"MISSING LIB: {lib_path}", file=sys.stderr)
        return False

    try:
        chain = _resolve_extends_chain(lib_path, sym_name)
        flat, _ = sb.load_kicad10_symbol(lib_name, sym_name, symbol_dir=symbol_dir)
    except (KeyError, ValueError) as exc:
        print(f"MISSING SYMBOL {lib_name}:{sym_name}: {exc}", file=sys.stderr)
        return False

    xs: list[float] = []
    ys: list[float] = []
    pins: list[tuple[int, str, str, str, float, float, float, float]] = []
    unit_re = re.compile(r"_(\d+)_(\d+)$")

    for sub in sb._find_children(flat, "symbol"):
        m = unit_re.search(str(sub[1]))
        if not m:
            continue
        unit_idx, style_idx = int(m.group(1)), int(m.group(2))
        if style_idx not in (0, 1):
            continue
        for child in sub[2:]:
            if not isinstance(child, list) or not child:
                continue
            if child[0] == "pin":
                ptype = str(child[1])
                at_n = sb._find_child(child, "at")
                name_n = sb._find_child(child, "name")
                num_n = sb._find_child(child, "number")
                len_n = sb._find_child(child, "length")
                if at_n and name_n and num_n:
                    px, py, pang = float(at_n[1]), float(at_n[2]), float(at_n[3])
                    plen = float(len_n[1]) if len_n else 0.0
                    pins.append(
                        (
                            unit_idx,
                            str(num_n[1]),
                            str(name_n[1]),
                            ptype,
                            px,
                            py,
                            pang,
                            plen,
                        )
                    )
                    xs.append(px)
                    ys.append(py)
            else:
                _collect_graphic_coords(child, xs, ys)

    bbox = (
        f"X=[{min(xs):.2f}, {max(xs):.2f}] Y=[{min(ys):.2f}, {max(ys):.2f}]"
        if xs
        else "empty"
    )
    print(f"{lib_name}:{sym_name} extends={chain} bbox=({bbox})")
    for unit_idx, pnum, pname, ptype, px, py, pang, plen in sorted(
        pins, key=lambda p: (p[0], p[1])
    ):
        print(
            f"  u{unit_idx} pin {pnum:>3s} ({pname:6s}) {ptype:10s} "
            f"at=({px:6.2f}, {py:6.2f}) ang={pang:3.0f} len={plen:.3f}"
        )
    return True


def _print_netlist_summary(net_path: Path) -> set[str]:
    """Print components and nets from `.net` and return the unique `Lib:Sym` set."""
    parts = sb.load_netlist_parts_metadata(net_path)
    _, multi_nets, single_nets = sb._parse_netlist_graph(net_path)
    lib_ids: set[str] = set()

    phys_refs = sorted(r for r in parts if not r.startswith("#"))
    print(f"=== COMPONENTS ({len(phys_refs)}) ===")
    for ref in phys_refs:
        meta = parts[ref]
        if meta.lib_id:
            lib_ids.add(meta.lib_id)
        flags: list[str] = []
        if meta.dnp:
            flags.append("DNP")
        if meta.exclude_from_bom:
            flags.append("NO-BOM")
        flag_str = f" [{' '.join(flags)}]" if flags else ""
        print(
            f"  {ref:8s} | {meta.value:18s} | {meta.lib_id:34s} | "
            f"{meta.footprint}{flag_str}"
        )

    total_nets = len(multi_nets) + len(single_nets)
    print(f"\n=== NETS ({total_nets}) ===")
    for pinset, name in sorted(multi_nets.items(), key=lambda kv: kv[1]):
        pins_str = ", ".join(f"{r}.{p}" for r, p in sorted(pinset))
        print(f"  {name:18s} ({len(pinset):2d}): {pins_str}")
    for (ref, pin), name in sorted(single_nets.items(), key=lambda kv: (kv[1], kv[0])):
        print(f"  {name:18s} ( 1): {ref}.{pin}")
    return lib_ids


def _verify_schematic(sch_path: Path, net_path: Path, kicad_cli: Path) -> int:
    """Run KiCad 10 ERC and compare schematic netlist against `.net`. Returns exit code."""
    try:
        summary = sb.verify_schematic(
            sch_path, net_path, kicad_cli=kicad_cli, quiet=True
        )
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        f"PASS: {summary['schematic']} -> 0 ERC errors (0 warnings, "
        f"{summary['lib_notices']} unconfigured-lib notices), "
        f"{summary['components']} components & {summary['total_nets']} nets "
        f"match {summary['netlist']} 100%."
    )
    if summary["lib_notices"] > 0:
        print(
            "NOTE: unconfigured-lib notices were emitted because global KiCad "
            "sym-lib-table/fp-lib-table could not be read in this environment; "
            "re-run `kicad-cli sch erc --severity-all` with global library tables "
            "accessible to confirm 0 `lib_symbol_mismatch` warnings."
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--net", type=Path, help="Path to authoritative KiCad .net netlist"
    )
    parser.add_argument(
        "--symbols-from-net",
        action="store_true",
        help="Inspect KiCad 10 symbol pinouts for every symbol referenced in --net",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=[],
        help="Explicit Lib:Symbol names to inspect (e.g. Device:R Transistor_BJT:BC848)",
    )
    parser.add_argument(
        "--symbol-dir",
        type=Path,
        default=sb._default_symbol_dir(),
        help="Directory containing KiCad 10 .kicad_sym libraries",
    )
    parser.add_argument(
        "--verify",
        type=Path,
        help="Verify a .kicad_sch file via kicad-cli ERC and netlist diff against --net",
    )
    parser.add_argument(
        "--kicad-cli",
        type=Path,
        default=sb._default_kicad_cli(),
        help="Path to kicad-cli executable",
    )
    args = parser.parse_args()

    if args.verify:
        if not args.net:
            parser.error("--verify requires --net")
        return _verify_schematic(
            args.verify.resolve(), args.net.resolve(), args.kicad_cli
        )

    lib_ids = list(args.symbols)
    if args.net:
        net_lib_ids = _print_netlist_summary(args.net.resolve())
        if args.symbols_from_net:
            lib_ids.extend(sorted(net_lib_ids))

    exit_code = 0
    if lib_ids:
        print("\n=== KICAD 10 SYMBOL PINOUTS ===")
        seen: set[str] = set()
        for item in lib_ids:
            if ":" not in item:
                print(
                    f"INVALID SYMBOL SPEC {item!r}: expected Lib:Symbol",
                    file=sys.stderr,
                )
                exit_code = 1
                continue
            if item in seen:
                continue
            seen.add(item)
            lib_name, sym_name = item.split(":", 1)
            if not _inspect_symbol(lib_name, sym_name, args.symbol_dir):
                exit_code = 1

    if not args.net and not lib_ids:
        parser.print_help()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
