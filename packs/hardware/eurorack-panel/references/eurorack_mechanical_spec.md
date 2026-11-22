# Eurorack Mechanical Specification & KiCad Footprint Offsets

## 1. Doepfer A-100 3U Panel Dimensions & HP Width Table

- **Standard 3U Panel Height**: **`128.5 mm`**
- **Maximum Rear PCB Height (between rails)**: **`108.0 mm – 110.0 mm`** (`108.0 mm` recommended, giving `10.25 mm` top and bottom clearance when centered behind a `128.5 mm` panel).
- **Horizontal Pitch (1 HP)**: `5.08 mm` (`0.200"`). Actual manufactured panels are slightly narrower than $N \times 5.08\text{ mm}$ to allow tolerance between adjacent modules:

| HP | Nominal $N \times 5.08\text{ mm}$ | Doepfer Standard Width ($\text{mm}$) | Mounting Holes | Left Hole $X_{\text{local}}$ ($\text{mm}$) | Right Hole $X_{\text{local}}$ ($\text{mm}$) |
| --: | :---: | :---: | :---: | :---: | :---: |
| **1 HP** | `5.08` | `5.00` | 1 top, 1 bottom | `2.50` | — |
| **2 HP** | `10.16` | `9.80` | 1 top, 1 bottom | `7.50` (or `5.00` slot) | — |
| **3 HP** | `15.24` | `15.00` | 1 top, 1 bottom | `7.50` | — |
| **4 HP** | `20.32` | **`20.00`** | 1 top, 1 bottom | **`7.50`** | — |
| **6 HP** | `30.48` | `30.00` | 1 top, 1 bottom | `7.50` | — |
| **8 HP** | `40.64` | `40.30` | 1 top, 1 bottom | `7.50` | — |
| **10 HP** | `50.80` | `50.50` | 2 top, 2 bottom | `7.50` | `43.18` (`7.50 + 7 × 5.08`) |
| **12 HP** | `60.96` | `60.60` | 2 top, 2 bottom | `7.50` | `53.34` (`7.50 + 9 × 5.08`) |
| **14 HP** | `71.12` | `70.80` | 2 top, 2 bottom | `7.50` | `63.50` (`7.50 + 11 × 5.08`) |
| **16 HP** | `81.28` | `80.90` | 2 top, 2 bottom | `7.50` | `73.66` (`7.50 + 13 × 5.08`) |
| **20 HP** | `101.60` | `101.30` | 2 top, 2 bottom | `7.50` | `93.98` (`7.50 + 17 × 5.08`) |

### Rack Mounting Holes / Slots (M3)
- **Vertical Y Coordinates (from Top Edge of `128.5 mm` Panel)**:
  - **Top Mounting Hole/Slot**: **`Y = 3.00 mm`**
  - **Bottom Mounting Hole/Slot**: **`Y = 125.50 mm`** (`3.00 mm` from bottom edge; `122.50 mm` vertical center-to-center spacing)
- **Hole vs. Oval Slot**:
  - Circular M3 hole: **`3.2 mm`** diameter (`NPTH`).
  - Oval M3 slot (recommended for PCB panels): **`5.5 mm` wide × `3.2 mm` tall** (`NPTH` oval pad + drill), accommodating both fixed threaded strips (`5.08 mm` pitch) and sliding M3 nuts.

---

## 2. Panel-Mounted Component Cutouts, Standoffs & KiCad Offsets

Most vertical PCB-mounted panel components establish a **`~10.0 mm – 11.0 mm`** board-to-panel standoff height between `F.Cu` of the main PCB and `B.Cu` of the front panel:

| Component Type | Common Part / MPN | KiCad Footprint | Footprint Origin `(0, 0)` | Shaft / Bushing Offset `(dx, dy)` at `rot=0` | Panel Hole Drill ($\text{mm}$) | Nut / Bezel Keepout OD ($\text{mm}$) | Board-to-Panel Standoff ($\text{mm}$) |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| **3.5mm Mono Jack (Thonkiconn)** | QingPu `WQP-PJ398SM` / `PJ301M-12` | `Connector_Audio:Jack_3.5mm_QingPu_WQP-PJ398SM_Vertical_CircularHoles` | Pad `S` (Sleeve) | **`(0.00, +6.48)`** | **`6.2` – `6.3`** (M6×0.5 bushing) | **`9.5`** (Knurled / Hex nut) | `10.5` |
| **9mm Vertical Potentiometer** | Alpha `RV09AF-40` / Alps `RK09K` | `Potentiometer_THT:Potentiometer_Alps_RK09K_Single_Vertical` | Pad `1` | **`(+2.50, -7.00)`** *(check `fp_circle`)* | **`7.2` – `7.5`** (M7×0.75) or **`6.3`** (D-shaft) | **`10.5` – `11.0`** (M7 nut + washer) | `10.0` – `10.5` |
| **Sub-Mini Toggle Switch (`10-48`)** | Dailywell `2MS1T1B1M2QES` (`Tayda A-6087`) | `Eurorack_Custom:SW_Toggle_SPDT_Dailywell_2MS1` | Center (`Pin 2`) | **`(0.00, 0.00)`** | **`5.2`** (`4.95–5.2` hole, `7.2` back GND pad) | **`8.2`** (`7.0 mm` hex flats) | `10.5` |
| **Miniature Toggle Switch (`1/4-40`)** | Taiway `100-SP1-T1` / C&K `JS202011JCQN` | `Button_Switch_THT:SW_CuK_JS202011JCQN_DPDT_Straight` | Center / Pin `1` | Inspect `F.Fab` center | **`6.2`** (`8.2` back GND pad) | **`9.0`** (`8.0 mm` hex flats) | `10.5` |
| **3mm THT LED** | Standard 3mm LED | `LED_THT:LED_D3.0mm` | Pad `1` (Cathode) | **`(+1.27, 0.00)`** | **`3.2`** | `4.0` (flange) | Bend/spacer to `10.5` |
| **5mm THT LED** | Standard 5mm LED | `LED_THT:LED_D5.0mm` | Pad `1` (Cathode) | **`(+1.27, 0.00)`** | **`5.2`** | `6.0` (flange) | Bend/spacer to `10.5` |

### Computing Rotated Bushing Coordinates from KiCad Footprints
In KiCad's coordinate system ($X$ right, $Y$ down) where a footprint is placed at `(at X_fp Y_fp ROT_DEG)` on `F.Cu` and the shaft/bushing center inside the footprint definition is `(cx, cy)`:
- KiCad rotates footprints counter-clockwise by `ROT_DEG` in screen space:
  $$\Delta X = c_x \cos(\theta) + c_y \sin(\theta), \quad \Delta Y = -c_x \sin(\theta) + c_y \cos(\theta)$$
  where $\theta = \text{radians}(\text{ROT\_DEG})$.
- Always verify against the footprint's `fp_circle` on `F.Fab` or `F.SilkS`.

---

## 3. Custom Front-Face SVG Artwork (`F.SilkS` & `F.Mask`)

When using `--blank-front` with `--spec-md` to craft custom vector graphics for the front face in an external SVG editor or SVG-crafting skill:

1. **1:1 Millimeter SVG Canvas & Coordinate Origin**:
   - Set SVG root dimensions in millimeters matching the panel width and `128.50 mm` height, with an identical numeric `viewBox`:
     ```xml
     <svg xmlns="http://www.w3.org/2000/svg" width="30.00mm" height="128.50mm" viewBox="0 0 30.00 128.50">
     ```
   - SVG `(0, 0)` is the **top-left corner** of the panel (`+X` right, `+Y` down; `1 user unit = 1.00 mm`), matching KiCad's `grid_origin` / `aux_axis_origin`.
   - Maintain a `0.50 mm` artwork margin inside `Edge.Cuts`, and keep legends clear of `Dwgs.User` nut/bezel keepouts and the top/bottom `6.50 mm` Eurorack rail-lip & M3 washer strips.

2. **Exposed Copper vs. Bare FR4 Pullback (`F.Mask`)**:
   - Generated front panels include a solid **`F.Cu` `GND` shield plane** beneath the solder mask. Any shape placed on **`F.Mask`** removes solder mask and exposes **bare copper** (ENIG gold or HASL silver finish).
   - Because `F.Cu` pulls back **`0.40–0.50 mm`** from `Edge.Cuts` and around NPTH holes (`H1`–`H4`, `LED`s), keep `F.Mask` openings **`>= 0.60 mm`** inside board edges and **`>= drill/2 + 0.50 mm`** outside NPTH drills unless bare FR4 substrate is intentional.
   - Keep **`F.SilkS` and `F.Mask` non-overlapping (`>= 0.20 mm` clearance)** so fab houses do not clip silkscreen over exposed metal and KiCad DRC reports zero `silk_over_copper` errors.

3. **Paths-Only Plain SVG & Manufacturer Minimums (JLCPCB)**:
   - Convert all text objects and strokes into filled paths (`Object to Path` and `Stroke to Path`) before saving as **Plain SVG** so KiCad renders exact outlines without font mismatches.
   - Minimum feature sizes: `F.SilkS` stroke **`>= 0.15 mm`** (`0.18–0.25 mm` recommended), text height **`>= 0.80 mm`** (`1.0 mm+` recommended); `F.Mask` minimum opening and mask bridge **`>= 0.20 mm`**.

4. **Exact Registration Import into KiCad 10**:
   - KiCad's **File → Import → Graphics...** anchors the imported SVG using the bounding box of existing paths (ignoring empty canvas margins).
   - Include a temporary `0.05 mm` **registration rectangle** spanning `(0, 0)` to `(panel_w, 128.50)` in both `front_silkscreen.svg` and `front_soldermask.svg`.
   - Import each SVG at **Scale `1.0`** onto its target layer (`F.SilkS` or `F.Mask`), place its top-left at the panel origin `(panel_x0, panel_y0)` (or `(0, 0)` with aux origin active), **Ungroup**, delete the temporary registration rectangle, refill zones (`B`), and re-run DRC.
