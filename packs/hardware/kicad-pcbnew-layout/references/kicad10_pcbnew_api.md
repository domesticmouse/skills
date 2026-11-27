# KiCad 10 `pcbnew` Python API Reference & Pitfalls

Practical notes verified against KiCad `10.0.x` on macOS.

## 1. Self-Bootstrapping KiCad Python

System Python and project virtualenvs cannot import `pcbnew` directly unless KiCad's Python interpreter is used. Put this block at the top of any standalone PCB script before importing `pcbnew`:

```python
from __future__ import annotations

import os
import pathlib
import sys

KICAD_PYTHON = pathlib.Path(
    "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3"
)

try:
    import pcbnew
except ModuleNotFoundError:
    if KICAD_PYTHON.exists():
        os.execv(str(KICAD_PYTHON), [str(KICAD_PYTHON), *sys.argv])
    raise
```

Footprint libraries on macOS live at:

```python
FP_DIR = pathlib.Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints")
```

Load any footprint with `pcbnew.FootprintLoad(str(FP_DIR / f"{lib}.pretty"), fp_name)` (or `load_footprint(lib, fp_name, custom_fp_dirs=[ROOT / "footprints"])` to prefer project-local custom footprints before stock libraries).

In `create_base_board()`, setting `ds.SetGridOrigin(...)` and `ds.SetAuxOrigin(...)` to the board's top-left `(x0, y0)` aligns KiCad's GUI rulers and `silk_layout.json` coordinates to board-local `(0, 0)`. When a `.kicad_sch` accompanies the board, pass `sch_uuids=parse_schematic_unit1_uuids(sch_path)` to `populate_footprints()` so `fp.SetPath()` matches unit-1 schematic UUIDs for clean schematic-to-PCB parity.

### Python `3.9` Runtime Compatibility

KiCad 10 on macOS bundles **Python `3.9.13`**, while project `.venv` environments typically run Python `3.12+`:
- Always include `from __future__ import annotations` at the top of KiCad-bootstrapped scripts so `X | Y` type annotations evaluate lazily without `TypeError`.
- Avoid Python `3.10+` stdlib features such as `itertools.pairwise` (which `ruff` rule `RUF007` recommends on newer Python targets, causing `ImportError` inside KiCad Python).
- Lint KiCad-bootstrapped scripts with `ruff check --target-version py39` (or mark deliberate index loops `# noqa: RUF007`).

## 2. Board Initialization & Avoiding `Flip()` Segfaults

Calling `fp.Flip(...)` or accessing uninitialized layer tables on a bare `pcbnew.BOARD()` before a footprint or board is fully initialized can trigger a segmentation fault (exit code `139`). Always:

1. Write a minimal valid `(kicad_pcb (version 20240108) ... (layers ...))` shell to a temporary file and load it via `board = pcbnew.LoadBoard(tmp_path)`.
2. Call `board.SetFileName(str(out_path))`.
3. Call `board.Add(fp)` **before** calling `fp.SetPosition(...)`, `fp.Flip(...)`, or `fp.SetOrientationDegrees(...)`.
4. For `B.Cu` footprints, flip first and then set the desired back-side orientation:

```python
fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
if is_back:
    fp.Flip(fp.GetPosition(), False)
    fp.SetOrientationDegrees(rot_deg)
else:
    fp.SetOrientationDegrees(rot_deg)
```

## 3. KiCad 10 API Differences vs. Older Examples

| Legacy Pattern (Fails in KiCad 10) | KiCad 10 Working API |
| :--- | :--- |
| `ds.GetDefault()` | `ds.m_NetSettings.GetDefaultNetclass()` |
| `ds.m_TentVias = True` | `ds.m_TentViasFront = True` and `ds.m_TentViasBack = True` |
| `net_item.GetNet()` | `net_item.GetNetCode()` |
| `pcbnew.GR_TEXT_H_JUSTIFY_CENTER` | `pcbnew.GR_TEXT_H_ALIGN_CENTER` |
| `pcbnew.GR_TEXT_V_JUSTIFY_CENTER` | `pcbnew.GR_TEXT_V_ALIGN_CENTER` |
| `pcbnew.PCB_FP_TEXT_T` | Identify footprint text via `hasattr(item, "GetText")` or `isinstance(item, pcbnew.PCB_TEXT)` |
| `pad.GetZoneConnection()` / `SetZoneConnection(...)` | `pad.GetLocalZoneConnection()` / `pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_THERMAL)` |
| `fp.GetFieldByName("Silkscreen")` | Iterate `fp.GetFields()` matching `fld.GetName() == name` (or `get_footprint_field(fp, name)`) |
| `dr.IsFilled()` | `dr.GetFillMode() == pcbnew.FILL_T_FILLED_SHAPE` (`FILL_T_NO_FILL == 1` is truthy—never use `bool(dr.GetFillMode())`) |
| `pad.GetLocalSolderMaskMargin()` -> `int` | Returns `None` when inheriting board defaults; call `pad.GetSolderMaskExpansion(pcbnew.B_Mask)` / `F_Mask` (layer required) or fall back to `ds.m_SolderMaskExpansion` |
| `item.GetLayerName() == "B.SilkS"` | `GetLayerName()` returns canonical `"B.Silkscreen"` / `"F.Silkscreen"`; compare numeric layer IDs (`item.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS)`) |
| `via.GetWidth()` | Pass a copper layer argument (`via.GetWidth(pcbnew.B_Cu)`) to avoid KiCad's wx assert warning |
| `board.Remove(item)` / `fp.Remove(item)` | Use `board.Delete(item)` / `fp.Delete(item)` when deleting drawings, texts, or shapes in place to avoid dangling SWIG ownership |

## 4. `lib_footprint_issues` in Sandbox / Headless DRC

If you call `fp.SetFPID(pcbnew.LIB_ID(lib, fp_name))`, `kicad-cli pcb drc` looks up `lib` in the user's global `fp-lib-table` (`~/Library/Preferences/kicad/10.0/`). In sandboxed or CI environments without read access to global KiCad preferences, DRC emits `lib_footprint_issues` warnings for every component. Leaving the footprint ID populated by `pcbnew.FootprintLoad(...)` preserves footprint metadata cleanly without emitting `lib_footprint_issues` warnings.

## 5. DNP Flags, Zone Fills, and Connectivity

- Mark unpopulated components (`TP*`, optional test headers) and optical fiducials (`FID*`) using **all three** flags (plus `fp.SetBoardOnly(True)` on board-only fiducials for schematic-parity DRC) so neither `TP*` nor `FID*` leak into `kicad-cli pcb export pos --smd-only --exclude-dnp`:
  ```python
  fp.SetBoardOnly(True)  # on board-only fiducials
  fp.SetDNP(True)
  fp.SetExcludedFromBOM(True)
  fp.SetExcludedFromPosFiles(True)
  ```
- Note that SKiDL `3.0.0` emits valueless `(property (name "dnp"))` and `(property (name "exclude_from_bom"))` nodes in `.net` files (without a `(value ...)` child), so netlist parsers must treat `(property (name "dnp"))` as `True` even without `(value ...)`.
- When pouring `GND` copper zones (`pcbnew.ZONE`):
  - Enable island removal if available (`zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)`) to eliminate floating dead-copper islands.
  - Call `board.BuildConnectivity()` **before and after** `pcbnew.ZONE_FILLER(board).Fill(board.Zones())`. Skipping either call can leave stale ratsnest connections or DRC `unconnected_items` on `Zone [GND]`.
