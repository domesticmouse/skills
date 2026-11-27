---
name: extract-pdf-schematic
description: >-
  Extract a circuit or schematic from a specific PDF page into a cropped, upright
  lossless vector PDF without footers or rasterization. Use when extracting a
  schematic page from a manual PDF, or cropping and rotating a single vector PDF
  page cleanly.
---

# Extract PDF Schematic

Extract a single schematic page from a PDF into a cropped, upright, lossless vector PDF using [extract_schematic.py](./scripts/extract_schematic.py).

**Platform & Prerequisites:** macOS only — requires `osascript` (`PDFKit` / `AppKit`) and Xcode Command Line Tools (`swift` / `CoreGraphics`), with zero external Python packages.

## Steps

1. **Inspect the source page**
   Run `inspect` with a preview render:
   ```bash
   python3 .agents/skills/extract-pdf-schematic/scripts/extract_schematic.py inspect <manual.pdf> --page <N> --preview /tmp/schematic_src.png
   ```
   Inspect `/tmp/schematic_src.png` visually (e.g., with `read_file`). Confirm:
   - Page `<N>` holds the target schematic (check `neighbors` snippets if page numbering differs from PDF index).
   - Rotation needed to read upright (`90` clockwise for schematics printed 90° CCW with the title block on the top-right; `0` if already upright; `-90` if 90° CW).
   - `detected_crop.crop` (`sheet-rect` or `vector-bounds`) clears any bottom footer logo and page number (`footer_max_y`).

2. **Extract the lossless vector PDF**
   Run `extract` with a verification preview:
   ```bash
   python3 .agents/skills/extract-pdf-schematic/scripts/extract_schematic.py extract <manual.pdf> --page <N> --output <out.pdf> --rotate <90|0|-90|180> --preview /tmp/schematic_out.png
   ```
   - Pass `--crop x,y,w,h` only if `detected_crop` clipped a border or included unwanted footer artwork. Coordinates are in **PDF bottom-left user-space points** (matching `mediabox`), not top-left PNG preview pixels. Auto-crop heuristics assume unflipped PDF coordinates; supply `--crop` manually if a PDF uses Y-flipped or transformed content streams.
   - Confirm the JSON output reports `verified.page_count == 1`, `verified.rotation == 0`, landscape/upright `mediabox`, and `verified.large_images == []` (no rasterization). If `verified.large_images` is non-empty, the source manual itself embedded a raster scan rather than vector paths.

3. **Visually verify and clean up**
   Inspect `/tmp/schematic_out.png` visually (e.g., with `read_file`) and verify every criterion:
   - Title block sits upright in its expected corner (bottom-right for KiCad sheets) and reads left-to-right.
   - Grid labels run in reading order (e.g., `1..8` left-to-right, `A..F` top-to-bottom).
   - Complete outer schematic border is intact with clean, symmetric margins.
   - Manual footer logo and page number are absent.

   Use the `render` subcommand anytime you need a standalone PNG preview of an existing PDF page without re-extracting:
   ```bash
   python3 .agents/skills/extract-pdf-schematic/scripts/extract_schematic.py render <file.pdf> --page <N> --output /tmp/preview.png
   ```

   Remove temporary previews once verified:
   ```bash
   rm -f /tmp/schematic_src.png /tmp/schematic_out.png
   ```

4. **Update index links (when present)**
   If the repository maintains a `README.md` or schematic index table, add the extracted file's relative path and revision (from the title block) to the matching row.

## Notes

- **Stroked-vector size**: KiCad/Eeschema PDFs with outlined text can produce ~500–600 KB single-page PDFs while staying 100% pure vector; rely on `verified.large_images` rather than byte size alone to confirm vector fidelity.
- **Sandbox Swift cache**: `extract_schematic.py` routes Swift/Clang module caches to user-scoped temporary directories (`extract-pdf-schematic-swift-cache-<uid>` and `extract-pdf-schematic-clang-cache-<uid>` under `/tmp`) so `CoreGraphics` runs cleanly inside the sandbox.
