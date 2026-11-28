# KiCad 10 `.kicad_sch` Mechanics & Symbol Reference

Empirical rules verified against `kicad-cli 10.0.1` and stock KiCad 10 symbol libraries under `/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols`.

## 1. File Format & Symbol Flattening

- **Header**: Use `(version 20251024)`, `(generator "eeschema")`, `(generator_version "10.0")`, `(paper "A3")`, `(sheet_instances (path "/" (page "1")))`, and `(embedded_fonts no)`.
- **Why bypass SKiDL `generate_schematic()` (`schematizer`)**: `schematizer` fails with `RoutingFailure` on complex or global power nets and splits op-amp units into detached `auto_stub` islands. Build schematics directly with `SchematicBuilder` backed by SKiDL or `.net` metadata.
- **Quoted atoms vs bare tokens**: Preserve exact quoting (`""` empty strings, `"Reference"`, `"Value"`, `"Library:Symbol"`) — an unquoted empty string or unescaped quote breaks KiCad parsing.
- **Flattening `(extends ...)` symbols**: Derived symbols such as `Transistor_BJT:BC848` (`extends "Q_NPN_BEC"`), `Diode:1N4148W` (`extends "1N4001"`), and `Amplifier_Operational:TL074` (`extends "LM2902"`) cannot rely on `(extends ...)` inside embedded `lib_symbols`. Recursively merge header clauses (preserving parent flags such as `pin_names` and `in_bom` when the child only sets `embedded_fonts`), override `(property ...)` definitions, copy child `(symbol "<base>_u_s" ...)` units renamed to `<derived>_u_s`, drop `(extends ...)`, and rename the top-level symbol to `"<Lib>:<Sym>"`. This yields **0 `lib_symbol_mismatch` warnings** in KiCad 10 ERC.
- **Instances block & project name**: Every placed `(symbol ...)` must include `(instances (project "<project_name>" (path "/<root_uuid>" (reference "<ref>") (unit <unit>))))` plus `(pin "<num>" (uuid ...))` for every pin of that unit. Use `""` for `<project_name>` on standalone `.kicad_sch` files (when no `.kicad_pro` exists) or the `.kicad_pro` stem when inside a KiCad project, preventing `schematic has annotation errors` warnings in `kicad-cli sch export netlist`.
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

Property `(at x y ANGLE)` coordinates are **absolute sheet coordinates**, while KiCad 10 evaluates property angle and justification in the symbol's local frame and auto-unflips `180°` upside-down text:

- **Upright horizontal text (`0°` on sheet/PDF)**: Use `prop_angle = 270` when `angle = 90` (`90 + 270 = 360°`), `prop_angle = 90` when `angle = 270` (`270 + 90 = 360°`), and `prop_angle = 0` when `angle ∈ {0, 180}` (`_text_transform()` handles this automatically). Setting `prop_angle = 90` at `angle = 90` sums to `180°`, which KiCad unflips by swapping both `left <-> right` and `top <-> bottom`.
- **Full L/R and T/B justification compensation**: Compensate `(justify ...)` across both axes (`_compensate_justify()`):

| Symbol Orientation | Recommended `prop_angle` | Raw `(justify ...)` Flip | Compensation Applied |
| :--- | :--- | :--- | :--- |
| `angle=0, mirror=None` | `0` | None | None |
| `angle=90, mirror=None` | `270` | None | None |
| `angle=180, mirror=None` | `0` | `left <-> right`, `top <-> bottom` | Swap `L <-> R` & `T <-> B` |
| `angle=270, mirror=None` | `90` | None | None |
| `angle=0, mirror="x"` | `0` | `top <-> bottom` | Swap `T <-> B` |
| `angle=0, mirror="y"` | `0` | `left <-> right` | Swap `L <-> R` |

## 4. Verified KiCad 10 Eurorack Symbol Pinouts & Orientations

| KiCad Symbol | Local Pins (Y-up) | Common Orientations |
| :--- | :--- | :--- |
| `power:+12V`, `power:-12V` | `1=(0, 0)` | **Gotcha**: both point **UP** at `angle=0`; use `angle=0` for `+12V` (up) and `angle=180` for `-12V` (hanging down). Place `PWR_FLAG` on a short side tap (`pwr_flag()` or `pwr_flag_offset`) rather than co-located on the rail arrow. |
| `power:GND`, `power:PWR_FLAG` | `1=(0, 0)` | `GND` points DOWN at `angle=0`, UP at `angle=180` (useful above `-12V` filter caps). |
| `Device:R`, `Device:C` | `1=(0, +3.81)`, `2=(0, -3.81)` | `angle=0`: `1` top / `2` bottom; `angle=90`: `1` left / `2` right; `angle=180`: `2` top / `1` bottom; `angle=270`: `2` left / `1` right |
| `Device:C_Polarized` | `1=(0, +3.81)` (`+`), `2=(0, -3.81)` (`-`) | `angle=0`: `+` top (`+12V` or `GND` above `-12V`); `angle=180`: `-` top / `+` bottom |
| `Device:D`, `Device:D_Schottky`, `Diode:1N4148W`, `Device:LED` | `1=K=(-3.81, 0)`, `2=A=(+3.81, 0)` | `angle=0`: `K` left / `A` right (`\|<--`); `angle=180`: `A` left / `K` right (`-->\|`); `angle=90`: `A` top / `K` bottom; `angle=270`: `K` top / `A` bottom (`1N4148W` extends `1N4001`) |
| `Device:LED_Dual_Bidirectional` | `1=KA=(+7.62, 0)`, `2=AK=(-7.62, 0)` | `angle=90`: `1` top / `2` bottom (vertical LED indicator column) |
| `Device:R_Potentiometer` | `1=(0, +3.81)`, `2=(+3.81, 0)` (W), `3=(0, -3.81)` | `angle=0`: `1` top / `3` bottom / `2` right; `mirror="x"`: `3` top / `1` bottom / `2` right; `angle=180`: `3` top / `1` bottom / `2` left; `angle=90`: `1` left / `3` right / `2` top; `angle=270`: `3` left / `1` right / `2` bottom |
| `Diode:BAT54S` | `1=A=(-7.62, 0)`, `2=K=(+7.62, 0)`, `3=COM=(0, -5.08)` | `angle=90`: `K` top (`+12V`), `A` bottom (`GND`), `COM` right; `mirror="y"`: `K` right, `A` left, `COM` down (rectifier feedback) |
| `Transistor_BJT:BC848` (NPN) & `BC858` (PNP) | `1=B=(-5.08, 0)`, `2=E=(+2.54, -5.08)`, `3=C=(+2.54, +5.08)` | `angle=0`: `B` left, `C` top, `E` bottom (NPN); `mirror="x"`: `B` left, `E` top, `C` bottom (PNP shunt); `angle=180`: `B` right, `E` top, `C` bottom (PNP clamp) |
| `Amplifier_Operational:TL074` & `TL072` | Units 1–4 (`TL074`) / 1–2 (`TL072`): `+=(-7.62, +2.54)`, `-=(-7.62, -2.54)`, `OUT=(+7.62, 0)`. Power unit: `TL074` Unit 5 has `4=V+=(-2.54, +7.62)`, `11=V-=(-2.54, -7.62)`; `TL072` Unit 3 has `8=V+=(-2.54, +7.62)`, `4=V-=(-2.54, -7.62)` | `mirror="x"` puts `-` on TOP (feedback loops above) and `+` on BOTTOM; `angle=0` puts `+` on TOP and `-` on BOTTOM |
| `Connector_Generic:Conn_02x05_Odd_Even` | Odds (`1,3,5,7,9`) at `x=-5.08`, Evens (`2,4,6,8,10`) at `x=+7.62`; `1,2` at `y=+5.08` -> `9,10` at `y=-5.08` | `mirror="x"` puts pins `9,10` (`+12V`) at TOP, `3..8` (`GND`) middle, `1,2` (`-12V`) at BOTTOM |
| `Connector_Audio:AudioJack2_SwitchT` | `S=(5.08, 2.54)`, `T=(5.08, 0)`, `TN=(5.08, -2.54)` | `angle=0`: pins exit RIGHT (`S` top, `TN` bottom); `mirror="x"`: pins exit RIGHT (`TN` top, `T` mid, `S` bottom — ideal for top-normaled inputs); `angle=180` / `mirror="y"`: pins exit LEFT (outputs) |
| `Switch:SW_SPDT` | `1=(5.08, 2.54)`, `2=(-5.08, 0)`, `3=(5.08, -2.54)` | `angle=0`: `2` left, `1` top-right, `3` bottom-right; `angle=180`: `3` top-left, `1` bottom-left, `2` mid-right; `angle=270`: `2` top, `3` bottom-left, `1` bottom-right |
| `Switch:SW_Push` | `1=(-5.08, 0)`, `2=(5.08, 0)` | `angle=0`: `1` left, `2` right |
| `Connector:TestPoint` | `1=(0, 0)`, loop center `(0, 3.302)` | `angle=0`: loop above wire; `angle=90`: pin right / loop left (horizontal test-point columns); `angle=180`: loop below wire |

## 5. Wiring, Junctions, and ERC Pitfalls

- **Automatic junctions**: `SchematicBuilder` emits `(junction (at x y) ...)` only where `wire_endpoints + pin_count >= 3` or where a wire endpoint or pin lies strictly inside another wire segment. Never place a junction on a 2-wire corner or a non-connecting crossing.
- **Label placement & `unconnected_wire_endpoint`**: Local `(label ...)` text floats above horizontal wires cleanly when `justify="left bottom"` (default in `label()`), `"right bottom"`, or `"bottom"`. When terminating an open stub wire with a local net label, anchor `(label ...)` directly on the open wire endpoint rather than mid-wire to avoid `unconnected_wire_endpoint` ERC warnings; use `left bottom` on left-facing open ends and `right bottom` on right-facing open ends.
- **No wire-through-pin shorts**: Never route a wire across the opposite pin of a 2-pin passive or an unrelated vertical power stub; always use `b.pin(ref, pin_id)` coordinates.
- **Exact symmetric pin numbers**: Even for symmetric 2-pin `R`/`C` parts, match pin `1` vs pin `2` to `.net` so `kicad-cli sch export netlist` matches `.net` 100% without pin-swap diffs.
- **`PWR_FLAG` isolation**: Place `power:PWR_FLAG` (`#FLG01..`) only inside `.kicad_sch` on `+12V`, `-12V`, and `GND` (ideally on a short side tap via `pwr_flag()` / `pwr_flag_offset`), **after** `generate_netlist()` and BOM export, so `PWR_FLAG` never breaks netlist generation or leaks into JLCPCB BOMs.
- **Sandbox ERC masking pitfall**: In restricted environments where `kicad-cli` cannot read KiCad's global `sym-lib-table`/`fp-lib-table`, KiCad emits `lib_symbol_issues` and `footprint_link_issues`, and `lib_symbol_issues` **masks** `lib_symbol_mismatch`. Verify `0` `unconnected_wire_endpoint`, `label_dangling`, `pin_not_connected`, `power_pin_not_driven`, and `multiple_net_names` first, and whenever `unconfigured-lib notices > 0`, re-run `kicad-cli sch erc --severity-all` with global library tables accessible to confirm `0` `lib_symbol_mismatch`.
