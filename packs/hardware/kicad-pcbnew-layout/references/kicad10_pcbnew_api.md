# KiCad 10 `pcbnew` Python API Reference & Pitfalls

Practical notes verified against KiCad `10.0.1` on macOS.

## 1. Self-Bootstrapping KiCad Python

System Python and project virtualenvs cannot import `pcbnew` directly unless KiCad's Python interpreter is used. Put this block at the top of any standalone PCB script before importing `pcbnew`:

```python
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

Load any footprint with `pcbnew.FootprintLoad(str(FP_DIR / f"{lib}.pretty"), fp_name)`.

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

## 4. `lib_footprint_issues` in Sandbox / Headless DRC

If you call `fp.SetFPID(pcbnew.LIB_ID(lib, fp_name))`, `kicad-cli pcb drc` looks up `lib` in the user's global `fp-lib-table` (`~/Library/Preferences/kicad/10.0/`). In sandboxed or CI environments without read access to global KiCad preferences, DRC emits `lib_footprint_issues` warnings for every component. Leaving the footprint ID populated by `pcbnew.FootprintLoad(...)` preserves footprint metadata cleanly without emitting `lib_footprint_issues` warnings.

## 5. DNP Flags, Zone Fills, and Connectivity

- Mark unpopulated components (`TP*`, optional test headers) using both flags:
  ```python
  fp.SetDNP(True)
  fp.SetExcludedFromBOM(True)
  ```
- When pouring `GND` copper zones (`pcbnew.ZONE`):
  - Enable island removal if available (`zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)`) to eliminate floating dead-copper islands.
  - Call `board.BuildConnectivity()` **before and after** `pcbnew.ZONE_FILLER(board).Fill(board.Zones())`. Skipping either call can leave stale ratsnest connections or DRC `unconnected_items` on `Zone [GND]`.
