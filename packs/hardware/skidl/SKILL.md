---
name: skidl
description: >-
  Design electronic circuits in Python and generate KiCad netlists, PCBs,
  schematics, SVGs, and JLCPCB PCBA BOMs using SKiDL. Use this skill whenever a
  developer asks to write, modify, debug, or understand SKiDL circuit scripts,
  search KiCad symbol/footprint libraries or the JLCPCB/LCSC parts catalog from
  Python, run Electrical Rules Checking (ERC), create hierarchical subcircuits,
  or export circuits and BOMs to KiCad and JLCPCB.
---

# SKiDL Circuit & KiCad PCB Design

SKiDL is a Python library for describing electronic circuits as code and outputting netlists, PCB files, and schematics for KiCad (versions 5 through 10, defaulting to `KICAD10`).

## 1. Environment & Tool Configuration

* **Virtual Environment Setup (`uv`)**: `skidl` depends on `inspice` -> `h5py`. Avoid unreleased/bleeding-edge Python versions (such as Python 3.15) that lack prebuilt `h5py` binary wheels and fail compiling `libhdf5` from source. Target Python 3.12–3.14 and pass `--clear` so `uv venv` never blocks on an interactive prompt:
  ```bash
  uv venv --clear --python 3.14 .venv
  uv pip install skidl
  ```
* **Pre-Import Environment Variables (Sandbox & macOS Paths)**: Importing `skidl` immediately initializes `SkidlConfig` and `matplotlib`, which attempt to create `~/Library/Application Support/skidl` and `~/.matplotlib`. In restricted sandboxes or macOS environments without shell-exported KiCad variables, configure these **before** importing `skidl`:
  ```python
  import os

  os.environ.setdefault("XDG_DATA_HOME", "/tmp/xdg_data")
  os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl_config")
  if os.path.isdir("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"):
      os.environ.setdefault(
          "KICAD10_SYMBOL_DIR",
          "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols",
      )
      os.environ.setdefault(
          "KICAD_SYMBOL_DIR",
          "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols",
      )
  if os.path.isdir("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"):
      os.environ.setdefault(
          "KICAD10_FOOTPRINT_DIR",
          "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints",
      )
  ```
  * **macOS Sandbox Symbol Read Caveat**: In macOS sandboxes, `os.path.isdir("/Applications/KiCad/...")` returns `True` (since `stat()` is permitted), but reading `.kicad_sym` files under `/Applications/KiCad/...` raises `PermissionError`. When that happens, SKiDL logs `ERROR: Can't open file: <Lib>` and emits `(libsource (lib "NO_LIB") ...)` in the generated `.net` file. Always execute the SKiDL script outside the sandbox (`BypassSandbox: true`) when generating `.net` and `.xml` outputs against `/Applications/KiCad/...` symbol libraries so `<Lib>` names and `.log` files stay clean.
* **Default Tool**: `KICAD` aliases `KICAD10`. Switch versions at the top of a script if targeting an older KiCad installation:
  ```python
  from skidl import KICAD9, set_default_tool

  set_default_tool(KICAD9)  # Options: KICAD5, KICAD6, KICAD7, KICAD8, KICAD9, KICAD10
  ```
* **Symbol Libraries**: Controlled by `KICAD_SYMBOL_DIR` or versioned `KICAD<N>_SYMBOL_DIR` (e.g., `KICAD10_SYMBOL_DIR`). You can also append paths in code:
  ```python
  lib_search_paths[KICAD].append("/path/to/custom/symbols")
  ```
* **Footprint Libraries**: Resolved automatically from KiCad's global `fp-lib-table` or customized via `footprint_search_paths[KICAD]`.

## 2. Discovering Parts & Footprints

Before instantiating parts, query local KiCad libraries using Python one-liners to verify exact library names, symbol names, pin names/numbers, and footprint strings:

```python
from skidl import *

# Search symbols by keywords/regex (uses a cached SQLite DB)
search("linear regulator 3.3V")

# Inspect exact pin numbers, names, and electrical types of a symbol
show("Regulator_Linear", "AMS1117-3.3")

# Search footprints across .pretty libraries
search_footprints("SOT-223")
```

## 3. Instantiating Parts

Every physical component destined for a PCB **must** have a `footprint` attribute formatted as `"<Library>:<FootprintName>"`:

```python
from skidl import *

# Single part instance (automatically added to the circuit)
u1 = Part(
    "Regulator_Linear",
    "AMS1117-3.3",
    footprint="Package_TO_SOT_SMD:SOT-223-3_TabPin2",
    tag="u1_reg",  # Optional stable tag for deterministic KiCad UUIDs
)

# Template pattern for instantiating multiple copies
r_t = Part("Device", "R", dest=TEMPLATE, footprint="Resistor_SMD:R_0603_1608Metric")
c_t = Part("Device", "C", dest=TEMPLATE, footprint="Capacitor_SMD:C_0603_1608Metric")

r1, r2 = r_t(2, value="10K")  # Two 10K resistors
c_in, c_out = c_t(values=["10uF", "22uF"])
```

* **Custom Fields & Properties (`part.fields` vs. Attributes)**:
  * **Catalog & BOM Fields**: Because `SkidlBaseObject.__setattr__` only updates `part.fields` if the key *already* exists in `part.fields`, passing `LCSC="C14663"` to `Part()` or assigning `part.LCSC = "C14663"` sets a plain Python attribute that is **ignored** by `generate_xml()` and `generate_netlist()`. Always assign custom fields into the `part.fields` dict (`part.fields["LCSC"] = "C14663"`, `part.fields["MPN"] = "..."`, `part.fields["Notes"] = "Alt package: ..."`). Copies created from a `TEMPLATE` part automatically inherit a copy of `part.fields`.
  * **KiCad Boolean Flags**: Set `part.dnp = True` or `part.exclude_from_bom = True` as direct attributes on `part` (checked via `getattr(part, ...)` by `gen_netlist_comp`).
* **Custom On-the-Fly Parts**: See [Advanced Patterns](./references/advanced_patterns.md) for creating schematic-less parts with `SkidlPart` and `Pin`.

## 4. Selecting Pins & Wiring Nets

### Pin Indexing (`part[...]`)
* **By number or name**: `u1[1]`, `u1["VI"]`, or attribute access `u1.VI` / `u1.p1`.
* **Multiple pins**: Space/comma-separated string `u1["VI VO"]`, tuple `u1[1, 2]`, or slice `mcu[1:8]`.
* **Disambiguating names vs. numbers**: Use `u1.p[1]` (numbers only) or `u1.n["1"]` (names only).
* **Regex matching**: Enable `u1.match_pin_regex = True` or wrap with `Rgx`: `mcu[Rgx("PA[0-7]")]`.

### Making Connections
Never use `=` to assign to pins, nets, or buses; **always use `+=`** or network operators (`&` and `|`):

```python
vin, vout, gnd = Net("VIN"), Net("3V3"), Net("GND")

# 1. Explicit net attachment (+=)
vin += u1["VI"]
vout += u1["VO"]
gnd += u1["GND"]

# 2. Algebraic series (&) and parallel (|) networks (for 2-pin parts or 2-port pin slices)
vin & c_in & gnd
vout & (c_out | (r1 & led)) & gnd

# Multi-pin parts in a series network: specify [in_pin, out_pin]
vin & u1["VI VO"] & vout

# Branching a network with tee()
vin & r1 & tee(c_in & gnd) & r2 & vout
```

* **Unconnected Pins (`NC` & `builtins`)**: Attach intentionally unused pins to the built-in no-connect net (`u1["NC"] += builtins.NC`). Note that `NC` and `default_circuit` are injected into Python's `builtins` module at import time and are **not** in `skidl.__all__` (`from skidl import NC` raises `ImportError`). When using explicit imports, `import builtins` and reference `builtins.NC` and `builtins.default_circuit`. Inside functions or `@subcircuit` blocks, always place the pin on the left (`u1["NC"] += builtins.NC`).
* **Buses**: Create multi-bit signals with `bus = Bus("DATA", 8)` and connect slices with `bus[0:7] += mcu["PA[0:7]"]`.

## 5. Electrical Rules Checking (ERC)

Always run `ERC()` before generating outputs:

```python
# Mark external power rails as driven so ERC doesn't flag "No drivers for net"
vin.drive = POWER
gnd.drive = POWER

# Disable ERC on specific nets/pins/parts if needed
test_point_net.do_erc = False

# Custom assertions evaluated during ERC()
erc_assert("len(vout) >= 2", "3V3 output rail has no load!")

ERC()
```

## 6. Exporting to KiCad & JLCPCB PCBA

Choose the output method that matches the user's workflow (by default, export the `.net` netlist, `.xml` BOM, and JLCPCB `.csv` BOM; **omit `generate_svg()` and `generate_schematic()` unless the user explicitly asks for diagram/schematic files**, as auto-routed SVGs clutter the repository and are not used by KiCad's PCB layout flow):

```python
# 1. KiCad Netlist (.net) — Primary workflow for KiCad PCB Editor
# In KiCad PCB Editor (pcbnew): File -> Import -> Netlist... -> Update PCB
generate_netlist(file_="my_board.net")

# 2. XML BOM (.xml)
generate_xml(file_="my_board_bom.xml")

# 3. Direct KiCad PCB (.kicad_pcb) — Optional
# Requires `kinet2pcb` and KiCad's `pcbnew` Python module in the active Python environment
generate_pcb(fp_libs=["/path/to/footprints.pretty"])

# 4. Optional Visual Diagrams (.svg / .kicad_sch / .dot) — ONLY when explicitly requested
# Note: generate_schematic() uses schematizer's global router, which can raise
# skidl.errors.RoutingFailure on dense multi-pin connectors.
generate_svg(filepath="output_dir", top_name="my_board", flatness=0.0)
generate_schematic(filepath="output_dir", top_name="my_board")
generate_dot(file_="circuit.dot")
```

* **JLCPCB PCBA BOM & Live LCSC Part Search**:
  * To verify live JLCPCB stock, Basic vs. Extended library status (`$0` vs. `$3` feeder setup fee), and unit pricing before assigning LCSC part numbers, run [jlcpcb_search.py](./scripts/jlcpcb_search.py):
    ```bash
    python3 .agents/skills/skidl/scripts/jlcpcb_search.py --in-stock-only "100k 0603" "TL074 SOIC-14"
    ```
  * To export a grouped 4-column JLCPCB BOM CSV (`Comment,Designator,Footprint,LCSC Part #`) or download offline catalog databases (`yaqwsx/jlcparts`, `CDFER/jlcpcb-parts-database`), read [JLCPCB PCBA BOM & Catalog Integration](./references/jlcpcb_bom.md).
* **Post-Export Verification Checklist**:
  1. Confirm `ERC()` reported `0 errors, 0 warnings` in stdout and `<script>.log`.
  2. Verify `<script>.net` contains no `(lib "NO_LIB")` fallback entries (which indicate symbol files were unreadable inside a sandbox).
  3. Verify every row in `jlcpcb_bom.csv` has non-empty `Footprint` and `LCSC Part #` values.

## 7. Code Quality & Linting (`ruff`)

* **Mandatory Post-Edit & Post-Run Step**: Whenever you create, modify, or execute a SKiDL Python script (or any helper Python script), **always** run `ruff` lint and format over the Python files before finishing the task:
  ```bash
  ruff check --fix <script>.py <script>_sklib.py
  ruff format <script>.py <script>_sklib.py
  ```
* **Always Run `ruff` *After* Executing the SKiDL Script**: Running a SKiDL script emits or overwrites `<script>_sklib.py` (the auto-generated backup symbol library) with unformatted code. Always run `ruff check --fix` and `ruff format` *after* the final execution of `<script>.py` so both `<script>.py` and `<script>_sklib.py` remain lint-clean and formatted.
* **Scoped Target Files**: Target `ruff` specifically at your script, its `<script>_sklib.py` backup library, and any modified skill scripts (e.g., `.agents/skills/skidl/scripts/jlcpcb_search.py`) rather than `.` so third-party scripts inside `.agents/skills/` are never modified.
* **Explicit Imports**: In saved circuit scripts, prefer explicit imports (`import builtins` + `from skidl import ERC, POWER, TEMPLATE, Net, NetClass, Part, generate_netlist, generate_xml, subcircuit`) over `from skidl import *`. Never put `NC` or `default_circuit` in `from skidl import ...`; access them via `builtins.NC` and `builtins.default_circuit`. Add `# noqa: E402` if `os.environ` setup precedes the import.
* **Executable Shebangs**: If including `#!/usr/bin/env python3`, run `chmod +x <script>.py` so `ruff` (`EXE001`) passes.

## 8. Hierarchy, Design Classes & SPICE

For hierarchical subcircuits (`@subcircuit`, `SubCircuit`, `Interface`), PCB routing classes (`NetClass`, `PartClass`), missing footprint handlers, and converting existing KiCad netlists to SKiDL (`netlist_to_skidl`), read [Advanced Patterns](./references/advanced_patterns.md).
