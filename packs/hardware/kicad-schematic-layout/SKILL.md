---
name: kicad-schematic-layout
description: >-
  Generate clean, wired single-sheet A3 KiCad 10 schematics from a SKiDL circuit
  or .net netlist, replace unreadable auto-generated or label-only .kicad_sch
  files, verify KiCad 10 ERC with 100% netlist/DNP parity, or debug symbol
  flattening, text rotation/justification, and schematic wiring issues.
---

# KiCad 10 Single-Sheet Schematic Layout

Generate a publication-grade, single-sheet wired KiCad 10 `.kicad_sch` backed by the circuit's authoritative metadata (`.net` / SKiDL), verified **100%** for ERC, netlist connectivity, DNP flags, and visual legibility.

## Workflow Steps

1. **Inspect netlist, library symbols, and optional reference**:
   Run [inspect_schematic_inputs.py](./scripts/inspect_schematic_inputs.py) to dump every component (ref, value, footprint, DNP/NO-BOM flags), every net pin-set, and every resolved KiCad 10 symbol pin coordinate and bounding box:
   ```bash
   python3 .agents/skills/kicad-schematic-layout/scripts/inspect_schematic_inputs.py --net path/to/module.net --symbols-from-net
   ```
   When matching an existing reference schematic PDF, inspect it visually at this step to extract block order and signal flow.
   *Done when*: Every component ref, value, footprint, DNP status, multi-unit count, net pin-set, and pin orientation is accounted for.

2. **Partition the A3 sheet (`420 × 297 mm`) into signal-flow zones**:
   - Keep all placed coordinates on the **`1.27 mm`** (`2.54 mm` preferred) schematic grid inside the printable A3 frame (`X ∈ [15, 405]`, `Y ∈ [15, 280]`), keeping the bottom-right title block (`X ∈ [295, 410]`, `Y ∈ [248, 287]`) clear.
   - Lay out functional stages left-to-right (inputs left -> conditioning -> core processing -> output right; power entry & op-amp power units in a dedicated power/decoupling zone; bias/indicators/DNP test points along the lower row) inside labeled `section_box()` frames.
   - Split multi-unit op-amps (`TL072`, `TL074`) into functional units plus a dedicated power unit with adjacent decoupling capacitors.
   - Use either pure rotation (`angle ∈ {0, 90, 180, 270}`) OR pure mirror (`mirror ∈ {"x", "y"}` at `angle=0`), checking [kicad10_sch_mechanics.md](./references/kicad10_sch_mechanics.md) before placing asymmetrical symbols (`power:-12V`, `AudioJack2_SwitchT`, `SW_SPDT`, `BAT54S`, BJTs).
   *Done when*: Every functional stage, power rail, and multi-unit op-amp section has explicit non-overlapping canvas bounds.

3. **Build the deterministic schematic generator**:
   - Import `SchematicBuilder`, `load_netlist_parts_metadata`, `load_skidl_parts_metadata`, and `verify_schematic` from [sch_builder.py](./scripts/sch_builder.py) (adding `.agents/skills/kicad-schematic-layout/scripts` to `sys.path`; set `KICAD10_SYMBOL_DIR` and ensure `kicad-cli` is on `PATH` on non-macOS hosts).
   - Use `""` as `project_name` for standalone `.kicad_sch` files (when no `.kicad_pro` exists) or the `.kicad_pro` stem when inside a KiCad project.
   - When integrating with SKiDL, invoke schematic generation **after** `ERC()`, `generate_netlist()`, and BOM export (and remove any stale auto-generated sub-sheets) so `PWR_FLAG` stays isolated inside `.kicad_sch`.
   - Match pin `1` vs pin `2` (plus diode `A`/`K`, pot `1`/`2`/`3`) to the `.net` pin numbers, route orthogonal segments via `wire()` / `wire_hv()` / `wire_vh()` around component bodies, place `pwr_flag()` on a dedicated short tap (or `power(..., pwr_flag=True, pwr_flag_offset=(5.08, 0))`) once per rail (`+12V`, `-12V`, `GND`), anchor local `label()`s directly on open wire endpoints using bottom justification (`left bottom`, `right bottom`, or `bottom`), and place `no_connect()` on intentionally unused pins (`TN`, unused throws).
   *Done when*: The generator emits a single deterministic `.kicad_sch` cleanly and removes any stale sub-sheets.

4. **Verify ERC, DNP, and 100% netlist equivalence (hard gate)**:
   Run the verification gate:
   ```bash
   python3 .agents/skills/kicad-schematic-layout/scripts/inspect_schematic_inputs.py --verify path/to/module.kicad_sch --net path/to/module.net
   ```
   Confirm zero `PWR_FLAG` leaks in netlist/BOM exports:
   ```bash
   grep -c "PWR_FLAG" path/to/module.net path/to/module_bom.xml path/to/jlcpcb_bom.csv || true
   ```
   If `--verify` reports `unconfigured-lib notices > 0`, also run `kicad-cli sch erc --severity-all path/to/module.kicad_sch` with global KiCad library tables accessible so `lib_symbol_issues` cannot mask `lib_symbol_mismatch`. Optionally run `.agents/skills/kicad/scripts/analyze_schematic.py` when the external `aklofas/kicad-happy` skill is installed.
   *Done when*: KiCad ERC reports `0` errors and `0` electrical/symbol-mismatch warnings (`0` `unconnected_wire_endpoint`, `0` `lib_symbol_mismatch`), every component (`value`, `footprint`, `dnp`, `exclude_from_bom`) and net pin-set matches `.net` 100%, and `PWR_FLAG` count is `0` across `.net`/BOM files.

5. **Visual PDF and zoomed crop inspection (hard gate)**:
   Export PDF and render both a full-page PNG and zoomed per-zone crops into `/tmp/`:
   ```bash
   kicad-cli sch export pdf -o /tmp/<module>_preview.pdf path/to/module.kicad_sch
   ```
   Inspect every zone crop visually for upright horizontal (`0°`) `Reference`/`Value`/net text, clear separation from wires and symbol bodies, downward-pointing `-12V` / upright `GND`/`+12V`, non-colliding `PWR_FLAG` taps, and clean T-junction dots. Fix any visual collision in the script and repeat Steps 4–5 until spotless.
   *Done when*: All zoomed zone crops show zero text/wire/symbol collisions and legible left-to-right signal flow.

6. **Lint, format, and re-verify after final edits**:
   Run Ruff strictly on authored/modified Python files (excluding auto-generated `*_sklib.py` and third-party skills):
   ```bash
   ruff check --fix path/to/schematic.py path/to/circuit.py
   ruff format path/to/schematic.py path/to/circuit.py
   ruff check path/to/schematic.py path/to/circuit.py && ruff format --check path/to/schematic.py path/to/circuit.py
   ```
   If formatting changed the generator script, re-run it and re-run Step 4 (`--verify`) after the final edit.
   *Done when*: `ruff check` and `ruff format --check` exit `0`, and Step 4 passes against the final files on disk.
