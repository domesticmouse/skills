# SKiDL Advanced Patterns & Reference

## 1. Hierarchical Design (`@subcircuit`, `SubCircuit`, `Group`, `Interface`)

SKiDL embeds your hierarchy into the KiCad netlist (`sheetpath` and deterministic UUID `tstamps`), enabling hierarchical component selection and room/group placement in KiCad's `pcbnew`.

### Function Decorator (`@subcircuit`)
```python
from skidl import *


@subcircuit
def ldo_regulator(vin, vout, gnd):
    u = Part(
        "Regulator_Linear",
        "AMS1117-3.3",
        footprint="Package_TO_SOT_SMD:SOT-223-3_TabPin2",
    )
    c = Part("Device", "C", dest=TEMPLATE, footprint="Capacitor_SMD:C_0805_2012Metric")
    c_in, c_out = c(2, value="10uF")

    vin & c_in & gnd
    vout & c_out & gnd
    vin += u["VI"]
    vout += u["VO"]
    gnd += u["GND"]


# Instantiate two independent regulators with explicit tags for stable PCB UUIDs
vin, v3v3_a, v3v3_b, gnd = Net("VIN"), Net("3V3_A"), Net("3V3_B"), Net("GND")
ldo_regulator(vin, v3v3_a, gnd, tag="reg_a")
ldo_regulator(vin, v3v3_b, gnd, tag="reg_b")
```

* **Root Node Tag Constraint**: Always pass `tag="..."` to `@subcircuit` invocations and `Part(...)` instances for deterministic KiCad UUIDs, but **never** modify `default_circuit.root.tag` from its default empty string `""`. KiCad's netlist generator (`gen_sheetpath`) requires the root hierarchy level to be `""` (representing `/`) and will raise `AssertionError: Top level of hierarchy must be an empty string.` if changed.

### Context Manager (`with SubCircuit(...)` or `with Group(...)`)
```python
with SubCircuit("analog_frontend", tag="afe1"):
    r1 = Part("Device", "R", value="1K", footprint="Resistor_SMD:R_0603_1608Metric")
    # Parts and nets created inside this block belong to the subcircuit node
```

### Interfaces (`Interface`)
Bundle related signals (e.g., SPI, I2C, power rails) into a single object that supports both attribute and dictionary indexing, as well as bulk `+=` connection between matching interfaces:
```python
spi_bus = Interface(
    sck=Net("SPI_SCK"),
    mosi=Net("SPI_MOSI"),
    miso=Net("SPI_MISO"),
    cs=Net("SPI_CS"),
)

spi_bus.sck += mcu["PA5"]
```

---

## 2. Design Rules (`NetClass` and `PartClass`)

Assign KiCad NetClasses and Component Classes in Python so they propagate into the generated `.net` file:

```python
from skidl import *

# Define classes with priority (lower number = higher priority when resolving conflicts)
pwr_netclass = NetClass("HighCurrentPower", priority=1, trace_width=0.8, clearance=0.3)
analog_partclass = PartClass("PrecisionAnalog", priority=1)

vcc = Net("VCC")
vcc.netclasses = pwr_netclass

u_adc = Part("Analog_ADC", "MCP3008", footprint="Package_DIP:DIP-16_W7.62mm")
u_adc.partclasses = analog_partclass
```
You can also assign `netclasses` or `partclasses` to a `SubCircuit` node so every net/part inside it inherits those classes automatically.

---

## 3. Handling Missing Footprints (`empty_footprint_handler`)

When generating a netlist or PCB, SKiDL checks every part for a non-empty `footprint` attribute and invokes `skidl.empty_footprint_handler(part)` if one is missing. You can define a custom handler to automatically assign default footprints before `generate_netlist()` or `generate_pcb()`:

```python
import skidl
from skidl import *


def my_footprint_handler(part):
    if part.ref_prefix in ("R", "C", "L") and len(part.pins) == 2:
        part.footprint = "Resistor_SMD:R_0805_2012Metric"
    else:
        skidl.default_empty_footprint_handler(part)


skidl.empty_footprint_handler = my_footprint_handler
```

---

## 4. Creating Ad-Hoc Parts in Code (`SkidlPart` & `Pin`)

If a component doesn't exist in any KiCad symbol library, you can define it purely in Python using `SkidlPart` (alias `Part(tool=SKIDL)`) and attach a valid KiCad footprint:

```python
from skidl import *
from skidl.pin import pin_types

conn = SkidlPart(
    name="Custom_4Pin_Header",
    ref_prefix="J",
    footprint="Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
)
conn += Pin(num=1, name="VCC", func=pin_types.PWRIN)
conn += Pin(num=2, name="TX", func=pin_types.OUTPUT)
conn += Pin(num=3, name="RX", func=pin_types.INPUT)
conn += Pin(num=4, name="GND", func=pin_types.PWRIN)
```

Common `pin_types` values:
* `pin_types.INPUT`, `pin_types.OUTPUT`, `pin_types.BIDIR`, `pin_types.TRISTATE`
* `pin_types.PASSIVE`, `pin_types.UNSPEC`
* `pin_types.PWRIN`, `pin_types.PWROUT`
* `pin_types.OPENCOLL`, `pin_types.OPENEMIT`, `pin_types.NOCONNECT`

---

## 5. Converting Existing KiCad Netlists to SKiDL

To migrate an existing KiCad schematic/netlist to SKiDL code:
* **CLI**:
  ```bash
  netlist_to_skidl -i my_project.net -o my_project_skidl.py -w
  ```
* **Python API**:
  ```python
  from skidl import netlist_to_skidl

  python_code = netlist_to_skidl("my_project.net")
  ```

---

## 6. Multiple Independent Circuits & Resetting State

By default, all parts and nets register with ` builtins.default_circuit`.
* **Resetting**: Call `reset()` to clear `default_circuit` (commonly used in tests or interactive notebooks).
* **Explicit `Circuit` objects**: Instantiate `ckt = Circuit()` and either pass `circuit=ckt` to parts/nets or use it as a context manager:
  ```python
  with Circuit() as my_ckt:
      r = Part("Device", "R", footprint="Resistor_SMD:R_0805_2012Metric")
      my_ckt.ERC()
      my_ckt.generate_netlist(file_="my_ckt.net")
  ```
