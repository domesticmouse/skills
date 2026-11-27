#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

KICAD_PYTHON="/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3"

echo "==> Running ruff (py39 target on py39-compatible scripts)"
ruff check --target-version py39 \
  packs/hardware/describe-schematic-pdf/scripts/render_schematic_tiles.py \
  packs/hardware/describe-schematic-pdf/scripts/verify_circuit_md.py \
  packs/hardware/eurorack-panel/scripts/import_panel_svgs.py \
  packs/hardware/extract-pdf-schematic/scripts/extract_schematic.py \
  packs/hardware/kicad-pcbnew-layout/scripts/pcbnew_layout_template.py \
  packs/hardware/kicad-silkscreen-markup/scripts/silk_annotator.py \
  packs/hardware/kicad-silkscreen-markup/scripts/silk_layout.py

echo "==> Running ruff check & format --check on hardware scripts and tests"
ruff check \
  packs/hardware/describe-schematic-pdf/scripts \
  packs/hardware/eurorack-panel/scripts \
  packs/hardware/extract-pdf-schematic/scripts \
  packs/hardware/kicad-pcbnew-layout/scripts \
  packs/hardware/kicad-silkscreen-markup/scripts \
  tests
ruff format --check \
  packs/hardware/describe-schematic-pdf/scripts/render_schematic_tiles.py \
  packs/hardware/describe-schematic-pdf/scripts/verify_circuit_md.py \
  packs/hardware/eurorack-panel/scripts/audit_panel_svgs.py \
  packs/hardware/eurorack-panel/scripts/import_panel_svgs.py \
  packs/hardware/extract-pdf-schematic/scripts/extract_schematic.py \
  packs/hardware/kicad-pcbnew-layout/scripts/pcbnew_layout_template.py \
  packs/hardware/kicad-silkscreen-markup/scripts/render_silk_preview.py \
  packs/hardware/kicad-silkscreen-markup/scripts/silk_annotator.py \
  packs/hardware/kicad-silkscreen-markup/scripts/silk_layout.py \
  tests

if [ -x "$KICAD_PYTHON" ]; then
  echo "==> Running KiCad Python unittest suite"
  "$KICAD_PYTHON" -m unittest discover -s tests -p "test_*.py" -v
else
  echo "SKIP: KiCad Python not found at $KICAD_PYTHON"
fi

if command -v uv >/dev/null 2>&1; then
  echo "==> Running Pillow/NumPy unittest suite via uv"
  uv run --with pillow --with numpy python3 -m unittest discover -s tests -p "test_*.py" -v
else
  echo "==> Running system Python unittest suite"
  python3 -m unittest discover -s tests -p "test_*.py" -v
fi
