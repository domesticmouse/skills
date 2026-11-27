# Circuit Description Markdown Format

Every extracted circuit description must use the following 6-section layout in order so it is both human-readable and machine-parseable by `verify_circuit_md.py` and downstream SKiDL/KiCad scripts.

---

## 1. Title & Metadata (`## Metadata`)

Start with `# <Module Name> — Circuit Description`, followed by `## Metadata` containing a two-column table (`| Field | Value |`) with:
- **Module Title**: Exact title from the schematic title block
- **Source PDF**: Relative Markdown link (`[<file>.pdf](<file>.pdf)`)
- **Schematic File**: Source `.sch` / `.kicad_sch` filename from title block
- **Boards / Project** *(if multi-PCB)*: Board names / project code
- **Revision**, **Date**, **Author**, **KiCad Version**, **Sheet Size**
- **Power Supply**: e.g., `±12V Eurorack 10-pin IDC header (XP1)`
- **Schematic Notes / Errata**: Verbatim callouts, alternate values, unused designators, special part requirements

---

## 2. Overview & Signal Flow (`## Overview & Signal Flow`)

- One concise paragraph summarizing the synthesis/processing topology.
- A `mermaid` `flowchart LR` diagram showing signal and CV flow.
  - Quote node labels containing parentheses, slashes, or special characters (e.g., `RES["Bridged-T Resonator (DA1A)"]`).
  - Avoid HTML tags inside labels.

---

## 3. Panel I/O, Controls & Test Points (`## Panel I/O, Controls & Test Points`)

Include subsections:
- `### Jacks`: `| Ref | Label | Type | Direction | Tip | Sleeve | Switch (Normalling) |` (or `| Ref | Label | Type | Direction | Tip | Ring / Switch | Sleeve |` when TRS stereo jacks are present)
- `### Controls`: `| Ref | Label | Value / Type | Wiring | Function |`
- `### Test Points` (or `### Test Points & Mounting Pads`): `| Ref | Silkscreen Label | Net | Signal Description |`

---

## 4. Functional Circuit Blocks (`## Functional Circuit Blocks`)

Numbered subsections (`### 1. ...`, `### 2. ...`) covering every subcircuit:
- Reference designators in headings or bullets
- Circuit topology, voltage thresholds, RC time constants / filter cutoffs, gain expressions, transistor operating modes, diode clamping/waveshaping
- For multi-PCB designs, include a **board-to-board interconnect pin mapping table** (`XP*` ↔ `XS*`).

---

## 5. Bill of Materials (`## Bill of Materials (BOM)`)

A single Markdown table sorted alphabetically/numerically by `Ref`, terminated by `---` before `## Pin-to-Pin Netlist`:

```markdown
| Ref | Value / Part | Category / Spec | Block | Notes |
| --- | --- | --- | --- | --- |
```

Include clear keywords in `Category / Spec` so `verify_circuit_md.py` infers the exact pin set:
- Potentiometers / Trimmers: include `Potentiometer` or `Trimmer`
- Electrolytic / Polarized caps: include `Electrolytic`, `Polarized`, or `Tantalum`
- Stereo TRS jacks: include `TRS` or `Stereo`; unswitched mono jacks: include `Unswitched`
- Switches: include `SPST`, `SPDT`, or `DPDT`
- Connectors / Headers / Sockets: include `NxM` (e.g., `2x5`, `1x16`, `1x20`) or `N-pin`
- Standard ICs (`TL072`, `TL074`, `NJM4556AD`, `CD40106BE`, etc.): pin count is recognized from `Value / Part`, or specify `N-pin` in `Category / Spec`.

---

## 6. Pin-to-Pin Netlist (`## Pin-to-Pin Netlist`)

State the **Pin Naming Convention** upfront, then provide the table:

```markdown
| Net | Connected Pins | Description |
| --- | --- | --- |
```

### Pin Naming Convention

| Component Family | Pin Names |
| --- | --- |
| 2-pin symmetric passives (`R*`, non-polarized `C*`, `L*`, `FB*`) | `.1`, `.2` |
| Polarized capacitors (`C*` Electrolytic/Tantalum) | `.+`, `.-` |
| Diodes & LEDs (`VD*`, `D*`, `LED*`) | `.A` (anode), `.K` (cathode) |
| BJTs (`VT*`, `Q*`) | `.B` (base), `.C` (collector), `.E` (emitter) |
| FETs (`Q*` MOSFET/JFET) | `.G` (gate), `.D` (drain), `.S` (source) |
| Potentiometers & Trimmers (`R*`, `RV*`, `VR*`) | `.CCW`, `.W` (wiper), `.CW` |
| Switches (`SW*`) | `.1`, `.2`, `.3` (SPDT); `.1`–`.6` (DPDT); `.1`–`.2` (SPST) |
| Mono switched jacks (`XS*`, `J*`) | `.T` (tip), `.S` (sleeve), `.SW` (normalled switch) |
| Stereo TRS jacks (`XS*`, `J*`) | `.T` (tip), `.R` (ring), `.S` (sleeve) |
| ICs (`DA*`, `DD*`, `U*`) & Headers (`XP*`, `XS11`+) | IC/header pin numbers `.1`–`.N` |
| Test points & mounting pads (`TP*`, `X*`) | `.1` |

Format `Connected Pins` as comma-separated backticked `Ref.Pin` tokens (e.g., `` `DA1.1`, `R22.2`, `TP1.1` ``) without range shortcuts, and end with an `NC` row listing all intentionally unconnected pins.
