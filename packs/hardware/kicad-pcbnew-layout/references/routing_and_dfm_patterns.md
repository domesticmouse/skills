# Routing, Mechanical & DFM Patterns for Automated 2-Layer PCBs

Patterns distilled from generating and debugging a dense 62-part, 36-net 6 HP Eurorack mixed-signal PCB (`0` DRC violations, `0` analyzer errors, `0` `VP-001` via-in-pad warnings).

## 1. Eurorack `F.Cu` Controls + `B.Cu` SMD/Power Sandwich

When height/width is tight (e.g., `30.00 x 108.00 mm` rear PCB centered behind a `30.00 x 128.50 mm` 6 HP 3U panel with `10.25 mm` top/bottom rail clearance):

- **Front side (`F.Cu`)**: Panel-interface THT components only (pots, 3.5 mm jacks, front LEDs) kept flush to the rear of the faceplate.
- **Back side (`B.Cu`)**: Shrouded `2x5` IDC power header (`J_PWR`), `DNP` test points (`TP1`–`TP8`), and all SMD ICs/passives/diodes.
- **Exact footprint-origin-to-bushing math** (KiCad 10 standard libraries):
  - `Potentiometer_Alpha_RD901F-40-00D_Single_Vertical` at `rot = 90°`: shaft center is `(+2.50, -7.50) mm` relative to footprint origin (e.g. origin `(5.50, 33.50)` aligns shaft at `(8.00, 26.00)`).
  - `Jack_3.5mm_QingPu_WQP-PJ398SM_Vertical_CircularHoles` at `rot = 0°`: bushing center is `(0.00, +6.48) mm` relative to origin, and includes an internal circular `F.Cu` keepout zone (`fp.Zones()`) around the bushing that the router **must** extract and avoid (`block_via = True` on `F.Cu`).
  - `LED_D3.0mm` at `rot = 0°`: lens center is `(+1.27, 0.00) mm` relative to origin (`Pad 1` = cathode, `Pad 2` = anode at `+2.54 mm`).
- **THT Keepout Discipline**: Avoid placing `B.Cu` SMD parts inside panel-component courtyard/lug footprints or across THT drill clearance zones; cluster SMDs in inter-row corridors (`top zone`, between `RV1/2` and `RV3/4` lug/pin bands, mid jack corridor, and bottom power zone).

## 2. Routing Order & Pre-Routing Traps

On dense mixed-signal boards with SOIC-14 op-amps (`U1`/`U2`) flanked closely by `0603` decoupling caps (`C5`–`C8`):

1. **Immediate `B.Cu` SMD `GND` Stitching Vias**:
   Place a nearby `GND` via (`0.60 / 0.30 mm` tented) + short `B.Cu` stub for **every** `B.Cu` SMD `GND` pad before routing any signal nets. Otherwise horizontal signal tracks will trap SMD `GND` pads inside isolated copper pockets.
2. **Reserve IC Outward Escape Stubs Before General Routing**:
   - Measure escape offsets from the pad's **actual outer copper edge** (`x0 - 0.05` on left side, `x1 + 0.05` on right side), **not** `cx ± 0.55`. SOIC-14 pads are `1.95 mm` wide (`half-width = 0.975 mm`), so `cx ± 0.55` stays inside the pad and invites via-in-pad failures.
3. **Pre-Route Decoupling Caps**:
   Connect `U1.4 <-> C5`, `U1.11 <-> C6`, `U2.4 <-> C7`, and `U2.11 <-> C8` directly on `B.Cu` at power trace width (`0.30 mm`) and merge those pairs into connected clusters before A* runs.
4. **Prioritize Constricted IC Breakout Nets**:
   Horizontally pre-routed `-12V` decoupling traces above narrow IC-to-passive channels can bottleneck adjacent IC pins (`U1.12` / `U1.14` / `U2.13`). Route constrained IC breakout nets (`is_pwr = -1`) first, then power rails (`is_pwr = 0`, `0.30 mm`), then general signal nets (`is_pwr = 1`, `0.25 mm`) sorted by bounding-box span.

## 3. Preventing `VP-001` (Via-in-Pad) & `holes_co_located`

Two grid bugs commonly appear when writing an A* PCB router:

- **Via-in-Pad (`VP-001`)**: Allowing `can_place_via()` whenever `pad_net[L][idx] == net_code` causes the router to drop vias inside same-net SMD pads.
  - **Fix**: Populate an explicit `smd_via_block` map using exact grid-point testing (`x0 - 0.02 <= px <= x1 + 0.02` and `y0 - 0.02 <= py <= y1 + 0.02` — avoid coarse `floor`/`ceil` rounding over `pad_net`, which can block every grid column in a `1.3 mm` SOIC-to-`0603` channel). Always reject vias when `smd_via_block[idx]` is set, even if `vstate in targets`.
- **Co-Located Drill Holes (`holes_co_located`)**: Letting A* transition `F.Cu <-> B.Cu` at a THT pad anchor and emitting `add_via()` drops a `0.30 mm` via drill directly inside the THT plated hole.
  - **Fix**: Record all THT pad grid anchors in `tht_pad_grid[(gx, gy)] = net_code`. Inside A*, allow `0`-cost layer transitions at `tht_pad_grid` cells matching the current net without checking `can_place_via()`, and skip `add_via()` during track emission when `tht_pad_grid.get((gx, gy)) == net_code`. Also block `via_block` around all THT drills (including unconnected pot mounting lugs).

## 4. Preserving T-Junctions During Collinear Segment Merging

Collapsing collinear steps along each A* path dramatically cuts segment count (~4000 micro-segments -> ~500 clean tracks). However, if branch `B` starts or ends on an intermediate vertex `p` of branch `A` (`main_copper`), and `p` falls onto an off-grid stub or via junction that gets merged across blindly or leaves an endpoint mismatch, KiCad DRC flags `track_dangling`.

- **Fix**:
  1. Immediately mark segments/vias on `router` as each branch is routed, and collect `junctions.add(path[0]); junctions.add(path[-1])`.
  2. Emit merged tracks after all branches of a net complete via `_merge_collinear_path(path, junctions)`, keeping any vertex `p_cur in junctions` intact even when collinear.
  3. Deduplicate emitted vias per net (`emitted_vias.add((gx, gy))`).

## 5. Silkscreen Label Corridors & Density-Adaptive Passive Labeling

On narrow boards (`<= 30 mm` wide) where 45–60 SMD parts share `B.Cu` alongside THT panel pin headers and test points, cramming `0603` passives into `< 2.0 mm` vertical/horizontal pitches leaves zero local solder mask for `<REF> + <VAL>` pairs (`~5–9 mm` wide each at `0.80 mm` text height).

- **Pair `1.5–2.0 mm` row spacing with value-only passive labels (`R*`, `C*`)**:
  - Keep at least `1.5–2.0 mm` of clear solder mask beside dense `0603`/`0805` passive rows and away from THT pad rows and IC `.Fab` bodies.
  - On dense sides (`>= 1.0 footprints/cm²` or `>= 35` parts), label resistors (`R*`) and capacitors (`C*`) with only their concise primary value (`10k`, `100nF`, `15pF`, `22uF`) via `place_ref_val_pair(..., val_only="auto")` / `place_val_only()` so every label fits within `<= 3.5 mm` of its own footprint edge (`<= 6.0 mm` for THT).
  - Reserve `<REF> + <VAL>` pairs for ICs (`U*`), diodes (`D*`), controls (`RV*`), jacks (`J*`), LEDs, and test points (`TP*`), and never add board-wide fallback scans that scatter labels across the board.
