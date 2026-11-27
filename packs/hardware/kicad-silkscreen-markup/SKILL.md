---
name: kicad-silkscreen-markup
description: >-
  Apply collision-free Reference and Value/Function silkscreen labels (with
  density-adaptive value-only labeling for passive R*/C* parts on crowded
  boards), SMD/THT .Fab body keepouts, dual-sided THT/test-point labels,
  component polarity indicators, 5x5 mm JLCPCB QR code placeholders, complete
  B.Fab fabrication notes, iterative silk_layout.json round-trip editing and
  KiCad GUI sync (silk_layout.py), mm-ruler 3D silkscreen previews
  (render_silk_preview.py), and tether-drift/collision inspection
  (silk_annotator.py --inspect) on a KiCad 10 .kicad_pcb. Use when annotating
  a generated or existing KiCad PCB for JLCPCB assembly review, nudging or
  syncing individual silkscreen labels, or fixing silk_overlap or
  silk_over_copper DRC violations.
---

# KiCad Silkscreen & Fabrication Markup

Use this workflow to turn raw footprint placements into clean, DFM-compliant top and bottom silkscreens and fabrication drawings without `silk_overlap`, `silk_over_copper`, or unreadable distant label drift.

Helper module and inspection CLI: [silk_annotator.py](./scripts/silk_annotator.py).

## Core Principles

1. **Measure True KiCad Stroke Text Bounding Boxes**:
   Character-width heuristics (e.g., `0.76 * height`) underestimate uppercase glyphs (`R`, `V`, `T`, `W`), causing neighboring labels or `<REF>`/`<VAL>` pairs to collide. Instead, create a scratch `pcbnew.PCB_TEXT(board)` object, configure size/thickness, call `GetBoundingBox()` at `0°`, cache by `(text, height, thickness)`, and add `+0.06 mm` safety padding.

2. **Seed `SilkGrid` with Mask-Expanded Pads, Footprint Silk Outlines, and SMD/THT `.Fab` Bodies**:
   Before placing any silkscreen text or graphics:
   - Hide initial `fp.Reference()` and `fp.Value()` items so their default positions do not act as false obstacles.
   - Compute board boundaries with `board_edge_bounds(board)` (insetting `Edge.Cuts` items by half their stroke width instead of using raw `GetBoardEdgesBoundingBox()`, which inflates dimensions by `0.10 mm` stroke width).
   - Populate `keepout[side]` with pad bboxes expanded by effective solder-mask opening (`F.Mask`/`B.Mask` expansion + `0.25 mm` margin) so `silk_over_copper` and mask encroachment are impossible.
   - Populate `keepout[side]` with every non-text footprint graphic (`not hasattr(gi, "GetText")`) on `F.SilkS`/`B.SilkS` (`+0.20 mm` margin) so labels never cross pot bodies, jack circles, LED outlines, or SOIC silk borders.
   - Automatically block mounting-side `.Fab` package body interiors (`F.Fab`/`B.Fab`, `+0.05 mm` margin) for **both** SMD (`SOIC-14`, `SOD-123`) and THT (`J*` shrouded headers, `C*` radial electrolytics, `RV*` pots, `LED*`) footprints, plus fiducial (`FID*`) `2.0 mm` solder-mask openings (`±1.25 mm`). Handled automatically by `SilkGrid(board, block_smd_fab=True, block_tht_fab=True)`.

3. **Density-Adaptive Labeling: Value-Only Passives vs. `<REF> + <VAL>`**:
   On dense boards (`>= 1.0 footprints/cm²` on a side, or `>= 35` parts on a side, checked by `SilkGrid.is_dense(side)`), printing both `<REF>` and multi-word `<VAL>` suffixes on every passive component saturates the silkscreen and forces labels far away from their footprints:
   - **Resistors and Capacitors (`R*`, `C*`, including suffixed/underscored passives like `R16A`, `R_PWR`, `C_DEC1`, excluding `RV*` pots) on Dense Sides**: Print **only the concise primary value token** (e.g., `10k`, `100k`, `100nF`, `15pF`, `47pF`, `22uF` — stripping secondary tolerance/dielectric/wattage suffixes such as `0.1%`, `C0G`, `50V`, `1W`) via a single `pcbnew.PCB_TEXT(fp)` (`fp_text user`) item on `.SilkS`, while keeping both `fp.Reference()` and `fp.Value()` hidden on `.Fab`. Handled automatically by `place_ref_val_pair(..., val_only="auto")` or `place_val_only()`.
   - **Active, Polarized, & User-Interface Components (`U*`, `D*`, `LED*`, `Q*`, `RV*`, `J*`, `SW*`, `TP*`)**: Keep `fp.Reference()` visible on the primary silkscreen layer (`>= 0.80 mm` height, `>= 0.15 mm` stroke, `0°`/`90°` rotations only), keep `fp.Value().SetVisible(False)` on `.Fab` (`0` `values_visible_on_silk` clutter warnings), and place the concise value/function token (derived via `get_fp_silkscreen_field(fp)`) in a `pcbnew.PCB_TEXT(fp)` (`fp_text user`) item beside or stacked with `<REF>` (`gap >= 0.35 mm`, allowing shifted stacked pairs within `<= 1.2 mm` when corridors are tight).
   - **Fiducials (`FID*`)**: Keep both `fp.Reference()` and `fp.Value()` hidden on `.Fab` so fiducials carry no silkscreen text.
   - **Analyzer Compatibility**: `analyze_pcb.py` (`aklofas/kicad-happy`) emits **zero** `findings[]` errors when passive `fp.Reference()` fields live on `.Fab`, though its `silkscreen_completeness` section still reports `"warning"` on `checks.ref_designators_visible` (`< 90%`) and `checks.polarity_markers` (unconditional `polarity_reminder` whenever `> 3` polarized parts exist). Treat `silk_annotator.py --inspect` and `kicad-cli pcb drc --severity-all` as authoritative for `100%` non-fiducial silkscreen coverage and collision/clearance verification.

4. **Strict Local Tether & Failure Detection — Never Use Board-Wide Fallbacks**:
   Every label must stay tethered immediately adjacent to its own footprint (`<= 3.5 mm` edge distance for SMD; `<= 6.0 mm` for THT), and `<REF>`/`<VAL>` pairs must never be split apart (`<= 1.2 mm` pair separation):
   - **Never** write fallback loops that expand `max_radius` across the board (`12–24+ mm`) or scan the entire board to force labels into distant open spaces. A label sitting next to the wrong component is worse than failing early.
   - If `place_ref_val_pair()` / `place_val_only()` returns `None` or `silk_annotator.py --inspect` exits non-zero (`UNLABELED`, `TETHER DRIFT`, or `SPLIT PAIR`), spread out the dense component placement (leave `>= 1.5–2.0 mm` label corridors between passive rows and IC pads) instead of pushing labels across the board.

5. **Account for `B.SilkS` Mirroring**:
   On `B.SilkS` (`SetMirrored(True)`), `+X` in board coordinates appears to the **visual left** when looking at the back of the board. Place `<REF>` at `-sign * offset` (`sign = -1.0` on `B.SilkS`, `+1.0` on `F.SilkS`) and `<VAL>` at `+sign * offset` so `<REF> <VAL>` always reads left-to-right on both sides (handled automatically by `place_ref_val_pair()`).

6. **Dual-Sided THTs, Polarity Markers, Board Title/Rev & QR Placeholders**:
   Use grid-checked helpers `get_fp_silkscreen_field()`, `place_board_label()`, `place_silk_rect()`, `place_silk_dot()`, and `place_silk_seg()` (or raw `add_silk_*` primitives when coordinates are already validated) from [silk_annotator.py](./scripts/silk_annotator.py):
   - **THT & Test Points**: Place secondary-side `PCB_TEXT(fp)` / `PCB_TEXT(board)` labels so panel controls, power headers (e.g., `J_PWR`), and test points (e.g., `TP1`–`TP8`) can be probed and debugged from either side.
   - **Polarity**: Add IC Pin-1 solid dots (e.g., `U1`/`U2`), bold `0.25 mm` external cathode bars outside `D_SOD-123` Pad 1 (`K`), LED `+`/`-` markers (e.g., `D4`), pot Pin-1 `"1"` markers, and power header polarity callouts (e.g., `J_PWR` `-12V RED` stripe bar + `-12V` / `GND` / `+12V` rail labels).
   - **Board Name & Revision**: Place board title and revision strings from `board.GetTitleBlock()` (`board_name` / `revision_marking`) on `F.SilkS`/`B.SilkS` via `place_board_label(grid, board, side, f"{tb.GetTitle()} {tb.GetRevision()}".strip())`.
   - **JLCPCB QR Placeholders**: Reserve and draw a filled `5.0 x 5.0 mm` solid silkscreen square (one side such as `F.SilkS` is sufficient on dense 2-sided boards, or both sides when space permits), clearing all vias and same-side copper tracks. `silk_annotator.py --inspect` validates `PCB_SHAPE` silk graphics against pads/masks/`.Fab`/edges/texts and checks `5 × 5 mm` QR squares for zero vias or copper tracks.

7. **`100%` Complete `B.Fab` Fabrication Notes**:
   `analyze_pcb.py` (`fab_notes_completeness`) checks 6 fabrication metadata items (`ipc_class`, `surface_finish`, `board_thickness`, `copper_weight`, `solder_mask`, `material`). Call `add_standard_fab_notes(board, cx, y_below_board)` (placing notes outside `Edge.Cuts`, e.g., `board_y1 + 5.0 mm` centered in X, so long lines never cross footprint `.Fab` bodies on compact boards) to emit compliant `B.Fab` lines containing `IPC-6012 CLASS 2`, `THICKNESS: 1.6mm`, `1oz CU`, `FR4`, `ENIG / HASL-LF`, and `SOLDER MASK: BLACK`.

## Iterative `silk_layout.json` Tuning & Visual Previews

When polishing individual labels without regenerating copper/zones or syncing manual KiCad GUI moves, use [silk_layout.py](./scripts/silk_layout.py) and [render_silk_preview.py](./scripts/render_silk_preview.py) (see [silk_layout_workflow.md](./references/silk_layout_workflow.md) for the JSON schema and `B.SilkS` mirrored axis guide):

```bash
# Extract current silkscreen into silk_layout.json (or sync manual KiCad GUI moves)
python3 .agents/skills/kicad-silkscreen-markup/scripts/silk_layout.py --pcb Board.kicad_pcb --extract --layout silk_layout.json

# Inspect a component's labels and <= 5 mm neighbors, edit silk_layout.json, then restamp (~1 s)
python3 .agents/skills/kicad-silkscreen-markup/scripts/silk_layout.py --pcb Board.kicad_pcb --show U1 C1
python3 .agents/skills/kicad-silkscreen-markup/scripts/silk_layout.py --pcb Board.kicad_pcb --apply --layout silk_layout.json

# Render zoomed or full-board 3D preview with board-local mm rulers into workspace-local analysis/
.venv/bin/python .agents/skills/kicad-silkscreen-markup/scripts/render_silk_preview.py --pcb Board.kicad_pcb --ref U1
```

## Verification

```bash
# Inspect silkscreen labeling, PCB_SHAPE graphics, QR copper/via keepouts, collisions, tether drift, and split pairs
python3 .agents/skills/kicad-silkscreen-markup/scripts/silk_annotator.py --inspect Board.kicad_pcb

# Confirm zero silk_overlap / silk_over_copper warnings and errors in KiCad DRC
kicad-cli pcb drc --severity-all --format json --output /tmp/drc.json Board.kicad_pcb

# Optional: confirm fab_notes_completeness and zero assembly/silkscreen findings
# (requires external aklofas/kicad-happy skill and .venv Python >= 3.10)
if [ -f .agents/skills/kicad/scripts/analyze_pcb.py ]; then
  .venv/bin/python .agents/skills/kicad/scripts/analyze_pcb.py Board.kicad_pcb --full --output /tmp/pcb_analysis.json
fi
```

Confirm `silk_annotator.py --inspect` reports `RESULT: PASS` (`100%` labeled non-fiducial footprints, `0` overlaps, `0` keepout hits, `0` out-of-bounds, `0` QR via/track hits, `0` tether drift hits, and `0` split pair hits).
