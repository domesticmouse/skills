---
name: kicad-schematic-layout
description: >-
  Generate clean, wired single-sheet A3 KiCad 10 .kicad_sch schematics from a
  SKiDL or Eeschema .net netlist, matching a reference schematic PDF's signal
  flow and visual style. Use when replacing unreadable auto-generated or
  label-mode schematics, rebuilding a schematic in the style of a reference PDF,
  verifying KiCad 10 ERC and 100% netlist equivalence, or resolving KiCad 10
  .kicad_sch symbol flattening, text rotation, and wiring issues.
---

# KiCad 10 Single-Sheet Schematic Layout

Rebuild unreadable or label-only `.kicad_sch` outputs into a publication-grade, single-sheet wired KiCad 10 schematic matching a reference PDF's left-to-right analog flow and verified 100% against the authoritative `.net` netlist.

## Workflow Steps

1. **Inspect netlist, library symbols, and reference PDF**:
   Run [inspect_schematic_inputs.py](./scripts/inspect_schematic_inputs.py) to extract every component, net, and KiCad 10 symbol pin coordinate/bounding box (resolving `(extends ...)` chains), and view any target reference PDF directly:
   ```bash
   python3 .agents/skills/kicad-schematic-layout/scripts/inspect_schematic_inputs.py --net path/to/module.net --symbols-from-net
   ```
   *Done when*: Every component ref, value, footprint, multi-unit count, net pin-set, and pin orientation is accounted for.

2. **Partition the A3 sheet (`420 × 297 mm`) into signal-flow zones**:
   - Place all coordinates on the **`1.27 mm`** (`2.54 mm` preferred) schematic grid inside the A3 printable frame (`X ∈ [15, 405]`, `Y ∈ [15, 280]`), keeping the bottom-right title block (`X ∈ [295, 410]`, `Y ∈ [248, 287]`) clear.
   - Mirror the reference schematic's left-to-right signal flow (inputs/triggers left -> conditioning/envelope -> core voice/resonator -> output right; power entry & op-amp power units bottom-left; auxiliary indicators bottom-center).
   - Split multi-unit op-amps (`TL072`, `TL074`) into functional units plus a dedicated power unit on the bottom-left power block, with local decoupling caps adjacent.
   - Use either pure rotation (`angle ∈ {0, 90, 180, 270}`) OR pure mirror (`mirror ∈ {"x", "y"}` at `angle=0`) so pin coordinates stay unambiguous. See [kicad10_sch_mechanics.md](./references/kicad10_sch_mechanics.md).
   *Done when*: Every zone, rail bus, and multi-unit op-amp section has dedicated non-overlapping canvas bounds.

3. **Implement the deterministic schematic generator & export hook**:
   - Import `SchematicBuilder`, `load_netlist_parts_metadata`, `load_skidl_parts_metadata`, and `verify_schematic` from [sch_builder.py](./scripts/sch_builder.py) (adding `.agents/skills/kicad-schematic-layout/scripts` to `sys.path`; set `KICAD10_SYMBOL_DIR` and ensure `kicad-cli` is on `PATH` on non-macOS hosts) instead of reimplementing S-expression serialization.
   - When integrating into a SKiDL pipeline, invoke the custom schematic generator **after** `ERC()`, `generate_netlist()`, and BOM export (removing any stale sub-sheets) so `PWR_FLAG` never breaks netlist export or leaks into BOMs.
   - Orient every 2-pin resistor/capacitor (`1` vs `2`), diode (`A` vs `K`), polarized electrolytic, BJT, and potentiometer (`1`/`2`/`3`) to match the exact `.net` pin numbers, and connect every pin via orthogonal `wire()` / `wire_hv()` / `wire_vh()` segments (never route a wire straight through a 2-pin component's body).
   - Attach `power("...", ..., pwr_flag=True)` once per power rail (`+12V`, `-12V`, `GND`) inside the schematic only, and place `no_connect()` on intentionally unconnected output jack switch pins (`TN`).
   *Done when*: Running the generator removes stale sub-sheets and emits a single `.kicad_sch`.

4. **Verify ERC and 100% netlist equivalence (hard gate)**:
   Run the verification CLI (or `verify_schematic()`):
   ```bash
   python3 .agents/skills/kicad-schematic-layout/scripts/inspect_schematic_inputs.py --verify path/to/module.kicad_sch --net path/to/module.net
   ```
   Confirm zero `PWR_FLAG` leaks in `.net`, `_bom.xml`, and `_jlcpcb_bom.csv`:
   ```bash
   grep -c "PWR_FLAG" path/to/module.net path/to/module_bom.xml path/to/module_jlcpcb_bom.csv || true
   ```
   *Done when*: `kicad-cli sch erc --severity-all` reports `0` errors and `0` electrical warnings (`0` `lib_symbol_mismatch`), every component matches `.net`, every net pin-set matches `.net` 100%, and `PWR_FLAG` count is `0` across netlist/BOM files.

5. **Visual PDF inspection & polish loop (hard gate)**:
   Export to PDF and inspect the rendered page visually:
   ```bash
   kicad-cli sch export pdf -o /tmp/<module>_preview.pdf path/to/module.kicad_sch
   ```
   Check every zone for:
   - Horizontal (`0°`) upright `Reference`, `Value`, and panel control labels (handled automatically by `SchematicBuilder.place()` via `prop_angle = angle % 180` and `justify` flip compensation).
   - Zero text overlapping wires, symbol graphics, or neighboring labels.
   - Upright `GND`/`+12V`/`-12V` power symbols and clean junction dots strictly at T-intersections and 3+-way nodes.
   Fix any visual collision in the layout script, re-run Step 4, re-export the PDF, and re-inspect until spotless.
   *Done when*: Full-sheet PDF inspection shows zero label overlaps, zero wire-through-body crossings, and clear signal-flow legibility matching the reference PDF.

6. **Lint and format**:
   Run Ruff checks on all authored/modified Python files (excluding auto-generated `*_sklib.py` if unmodified):
   ```bash
   ruff check path/to/schematic.py path/to/circuit.py
   ruff format --check path/to/schematic.py path/to/circuit.py
   ```
   *Done when*: Both `ruff check` and `ruff format --check` exit `0`.
