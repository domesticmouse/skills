---
name: describe-schematic-pdf
description: >-
  Extract a rebuild-ready Markdown circuit specification (metadata, Mermaid
  signal flow, panel I/O, functional blocks, complete BOM, and verified
  pin-to-pin netlist) from a schematic PDF. Use when documenting a circuit
  schematic PDF into Markdown, extracting a BOM and netlist from a PDF
  schematic for SKiDL/KiCad rebuilds, or auditing schematic connectivity.
---

# Describe Schematic PDF

Extract a complete, rebuild-ready Markdown circuit specification from a vector schematic PDF using [render_schematic_tiles.py](./scripts/render_schematic_tiles.py) for high-resolution visual inspection and [verify_circuit_md.py](./scripts/verify_circuit_md.py) for BOM/netlist verification. Follow the exact output schema in [references/markdown-spec-format.md](./references/markdown-spec-format.md).

**Platform & Prerequisites:** `render_schematic_tiles.py` requires macOS with Xcode Command Line Tools (`swift` / `PDFKit` / `CoreGraphics`); `verify_circuit_md.py` is cross-platform Python 3.9+ with zero external packages.

## Steps

1. **Render overlapping high-resolution tiles**
   ```bash
   python3 .agents/skills/describe-schematic-pdf/scripts/render_schematic_tiles.py tile <schematic.pdf> --out-dir /tmp/schematic_tiles
   ```
   Defaults: `--cols 3 --rows 2 --scale 4.5 --overlap 35 --page 1`. The command prints JSON containing `page_size` and each tile's `pdf_rect` (`[x, y, w, h]` in upright bottom-left PDF coordinates), which you can use to derive `--rect` in Step 2. Inspect every rendered tile visually (e.g., with `read_file`). Done when every region of the sheet—including the title block, schematic notes, power supply, and any board-to-board headers—has been read at tile resolution. (If the schematic sits sideways or with footers inside a multi-page manual, use `extract-pdf-schematic` first to extract a clean, upright single-page PDF.)

2. **Zoom-verify dense or ambiguous regions**
   Whenever diode orientations (bridges, power Schottkys, clamping pairs), transistor emitter arrows, potentiometer `CW`/`CCW` markings, wire junctions vs crossings, or packed IC pins are uncertain, crop that region in upright PDF coordinates (origin bottom-left, matching `tile` JSON's `page_size` and `pdf_rect`) at `12x`:
   ```bash
   python3 .agents/skills/describe-schematic-pdf/scripts/render_schematic_tiles.py crop <schematic.pdf> --rect <x,y,w,h> --output /tmp/schematic_tiles/zoom.png --scale 12.0
   ```
   Inspect `/tmp/schematic_tiles/zoom.png` visually. Done when zero symbols, values, or junctions are guessed.

3. **Cross-check an accompanying manual (when present)**
   If a build manual PDF exists in the repo, search it for BOM counts, alternate values, or calibration trimmers:
   ```bash
   python3 .agents/skills/describe-schematic-pdf/scripts/render_schematic_tiles.py search-manual <manual.pdf> <term1> [term2 ...]
   ```
   Treat the schematic PDF as ground truth for pinouts, errata callouts, and revisions; record any manual-specific calibration notes or BOM clarifications in `Metadata` and `Functional Circuit Blocks`.

4. **Audit designator continuity and electrical sense**
   Check each designator series (`R`, `C`, `VD`/`D`, `VT`/`Q`, `DA`/`DD`/`U`, `SW`, `XS`/`J`, `XP`, `TP`, `X`) from `1..N` and confirm any skipped numbers are genuinely absent on the sheet. Verify negative-rail diode/electrolytic polarities, op-amp `+`/`-` inputs, and potentiometer taper/rotation labels (`CW`/`CCW`) make electrical sense. Done when every component on the sheet is accounted for.

5. **Write the Markdown specification**
   Author the output `.md` file following every section, table header, pin naming convention, and Mermaid rule in [references/markdown-spec-format.md](./references/markdown-spec-format.md). Include every component once in the BOM and every pin—including `NC` pins—in the netlist. If the repo maintains a `README.md` or module index table, link the new `.md` file there.

6. **Verify BOM/netlist parity and clean up**
   Run the automated validator and fix every reported error until it exits `0` with `Errors=0`:
   ```bash
   python3 .agents/skills/describe-schematic-pdf/scripts/verify_circuit_md.py <out.md> [--readme README.md]
   ```
   Remove temporary tiles once verified:
   ```bash
   rm -rf /tmp/schematic_tiles
   ```

## Key Pitfalls

- **Preserve schematic errata verbatim**: Capture silkscreen overrides (e.g., value-change callouts), mandatory transistor grades, `1%` resistor tolerances, and dielectric notes (`Film`, `Electrolytic`) in both `Metadata` and the `BOM`.
- **Keep `NC` pins explicit**: List floating jack `.SW` contacts, intentionally unconnected transistor pins, and unused prototyping pads in the `NC` netlist row so pin-completeness verification passes and SKiDL rebuilds match.
- **Distinguish jack types**: Mono switched jacks use `.T`, `.S`, `.SW`; stereo TRS jacks use `.T`, `.R`, `.S`.
- **Preserve two-board labels**: On multi-PCB modules, keep Control-board vs Main-board net names distinct (e.g., `*_C` vs non-`_C`) and document the header/socket pinout mapping in `Functional Circuit Blocks`.
- **Sandbox Swift cache**: `render_schematic_tiles.py` routes Swift/Clang module caches to user-scoped temporary directories (`describe-schematic-pdf-swift-cache-<uid>` and `describe-schematic-pdf-clang-cache-<uid>` under the system temp dir) so `CoreGraphics` runs cleanly inside sandboxes.
