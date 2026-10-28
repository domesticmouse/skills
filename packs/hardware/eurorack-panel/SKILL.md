---
name: eurorack-panel
description: >-
  Design, inspect, and generate mated 3U Eurorack front panels in KiCad (.kicad_pcb)
  from an existing main circuit PCB. Automatically extracts jack, potentiometer,
  switch, and LED coordinates from the main board, applies footprint-to-bushing
  mechanical offsets (such as the +6.48mm WQP-PJ398SM Thonkiconn offset), places
  Doepfer A-100 standard M3 mounting slots, generates silkscreen labels and input
  callout badges, fills grounded F.Cu/B.Cu copper shield planes via KiCad's
  pcbnew API, runs DRC checks, and exports fabrication-ready Gerbers, Excellon
  drills, and 3D renders. Use whenever the user asks to plan, design, align,
  create, or export a Eurorack front panel or faceplate in KiCad.
---

# Eurorack Front Panel Design & Generation (`eurorack-panel`)

This skill automates the mechanical alignment, KiCad `.kicad_pcb` generation, DRC verification, and Gerber/Drill export of **Doepfer A-100 3U Eurorack Front Panels** mated to a main circuit PCB.

## 1. Critical Mechanical Alignment Rules

1. **Footprint Origin vs. Bushing/Shaft Center**:
   - In KiCad, panel-mounted component footprints (jacks, vertical pots, switches, LEDs) rarely place their `(0, 0)` origin at the mechanical shaft/bushing center.
   - Example: In `Connector_Audio:Jack_3.5mm_QingPu_WQP-PJ398SM_Vertical_CircularHoles` (Thonkiconn), `(0, 0)` is **Pad `S` (Sleeve)**, while the **M6 threaded bushing center** (`fp_circle`) is offset by **`(0.00, +6.48 mm)`** at `rotation = 0°`.
   - Always locate the shaft/bushing `fp_circle` inside the footprint definition and rotate the offset `(cx, cy)` by the footprint's placement angle before drilling panel cutouts. See [Eurorack Mechanical Specification & KiCad Footprint Offsets](./references/eurorack_mechanical_spec.md) for the complete HP width and component offset tables.
2. **Vertical Centering & Rail Lip Clearance**:
   - Standard 3U panel height is **`128.5 mm`**.
   - Centering a `108.0 mm` main PCB vertically behind a `128.5 mm` panel leaves **`10.25 mm`** of clearance at both the top and bottom edges, clearing standard `~7.5 mm` Eurorack rail lips and M3 mounting hardware.
   - Keep the panel in the **same global KiCad coordinate system** as the main PCB while setting `(grid_origin X0 Y0)` and `(aux_axis_origin X0 Y0)` to the panel's top-left corner so every hole shares identical global `(X, Y)` coordinates with the main PCB's bushing centers.
3. **Grounded Shield Planes & Smooth Front Solder Mask**:
   - Use plated through-holes (`thru_hole circle`, `6.2 mm` drill, `8.6 mm` pad) with `(layers "*.Cu" "B.Mask")` on jack cutouts:
     - **Front (`F.Cu` / `F.Mask`)**: Solid zone connection (`(connect_pads yes)`) tented under solder mask for a smooth, blemish-free exterior finish with zero thermal-spoke shadows or exposed copper rings around the `9.5 mm` M6 nuts.
     - **Back (`B.Cu` / `B.Mask`)**: Exposed `8.6 mm` gold/HASL grounding ring so tightening the jack nuts or resting the jack bushing shoulders automatically bonds both `F.Cu` and `B.Cu` shield planes to chassis `GND`.
   - Place **`JLCJLCJLCJLC`** on `B.SilkS` (mirrored) so the PCB manufacturer prints the order barcode on the rear face.

---

## 2. Automated Panel Workflow

### Step 1: Inspect Main PCB Coordinates & Bushing Offsets
Run [generate_eurorack_panel.py](./scripts/generate_eurorack_panel.py) with `--inspect` to parse the main `.kicad_pcb` file, auto-detect its `Edge.Cuts` outline (`gr_rect` or `gr_line`) and HP width, extract panel-mounted components (3.5mm jacks, vertical potentiometers, toggle switches, and 3mm/5mm THT LEDs), and print the exact footprint-origin, global-bushing, and panel-local `(X, Y)` coordinates:

```bash
python3 .agents/skills/eurorack-panel/scripts/generate_eurorack_panel.py \
    --main-pcb BufferedMult.kicad_pcb \
    --inspect
```

### Step 2: Generate the Panel `.kicad_pcb`, Run DRC, and Export Gerbers
Generate the standalone front panel board, automatically refill `F.Cu` and `B.Cu` `GND` copper zones via KiCad's bundled `pcbnew.ZONE_FILLER`, run `kicad-cli pcb drc`, and package Gerbers + Excellon drills (run outside the sandbox with `BypassSandbox: true` on macOS if sandbox access to `/Applications/KiCad/KiCad.app` is restricted):

```bash
python3 .agents/skills/eurorack-panel/scripts/generate_eurorack_panel.py \
    --main-pcb BufferedMult.kicad_pcb \
    --output BufferedMult_Panel.kicad_pcb \
    --title "BUF MULT" \
    --subtitle "1:3 / 1:6" \
    --gerber-dir production/panel \
    --zip production/BufferedMult_Panel.zip \
    --drc
```

### Step 3: Verify with KiCad PCB/Gerber Analyzers & 3D Renders
1. **Static & Gerber Verification** (using the [`aklofas/kicad-happy`](https://github.com/aklofas/kicad-happy) `kicad` skill analyzers when present):
   ```bash
   python3 .agents/skills/kicad/scripts/analyze_pcb.py BufferedMult_Panel.kicad_pcb --full --output /tmp/panel_pcb.json
   python3 .agents/skills/kicad/scripts/analyze_gerbers.py production/panel/ --full --output /tmp/panel_gerbers.json
   ```
   Confirm `0` DRC errors, `0` unconnected items, `0` Gerber findings, and exact drill counts (`8` jack PTH holes + `2` or `4` M3 NPTH oval slots).
2. **Visual 3D Raytraced Inspection**:
   ```bash
   /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli pcb render \
       --side top --width 800 --height 2400 --output /tmp/panel_front.png BufferedMult_Panel.kicad_pcb
   /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli pcb render \
       --side bottom --width 800 --height 2400 --output /tmp/panel_back.png BufferedMult_Panel.kicad_pcb
   ```
   Inspect `/tmp/panel_front.png` and `/tmp/panel_back.png` to confirm silkscreen labels clear all `9.5 mm` M6 nut keepouts (`Dwgs.User` circles) and board edges.

---

## 3. Code Quality & Linting (`ruff`)

* **Mandatory Lint & Format Step**: Whenever you create or modify Python scripts for panel generation or PCB inspection (such as [generate_eurorack_panel.py](./scripts/generate_eurorack_panel.py) or any project Python files), **always** run `ruff` lint and format over the modified Python files before finishing:
  ```bash
  ruff check --fix .agents/skills/eurorack-panel/scripts/generate_eurorack_panel.py
  ruff format .agents/skills/eurorack-panel/scripts/generate_eurorack_panel.py
  ```
* **Scoped Target Files**: Pass explicit Python file paths to `ruff` rather than `.` so third-party skill scripts in `.agents/skills/` remain untouched.
* **Executable Shebangs**: If a script starts with `#!/usr/bin/env python3`, ensure it has executable permissions (`chmod +x <script>.py`) so `ruff` (`EXE001`) passes.
