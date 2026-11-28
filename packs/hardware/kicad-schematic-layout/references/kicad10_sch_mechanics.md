# KiCad 10 `.kicad_sch` Mechanics & Symbol Reference

Empirical rules verified against `kicad-cli 10.0.1` and stock KiCad 10 symbol libraries under `/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols`.

## 1. File Format & Symbol Flattening

- **Header**: Use `(version 20251024)`, `(generator "eeschema")`, `(generator_version "10.0")`, `(paper "A3")`, `(sheet_instances (path "/" (page "1")))`, and `(embedded_fonts no)`.
- **Quoted atoms vs bare tokens**: Preserve exact quoting (`""` empty strings, `"Reference"`, `"Value"`, `"Library:Symbol"`) — an unquoted empty string or unescaped quote breaks KiCad parsing.
- **Flattening `(extends ...)` symbols**: Derived symbols such as `Transistor_BJT:BC848` (`extends "Q_NPN_BEC"`), `Transistor_BJT:BC858` (`extends "Q_PNP_BEC"`), and `Amplifier_Operational:TL074` (`extends "LM2902"`) cannot rely on `(extends ...)` inside embedded `lib_symbols`. Recursively merge header clauses, override `(property ...)` definitions, copy child `(symbol "<base>_u_s" ...)` units renamed to `<derived>_u_s`, drop `(extends ...)`, and rename the top-level symbol to `"<Lib>:<Sym>"`. This yields **0 `lib_symbol_mismatch` warnings** in KiCad 10 ERC.
- **Instances block**: Every placed `(symbol ...)` must include `(instances (project "<project_name>" (path "/<root_uuid>" (reference "<ref>") (unit <unit>))))` plus `(pin "<num>" (uuid ...))` for every pin of that unit.
- **`(justify center)` rejection**: KiCad 10 rejects `(justify center)` in schematic property/text `(effects ...)` and fails to load the file (`rc=3`). Centering is the default when horizontal justify is omitted; only emit `left`, `right`, `top`, or `bottom`.
- **DNP / BOM exclusion**: Propagate `dnp` -> `(dnp yes)` and `exclude_from_bom` -> `(in_bom no)` on test points (`TP*`) and DNP parts.

## 2. Coordinate Transform (Symbol Y-Up to Sheet Y-Down)

KiCad symbol definitions have `+Y` pointing **UP**; schematic sheets have `+Y` pointing **DOWN** (`(0, 0)` top-left, `(420, 297)` bottom-right for A3). Never combine `angle != 0` with `mirror` — use either pure rotation or pure mirror at `angle=0`:

| Transform | `rx` | `ry` | Sheet `(wx, wy)` |
| :--- | :--- | :--- | :--- |
| `angle=0, mirror=None` | `px` | `py` | `(sx + px, sy - py)` |
| `angle=90, mirror=None` | `-py` | `px` | `(sx - py, sy - px)` |
| `angle=180, mirror=None` | `-px` | `-py` | `(sx - px, sy + py)` |
| `angle=270, mirror=None` | `py` | `-px` | `(sx + py, sy + px)` |
| `angle=0, mirror="x"` | `px` | `-py` | `(sx + px, sy + py)` (flips top/bottom) |
| `angle=0, mirror="y"` | `-px` | `py` | `(sx - px, sy - py)` (flips left/right) |

## 3. Property Text Rotation & Justification Truth Table

Property `(at x y ANGLE)` coordinates are **absolute sheet coordinates**, while KiCad evaluates text rotation and horizontal justification relative to the symbol's orientation:

- **Upright horizontal text (`0°` on sheet/SVG)**: Set property `angle = sym_angle % 180` (`0` for `sym_angle ∈ {0, 180}`, `90` for `sym_angle ∈ {90, 270}`). Leaving `prop_angle=0` on `90°`/`270°` symbols renders `Reference`/`Value` vertically (`-90°`).
- **Horizontal justification flip**: When `prop_angle = sym_angle % 180`, KiCad swaps `left <-> right` on specific orientations:

| Symbol Orientation | `(justify left)` Behavior | `(justify right)` Behavior | Sheet Compensation |
| :--- | :--- | :--- | :--- |
| `angle=0, mirror=None` | Extends right | Extends left | None |
| `angle=90, mirror=None` | Extends **left** | Extends **right** | Flip `left <-> right` |
| `angle=180, mirror=None` | Extends **left** | Extends **right** | Flip `left <-> right` |
| `angle=270, mirror=None` | Extends right | Extends left | None |
| `angle=0, mirror="x"` | Extends right | Extends left | None |
| `angle=0, mirror="y"` | Extends **left** | Extends **right** | Flip `left <-> right` |

## 4. Verified KiCad 10 Eurorack Symbol Pinouts & Orientations

| KiCad Symbol | Local Pins (Y-up) | Common Orientations |
| :--- | :--- | :--- |
| `Device:R`, `Device:C` | `1=(0, +3.81)`, `2=(0, -3.81)` | `angle=0`: `1` top / `2` bottom; `angle=90`: `1` left / `2` right; `angle=180`: `2` top / `1` bottom; `angle=270`: `2` left / `1` right |
| `Device:C_Polarized` | `1=(0, +3.81)` (`+`), `2=(0, -3.81)` (`-`) | `angle=0`: `+` top (`+12V` or `GND` above `-12V`); `angle=180`: `-` top / `+` bottom |
| `Device:D`, `Device:D_Schottky`, `Device:LED` | `1=K=(-3.81, 0)`, `2=A=(+3.81, 0)` | `angle=0`: `K` left / `A` right (`\|<--`); `angle=180`: `A` left / `K` right (`-->\|`); `angle=90`: `A` top / `K` bottom; `angle=270`: `K` top / `A` bottom |
| `Device:R_Potentiometer` | `1=(0, +3.81)`, `2=(+3.81, 0)` (W), `3=(0, -3.81)` | `angle=0`: `1` top / `3` bottom / `2` right; `angle=180`: `3` top / `1` bottom / `2` left; `angle=90`: `1` left / `3` right / `2` top; `angle=270`: `3` left / `1` right / `2` bottom |
| `Diode:BAT54S` | `1=A=(-7.62, 0)`, `2=K=(+7.62, 0)`, `3=COM=(0, -5.08)` | `angle=90`: `K` top (`+12V`), `A` bottom (`GND`), `COM` right |
| `Transistor_BJT:BC848` (NPN) & `BC858` (PNP) | `1=B=(-5.08, 0)`, `2=E=(+2.54, -5.08)`, `3=C=(+2.54, +5.08)` | `angle=0`: `B` left, `C` top, `E` bottom (NPN); `mirror="x"`: `B` left, `E` top, `C` bottom (PNP shunt); `angle=180`: `B` right, `E` top, `C` bottom (PNP clamp) |
| `Amplifier_Operational:TL074` & `TL072` | Units 1–4 (`TL074`) / 1–2 (`TL072`): `+=(-7.62, +2.54)`, `-=(-7.62, -2.54)`, `OUT=(+7.62, 0)`. Power unit: `TL074` Unit 5 has `4=V+=(-2.54, +7.62)`, `11=V-=(-2.54, -7.62)`; `TL072` Unit 3 has `8=V+=(-2.54, +7.62)`, `4=V-=(-2.54, -7.62)` | `mirror="x"` puts `-` on TOP (feedback loops above) and `+` on BOTTOM; `angle=0` puts `+` on TOP and `-` on BOTTOM |
| `Connector_Generic:Conn_02x05_Odd_Even` | Odds (`1,3,5,7,9`) at `x=-5.08`, Evens (`2,4,6,8,10`) at `x=+7.62`; `1,2` at `y=+5.08` -> `9,10` at `y=-5.08` | `mirror="x"` puts pins `9,10` (`+12V`) at TOP, `3..8` (`GND`) middle, `1,2` (`-12V`) at BOTTOM |
| `Connector_Audio:AudioJack2_SwitchT` | `S=(5.08, 2.54)`, `T=(5.08, 0)`, `TN=(5.08, -2.54)` | `angle=0`: pins exit RIGHT (inputs); `mirror="y"`: pins exit LEFT (outputs/right-facing CV inputs) |
| `Switch:SW_SPDT` | `1=(5.08, 2.54)`, `2=(-5.08, 0)`, `3=(5.08, -2.54)` | `angle=180`: `3` top-left, `1` bottom-left, `2` mid-right |
| `Switch:SW_Push` | `1=(-5.08, 0)`, `2=(5.08, 0)` | `angle=0`: `1` left, `2` right |
| `Connector:TestPoint` | `1=(0, 0)`, loop center `(0, 3.302)` | `angle=0`: loop above wire; `angle=180`: loop below wire |

## 5. Wiring, Junctions, and ERC Pitfalls

- **Automatic junctions**: Emit `(junction (at x y) ...)` only where `wire_endpoints + pin_count >= 3` (`>= 3` deduplicated wire endpoints, or `>= 2` wire endpoints meeting a symbol/power pin), or where a wire endpoint or symbol pin lies strictly inside the interior of another wire segment. Never place a junction on a 2-wire corner or a non-connecting crossing.
- **No wire-through-pin shorts**: Never route a horizontal/vertical wire across the opposite pin of a 2-pin passive (e.g., routing a bus wire through pin 1 to reach pin 2, or crossing an unrelated power vertical stub). Always check `pin(ref, pin_id)` coordinates before routing long buses.
- **Exact symmetric pin numbers**: Even for symmetric 2-pin `R`/`C` parts, match pin `1` vs pin `2` to `.net` so `kicad-cli sch export netlist` matches SKiDL's `.net` 100% without pin-swap diffs.
- **`PWR_FLAG` isolation**: Attach `power:PWR_FLAG` (`#FLG01..`) only inside the `.kicad_sch` on `+12V`, `-12V`, and `GND`, **after** `generate_netlist()` / BOM export, so `PWR_FLAG` never breaks netlist generation or leaks into JLCPCB BOMs.
- **ERC noise filtering**: In headless/sandbox runs where KiCad's global `sym-lib-table`/`fp-lib-table` isn't configured, `kicad-cli sch erc --severity-all` emits `lib_symbol_issues` and `footprint_link_issues` warnings; assert `0` errors and `0` other warnings (`lib_symbol_mismatch`, `multiple_net_names`, `pin_not_connected`, `wire_dangling`, `power_pin_not_driven`).
