# Declarative `silk_layout.json` Workflow & Visual Preview Loop

Use [silk_layout.py](../scripts/silk_layout.py) and [render_silk_preview.py](../scripts/render_silk_preview.py) to adjust individual silkscreen labels without regenerating copper/zones or causing cascading shifts across neighboring parts.

---

## 1. Coordinate System & Schema (`silk_layout.json`)

- **Board-local mm:** All coordinates in `silk_layout.json` are relative to `board_origin_mm` (`AuxOrigin` when set, otherwise `Edge.Cuts` top-left `(x0, y0)`). Editing one footprint entry never shifts any neighbor.
- **Auto-placement opt-in:** Set any footprint entry to `"auto"` (e.g., `"C1": "auto"`) to let `--apply` place it via `place_ref_val_pair(..., val_only="auto")` around all pinned items.
- **Visual movement directions (bottom vs. top view):**
  - `F.SilkS` (`top` view): right = `+x`, left = `-x`, down = `+y`, up = `-y`.
  - `B.SilkS` (`bottom` view): **left = `+x`, right = `-x`**, down = `+y`, up = `-y` (the rear side is viewed horizontally mirrored).

```json
{
  "version": 1,
  "board_origin_mm": [100.0, 40.0],
  "board_size_mm": [30.0, 108.0],
  "qr_rects": [{"layer": "F.SilkS", "x0": 23.8, "y0": 1.0, "x1": 28.8, "y1": 6.0, "filled": true, "width": 0.15}],
  "dots": [],
  "segments": [],
  "board_texts": [],
  "footprints": {
    "U1": {
      "ref": {"layer": "B.SilkS", "x": 15.0, "y": 78.2, "deg": 0.0, "height": 0.8, "thickness": 0.15},
      "texts": [{"layer": "B.SilkS", "text": "TL074H", "x": 15.0, "y": 79.4, "deg": 0.0, "height": 0.8, "thickness": 0.15}]
    },
    "C1": "auto"
  }
}
```

---

## 2. Workflow A — Iterative Edits via `silk_layout.json`

1. **Extract an initial snapshot** (if `silk_layout.json` does not exist yet):
   ```bash
   python3 .agents/skills/kicad-silkscreen-markup/scripts/silk_layout.py \
     --pcb Board.kicad_pcb --extract --layout silk_layout.json
   ```
2. **Inspect the target neighborhood** (positions + `<= 5.0 mm` obstacles):
   ```bash
   python3 .agents/skills/kicad-silkscreen-markup/scripts/silk_layout.py \
     --pcb Board.kicad_pcb --show U1 C1
   ```
3. **Edit only the target entry in `silk_layout.json`**:
   - Keep `deg` at `0.0` or `90.0` (`B.SilkS` mirroring is handled automatically).
   - Keep `fp.Value()` hidden on `.Fab` (edit `texts` items, never unhide `fp.Value()`).
   - Stay within `3.5 mm` SMD / `6.0 mm` THT tether bounds and `<= 1.2 mm` `<REF>`/`<VAL>` pair split, clear of mask-expanded pads, `.Fab` bodies, silk shapes, and QR copper keepouts.
4. **Restamp in place (~1 s)** (preserves copper, tracks, vias, zones, and existing `B.Fab` notes unless `--restamp-fab-notes` is passed; exits non-zero if `inspect_board_silk` fails):
   ```bash
   python3 .agents/skills/kicad-silkscreen-markup/scripts/silk_layout.py \
     --pcb Board.kicad_pcb --apply --layout silk_layout.json
   ```
5. **Render and inspect a zoomed mm-ruler preview** (save into workspace-local `analysis/` or conversation artifacts, never `/tmp/` when viewing images; note that ruler alignment derives from the rendered board alpha bbox, so 3D bodies overhanging `Edge.Cuts` can slightly offset ruler ticks):
   ```bash
   .venv/bin/python .agents/skills/kicad-silkscreen-markup/scripts/render_silk_preview.py \
     --pcb Board.kicad_pcb --silk-layout silk_layout.json --ref U1 \
     --output analysis/silk_preview_U1.png
   ```

---

## 3. Workflow B — Sync Manual KiCad GUI Edits

> **CRITICAL:** If labels were moved manually in KiCad PCB Editor, always run `--extract` **before** running `--apply` or your board generator script, or unsynced GUI edits will be overwritten.

```bash
python3 .agents/skills/kicad-silkscreen-markup/scripts/silk_layout.py \
  --pcb Board.kicad_pcb --extract --layout silk_layout.json
```

Review the printed per-ref diff and `inspect_board_silk` status, then render full-side verification previews (`--side top --full` and `--side bottom --full`) alongside `kicad-cli pcb drc --refill-zones --severity-all`.
