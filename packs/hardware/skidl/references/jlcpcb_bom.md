# JLCPCB PCBA BOM & Catalog Integration

When preparing a SKiDL circuit for JLCPCB SMT/PCBA assembly, you must embed component catalog metadata into `part.fields`, verify live stock and Basic/Extended library status, and export a grouped 4-column CSV BOM alongside the KiCad netlist.

---

## 1. Embedding Custom Fields in SKiDL (`part.fields`)

### The `SkidlBaseObject.__setattr__` Gotcha
In SKiDL, `SkidlBaseObject.__setattr__` only writes an attribute into `part.fields` if the key **already exists** in `part.fields`:
```python
if key == "fields" or key not in self.fields:
    super().__setattr__(key, value)
else:
    self.fields[key] = value
```
Therefore, passing arbitrary keyword arguments like `Part(..., LCSC="C49678")` or assigning `part.LCSC = "C49678"` creates a plain Python attribute on the `Part` instance and **will NOT be exported** in `<fields>` by `generate_xml()` or `generate_netlist()`.

### Correct Way to Add Exported Fields
Always assign custom catalog metadata directly into the `part.fields` dictionary:
```python
r_t = Part("Device", "R", dest=TEMPLATE, footprint="Resistor_SMD:R_0805_2012Metric")
r_t.fields["LCSC"] = "C17710"
r_t.fields["MPN"] = "0805W8F4700T5E"
r_t.fields["JLCPCB_Class"] = "Basic"

# Template copies automatically inherit a copy of `r_t.fields`
r1, r2 = r_t(2, value="470R", tag="r_out")
```
* **Exception for `dnp` and `exclude_from_bom`**: KiCad's netlist generator (`gen_netlist_comp`) checks `getattr(part, "dnp", False)` and `getattr(part, "exclude_from_bom", False)` as direct attributes on `part` (emitting `(property (name "dnp"))`). Set those directly on the part (`part.dnp = True`), while keeping catalog strings (`LCSC`, `MPN`, etc.) in `part.fields`.

---

## 2. Querying the JLCPCB Catalog for Live Stock & Cost

Never rely purely on memorized LCSC `C`-numbers—parts frequently go out of stock, become deprecated (`(SMTonly)` with `0` stock, such as `C17407`), or map to a different package than expected (e.g., `C6965` is an SO-8 `TL081CDT`, whereas `C12594` and `C6963` are SOIC-14 `TL074`).

### Option A: Live Query Helper Script (Recommended for BOM Verification)
Run [jlcpcb_search.py](../scripts/jlcpcb_search.py) to query JLCPCB's live `selectSmtComponentList/v2` endpoint (with automatic fallback to `jlcsearch.tscircuit.com`):
```bash
python3 .agents/skills/skidl/scripts/jlcpcb_search.py --in-stock-only "100k 0805" "TL074 SOIC-14" "10uF D6.3xL5.4mm"
```
*(Note: Because this script makes HTTPS requests to `jlcpcb.com`, run it outside the sandbox if sandbox network access is disabled.)*

### Option B: Lightweight `jlcsearch` JSON API
Query `https://jlcsearch.tscircuit.com` directly:
* General search: `https://jlcsearch.tscircuit.com/api/search?q=TL074&limit=5`
* Parametric category endpoints: `https://jlcsearch.tscircuit.com/resistors/list.json?package=0805&resistance=470`

### Option C: Full Offline Catalog Downloads
For bulk offline queries without rate limits:
* **`CDFER/jlcpcb-parts-database`** (`https://github.com/CDFER/jlcpcb-parts-database`): Provides daily builds of `jlcpcb-components-basic-preferred.csv` (~3 MB CSV of all Basic and Preferred Extended parts) and a ~1 GB FTS5-indexed SQLite database of all in-stock parts.
* **`yaqwsx/jlcparts`** (`https://yaqwsx.github.io/jlcparts/`): Web UI and upstream scraper for parametric filtering.

---

## 3. JLCPCB Part Classes & Cost Optimization

JLCPCB categorizes SMT components into three tiers:
1. **Basic Parts (`componentLibraryType == "base"`)**: Pre-loaded on SMT machines; **\$0 feeder loading fee**. Always prefer Basic Parts for standard passives, diodes, regulators, and common ICs.
2. **Preferred Extended Parts (`preferredComponentFlag == True`)**: Promotional extended parts with **\$0 feeder loading fee**.
3. **Extended Parts (`componentLibraryType == "expand"`)**: Incur a **~\$3.00 setup/feeder loading fee per unique part line** per order. Consolidate values/footprints where possible to minimize unique Extended part lines.
4. **Panel-Mounted / Manual Through-Hole Parts**: Controls that must be aligned physically against a front panel before soldering (such as `WQP-PJ398SM` / Thonkiconn 3.5mm jacks or potentiometers) usually have `0` SMT stock on JLCPCB and should be omitted from the JLCPCB PCBA BOM for manual assembly.

### Commonly Used In-Stock Parts Reference
| Component | Package / KiCad Footprint | Verified LCSC # | MPN | Library Class | Notes / Footprint Sizing |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `100nF` 50V X7R MLCC | `0603` (`Capacitor_SMD:C_0603_1608Metric`) | `C14663` | `CC0603KRX7R9BB104` | Basic | Compact default for dense/Eurorack PCBs |
| `100K` 1% Thick Film Resistor | `0603` (`Resistor_SMD:R_0603_1608Metric`) | `C25803` | `0603WAF1003T5E` | Basic | Compact default for dense/Eurorack PCBs |
| `470R` 1% Thick Film Resistor | `0603` (`Resistor_SMD:R_0603_1608Metric`) | `C23179` | `0603WAF4700T5E` | Basic | Compact default for dense/Eurorack PCBs |
| `100nF` 50V X7R MLCC | `0805` (`Capacitor_SMD:C_0805_2012Metric`) | `C49678` | `CC0805KRX7R9BB104` | Basic | Larger hand-solderable alternative |
| `100K` 1% Thick Film Resistor | `0805` (`Resistor_SMD:R_0805_2012Metric`) | `C149504` *(not `C17407`)* | `0805W8F1003T5E` | Basic | Larger hand-solderable alternative |
| `470R` 1% Thick Film Resistor | `0805` (`Resistor_SMD:R_0805_2012Metric`) | `C17710` | `0805W8F4700T5E` | Basic | Larger hand-solderable alternative |
| `1N5819` / `B5819W` 40V 1A Schottky | `SOD-123` (`Diode_SMD:D_SOD-123`) | `C8598` | `B5819W` | Basic | **Recommended default** (`4.6×2.3mm` courtyard, `-54%` area vs. `SMA`) |
| `1N5819WS` 40V 1A Schottky | `SOD-323` (`Diode_SMD:D_SOD-323`) | `C191023` | `1N5819WS` | Basic | **Ultra-compact alt** (`3.6×1.8mm` courtyard, `-72%` area vs. `SMA`; not `C2128` which is `1N4148WS`) |
| `1N5819` / `SS14` 40V 1A Schottky | `SMA` (`Diode_SMD:D_SMA`) | `C2480` | `SS14` | Basic | Large (`6.5×3.5mm` courtyard); use only for high-current rails |
| `TL074` Quad Op-Amp | `SOIC-14` (`Package_SO:SOIC-14_3.9x8.7mm_P1.27mm`) | `C2878713` *(TL074H)* / `C12594` *(TL074C)* / `C6963` *(ST)* | `TL074HIDR` / `TL074CDR` / `TL074CDT` | Extended | `TL074HIDR` (`C2878713`) is TI's modern CMOS/FET-input version |
| `10uF` 50V SMD Electrolytic | `SMD,D6.3xL5.4mm` (`Capacitor_SMD:CP_Elec_6.3x5.4`) | `C14162` *(or `C72488`)* | `RVT1H100M0605` | Extended | Check front-panel clearance before placing on `F.Cu` |
| `10uF` 25V Radial THT Electrolytic | `D5.0mm P2.00mm` (`Capacitor_THT:CP_Radial_D5.0mm_P2.00mm`) | `C713347` | `ECEA1EKS100` | Manual THT | `7mm` height fits under `~10.5mm` Thonkiconn jack standoff on `F.Cu` |
| `10uF` 16V SMD Tantalum | `CASE-A (3216)` | `C7171` | `TAJA106K016RNJ` | Basic | Do not use on `±12V` rails (`16V` rating lacks derating margin) |
| `2x5P` 2.54mm Shrouded IDC Header | `Through-Hole` (`Connector_IDC:IDC-Header_2x05_P2.54mm_Vertical`) | `C53207560` | `IDC2.54-2*5PZ` | Extended (THT) | Typically hand-soldered on `B.Cu` (`JLCPCB_Class = "Manual THT"`) |

* **Documenting Alternative Footprints/Parts**: When space constraints may require downsizing a component during layout (e.g., swapping `SOD-123` `B5819W` to `SOD-323` `1N5819WS`), record the verified alternative footprint, MPN, and LCSC part number in `part.fields["Notes"]` (or `part.fields["BOM Comments"]`) so the fallback option travels with the exported `.net` and `.xml` BOM files.

---

## 4. Exporting a JLCPCB-Compatible BOM CSV from SKiDL

JLCPCB does not accept KiCad `.xml` BOMs directly; it requires a `.csv` with four columns: `Comment`, `Designator`, `Footprint`, and `LCSC Part #`, with identical parts grouped onto a single row.

Include this helper in your SKiDL script and call it right after `generate_xml()`:

```python
import builtins
import csv


def generate_jlcpcb_bom(file_="jlcpcb_bom.csv", include_tht=False):
    """
    Export a grouped JLCPCB PCBA BOM CSV (`Comment,Designator,Footprint,LCSC Part #`).
    By default, exports all SMT components with an assigned LCSC part number and
    excludes hand-soldered through-hole connectors unless `include_tht=True`.
    """
    groups = {}
    for part in builtins.default_circuit.parts:
        lcsc = part.fields.get("LCSC", "")
        jlc_class = part.fields.get("JLCPCB_Class", "")
        if (
            not lcsc
            or getattr(part, "dnp", False)
            or getattr(part, "exclude_from_bom", False)
        ):
            continue
        if not include_tht and "THT" in jlc_class:
            continue

        comment = part.value_to_str()
        footprint = getattr(part, "footprint", "").split(":")[-1]
        key = (comment, footprint, lcsc)
        groups.setdefault(key, []).append(part.ref)

    with open(file_, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (comment, footprint, lcsc), refs in groups.items():
            writer.writerow([comment, ", ".join(refs), footprint, lcsc])
```
