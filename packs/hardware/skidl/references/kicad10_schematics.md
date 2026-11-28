# KiCad 10 Schematics & Verification (`skidl==3.0.0` + `schematizer==0.2.0`)

Load this guide when generating visual KiCad schematics (`.kicad_sch`) from SKiDL scripts. For standard PCB workflows, `.net` + `jlcpcb_bom.csv` export is primary and `.kicad_sch` generation is optional.

---

## 1. Eight Verified KiCad 10 Schematic Rules

### 1. Never call bare `generate_schematic()` defaults
Bare `generate_schematic()` defaults to `auto_stub=False, retries=2`, which raises `skidl.errors.RoutingFailure` on non-trivial circuits (`GlobalRoutingFailure` on flat Eurorack circuits, `SwitchboxRoutingFailure` inside `@subcircuit` blocks).

### 2. Choose one of the three supported schematic modes
* **Hierarchical human-readable (recommended):** Group parts into `@subcircuit` blocks of ~5–15 parts each and call:
  ```python
  generate_schematic(
      filepath="output_dir",
      top_name="my_board",
      flatness=0.0,
      auto_stub=True,
      retries=5,
  )
  ```
* **Deterministic zero-failure:** Use labels-only mode (`schematizer.engine.labels.write_labels_schematic`), bypassing placement optimization and wire routing entirely:
  ```python
  generate_schematic(filepath="output_dir", top_name="my_board", mode="labels")
  ```
* **Single-sheet routed:** Place all parts at the top level (no `@subcircuit` children) and pass `auto_stub=True`:
  ```python
  generate_schematic(filepath="output_dir", top_name="my_board", auto_stub=True, retries=5)
  ```

### 3. Never combine `@subcircuit` with `flatness > 0` (including `flatness=1.0`)
In `schematizer==0.2.0` (`sexp_schematic.py:node_to_sexp_schematic`), the parent node's dangling-wire purge builds `_anchor_pts` only from `root.parts`, which is empty when parts live inside flattened subcircuits. As a result, it deletes wires returned by flattened children while leaving snapped decoupling-cap `+12V` labels suppressed—silently disconnecting pins such as `C1` Pin 1 (`unconnected-(C1-Pad1)`). Keep `flatness=0.0` whenever `@subcircuit` is used.

### 4. Never combine `@subcircuit` with `auto_stub=False`
Unstubbed boundary nets emit unconnected parent sheet pins and dangling child `hierarchical_label` items stacked at `(5.0, 10.0)`. Always keep `auto_stub=True` for hierarchical routed schematics.

### 5. Explicitly stub negative power rails (`-12V`, `-5V`)
`schematizer`'s `_POWER_NET_RE` (`gen_schematic.py` and `snap.py`) automatically recognizes `+12V`, `GND`, `VCC`, `VDD`, `VSS`, `VEE`, etc., as power rails, but returns `False` for negative voltages like `-12V` and `-5V`. Set `.stub = True` explicitly on negative power nets:
```python
vp = Net("+12V")
vm = Net("-12V")
gnd = Net("GND")
vm.stub = True  # Required so schematizer stubs -12V instead of routing long wires
```

### 6. Add `power:PWR_FLAG` only *after* `generate_netlist()` and BOM export
Eurorack power typically enters through a passive `Connector_Generic:Conn_02x05_Odd_Even` header. Setting `vp.drive = POWER` satisfies SKiDL's `ERC()`, but KiCad 10 Eeschema still raises `[power_pin_not_driven]` on `TL072` `V+`/`V-` pins and any `GND`-tied input pin.

Attaching `Part("power", "PWR_FLAG")` to `+12V`, `-12V`, and `GND` yields `0` KiCad 10 ERC errors (leaving only benign `[lib_symbol_mismatch]` warnings). However, because `PWR_FLAG` has no PCB footprint, `generate_netlist()` raises `ERROR: No footprint for PWR_FLAG/#FLG*` if `PWR_FLAG` exists during netlist export. Always add `PWR_FLAG` only in a post-netlist, post-BOM schematic pass:

```python
import builtins
from skidl import ERC, POWER, Part, generate_netlist, generate_schematic, generate_xml

# ... build circuit, set vp.drive = POWER, vm.drive = POWER, gnd.drive = POWER ...
vm.stub = True

# 1. Run SKiDL ERC and export netlist + BOMs BEFORE adding PWR_FLAG
ERC()
generate_netlist(file_="my_board.net")
generate_xml(file_="my_board_bom.xml")
generate_jlcpcb_bom(file_="jlcpcb_bom.csv")

# 2. Post-netlist KiCad schematic pass: attach PWR_FLAG for Eeschema ERC
for pwr_net in (vp, vm, gnd):
    flg = Part("power", "PWR_FLAG")
    pwr_net += flg[1]

# Ignore SKiDL's missing-footprint check if re-running anything, or just generate schematic:
generate_schematic(
    filepath="schematic",
    top_name="my_board",
    flatness=0.0,
    auto_stub=True,
    retries=5,
)
```

*(Note: Keep `builtins.default_circuit` clean if you run further netlist exports afterward, or run the schematic pass in a separate helper/after all `.net` and BOM files are written.)*

### 7. Fail loudly in CI with `auto_stub_fallback="raise"`
`auto_stub_fallback` defaults to `"labels"` (silently falling back to labels-only mode if routing fails). When verifying routed schematic generation in CI or tests, pass `auto_stub_fallback="raise"` so routing failures surface immediately.

### 8. Ensure `kicad-cli` is on `PATH`
On macOS, add `/Applications/KiCad/KiCad.app/Contents/MacOS` to `PATH` before calling `generate_schematic()` so `schematizer` can run its Phase-2 KiCad ERC loop automatically.

---

## 2. Automated Verification (`verify_schematic.py`)

Always verify generated `.kicad_sch` files against KiCad 10 Eeschema ERC and the authoritative SKiDL `.net` netlist using [verify_schematic.py](../scripts/verify_schematic.py):

```bash
python3 .agents/skills/skidl/scripts/verify_schematic.py \
    schematic/my_board.kicad_sch \
    --netlist my_board.net
```

What `verify_schematic.py` checks:
1. Configures macOS KiCad environment variables and adds `/Applications/KiCad/KiCad.app/Contents/MacOS` to `PATH`.
2. Runs `kicad-cli sch erc --severity-all --format json` and fails on any ERC error or any warning other than benign `lib_symbol_mismatch` (override with `--strict-warnings` or `--allow-all-warnings`).
3. Checks that the SKiDL `.net` contains no `(lib "NO_LIB")` fallback entries.
4. Runs `kicad-cli sch export netlist --format kicadsexpr` on the `.kicad_sch` and performs a **pin-group parity comparison** against the SKiDL `.net` (ignoring `#PWR*`/`#FLG*` virtual power/flag symbols and `unconnected-*` `NC` pins) so silent schematic disconnects—such as `flatness=1.0` dropping `C1` Pin 1—fail immediately.

---

## 3. Alternative: Direct S-Expression Schematic Generator

When a publication-grade, deterministic single-sheet (e.g., A3 landscape) schematic exceeds `schematizer`'s auto-router, use [`kicad-schematic-layout`](../../kicad-schematic-layout/SKILL.md) (`sch_builder.py` + `inspect_schematic_inputs.py`) to drive the `.kicad_sch` S-expression directly from your SKiDL circuit (`build_circuit()`) so every value, footprint, custom field, and net connection retains a single source of truth:

- Parse KiCad 10 `.kicad_sym` files (`KICAD10_SYMBOL_DIR`), recursively flatten `(extends ...)` symbol inheritance, and embed flattened `(lib_symbols ...)` definitions so `kicad-cli` renders cleanly without global library lookup issues.
- Emit explicit wire coordinates, `global_label` / `power` symbols, `PWR_FLAG`s, and deterministic UUIDs, then verify `0` ERC errors and `100%` netlist pin-group parity with `verify_schematic.py`.
