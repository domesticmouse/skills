---
name: eurorack-panel
description: >-
  Design, inspect, and generate mated 3U Eurorack front panels in KiCad (.kicad_pcb)
  from an existing main circuit PCB. Automatically extracts jack, potentiometer,
  switch, and LED coordinates from the main board, applies footprint-to-bushing
  mechanical offsets (such as the +6.48mm WQP-PJ398SM Thonkiconn offset), detects
  10-48 sub-miniature (5.2mm) vs 1/4-40 miniature (6.2mm) toggle drills, places
  Doepfer A-100 standard M3 mounting slots, supports both auto-labeled and blank-front
  (--blank-front) faceplates with collision-free back-face B.SilkS metadata (module
  name, version, URL, 5x5mm JLCPCB QR placeholder), exports Markdown/JSON SVG
  dimension specifications (--spec-md) for downstream SVG-crafting apps (F.SilkS and
  F.Mask), fills grounded F.Cu/B.Cu copper shield planes, runs DRC checks, and
  exports fabrication-ready Gerbers, Excellon drills, and 3D renders. Use whenever
  the user asks to plan, design, align, create, or export a Eurorack front panel,
  blank faceplate, SVG dimension spec, or KiCad faceplate.
---

# Eurorack Front Panel Design & Generation (`eurorack-panel`)

This skill automates mechanical alignment, KiCad `.kicad_pcb` generation, SVG dimension specification export, DRC verification, and Gerber/Drill packaging for **Doepfer A-100 3U Eurorack Front Panels** mated to a main circuit PCB.

## 1. Critical Mechanical Alignment Rules

1. **Footprint Origin vs. Bushing/Shaft Center & Toggle Drills**:
   - In KiCad, panel-mounted component footprints (jacks, vertical pots, switches, LEDs) rarely place `(0, 0)` at the mechanical shaft/bushing center (e.g., Thonkiconn `WQP-PJ398SM` offsets `(0.00, +6.48 mm)` from Pad `S`).
   - Always locate the shaft/bushing `fp_circle` inside the footprint definition and rotate `(cx, cy)` by the placement angle before drilling cutouts.
   - Distinguish **`10-48` sub-miniature toggles** (e.g. Dailywell `2MS1` / Tayda `A-6087` -> **`5.2 mm`** drill, `7.2 mm` back GND pad) from **`1/4-40` miniature toggles** (`6.2 mm` drill), and override individual holes with `--drill REF=MM` if hardware varies. See [Eurorack Mechanical Specification & KiCad Footprint Offsets](./references/eurorack_mechanical_spec.md) for complete tables.
2. **Vertical Centering & Rail Lip Clearance**:
   - Standard 3U panel height is **`128.5 mm`**. Centering a `108.0 mm` main PCB leaves **`10.25 mm`** top/bottom clearance behind standard `~7.5 mm` Eurorack rail lips and M3 mounting slots.
   - Keep the panel in the **same global KiCad coordinate system** as the main PCB while setting `(grid_origin X0 Y0)` and `(aux_axis_origin X0 Y0)` to the panel's top-left corner so every hole shares identical global `(X, Y)` coordinates with the main PCB's bushing centers.
3. **Grounded Shield Planes, Smooth Front Mask & Collision-Free Back Silkscreen**:
   - Use plated through-holes with `(layers "*.Cu" "B.Mask")` on jack, pot, and switch cutouts so `F.Mask` tents `F.Cu` cleanly on the front while `B.Mask` exposes an annular grounding ring on the rear for chassis `GND` bonding.
   - On `B.SilkS`, the generator automatically places mirrored (`(justify mirror)`), non-overlapping **module name + version/HP**, optional **GitHub/project URL**, and a **`5.0 × 5.0 mm` solid filled JLCPCB QR placeholder** clear of all `B.Mask` pads, M3 slots, and panel edges.

---

## 2. Automated Panel Workflow

### Step 1: Inspect Coordinates & Optionally Export SVG Dimension Spec
Run [generate_eurorack_panel.py](./scripts/generate_eurorack_panel.py) with `--inspect` to parse the main `.kicad_pcb`, auto-detect its `Edge.Cuts` outline and HP width, extract panel-mounted controls, and print the coordinate/drill table. Add `--spec-md` (plus `--url`, `--version`, `--blank-front`, `--drill`) to emit a complete **Markdown + embedded JSON SVG dimension spec** without generating a `.kicad_pcb` yet:

```bash
python3 .agents/skills/eurorack-panel/scripts/generate_eurorack_panel.py \
    --main-pcb envelope_follower.kicad_pcb \
    --inspect \
    --url "github.com/domesticmouse/EnvelopeFollowerWithSkewLimiter" \
    --spec-md panel_svg_spec.md
```

### Step 2A: Generate a Standard Auto-Labeled Front Panel
Generate the standalone front panel board with auto-derived `F.SilkS` labels/badges, refill `F.Cu`/`B.Cu` `GND` zones via `pcbnew.ZONE_FILLER`, run `kicad-cli pcb drc`, and package Gerbers + Excellon drills (run outside the sandbox with `BypassSandbox: true` on macOS if sandbox access to `/Applications/KiCad/KiCad.app` is restricted):

```bash
python3 .agents/skills/eurorack-panel/scripts/generate_eurorack_panel.py \
    --main-pcb BufferedMult.kicad_pcb \
    --output BufferedMult_Panel.kicad_pcb \
    --title "BUF MULT" \
    --subtitle "1:3 / 1:6" \
    -l D4=ENV \
    --gerber-dir production/panel \
    --zip production/BufferedMult_Panel.zip \
    --drc
```

### Step 2B: Generate a Blank-Front Faceplate & Export SVG Spec
Pass `--blank-front` to emit **zero `F.SilkS` graphics** on the front while placing mirrored module name, `--version` (defaults to `title_block.rev`), `--url`, and the `5 × 5 mm` JLCPCB QR square on `B.SilkS`. Pass `--spec-md` to produce the Markdown + JSON spec for a downstream SVG-crafting skill/app:

```bash
python3 .agents/skills/eurorack-panel/scripts/generate_eurorack_panel.py \
    --main-pcb envelope_follower.kicad_pcb \
    --output envelope_follower_panel.kicad_pcb \
    --blank-front \
    --title "ENVELOPE FOLLOWER + SKEW LIMITER" \
    --version "Rev 1.0" \
    --url "github.com/domesticmouse/EnvelopeFollowerWithSkewLimiter" \
    --spec-md panel_svg_spec.md \
    --drc
```

To apply custom artwork generated from `panel_svg_spec.md` onto the blank front face:
1. Pass `panel_svg_spec.md` to your SVG-crafting skill/app to produce aligned **1:1 mm** Plain SVGs (text/strokes converted to paths) for `F.SilkS` and `F.Mask` with a `(0, 0)` → `(panel_w, 128.50)` registration frame.
2. In KiCad PCB Editor, open the generated `*_panel.kicad_pcb`, run **File → Import → Graphics...** at Scale `1.0` onto `F.SilkS` and `F.Mask`, anchor at the panel origin, **Ungroup** and delete the temporary registration frame, press **`B`** to refill zones, and re-run `kicad-cli pcb drc`. See Section 3 of [Eurorack Mechanical Specification & KiCad Footprint Offsets](./references/eurorack_mechanical_spec.md) for copper pullback and clearance rules.

### Step 3: Verify with KiCad PCB/Gerber Analyzers & 3D Renders
1. **Static & Gerber Verification** (using the [`aklofas/kicad-happy`](https://github.com/aklofas/kicad-happy) `kicad` skill analyzers when present; use `.venv/bin/python` with Python `>= 3.10`):
   ```bash
   .venv/bin/python .agents/skills/kicad/scripts/analyze_pcb.py BufferedMult_Panel.kicad_pcb --full --output /tmp/panel_pcb.json
   .venv/bin/python .agents/skills/kicad/scripts/analyze_gerbers.py production/panel/ --full --output /tmp/panel_gerbers.json
   ```
   Confirm `0` DRC errors, `0` unconnected items, `0` Gerber errors, and drill counts matching the panel's component manifest (grounded jack/pot/switch PTH cutouts + `2` or `4` M3 NPTH oval mounting slots + any NPTH LED apertures; note that `analyze_gerbers.py` counts NPTH LED holes such as `3.2 mm` under `mounting_holes`, and `analyze_pcb.py` may emit benign `CP-002` `info` notices on copper-shield panels).
2. **Visual 3D Raytraced Inspection** (always render into workspace-local paths—**never** `/tmp/`, where reading external images can trigger permission timeouts):
   ```bash
   mkdir -p panel
   /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli pcb render \
       --side top --width 800 --height 2400 --output panel/BufferedMult_Panel_front.png BufferedMult_Panel.kicad_pcb
   /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli pcb render \
       --side bottom --width 800 --height 2400 --output panel/BufferedMult_Panel_back.png BufferedMult_Panel.kicad_pcb
   ```
   Inspect `panel/BufferedMult_Panel_front.png` and `panel/BufferedMult_Panel_back.png` to confirm silkscreen labels clear all `9.5 mm` M6 nut keepouts (`Dwgs.User` circles) and board edges.

---

## 3. Code Quality & Linting (`ruff`)

* **Mandatory Lint & Format Step**: Whenever you create or modify Python scripts for panel generation or PCB inspection (such as [generate_eurorack_panel.py](./scripts/generate_eurorack_panel.py) or any project Python files), **always** run `ruff` lint and format over the modified Python files before finishing:
  ```bash
  ruff check --fix .agents/skills/eurorack-panel/scripts/generate_eurorack_panel.py
  ruff format .agents/skills/eurorack-panel/scripts/generate_eurorack_panel.py
  ```
* **Scoped Target Files**: Pass explicit Python file paths to `ruff` rather than `.` so third-party skill scripts in `.agents/skills/` remain untouched.
* **Executable Shebangs**: If a script starts with `#!/usr/bin/env python3`, ensure it has executable permissions (`chmod +x <script>.py`) so `ruff` (`EXE001`) passes.
