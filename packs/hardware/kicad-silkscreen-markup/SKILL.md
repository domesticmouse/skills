---
name: kicad-silkscreen-markup
description: >-
  Apply collision-free Reference and Value/Function silkscreen labels, dual-sided
  THT/test-point labels, component polarity indicators, 5x5 mm JLCPCB QR code
  placeholders, and complete B.Fab fabrication notes to a KiCad 10 .kicad_pcb.
  Use when annotating a generated or existing KiCad PCB for JLCPCB assembly
  review, fixing silk_overlap or silk_over_copper DRC violations, or achieving
  100% ref visibility and fab_notes_completeness in KiCad PCB analyzers.
---

# KiCad Silkscreen & Fabrication Markup

Use this workflow to turn raw footprint placements into clean, DFM-compliant top and bottom silkscreens and fabrication drawings without `silk_overlap` or `silk_over_copper` DRC errors.

Helper module and inspection CLI: [silk_annotator.py](./scripts/silk_annotator.py).

## Core Principles

1. **Measure True KiCad Stroke Text Bounding Boxes**:
   Character-width heuristics (e.g., `0.76 * height`) underestimate uppercase glyphs (`R`, `V`, `T`, `W`), causing neighboring labels or `<REF>`/`<VAL>` pairs to collide. Instead, create a scratch `pcbnew.PCB_TEXT(board)` object, configure size/thickness, call `GetBoundingBox()` at `0°`, cache by `(text, height, thickness)`, and add `+0.06 mm` safety padding.

2. **Seed `SilkGrid` with Both Pads and Footprint Outlines**:
   Before placing any silkscreen text or graphics:
   - Hide initial `fp.Reference()` and `fp.Value()` items so their default positions do not act as false obstacles.
   - Populate `keepout[side]` with all pad and solder-mask bounding boxes (`F.Mask`/`B.Mask`, `+0.25 mm` margin) so `silk_over_copper` is impossible.
   - Populate `keepout[side]` with every non-text footprint graphic (`not hasattr(gi, "GetText")`) on `F.SilkS`/`B.SilkS` (`+0.20 mm` margin) so labels never cross pot bodies, jack circles, LED outlines, or SOIC silk borders.

3. **Pair Visible `Reference` with User-Text Value (`0` Clutter Warnings)**:
   Hardware PCB analyzers (`analyze_pcb.py`) require `Reference` fields visible on `.SilkS` (`refs_visible_on_silk`) while flagging visible `Value` fields on `.SilkS` (`values_visible_on_silk`) as assembly clutter:
   - Keep `fp.Value().SetVisible(False)` on `.Fab`.
   - Keep `fp.Reference()` visible on the primary silkscreen layer (`>= 0.80 mm` height, `>= 0.15 mm` stroke, `0°`/`90°` rotations only).
   - Place the concise value/function token (e.g., `10k`, `100nF`, `IN`, `GAIN`, `ATK`) in a separate `pcbnew.PCB_TEXT(fp)` (`fp_text user`) item with `gap >= 0.35 mm` between the two bounding boxes (`>= 0.20 mm` minimum edge separation for JLCPCB/KiCad `0.15 mm` silk clearance).
   - Search a dense `0.65 mm` 2D Euclidean offset grid sorted by distance squared from the component center, preferring `>= 0.45 mm` board-edge clearance — implemented directly by `place_ref_val_pair()` in [silk_annotator.py](./scripts/silk_annotator.py).

4. **Account for `B.SilkS` Mirroring**:
   On `B.SilkS` (`SetMirrored(True)`), `+X` in board coordinates appears to the **visual left** when looking at the back of the board. Place `<REF>` at `-sign * offset` (`sign = -1.0` on `B.SilkS`, `+1.0` on `F.SilkS`) and `<VAL>` at `+sign * offset` so `<REF> <VAL>` always reads left-to-right on both sides (handled automatically by `place_ref_val_pair()`).

5. **Dual-Sided THTs, Polarity Markers & QR Placeholders**:
   Use `add_silk_text()`, `add_silk_rect()`, `add_silk_dot()`, and `add_silk_seg()` from [silk_annotator.py](./scripts/silk_annotator.py) for secondary labels and graphics:
   - **THT & Test Points**: Place secondary-side `PCB_TEXT(board)` + `PCB_TEXT(fp)` labels so panel controls, power headers (e.g., `J_PWR`), and test points (e.g., `TP1`–`TP8`) can be probed and debugged from either side.
   - **Polarity**: Add IC Pin-1 solid dots (e.g., `U1`/`U2`), bold `0.25 mm` external cathode bars outside `D_SOD-123` Pad 1 (`K`), LED `+`/`-` markers (e.g., `D4`), pot Pin-1 `"1"` markers, and power header polarity callouts (e.g., `J_PWR` `-12V RED` stripe bar + `-12V` / `GND` / `+12V` rail labels).
   - **JLCPCB QR Placeholders**: Reserve and draw filled `5.0 x 5.0 mm` solid silkscreen squares on `F.SilkS` and `B.SilkS`.

6. **`100%` Complete `B.Fab` Fabrication Notes**:
   `analyze_pcb.py` (`fab_notes_completeness`) checks 6 fabrication metadata items (`ipc_class`, `surface_finish`, `board_thickness`, `copper_weight`, `solder_mask`, `material`). Call `add_standard_fab_notes(board, ...)` from [silk_annotator.py](./scripts/silk_annotator.py) to emit compliant `B.Fab` lines containing `IPC-6012 CLASS 2`, `THICKNESS: 1.6mm`, `1oz CU`, `FR4`, `ENIG / HASL-LF`, and `SOLDER MASK: BLACK`.

## Verification

```bash
# Inspect silkscreen visibility and collisions directly via KiCad's bounding boxes
python3 .agents/skills/kicad-silkscreen-markup/scripts/silk_annotator.py --inspect Board.kicad_pcb

# Confirm zero silk_overlap / silk_over_copper in KiCad DRC
kicad-cli pcb drc --format json --output /tmp/drc.json Board.kicad_pcb

# Confirm 100% refs_visible_on_silk & fab_notes_completeness
python3 .agents/skills/kicad/scripts/analyze_pcb.py Board.kicad_pcb --full --output /tmp/pcb_analysis.json
```
