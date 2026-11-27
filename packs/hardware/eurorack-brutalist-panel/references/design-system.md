# Dark Techno / Brutalist Eurorack Panel Design System

Visual, typographic, geometric, and fabrication specification for **Matte Black + ENIG Gold + White Silkscreen** 3U Eurorack front panels.

---

## 1. Palette & PCB Stackup

Always draw `01_F_Mask_Gold` and `02_F_SilkS_White` in **Preview Hex** (`#D8B154` / `#F4F5F7`) inside VectorCraft so `preview_*.png` renders accurately and `_audit_*.png` (which renders on a black background) stays non-empty; `audit_panel_svgs.py` remaps fills to **Fab Hex** during `1:1 mm` normalization.

| Layer / Role | Preview Hex | Fab SVG Hex | KiCad Stackup / Finish |
| :--- | :--- | :--- | :--- |
| **FR4 Substrate / Mask** | `#141518` (rim `#2a2d34`) | — | `F.Mask` / `B.Mask`: `"Black"` (`0.01 mm`) |
| **Exposed Copper (`F.Mask`)** | `#D8B154` | `#C89B3C` | `F.Cu` / `B.Cu` (`0.035 mm`) + `"ENIG"` copper finish |
| **Top / Bottom Ink (`F.SilkS`)** | `#F4F5F7` | `#000000` | `F.SilkS` / `B.SilkS`: `"White"` |
| **Mockup Drills & LED** | `#07080a` (rim `#383c46`, LED `#1c3322`) | — | PTH/NPTH cutouts |
| **Keepout Overlay (`preview_keepouts.png`)** | `#00d4ff` knobs, `#ffaa00` nuts/bezels, `#ff33aa` rails/M3 washers, `#44ff66` `F.Cu`/NPTH pullbacks | — | Visual verification layer only |

---

## 2. Typography & Baseline Alignment

Use macOS fonts verified in `vectorcraft-cli` with zero fallback warnings:

| Role | Font Family | Style | Verified `cap_height / size` | Notes |
| :--- | :--- | :--- | :---: | :--- |
| **Title slab & tight labels** | `DIN Condensed` | `Bold` | `0.712` | Compact headers, slab knockouts, and tight jack/switch labels (e.g., `ENV / SKEW`, `SMOOTH`, `SLEW IN`, `INV OUT`) |
| **Primary control labels** | `DIN Alternate` | `Bold` | `0.720` | Pot labels and short jack/polarity tags (e.g., `GAIN`, `RAW`, `+ / −`, `FAST`, `IN`, `OUT`) |
| **Maker / rev signature** | `Menlo` | `Bold` | `0.728` | Compact footer tags (e.g., `<MAKER> // R1.0`); avoids missing `JetBrains Mono Bold` style warning |

- **Vertical centering:** `text.create` anchors at the typographic **baseline**. Center uppercase labels vertically inside a band centered at `cy` via:
  ```python
  y_baseline = cy + 0.5 * (cap_ratio * size_mm)
  ```
- **Monochrome KiCad rule:** VectorCraft exports all glyphs via `type.createOutlines`. Punch inverted labels (e.g., title slab and output-pill knockouts) out of solid shapes with `object.pathfinder.minusFront` rather than stacking dark text over light fills.

---

## 3. Brutalist Architectural Vocabulary & Symmetry

1. **Top Rail Right Hero Emblem (`F.Mask`):** Place a bold ENIG Gold signal/topology emblem beside the top-left `H1` slot, keeping `>= 1.50 mm` clear of the `7.0 mm` M3 washer sweep (`hx ± (slot_w - slot_h)/2 ± 3.50 mm`) and `>= 0.80 mm` from `Edge.Cuts`. When combining an envelope with underlying waveform bars, keep all bars beneath the envelope on a shared baseline with equal tail bars underneath flat sustain/decay segments.
2. **Title Slab (`F.Mask`) + Hairline Rule (`F.SilkS`):** Full-width chamfered ENIG Gold polygon (`tr` + `bl` diagonal chamfers) with bold short title punched out via `minusFront`, underlined `~0.6–0.7 mm` below by a `0.24 mm` white rule.
3. **Segmented Side Edge Rails (`F.Mask`):** Vertical `0.42 mm` ENIG Gold bars inset `0.85 mm` from left/right `Edge.Cuts`, broken cleanly at control-row boundaries.
4. **Potentiometer Rows (`F.SilkS` + `F.Mask`):**
   - **Labels:** Left-aligned horizontal labels tucked into the upper-left corner pocket outside the `14.0 mm` max-knob circle (`y_baseline ≈ y_pot - 5.20 mm` for `15.5 mm` pitch).
   - **300° Radial Scales:** `11` ticks (`-150°..+150°`, `30°` step) extending outside `14.0 mm` knob skirts (`R = 6.40..8.00 mm` major `0.28 mm`, `R = 6.50..7.60 mm` minor `0.20 mm`; cap `0°` at `R = 7.60 mm` to clear upper neighbors).
   - **Functional Gold Accents:** Reserve `F.Mask` marks for functional extremes or detents (e.g., `+150°` max-drive wedge, `12 o'clock` center-detent chevron).
   - **Right-Flank Sculptural Glyphs (`F.Mask`):** Pair each control with a geometric transfer-function motif (e.g., `GAIN` stepped bars, `ATK` `_/‾` rise, `REL` `‾\_` fall, `OFFSET` `[+]`/`—`/`[−]`) clearing dial ticks by `>= 0.90 mm`. **Mirror corner chamfers across symmetry axes** (e.g., `[+]` `tl`/`br` vs `[−]` `tr`/`bl`).
5. **Mode & Monitor Row (`SW` / `LED`):**
   - Match labels strictly to hardware lever truth in `panel_svg_spec.md` (e.g., `SW1` UP = `SMOOTH`, `SW2` UP = `SLOW`).
   - Frame 3 mm LEDs with a flat-sided octagonal ENIG Gold bezel (`regular_polygon_points(..., 8, rot_deg=22.5)`, `R_mid ≈ drill/2 + 1.22 mm`, `0.52 mm` stroke) whose inner apothem clears the NPTH copper pullback (`drill/2 + 0.50 mm`).
6. **Patchbay Hierarchy:**
   - Separate controls from jacks with a `0.55 mm` full-width ENIG Gold bus bar.
   - Connect normaled jack pairs with a solid ENIG Gold arrow (`→`) clearing `9.5 mm` nut keepouts by `>= 0.65 mm`.
   - Enclose outputs inside a chamfered ENIG Gold **Output Bay frame** (`0.50 mm` inside-aligned stroke) with a `0.50 mm` vertical divider spine between jacks.
   - Punch output labels out of chamfered solid white pills (`minusFront`). **Align pill outer bottom chamfers parallel to the enclosing Output Bay frame corners and mirror them across the spine** (left output `tr`/`bl`, right output `tl`/`br`).
7. **Footer (`H2` Rail):** Place a chamfered ENIG Gold registration square beside the right-aligned `Menlo Bold` maker/revision tag (e.g., `<MAKER> // R1.0`), clear of `H2`'s M3 washer sweep.

---

## 4. Hard Fabrication & Clearance Rules

| Rule | Spec Minimum | Design Target | Checked By |
| :--- | :---: | :---: | :--- |
| `F.SilkS` edge inset | `>= 0.50 mm` | `>= 0.60 mm` | `audit_panel_svgs.py` |
| `F.Mask` edge pullback (over `F.Cu` pour) | `>= 0.60 mm` | `>= 0.80 mm` | `audit_panel_svgs.py` |
| `F.Mask` NPTH LED pullback | `>= drill/2 + 0.50 mm` | `>= drill/2 + 0.60 mm` | `audit_panel_svgs.py` |
| `F.SilkS` ↔ `F.Mask` clearance | `>= 0.20 mm` | `>= 0.30 mm` | `audit_panel_svgs.py` + `kicad-cli pcb drc` |
| `F.SilkS` stroke / cap height | `>= 0.15 mm` / `>= 0.80 mm` | `>= 0.20 mm` / `>= 1.10 mm` | Design review |
| `F.Mask` opening / bridge | `>= 0.20 mm` | `>= 0.28 mm` | Design review |
| M3 washer / nut / bezel keepouts | `0` overlap | `>= 0.65 mm` clear | `audit_panel_svgs.py` |
| Fab SVGs | `1:1 mm` Plain SVG, paths only, `#registration_frame` `(0,0)→(W,H)` | Exact | `audit_panel_svgs.py` + `vectorcraft-cli info` |
