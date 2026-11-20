---
name: kicad-silkscreen-markup
description: >-
  Apply collision-free Reference and Value/Function silkscreen labels (with
  density-adaptive value-only labeling for passive R*/C* parts on crowded
  boards), SMD .Fab body keepouts, dual-sided THT/test-point labels, component
  polarity indicators, 5x5 mm JLCPCB QR code placeholders, and complete B.Fab
  fabrication notes to a KiCad 10 .kicad_pcb. Use when annotating a generated
  or existing KiCad PCB for JLCPCB assembly review, fixing silk_overlap or
  silk_over_copper DRC violations, or detecting tether-drift and collision
  failures via silk_annotator.py --inspect.
---

# KiCad Silkscreen & Fabrication Markup

Use this workflow to turn raw footprint placements into clean, DFM-compliant top and bottom silkscreens and fabrication drawings without `silk_overlap`, `silk_over_copper`, or unreadable distant label drift.

Helper module and inspection CLI: [silk_annotator.py](./scripts/silk_annotator.py).

## Core Principles

1. **Measure True KiCad Stroke Text Bounding Boxes**:
   Character-width heuristics (e.g., `0.76 * height`) underestimate uppercase glyphs (`R`, `V`, `T`, `W`), causing neighboring labels or `<REF>`/`<VAL>` pairs to collide. Instead, create a scratch `pcbnew.PCB_TEXT(board)` object, configure size/thickness, call `GetBoundingBox()` at `0°`, cache by `(text, height, thickness)`, and add `+0.06 mm` safety padding.

2. **Seed `SilkGrid` with Pads, Footprint Silk Outlines, and SMD `.Fab` Bodies**:
   Before placing any silkscreen text or graphics:
   - Hide initial `fp.Reference()` and `fp.Value()` items so their default positions do not act as false obstacles.
   - Populate `keepout[side]` with all pad and solder-mask bounding boxes (`F.Mask`/`B.Mask`, `+0.25 mm` margin) so `silk_over_copper` is impossible.
   - Populate `keepout[side]` with every non-text footprint graphic (`not hasattr(gi, "GetText")`) on `F.SilkS`/`B.SilkS` (`+0.20 mm` margin) so labels never cross pot bodies, jack circles, LED outlines, or SOIC silk borders.
   - Automatically block SMD `.Fab` package body interiors (`F.Fab`/`B.Fab`, `+0.05 mm` margin) so labels never land under IC (`SOIC-14`) or diode bodies whose `.SilkS` only draws end-cap lines, and block fiducial (`FID*`) `2.0 mm` solder-mask openings (`±1.25 mm`). Handled automatically by `SilkGrid(board, block_smd_fab=True)`.

3. **Density-Adaptive Labeling: Value-Only Passives vs. `<REF> + <VAL>`**:
   On dense boards (`>= 1.0 footprints/cm²` on a side, or `>= 35` parts on a side, checked by `SilkGrid.is_dense(side)`), printing both `<REF>` and multi-word `<VAL>` suffixes on every passive component saturates the silkscreen and forces labels far away from their footprints:
   - **Resistors and Capacitors (`R*`, `C*`, excluding `RV*` pots) on Dense Sides**: Print **only the concise primary value token** (e.g., `10k`, `100k`, `100nF`, `15pF`, `47pF`, `22uF` — stripping secondary tolerance/dielectric/wattage suffixes such as `0.1%`, `C0G`, `50V`, `1W`) via a single `pcbnew.PCB_TEXT(fp)` (`fp_text user`) item on `.SilkS`, while keeping both `fp.Reference()` and `fp.Value()` hidden on `.Fab`. Handled automatically by `place_ref_val_pair(..., val_only="auto")` or `place_val_only()`.
   - **Active, Polarized, & User-Interface Components (`U*`, `D*`, `LED*`, `Q*`, `RV*`, `J*`, `SW*`, `TP*`)**: Keep `fp.Reference()` visible on the primary silkscreen layer (`>= 0.80 mm` height, `>= 0.15 mm` stroke, `0°`/`90°` rotations only), keep `fp.Value().SetVisible(False)` on `.Fab` (`0` `values_visible_on_silk` clutter warnings), and place the concise value/function token in a `pcbnew.PCB_TEXT(fp)` (`fp_text user`) item beside or stacked with `<REF>` (`gap >= 0.35 mm`).
   - **Fiducials (`FID*`)**: Keep both `fp.Reference()` and `fp.Value()` hidden on `.Fab` so fiducials carry no silkscreen text.
   - **Analyzer Compatibility**: `analyze_pcb.py` (`aklofas/kicad-happy`) does **not** emit any `findings[]` error when passive `fp.Reference()` fields live on `.Fab`; `silk_annotator.py --inspect` verifies `100%` of non-fiducial footprints are labeled on `.SilkS` (counting both `<REF>`-labeled parts and value-only passives).

4. **Strict Local Tether & Failure Detection — Never Use Board-Wide Fallbacks**:
   Every label must stay tethered immediately adjacent to its own footprint (`<= 3.5 mm` edge distance for SMD; `<= 6.0 mm` for THT), and `<REF>`/`<VAL>` pairs must never be split apart (`<= 1.2 mm` pair separation):
   - **Never** write fallback loops that expand `max_radius` across the board (`12–24+ mm`) or scan the entire board to force labels into distant open spaces. A label sitting next to the wrong component is worse than failing early.
   - If `place_ref_val_pair()` / `place_val_only()` returns `None` or `silk_annotator.py --inspect` exits non-zero (`UNLABELED`, `TETHER DRIFT`, or `SPLIT PAIR`), spread out the dense component placement (leave `>= 1.5–2.0 mm` label corridors between passive rows and IC pads) instead of pushing labels across the board.

5. **Account for `B.SilkS` Mirroring**:
   On `B.SilkS` (`SetMirrored(True)`), `+X` in board coordinates appears to the **visual left** when looking at the back of the board. Place `<REF>` at `-sign * offset` (`sign = -1.0` on `B.SilkS`, `+1.0` on `F.SilkS`) and `<VAL>` at `+sign * offset` so `<REF> <VAL>` always reads left-to-right on both sides (handled automatically by `place_ref_val_pair()`).

6. **Dual-Sided THTs, Polarity Markers & QR Placeholders**:
   Use `add_silk_text()`, `add_silk_rect()`, `add_silk_dot()`, and `add_silk_seg()` from [silk_annotator.py](./scripts/silk_annotator.py) for secondary labels and graphics:
   - **THT & Test Points**: Place secondary-side `PCB_TEXT(board)` + `PCB_TEXT(fp)` labels so panel controls, power headers (e.g., `J_PWR`), and test points (e.g., `TP1`–`TP8`) can be probed and debugged from either side.
   - **Polarity**: Add IC Pin-1 solid dots (e.g., `U1`/`U2`), bold `0.25 mm` external cathode bars outside `D_SOD-123` Pad 1 (`K`), LED `+`/`-` markers (e.g., `D4`), pot Pin-1 `"1"` markers, and power header polarity callouts (e.g., `J_PWR` `-12V RED` stripe bar + `-12V` / `GND` / `+12V` rail labels).
   - **JLCPCB QR Placeholders**: Reserve and draw filled `5.0 x 5.0 mm` solid silkscreen squares on `F.SilkS` and `B.SilkS`.

7. **`100%` Complete `B.Fab` Fabrication Notes**:
   `analyze_pcb.py` (`fab_notes_completeness`) checks 6 fabrication metadata items (`ipc_class`, `surface_finish`, `board_thickness`, `copper_weight`, `solder_mask`, `material`). Call `add_standard_fab_notes(board, ...)` from [silk_annotator.py](./scripts/silk_annotator.py) to emit compliant `B.Fab` lines containing `IPC-6012 CLASS 2`, `THICKNESS: 1.6mm`, `1oz CU`, `FR4`, `ENIG / HASL-LF`, and `SOLDER MASK: BLACK`.

## Verification

```bash
# Inspect silkscreen labeling, collisions, keepouts, tether drift, and split pairs (exits 0 only on RESULT: PASS)
python3 .agents/skills/kicad-silkscreen-markup/scripts/silk_annotator.py --inspect Board.kicad_pcb

# Confirm zero silk_overlap / silk_over_copper in KiCad DRC
kicad-cli pcb drc --format json --output /tmp/drc.json Board.kicad_pcb

# Confirm fab_notes_completeness and zero assembly/silkscreen findings
python3 .agents/skills/kicad/scripts/analyze_pcb.py Board.kicad_pcb --full --output /tmp/pcb_analysis.json
```

Confirm `silk_annotator.py --inspect` reports `RESULT: PASS` (`100%` labeled non-fiducial footprints, `0` overlaps, `0` keepout hits, `0` out-of-bounds, `0` tether drift hits, and `0` split pair hits).
