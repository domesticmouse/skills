---
name: kicad-pcbnew-layout
description: >-
  Programmatically generate, place, route, and copper-pour a 2-layer KiCad 10
  .kicad_pcb board from a KiCad .net netlist using KiCad's pcbnew Python API.
  Use when generating a complete routed PCB from a SKiDL or Eeschema netlist,
  building Eurorack F.Cu control + B.Cu SMD/power sandwich boards, fixing
  pcbnew Python segfaults or DRC/VP-001/holes_co_located/track_dangling issues,
  or verifying automated PCB layouts against KiCad DRC and analyzers.
---

# KiCad pcbnew Automated 2-Layer Layout

Use this workflow when turning a KiCad `.net` netlist into a fully placed, routed, copper-poured, and DRC-clean `.kicad_pcb` via Python (`pcbnew`).

## Workflow Steps

1. **Self-bootstrap to KiCad's Python runtime**:
   On macOS, `pcbnew` is bundled inside KiCad (`KiCad.app`) rather than system or virtualenv Python. Re-exec the generator script automatically when `import pcbnew` raises `ModuleNotFoundError`. See [kicad10_pcbnew_api.md](./references/kicad10_pcbnew_api.md).

2. **Parse the `.net` netlist dynamically**:
   Extract every component's `ref`, `value`, `footprint` (`lib:fp_name`), `tstamp`, custom fields (`LCSC`, `MPN`, `Manufacturer`, `Silkscreen`, `Notes`), `dnp` status, and all net connections (`(ref, pin)` nodes). Never hardcode net codes or component metadata that already exists in `.net`—consume each footprint's `Silkscreen` field directly (via `get_footprint_field(fp, "Silkscreen")` or `get_fp_silkscreen_field(fp)`) instead of maintaining duplicate label dicts that drift from the netlist.
   - Reusable implementation & `--netlist` summary CLI: [pcbnew_layout_template.py](./scripts/pcbnew_layout_template.py).

3. **Initialize the board safely & assign footprints**:
   - Write a minimal KiCad PCB shell and open it with `pcbnew.LoadBoard()` instead of calling `fp.Flip()` directly on an uninitialized `pcbnew.BOARD()`.
   - `board.Add(fp)` **before** calling `fp.Flip(pos, False)` or setting rotation (`Flip` must precede `SetOrientationDegrees`).
   - Do **not** overwrite loaded footprints with `fp.SetFPID(pcbnew.LIB_ID(lib, fp_name))` when running in headless/sandboxed environments where global `fp-lib-table` cannot be opened, or `kicad-cli pcb drc` will emit `lib_footprint_issues` warnings for every footprint.
   - Mark optional / unpopulated parts (e.g., `TP1`–`TP8`, `dnp=True`, or by passing `dnp_prefixes=("TP",)` to `parse_netlist()`) and optical fiducials (`FID*`, via `populate_footprints()` / `add_fiducials()`) with **all three** flags: `fp.SetDNP(True)`, `fp.SetExcludedFromBOM(True)`, and `fp.SetExcludedFromPosFiles(True)` so neither `TP*` nor `FID*` leak into JLCPCB CPL exports (`--smd-only --exclude-dnp`).

4. **Plan Eurorack / 2-layer sandwich placement**:
   Place panel-mounted controls on `F.Cu` aligned to panel bushing coordinates (applying footprint-origin-to-bushing mechanical offsets), and place headers, test points, and SMDs on `B.Cu`. Leave `>= 1.5–2.0 mm` silkscreen label corridors between SMD passive rows and adjacent IC/THT keepouts so local labels stay within `3.5 mm` tether bounds. See [routing_and_dfm_patterns.md](./references/routing_and_dfm_patterns.md).

5. **Route with DFM-safe rules and pour `GND` zones**:
   - Pre-place immediate `GND` stitching vias for every `B.Cu` SMD `GND` pad before signal routing so signal traces never box in ground pads.
   - Reserve outward IC escape stubs just beyond actual outer pad edges (`x0 - 0.05` / `x1 + 0.05`) and pre-route decoupling cap power connections before general routing.
   - Block via centers inside exact SMD pad extents (`[x0 - 0.02, x1 + 0.02] x [y0 - 0.02, y1 + 0.02]`, avoiding `0` `VP-001` via-in-pad warnings).
   - Allow free `F.Cu <-> B.Cu` layer transitions at current-net THT barrels without emitting a duplicate `PCB_VIA` (`0` `holes_co_located`).
   - Preserve multi-branch T-junction vertices when merging collinear path steps (`0` `track_dangling`).
   - Call `board.BuildConnectivity()` **both before and after** `pcbnew.ZONE_FILLER(board).Fill(board.Zones())` with `ISLAND_REMOVAL_MODE_ALWAYS`.

6. **Apply silkscreen & fab notes**:
   Pair layout generation with the [`kicad-silkscreen-markup`](../kicad-silkscreen-markup/SKILL.md) workflow using density-adaptive labeling (concise value-only tokens for `R*`/`C*` passives on dense sides, `<REF> + <VAL>` for active, polarized, and interface parts), polarity markings, QR placeholders, and `B.Fab` notes with strict local tethering (never use board-wide fallback scans).

## Mandatory Verification Sequence

Run all checks after any final edit to the generator script:

```bash
# 1. Mark executable (EXE001), lint against KiCad Python 3.9, format-check, and regenerate PCB
chmod +x generate_pcb.py
ruff check --target-version py39 generate_pcb.py && ruff format --check generate_pcb.py
python3 generate_pcb.py

# 2. KiCad DRC (with --severity-all and zone refill so silkscreen/copper warnings aren't hidden)
kicad-cli pcb drc --severity-all --refill-zones --format json --output /tmp/drc.json Board.kicad_pcb

# 3. Silkscreen tether-drift, keepout, and collision inspection
python3 .agents/skills/kicad-silkscreen-markup/scripts/silk_annotator.py --inspect Board.kicad_pcb

# 4. Eurorack mechanical check (if applicable)
python3 .agents/skills/eurorack-panel/scripts/generate_eurorack_panel.py --main-pcb Board.kicad_pcb --inspect

# 5. Full KiCad PCB static/DFM analysis (use .venv Python >= 3.10; kicad_core/sexp.py fails under KiCad Python 3.9)
.venv/bin/python .agents/skills/kicad/scripts/analyze_pcb.py Board.kicad_pcb --full --output /tmp/pcb_analysis.json

# 6. Verify DNP / fiducial exclusion in exported SMT placement CSV (substitute --side front if top-populated)
kicad-cli pcb export pos --format csv --units mm --side back --smd-only --exclude-dnp --output /tmp/cpl_check.csv Board.kicad_pcb

# 7. Visual inspection of top and bottom 3D renders (render into workspace-local paths, not /tmp/)
mkdir -p analysis
kicad-cli pcb render --side top -o analysis/top.png --width 1200 --height 1600 --background transparent Board.kicad_pcb
kicad-cli pcb render --side bottom -o analysis/bottom.png --width 1200 --height 1600 --background transparent Board.kicad_pcb
```

Confirm:
- DRC (`--severity-all`) reports `0` violations/warnings, `0` unconnected items, and `0` schematic parity issues.
- `silk_annotator.py --inspect` exits `0` with `RESULT: PASS` (`0` tether drift, `0` split pairs, `0` overlaps, `0` keepout hits, `0` QR via/track hits).
- PCB analyzer reports `routing_complete: true`, `unrouted_net_count: 0`, `0` errors, and `0` `VP-001` via-in-pad warnings.
- Exported CPL CSV contains `0` `DNP` / `TP*` / `FID*` rows.
- Workspace-local `analysis/top.png` and `analysis/bottom.png` renders show legible text, tented vias, clean clearances, and expected side placement.
