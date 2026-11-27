#!/usr/bin/env python3
"""Verify a KiCad 10 .kicad_sch with kicad-cli ERC and SKiDL .net pin-group parity.

Usage:
    python3 .agents/skills/skidl/scripts/verify_schematic.py schematic/board.kicad_sch
    python3 .agents/skills/skidl/scripts/verify_schematic.py schematic/board.kicad_sch --netlist board.net
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

MACOS_KICAD_BIN = pathlib.Path("/Applications/KiCad/KiCad.app/Contents/MacOS")
MACOS_KICAD_SYMBOLS = pathlib.Path(
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"
)
MACOS_KICAD_FOOTPRINTS = pathlib.Path(
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
)

VIRTUAL_REF_PREFIXES = ("#PWR", "#FLG")
UNCONNECTED_NET_PREFIXES = ("unconnected-", "unconnected_")
UNCONNECTED_NET_NAMES = {"NC", "/NC", "~"}


def configure_kicad_env(
    env: dict[str, str] | None = None, *, mutate_os: bool = False
) -> dict[str, str]:
    """Populate KiCad / SKiDL environment defaults and prepend macOS KiCad CLI dir."""
    target = os.environ if mutate_os else dict(os.environ if env is None else env)
    target.setdefault("XDG_DATA_HOME", "/tmp/xdg_data")
    target.setdefault("MPLCONFIGDIR", "/tmp/mpl_config")

    if MACOS_KICAD_SYMBOLS.is_dir():
        sym_dir = str(MACOS_KICAD_SYMBOLS)
        target.setdefault("KICAD_SYMBOL_DIR", sym_dir)
        for ver in (6, 7, 8, 9, 10):
            target.setdefault(f"KICAD{ver}_SYMBOL_DIR", sym_dir)

    if MACOS_KICAD_FOOTPRINTS.is_dir():
        target.setdefault("KICAD10_FOOTPRINT_DIR", str(MACOS_KICAD_FOOTPRINTS))

    if MACOS_KICAD_BIN.is_dir():
        bin_dir = str(MACOS_KICAD_BIN)
        current_path = target.get("PATH", "")
        path_parts = [p for p in current_path.split(os.pathsep) if p]
        if bin_dir not in path_parts:
            target["PATH"] = os.pathsep.join([bin_dir, *path_parts])

    return target


def parse_sexpr(text: str) -> list:
    """Parse a KiCad S-expression string into nested Python lists and strings."""
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch == "#":
            while i < n and text[i] != "\n":
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
            if len(stack) <= 1:
                raise ValueError("Unexpected ')' in S-expression")
            stack.pop()
        else:
            stack[-1].append(tok)
    if len(stack) != 1 or not stack[0]:
        raise ValueError("Malformed S-expression: unclosed '(' or empty input")
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


def _is_virtual_ref(ref: str) -> bool:
    return ref.startswith(VIRTUAL_REF_PREFIXES)


def _is_unconnected_net(net_name: str) -> bool:
    stripped = net_name.lstrip("/")
    return (
        net_name in UNCONNECTED_NET_NAMES
        or stripped in UNCONNECTED_NET_NAMES
        or stripped.startswith(UNCONNECTED_NET_PREFIXES)
    )


def parse_netlist_connectivity(net_path: pathlib.Path) -> dict:
    """Extract physical component refs, NO_LIB errors, and >=2-pin net groups."""
    tree = parse_sexpr(net_path.read_text(encoding="utf-8"))
    comps_node = _find_child(tree, "components")
    nets_node = _find_child(tree, "nets")
    if comps_node is None or nets_node is None:
        raise ValueError(f"Missing components or nets section in {net_path}")

    physical_refs: set[str] = set()
    no_lib_refs: list[str] = []
    for comp in _find_children(comps_node, "comp"):
        ref_node = _find_child(comp, "ref")
        if not ref_node or len(ref_node) < 2:
            continue
        ref = str(ref_node[1])
        if _is_virtual_ref(ref):
            continue
        physical_refs.add(ref)

        libsource = _find_child(comp, "libsource")
        if libsource:
            lib_node = _find_child(libsource, "lib")
            if lib_node and len(lib_node) >= 2 and lib_node[1] == "NO_LIB":
                no_lib_refs.append(ref)

    groups: dict[frozenset[tuple[str, str]], list[str]] = {}
    pin_to_net: dict[tuple[str, str], str] = {}
    for net_node in _find_children(nets_node, "net"):
        name_node = _find_child(net_node, "name")
        net_name = str(name_node[1]) if name_node and len(name_node) >= 2 else ""

        physical_pins: set[tuple[str, str]] = set()
        for nd in _find_children(net_node, "node"):
            ref_n = _find_child(nd, "ref")
            pin_n = _find_child(nd, "pin")
            if not (ref_n and pin_n and len(ref_n) >= 2 and len(pin_n) >= 2):
                continue
            ref = str(ref_n[1])
            pin = str(pin_n[1])
            if _is_virtual_ref(ref):
                continue
            physical_pins.add((ref, pin))

        if _is_unconnected_net(net_name):
            for pin_ref in physical_pins:
                pin_to_net.setdefault(pin_ref, net_name)
            continue

        for pin_ref in physical_pins:
            pin_to_net[pin_ref] = net_name

        if len(physical_pins) >= 2:
            key = frozenset(physical_pins)
            groups.setdefault(key, []).append(net_name)

    return {
        "physical_refs": physical_refs,
        "no_lib_refs": sorted(no_lib_refs),
        "groups": groups,
        "pin_to_net": pin_to_net,
    }


def _format_pin_group(group: frozenset[tuple[str, str]]) -> str:
    return ", ".join(f"{ref}:{pin}" for ref, pin in sorted(group))


def compare_netlist_parity(
    skidl_net: pathlib.Path, sch_net: pathlib.Path
) -> dict[str, object]:
    """Compare physical components and >=2-pin net groups between two .net files."""
    skidl_data = parse_netlist_connectivity(skidl_net)
    sch_data = parse_netlist_connectivity(sch_net)

    no_lib_refs: list[str] = skidl_data["no_lib_refs"]
    skidl_refs: set[str] = skidl_data["physical_refs"]
    sch_refs: set[str] = sch_data["physical_refs"]

    missing_in_schematic = sorted(skidl_refs - sch_refs)
    extra_in_schematic = sorted(sch_refs - skidl_refs)

    skidl_groups: dict[frozenset[tuple[str, str]], list[str]] = skidl_data["groups"]
    sch_groups: dict[frozenset[tuple[str, str]], list[str]] = sch_data["groups"]
    sch_pin_to_net: dict[tuple[str, str], str] = sch_data["pin_to_net"]
    skidl_pin_to_net: dict[tuple[str, str], str] = skidl_data["pin_to_net"]

    missing_groups: list[dict[str, object]] = []
    for grp in sorted(skidl_groups.keys() - sch_groups.keys(), key=_format_pin_group):
        pin_states = {
            f"{ref}:{pin}": sch_pin_to_net.get((ref, pin), "<unlisted>")
            for ref, pin in sorted(grp)
        }
        missing_groups.append(
            {
                "skidl_nets": skidl_groups[grp],
                "pins": [f"{ref}:{pin}" for ref, pin in sorted(grp)],
                "schematic_pin_nets": pin_states,
            }
        )

    extra_groups: list[dict[str, object]] = []
    for grp in sorted(sch_groups.keys() - skidl_groups.keys(), key=_format_pin_group):
        pin_states = {
            f"{ref}:{pin}": skidl_pin_to_net.get((ref, pin), "<unlisted>")
            for ref, pin in sorted(grp)
        }
        extra_groups.append(
            {
                "schematic_nets": sch_groups[grp],
                "pins": [f"{ref}:{pin}" for ref, pin in sorted(grp)],
                "skidl_pin_nets": pin_states,
            }
        )

    passed = not (
        no_lib_refs
        or missing_in_schematic
        or extra_in_schematic
        or missing_groups
        or extra_groups
    )

    return {
        "passed": passed,
        "skidl_component_count": len(skidl_refs),
        "schematic_component_count": len(sch_refs),
        "skidl_group_count": len(skidl_groups),
        "schematic_group_count": len(sch_groups),
        "no_lib_refs": no_lib_refs,
        "missing_in_schematic": missing_in_schematic,
        "extra_in_schematic": extra_in_schematic,
        "missing_pin_groups": missing_groups,
        "extra_pin_groups": extra_groups,
    }


def resolve_kicad_cli(explicit_path: str | None, env: dict[str, str]) -> str | None:
    """Resolve kicad-cli binary from explicit flag, PATH, or macOS bundle."""
    if explicit_path:
        p = pathlib.Path(explicit_path)
        return (
            str(p) if p.is_file() else shutil.which(explicit_path, path=env.get("PATH"))
        )
    found = shutil.which("kicad-cli", path=env.get("PATH"))
    if found:
        return found
    candidate = MACOS_KICAD_BIN / "kicad-cli"
    return str(candidate) if candidate.is_file() else None


def run_erc(
    schematic: pathlib.Path,
    kicad_cli: str,
    env: dict[str, str],
    *,
    allowed_warnings: set[str],
    allow_all_warnings: bool,
    erc_output: pathlib.Path | None,
) -> dict[str, object]:
    """Execute `kicad-cli sch erc --severity-all --format json` and classify violations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = (
            erc_output if erc_output is not None else pathlib.Path(tmpdir) / "erc.json"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            kicad_cli,
            "sch",
            "erc",
            "--severity-all",
            "--format",
            "json",
            "--output",
            str(out_path),
            str(schematic),
        ]
        proc = subprocess.run(cmd, check=False, env=env, capture_output=True, text=True)
        if proc.returncode != 0 or not out_path.is_file():
            raise RuntimeError(
                f"kicad-cli sch erc failed (exit {proc.returncode}): {proc.stderr.strip()}"
            )
        report = json.loads(out_path.read_text(encoding="utf-8"))

    errors: list[dict[str, object]] = []
    disallowed_warnings: list[dict[str, object]] = []
    allowed_warning_items: list[dict[str, object]] = []
    excluded_count = 0

    for sheet in report.get("sheets") or []:
        sheet_path = sheet.get("path", "/")
        for v in sheet.get("violations") or []:
            if v.get("excluded"):
                excluded_count += 1
                continue
            item = {
                "sheet": sheet_path,
                "type": v.get("type", "unknown"),
                "severity": v.get("severity", "unknown"),
                "description": v.get("description", ""),
            }
            severity = item["severity"]
            v_type = str(item["type"])
            if severity == "error":
                errors.append(item)
            elif severity == "warning":
                if allow_all_warnings or v_type in allowed_warnings:
                    allowed_warning_items.append(item)
                else:
                    disallowed_warnings.append(item)
            else:
                disallowed_warnings.append(item)

    return {
        "passed": not errors and not disallowed_warnings,
        "kicad_version": report.get("kicad_version"),
        "error_count": len(errors),
        "disallowed_warning_count": len(disallowed_warnings),
        "allowed_warning_count": len(allowed_warning_items),
        "excluded_count": excluded_count,
        "errors": errors,
        "disallowed_warnings": disallowed_warnings,
        "allowed_warnings": allowed_warning_items,
    }


def export_schematic_netlist(
    schematic: pathlib.Path,
    kicad_cli: str,
    env: dict[str, str],
    out_path: pathlib.Path,
) -> None:
    """Run `kicad-cli sch export netlist --format kicadsexpr`."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        kicad_cli,
        "sch",
        "export",
        "netlist",
        "--format",
        "kicadsexpr",
        "--output",
        str(out_path),
        str(schematic),
    ]
    proc = subprocess.run(cmd, check=False, env=env, capture_output=True, text=True)
    if proc.returncode != 0 or not out_path.is_file():
        raise RuntimeError(
            f"kicad-cli sch export netlist failed (exit {proc.returncode}): "
            f"{proc.stderr.strip()}"
        )


def _print_human_report(summary: dict[str, object]) -> None:
    erc = summary["erc"]
    assert isinstance(erc, dict)
    print(f"Schematic: {summary['schematic']}")
    print(
        "ERC: "
        f"{erc['error_count']} error(s), "
        f"{erc['disallowed_warning_count']} disallowed warning(s), "
        f"{erc['allowed_warning_count']} allowed warning(s), "
        f"{erc['excluded_count']} excluded"
    )
    for err in erc["errors"]:  # type: ignore[index]
        print(f"  [ERROR] {err['sheet']} {err['type']}: {err['description']}")
    for warn in erc["disallowed_warnings"]:  # type: ignore[index]
        print(f"  [WARN]  {warn['sheet']} {warn['type']}: {warn['description']}")

    parity = summary.get("parity")
    if isinstance(parity, dict):
        print(
            "Netlist Parity: "
            f"{parity['skidl_component_count']} SKiDL / "
            f"{parity['schematic_component_count']} Eeschema components, "
            f"{parity['skidl_group_count']} SKiDL / "
            f"{parity['schematic_group_count']} Eeschema pin groups"
        )
        if parity["no_lib_refs"]:
            print(
                f"  [PARITY FAIL] SKiDL .net contains NO_LIB fallback for: "
                f"{', '.join(parity['no_lib_refs'])}"
            )
        if parity["missing_in_schematic"]:
            print(
                f"  [PARITY FAIL] Components missing in schematic: "
                f"{', '.join(parity['missing_in_schematic'])}"
            )
        if parity["extra_in_schematic"]:
            print(
                f"  [PARITY FAIL] Unexpected components in schematic: "
                f"{', '.join(parity['extra_in_schematic'])}"
            )
        for mg in parity["missing_pin_groups"]:  # type: ignore[index]
            nets = ", ".join(mg["skidl_nets"])
            pins = ", ".join(mg["pins"])
            states = ", ".join(f"{p}={n}" for p, n in mg["schematic_pin_nets"].items())
            print(
                f"  [PARITY FAIL] Missing pin group from SKiDL net [{nets}] "
                f"({pins}) -> schematic sees: {states}"
            )
        for eg in parity["extra_pin_groups"]:  # type: ignore[index]
            nets = ", ".join(eg["schematic_nets"])
            pins = ", ".join(eg["pins"])
            states = ", ".join(f"{p}={n}" for p, n in eg["skidl_pin_nets"].items())
            print(
                f"  [PARITY FAIL] Extra pin group in schematic net [{nets}] "
                f"({pins}) -> SKiDL sees: {states}"
            )

    print(f"RESULT: {'PASS' if summary['passed'] else 'FAIL'}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a KiCad 10 .kicad_sch via ERC and SKiDL .net parity."
    )
    parser.add_argument("schematic", type=pathlib.Path, help="Path to .kicad_sch file")
    parser.add_argument(
        "--netlist",
        type=pathlib.Path,
        default=None,
        help="Optional reference SKiDL .net file for pin-group parity check",
    )
    parser.add_argument(
        "--kicad-cli",
        default=None,
        help="Explicit path to kicad-cli (default: auto-detect on PATH / macOS KiCad.app)",
    )
    parser.add_argument(
        "--allow-warning",
        action="append",
        default=None,
        dest="allow_warnings",
        help=(
            "ERC warning type to allow without failing "
            "(repeatable; default: lib_symbol_mismatch)"
        ),
    )
    parser.add_argument(
        "--strict-warnings",
        action="store_true",
        help="Fail on all ERC warnings including lib_symbol_mismatch",
    )
    parser.add_argument(
        "--allow-all-warnings",
        action="store_true",
        help="Only fail ERC on errors, allowing all warning types",
    )
    parser.add_argument(
        "--erc-output",
        type=pathlib.Path,
        default=None,
        help="Optional path to save raw kicad-cli ERC JSON output",
    )
    parser.add_argument(
        "--sch-net-output",
        type=pathlib.Path,
        default=None,
        help="Optional path to save exported Eeschema .net file",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON summary to stdout",
    )
    args = parser.parse_args()

    if not args.schematic.is_file():
        print(f"[error] Schematic not found: {args.schematic}", file=sys.stderr)
        return 2
    if args.netlist is not None and not args.netlist.is_file():
        print(f"[error] Reference netlist not found: {args.netlist}", file=sys.stderr)
        return 2

    env = configure_kicad_env()
    kicad_cli = resolve_kicad_cli(args.kicad_cli, env)
    if kicad_cli is None:
        print(
            "[error] kicad-cli not found on PATH or at "
            f"{MACOS_KICAD_BIN / 'kicad-cli'}",
            file=sys.stderr,
        )
        return 2

    if args.strict_warnings:
        allowed_warnings: set[str] = set()
    elif args.allow_warnings is not None:
        allowed_warnings = set(args.allow_warnings)
    else:
        allowed_warnings = {"lib_symbol_mismatch"}

    try:
        erc_summary = run_erc(
            args.schematic,
            kicad_cli,
            env,
            allowed_warnings=allowed_warnings,
            allow_all_warnings=args.allow_all_warnings,
            erc_output=args.erc_output,
        )

        parity_summary: dict[str, object] | None = None
        if args.netlist is not None:
            with tempfile.TemporaryDirectory() as tmpdir:
                sch_net_path = (
                    args.sch_net_output
                    if args.sch_net_output is not None
                    else pathlib.Path(tmpdir) / "eeschema_export.net"
                )
                export_schematic_netlist(args.schematic, kicad_cli, env, sch_net_path)
                parity_summary = compare_netlist_parity(args.netlist, sch_net_path)
        elif args.sch_net_output is not None:
            export_schematic_netlist(
                args.schematic, kicad_cli, env, args.sch_net_output
            )
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    overall_passed = bool(erc_summary["passed"]) and (
        parity_summary is None or bool(parity_summary["passed"])
    )
    summary: dict[str, object] = {
        "passed": overall_passed,
        "schematic": str(args.schematic),
        "netlist": str(args.netlist) if args.netlist is not None else None,
        "erc": erc_summary,
        "parity": parity_summary,
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        _print_human_report(summary)

    return 0 if overall_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
