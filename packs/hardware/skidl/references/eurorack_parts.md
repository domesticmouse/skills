# Verified KiCad 10 Eurorack Symbol Reference

Verified against KiCad `10.0.1` symbol libraries (`/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols`) with `skidl==3.0.0`. Always inspect unfamiliar symbols with `print(show("<Library>", "<Symbol>"))` before wiring pins.

---

## 1. Symbol Traps & Verified Part IDs

### NPN BJT Trap (`Device:Q_NPN_BEC` Does Not Exist)
* **Trap:** `Device:Q_NPN_BEC` does **not** exist in KiCad 10's `Device.kicad_sym` and raises a symbol-lookup failure.
* **Use instead:**
  * `Transistor_BJT:Q_NPN_BEC` — generic NPN transistor with pin order Base (`1`), Emitter (`2`), Collector (`3`) (or match pin order to your transistor package, e.g. `CBE` / `EBC` / `BCE`).
  * `Transistor_BJT:BC548` — specific TO-92 / SOT-23 part (verify pinout vs. SOT-23 `BC848` / `MMBT3904` footprint).
  * `Device:Q_NPN` — generic unnumbered/CBE symbol in `Device.kicad_sym` (verify pin numbers with `show("Device", "Q_NPN")` before assigning a footprint).

---

## 2. Common Eurorack Symbols & Pinouts

| Component | KiCad 10 Library & Symbol | Pin Names / Numbers | Notes |
| :--- | :--- | :--- | :--- |
| **Dual Op-Amp** | `Amplifier_Operational:TL072` | Pins `1`–`8` (3 units: `A`, `B`, `C` power) | `1`=OUTA, `2`=-INA, `3`=+INA, `4`=V-, `5`=+INB, `6`=-INB, `7`=OUTB, `8`=V+ |
| **Quad Op-Amp** | `Amplifier_Operational:TL074` | Pins `1`–`14` (5 units: `A`–`D`, `E` power) | `4`=V+, `11`=V-; tie unused units as unity-gain buffers or rail-biased |
| **Potentiometer** | `Device:R_Potentiometer` | Pins `1`, `2`, `3` | `1`=CCW, `2`=Wiper, `3`=CW |
| **Switched Mono Jack** | `Connector_Audio:AudioJack2_SwitchT` | Pins `S`, `T`, `TN` | `S`=Sleeve (GND), `T`=Tip (signal), `TN`=Tip Normal (switched contact, opens when plug inserted) |
| **10-Pin Eurorack Power** | `Connector_Generic:Conn_02x05_Odd_Even` | Pins `1`–`10` (all `PASSIVE`) | `1, 2`=`-12V` (red stripe), `3`–`8`=`GND`, `9, 10`=`+12V` |

---

## 3. Wiring Notes for Eurorack Power & Op-Amps

```python
from skidl import POWER, Net, Part

pwr = Part(
    "Connector_Generic",
    "Conn_02x05_Odd_Even",
    footprint="Connector_IDC:IDC-Header_2x05_P2.54mm_Vertical",
)
vp = Net("+12V")
vm = Net("-12V")
gnd = Net("GND")

vp += pwr[9, 10]
vm += pwr[1, 2]
gnd += pwr[3, 4, 5, 6, 7, 8]

# Satisfy SKiDL ERC() for passive header rails:
vp.drive = POWER
vm.drive = POWER
gnd.drive = POWER
```

* Because `Conn_02x05_Odd_Even` pins are all `PASSIVE`, KiCad 10 Eeschema ERC flags `[power_pin_not_driven]` on `TL072`/`TL074` `V+`/`V-` pins unless `Part("power", "PWR_FLAG")` is attached to `+12V`, `-12V`, and `GND` **after** `generate_netlist()` (see [kicad10_schematics.md](./kicad10_schematics.md)).
* For `AudioJack2_SwitchT`, verify the physical `WQP-PJ398SM` Thonkiconn footprint pad numbering (`S`, `T`, `TN`) matches the symbol pins (`S`, `T`, `TN`).
* Register project-local custom `.pretty` footprint directories alongside stock KiCad libraries via:
  ```python
  import pathlib
  from skidl import KICAD, footprint_search_paths

  footprint_search_paths[KICAD].append(str(pathlib.Path(__file__).resolve().parent / "footprints"))
  ```

---

## 4. Additional Verified Eurorack & JLCPCB Parts

| Component | KiCad Footprint | Verified LCSC / Notes |
| :--- | :--- | :--- |
| **Alpha 9mm Vertical Pot** | `Potentiometer_THT:Potentiometer_Alpha_RD901F-40-00D_Single_Vertical` | Shaft center is `(+7.50, +2.50)` at `rot=0°` (check `F.Fab` circle) |
| **DNP Test Point (`RH-5001`)** | `TestPoint:TestPoint_Keystone_5000-5004_Miniature` | LCSC `C5199801` (`Ø 1.0 mm` drill; mark `part.dnp = True`, `exclude_from_bom = True`, `exclude_from_pos_files = True`) |
| **WIMA Box Film Capacitor** | `Capacitor_THT:C_Rect_L7.2mm_W4.5mm_P5.00mm_FKS2_FKP2_MKS2_MKP2` | Use `W7.2mm` variant for larger `2.2uF` box film parts |
| **TL074H Quad Op-Amp** | `Package_SO:SOIC-14_3.9x8.7mm_P1.27mm` | LCSC `C2878713` (`TL074HIDR`, Extended) |
| **Dual Schottky (`BAT54S`)** | `Package_TO_SOT_SMD:SOT-23` | Extended; verify Pin `1`=Anode, `2`=Cathode, `3`=Common vs. `Device:D_Schottky_x2_Serial_AKC` |
| **Schottky Diode (`B5819W`)** | `Diode_SMD:D_SOD-123` | LCSC `C8598` (Basic; `K` = Pin `1`, `A` = Pin `2`) |
