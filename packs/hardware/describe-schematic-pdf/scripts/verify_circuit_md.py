#!/usr/bin/env python3
"""Verify BOM-to-netlist parity, pin completeness, and README links for circuit Markdown specs."""

from __future__ import annotations

import argparse
import re
import sys
import urllib.parse
from pathlib import Path

KNOWN_IC_PINS = {
    "TL072": 8,
    "TL082": 8,
    "NE5532": 8,
    "LM358": 8,
    "LM393": 8,
    "NJM4556": 8,
    "NE555": 8,
    "TL074": 14,
    "TL084": 14,
    "LM324": 14,
    "CD40106": 14,
    "CD4011": 14,
    "CD4069": 14,
    "CD4013": 14,
    "LM13700": 16,
    "CD4049": 16,
    "CD4051": 16,
}

_GRID_RE = re.compile(
    r"(?<!\d)(\d+)\s*[x×]\s*(\d+)(?!\d)(?!\s*(?:mm|cm)\b)", re.IGNORECASE
)
_PIN_COUNT_RE = re.compile(r"(\d+)\s*-?\s*pin", re.IGNORECASE)


def strip_md(cell: str) -> str:
    return cell.strip().strip("`").strip()


def _split_md_row(line: str) -> list[str]:
    """Split a Markdown table row, preserving empty leading/trailing cells."""
    s = line.strip().removeprefix("|").removesuffix("|")
    return [c.strip() for c in s.split("|")]


def _extract_bom_rows(text: str) -> list[str] | None:
    """Locate the first Markdown table under '## Bill of Materials (BOM)'."""
    sec_match = re.search(
        r"## Bill of Materials \(BOM\)\s*\n(.*?)(?=\n## |\Z)",
        text,
        re.DOTALL,
    )
    if not sec_match:
        return None
    table_match = re.search(
        r"^\|[^\n]*\n\|[-| :]+\n((?:\|[^\n]*\n?)*)",
        sec_match.group(1),
        re.MULTILINE,
    )
    if not table_match:
        return None
    return [line for line in table_match.group(1).splitlines() if line.strip()]


def infer_expected_pins(ref: str, val: str, cat: str, notes: str) -> set[str] | None:
    """Infer expected pin names from a BOM row."""
    del notes
    val_cat = f"{val} {cat}"

    if re.match(r"^(?:RV|VR)\d+$", ref):
        return {"CCW", "W", "CW"}

    if re.match(r"^R\d+$", ref):
        if re.search(r"potentiometer|trimmer", cat, re.IGNORECASE):
            return {"CCW", "W", "CW"}
        return {"1", "2"}

    if re.match(r"^C\d+$", ref):
        if re.search(r"electrolytic|polarized|tantalum", cat, re.IGNORECASE) and not (
            re.search(r"\b(?:non[- ]?polarized|bipolar)\b", cat, re.IGNORECASE)
        ):
            return {"+", "-"}
        return {"1", "2"}

    if re.match(r"^(?:L|FB|F)\d+$", ref):
        return {"1", "2"}

    if re.match(r"^(?:VD|D|LED)\d+$", ref):
        return {"A", "K"}

    if re.match(r"^(?:VT|Q)\d+$", ref):
        if re.search(r"mosfet|jfet|\bfet\b", cat, re.IGNORECASE):
            return {"G", "D", "S"}
        return {"B", "C", "E"}

    if re.match(r"^SW\d+$", ref):
        if re.search(r"\bDPDT\b", val_cat, re.IGNORECASE):
            return {str(i) for i in range(1, 7)}
        if re.search(r"\bSPST\b", val_cat, re.IGNORECASE):
            return {"1", "2"}
        return {"1", "2", "3"}

    if re.match(r"^(?:TP|X|MH)\d+$", ref):
        return {"1"}

    if re.match(r"^(?:DA|DD|U|IC)\d+$", ref):
        for part_prefix, count in KNOWN_IC_PINS.items():
            if part_prefix.lower() in val.lower():
                return {str(i) for i in range(1, count + 1)}
        m = _PIN_COUNT_RE.search(val_cat)
        if m:
            return {str(i) for i in range(1, int(m.group(1)) + 1)}
        return None

    if re.match(r"^(?:XS|J)\d+$", ref):
        m_grid = _GRID_RE.search(val_cat)
        if m_grid:
            total = int(m_grid.group(1)) * int(m_grid.group(2))
            return {str(i) for i in range(1, total + 1)}
        m_pin = _PIN_COUNT_RE.search(val_cat)
        if m_pin:
            return {str(i) for i in range(1, int(m_pin.group(1)) + 1)}
        if re.search(r"\bTRS\b|\bStereo\b", cat, re.IGNORECASE):
            return {"T", "R", "S"}
        if re.search(r"\bUnswitched\b", cat, re.IGNORECASE):
            return {"T", "S"}
        return {"T", "S", "SW"}

    if re.match(r"^(?:XP|P|H|CON)\d+$", ref):
        m_grid = _GRID_RE.search(val_cat)
        if m_grid:
            total = int(m_grid.group(1)) * int(m_grid.group(2))
            return {str(i) for i in range(1, total + 1)}
        m_pin = _PIN_COUNT_RE.search(val_cat)
        if m_pin:
            return {str(i) for i in range(1, int(m_pin.group(1)) + 1)}
        return None

    return None


def report_designator_gaps(bom_refs: set[str]) -> list[str]:
    """Summarize any skipped numbers per reference prefix (informational only)."""
    by_prefix: dict[str, list[int]] = {}
    for ref in bom_refs:
        m = re.match(r"^([A-Z]+)(\d+)$", ref)
        if m:
            by_prefix.setdefault(m.group(1), []).append(int(m.group(2)))
    notes = []
    for prefix, nums in sorted(by_prefix.items()):
        hi = max(nums)
        missing = sorted(set(range(1, hi + 1)) - set(nums))
        if missing:
            notes.append(f"{prefix}: skipped {missing}")
    return notes


def verify_file(fpath: Path) -> int:
    text = fpath.read_text(encoding="utf-8")
    errors: list[str] = []

    bom_rows = _extract_bom_rows(text)
    if bom_rows is None:
        print(f"{fpath}: ERROR - Could not locate '## Bill of Materials (BOM)' table")
        return 1

    bom: dict[str, tuple[str, str, str]] = {}
    for raw_line in bom_rows:
        line = raw_line.strip()
        if not line.startswith("|"):
            break
        cols = _split_md_row(line)
        if len(cols) < 5:
            errors.append(f"Malformed BOM row (<5 cols): {raw_line}")
            continue
        ref = strip_md(cols[0])
        val = strip_md(cols[1])
        cat = cols[2].strip()
        notes = cols[4].strip()
        if ref in bom:
            errors.append(f"Duplicate BOM ref: {ref}")
        bom[ref] = (val, cat, notes)

    net_match = re.search(
        r"## Pin-to-Pin Netlist\b.*?\|\s*Net\s*\|\s*Connected Pins\s*\|\s*Description\s*\|\s*\n\|[-| :]+\n(.*)",
        text,
        re.DOTALL,
    )
    if not net_match:
        print(f"{fpath}: ERROR - Could not locate '## Pin-to-Pin Netlist' table")
        return 1

    nets: dict[str, list[str]] = {}
    pin_to_net: dict[str, str] = {}
    for raw_line in net_match.group(1).strip().splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            break
        cols = _split_md_row(line)
        if len(cols) < 2:
            errors.append(f"Malformed netlist row: {raw_line}")
            continue
        net = strip_md(cols[0])
        if net in nets:
            errors.append(f"Duplicate net '{net}'")
        pins = [strip_md(p) for p in cols[1].split(",") if strip_md(p)]
        if net != "NC" and len(pins) < 2:
            errors.append(f"Orphan net '{net}' has <2 pins: {pins}")
        nets[net] = pins
        for p in pins:
            if p in pin_to_net:
                errors.append(
                    f"Duplicate pin '{p}' on nets '{pin_to_net[p]}' and '{net}'"
                )
            pin_to_net[p] = net

    net_refs: set[str] = set()
    ref_pins: dict[str, set[str]] = {}
    for p in pin_to_net:
        if "." not in p:
            errors.append(f"Malformed pin token '{p}' (expected Ref.Pin)")
            continue
        ref, pin = p.split(".", 1)
        net_refs.add(ref)
        ref_pins.setdefault(ref, set()).add(pin)

    bom_refs = set(bom.keys())
    if bom_refs != net_refs:
        missing_in_net = sorted(bom_refs - net_refs)
        extra_in_net = sorted(net_refs - bom_refs)
        if missing_in_net:
            errors.append(f"BOM refs missing from netlist: {missing_in_net}")
        if extra_in_net:
            errors.append(f"Netlist refs missing from BOM: {extra_in_net}")

    for ref, (val, cat, notes) in bom.items():
        actual = ref_pins.get(ref, set())
        expected = infer_expected_pins(ref, val, cat, notes)
        if expected is None:
            errors.append(f"Cannot infer pin set for {ref} ({val} / {cat})")
        elif actual != expected:
            errors.append(
                f"Pin mismatch on {ref} ({val}): expected {sorted(expected)}, got {sorted(actual)}"
            )

        if (
            re.match(r"^(?:R|C|L|FB|F|VD|D|LED)\d+$", ref)
            and not re.search(r"potentiometer|trimmer", cat, re.IGNORECASE)
            and len(actual) == 2
        ):
            p1, p2 = sorted(actual)
            n1 = pin_to_net.get(f"{ref}.{p1}")
            n2 = pin_to_net.get(f"{ref}.{p2}")
            if n1 == n2 and n1 != "NC":
                errors.append(f"Shorted 2-pin component {ref} on net '{n1}'")

    gaps = report_designator_gaps(bom_refs)
    gap_str = f" | Designator gaps: {'; '.join(gaps)}" if gaps else ""
    print(
        f"{fpath}: BOM={len(bom)} components, Nets={len(nets)}, "
        f"Pins={len(pin_to_net)}, Errors={len(errors)}{gap_str}"
    )
    for err in errors:
        print(f"  ERROR: {err}")
    return len(errors)


def verify_readme(readme_path: Path) -> int:
    text = readme_path.read_text(encoding="utf-8")
    base = readme_path.parent
    errors = 0
    for raw_target in re.findall(r"\]\(([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)", text):
        if raw_target.startswith(("http://", "https://", "mailto:")):
            continue
        path_part = raw_target.split("#", 1)[0]
        if not path_part.lower().endswith((".pdf", ".md")):
            continue
        decoded = urllib.parse.unquote(path_part)
        target = (base / decoded).resolve()
        if not target.exists():
            print(f"{readme_path}: ERROR - Broken link '{raw_target}' -> {target}")
            errors += 1
    if errors == 0:
        print(f"{readme_path}: All local PDF/Markdown links verified (0 errors)")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files", nargs="+", help="Circuit description Markdown files to verify"
    )
    parser.add_argument(
        "--readme", help="Optional README.md to verify local .pdf/.md links"
    )
    args = parser.parse_args()

    total_errors = 0
    for f in args.files:
        p = Path(f)
        if not p.is_file():
            print(f"{p}: ERROR - File not found")
            total_errors += 1
            continue
        total_errors += verify_file(p)

    if args.readme:
        rp = Path(args.readme)
        if not rp.is_file():
            print(f"{rp}: ERROR - README file not found")
            total_errors += 1
        else:
            total_errors += verify_readme(rp)

    if total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
