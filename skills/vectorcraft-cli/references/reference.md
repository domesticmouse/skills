# `vectorcraft-cli` Detailed Reference

Reference derived from upstream [`storytold/vectorcraft`](https://github.com/storytold/vectorcraft) source files (`apps/vectorcraft-cli/src/main.rs`, `apps/vectorcraft-cli/src/perf.rs`, `crates/engine/src/steps.rs`, `crates/engine/src/cmd/fileio/formats.rs`, `apps/vectorcraft/src/prefs_dir.rs`, and `docs/mcp.md`). The installed binary's `vectorcraft-cli --help` and `vectorcraft-cli commands` outputs remain the live source of truth if your build differs.

---

## 1. Complete Command & Flag Reference

### Global Options

| Flag / Command | Notes |
|---|---|
| `--safe-mode SUBCOMMAND ...` | Must appear **before** the subcommand. Disables loading and running plug-ins (plug-in commands report that Safe Mode is active; installed plug-ins stay on disk). With `mcp`, forces a headless session and rejects `--connect`. |
| `help`, `-h`, `--help` | Prints full usage text plus live lists of readable and writable formats. Also accepted after any subcommand (after valued flags, so `run --cmd -h` keeps `-h` as the `--cmd` value). |
| `-V`, `--version` | Prints `vectorcraft-cli <version>`. |

### `mcp`

```sh
vectorcraft-cli mcp [--connect ADDR | --headless] \
  [--automation-read-root DIR]... [--automation-write-root DIR]... \
  [--allow-plugin-grants]
```

| Option | Notes |
|---|---|
| `--connect ADDR` | Connect over TCP to a running desktop app (e.g., `127.0.0.1:7979` started via `vectorcraft --control 7979` or `VECTORCRAFT_CONTROL_PORT`). Fails immediately if unreachable. |
| `--headless` | Force an in-process headless session with CPU rendering. UI-only tools (`ui_inspect`/`inspect_ui`, `ui_screenshot`/`screenshot {window:true}`, `type_text`, `answer_dialog`, `open_panel`) return errors. |
| *(neither flag)* | Tries connecting to `127.0.0.1:7979` once on startup and falls back to an in-process headless session if unreachable. |
| `--automation-read-root DIR` | Repeatable (also `--automation-read-root=DIR`). Enables file confinement and allows reads only inside `DIR` (existing folder; symlinks followed). Once confinement is enabled (at least one `--automation-*-root` flag is passed), omitting `--automation-read-root` grants no file reads. Passing neither flag runs unconfined. |
| `--automation-write-root DIR` | Repeatable (also `--automation-write-root=DIR`). Enables file confinement and allows writes only inside `DIR` (existing folder; symlinks followed). Once confinement is enabled (at least one `--automation-*-root` flag is passed), omitting `--automation-write-root` grants no file writes. Passing neither flag runs unconfined. |
| `--allow-plugin-grants` | Allows `plugin.install`'s `grant` and `allowHeavy` parameters in headless mode without interactive approval (persisted in `grants.json` unless `VECTORCRAFT_NO_PREFS` is set). |

**Conflict rules for `mcp`:**
- `--headless` cannot be combined with `--connect`.
- `--safe-mode` cannot be combined with `--connect`.
- `--allow-plugin-grants` implies `--headless` and cannot be combined with `--connect`.
- `--automation-read-root` and `--automation-write-root` imply `--headless` and cannot be combined with `--connect` (start the desktop app itself with `--control <port> --automation-read-root DIR --automation-write-root DIR`) or with `--allow-plugin-grants`.

### `run`

```sh
vectorcraft-cli run [--in FILE] \
  [--cmd ID [--params JSON] | --commands FILE|-]... \
  [--export FILE]... [--scale N] [--ppi N] [--allow-plugin-grants]
```

| Option | Short | Notes |
|---|---|---|
| `--in FILE` | `-i` | Open `FILE` (any readable format) via `app.open`. Without `--in`, `run` initializes a blank document unless the very first step is `file.new`. |
| `--cmd ID` | `-c` | Append an `engine.execute` step for command `ID`. |
| `--params JSON` | `-p` | JSON object of parameters for the immediately preceding `--cmd`. Must follow `--cmd` (cannot follow `--commands` or `--export`). Keys are validated against the command's parameter docs before running. |
| `--commands FILE \| -` | — | Read steps from `FILE` or standard input (`-`). Can be passed multiple times (`-` at most once). Steps execute in-place among `--cmd` and `--export` and share 0-based `$N` step numbering. |
| `--export FILE` | `-o` | Export current document to `FILE` (format from extension; `.ait` calls `file.saveAsTemplate`). |
| `--scale N` | `-s` | Run-wide raster export scale in pixels per point (applied to all raster `--export` steps in the invocation). Ignored for non-raster formats (e.g., SVG, PDF, DXF). |
| `--ppi N` | — | Run-wide positive finite raster export resolution in pixels per inch (applied to all raster `--export` steps in the invocation). Overrides `--scale`. Ignored for non-raster formats. |
| `--allow-plugin-grants` | — | Same as for `mcp`: enables `plugin.install` `grant` and `allowHeavy` in this run. |

**`--commands` input format & limits:**
- Must be UTF-8 text (an optional leading UTF-8 BOM `\u{feff}` is stripped).
- At most `64 MiB` (`67,108,864` bytes) and `100,000` steps.
- Accepts either a JSON array `[...]` or JSON Lines (one JSON object per non-blank line).
- Each step object must have `"command"` or `"id"` (string, not both), optional `"params"` (JSON object or `null`), and no other keys.
- Malformed input fails before any step runs, reporting the 0-based step index and entry/line number.
- On `stdout` pipe closure (`BrokenPipe`), `run` stops printing and finishes remaining steps (such as `--export`), exiting with status `0`.

### `commands`

```sh
vectorcraft-cli commands
```

Takes no options. Calls `engine.commands` and prints the full command catalogue as pretty JSON.

### `convert`

```sh
vectorcraft-cli convert IN OUT \
  [--scale N] [--ppi N] [--artboard I | --range R] \
  [--outline-text] [--decimals N] [--replace-lossy] \
  [--editing-data] [--legacy-name-encoding ENC] [--preserve-editing] \
  [--ai-version 7|pdf] [--hidden-objects layer|omit|visible] \
  [--transparent-images flatten|omit]
```

| Option | Short | Notes |
|---|---|---|
| `IN` `OUT` | — | Positional input and output paths. Output format comes from `OUT`'s extension (`.ait` writes a template via `file.saveAsTemplate`). |
| `--scale N` | `-s` | Raster pixels per point (ignored for non-raster outputs). |
| `--ppi N` | — | Positive finite raster PPI; overrides `--scale`. |
| `--artboard I` | `-a` | 0-based artboard index (invalid for `.ait`). |
| `--range R` | `-r` | 1-based artboard range, e.g. `"1-3,5"` (invalid for `.ait`). |
| `--outline-text` | — | Export SVG text (and legacy v7 `.ai` text) as path outlines instead of text elements. |
| `--decimals N` | — | SVG coordinate precision (`1`–`7`, default `3`). |
| `--replace-lossy` | — | Sets `acknowledgeLoss: true`, allowing `OUT == IN` when opening `IN` dropped unsupported content. |
| `--editing-data` | — | Opens `.ai` or EPS using `editingData: "always"` from the embedded editing copy even when it differs from the PDF/page stream. |
| `--legacy-name-encoding ENC` | — | Decode non-UTF-8 names in `.ai`/EPS editing data: `windows-1252` (default), `macintosh`, `windows-949`, `shift_jis`, `gbk`, or `big5`. |
| `--preserve-editing` | — | For PDF `OUT`, embeds the native VectorCraft document as an attachment (only when all artboards are exported; otherwise omitted with a warning). |
| `--ai-version 7\|pdf` | — | `.ai` output mode: `pdf` (default, PDF-compatible) or `7` (legacy version 7; writes one file per artboard, `OUT-<artboard>.ai` when multiple). |
| `--hidden-objects layer\|omit\|visible` | — | Legacy `.ai` hidden objects handling (default `layer`: hidden layer above each layer's hidden objects). Note: SVG and PSD automatically receive `hiddenLayers: true`. |
| `--transparent-images flatten\|omit` | — | Legacy `.ai` transparent image handling (default `flatten`). |

**Defaults & output for `convert`:**
- Default artboards (when neither `--artboard` nor `--range` is given): PDF writes every artboard; EPS writes visible art bounds; `.ait` writes a template of every artboard (and cannot be combined with `--artboard` or `--range`); other formats write artboard `0`.
- Prints a JSON result (including any `warnings` / `importWarnings`) to `stdout`.

### `info`

```sh
vectorcraft-cli info FILE
```

Takes `FILE` and no options. Prints pretty JSON with:
- `file`: input path
- `warnings`: import warnings from `app.open`
- `info`: `file.info` result (title, color mode, units, metadata)
- `artboards`: array of `{name, rect: [x, y, width, height]}`
- `kinds`: object counts by node kind (excluding ruler guides)
- `fonts`: `text.fonts` result

### `bench`

```sh
vectorcraft-cli bench FILE [--size WxH] [--iters N]
```

| Option | Default | Notes |
|---|---|---|
| `--size WxH` | `2880x1800` | Viewport dimensions in pixels (renders artboard 0 fitted to 95% of `WxH`). |
| `--iters N` | `5` | Warm iterations timed after 1 warmup frame for both `vectorcraft_render::default_threads()` and `0` (single-threaded). |

### `perf`

```sh
vectorcraft-cli perf [--paths N] [--deep] [--native-io [--artboards 1..4]]
```

| Option | Default | Notes |
|---|---|---|
| `--paths N` | `50000` | Synthetic mixed path count (`1600×1200` pt document). Capped at `50000` when `--native-io` is set. |
| `--deep` | off | Adds untracked timings, output FNV-1a hashes, and RSS / working-set memory measurements. Mutually exclusive with `--native-io`. |
| `--native-io` | off | Measures in-memory `file.saveAs` and `document.open` across 4 option presets (1 warmup + 5 samples, no disk I/O). Mutually exclusive with `--deep`. |
| `--artboards 1..4` | `1` | Repeats the synthetic artwork across `1` to `4` overlapping artboards. Requires `--native-io`. |

---

## 2. Step References (`$N` / `$last`)

Implemented in upstream `storytold/vectorcraft` (`crates/engine/src/steps.rs`) for both `vectorcraft-cli run` and MCP `command_batch` (note: `run --commands` accepts either `"command"` or `"id"`, whereas MCP `command_batch` steps require `"id"`).

- **Step index:** 0-based across all `--cmd`, `--commands`, and `--export` steps executed in the run (both `app.open` from `--in` and implicit blank-document setup happen before step `0`). Note that `--export` steps increment the 0-based index and update `$last`.
- **Syntax** (must match the entire JSON string value):
  - `"$N"` — entire result of step `N`
  - `"$last"` — entire result of the immediately preceding step
  - `".key"` — object property access (ASCII alphanumeric + `_`), or array index when the value is a JSON array (`"$2.ids.0"`)
  - `"[idx]"` — array element access with non-negative digits (`"$last.ids[0]"`)
- **Escaping:** A string starting with `"$$"` has one `$` stripped (`"$$1.99"` becomes `"$1.99"`) and is never resolved as a reference. Partial strings such as `"cost $1"` or `"a$1.id"` are left unchanged.
- **Limits & errors:**
  - Recursively resolves inside arrays and objects up to depth `64`.
  - Total copied JSON weight across all references in a single step is capped at `256 MiB`.
  - Any `$N` or `$last` reference pointing to a non-existent step or missing path fails the step with an error before the command runs.

---

## 3. Supported Formats

Defined in upstream `storytold/vectorcraft` (`crates/engine/src/cmd/fileio/formats.rs`: `OPEN_EXTS` and `export_extensions()`); run `vectorcraft-cli --help` to print the live format lists for your installed binary:

- **Readable (`run --in`, `convert`, `info`, `bench`, `open_file`):**
  - **Vector / Document:** `.vectorcraft`, `.drawcraft`, `.vctemplate`, `.svg`, `.svgz`, `.pdf`, `.ai`, `.ait`, `.eps`, `.epsf`, `.ps`, `.dxf`, `.emf`, `.wmf`, `.pct`, `.pic`, `.pict`, `.plt`, `.hpgl`, `.hgl`, `.hpg`, `.af`, `.afdesign`, `.afpub`, `.cdr`, `.cdt`, `.cmx`
  - **Raster / Layered:** `.psd`, `.pdd`, `.psb`, `.png`, `.pns`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.tif`, `.tiff`, `.bmp`, `.dib`, `.rle`, `.tga`, `.vda`, `.icb`, `.vst`, `.pcx`, `.pxr`, `.jp2`, `.jpf`, `.jpx`, `.j2k`, `.j2c`, `.jpc`, `.heic`, `.heif`, `.jxl`
- **Writable (`run --export`, `convert`, `export`):**
  - `.vectorcraft`, `.vctemplate`, `.svg`, `.svgz`, `.pdf`, `.ai`, `.ait` (written as template via `file.saveAsTemplate` in `convert`/`run`), `.eps`, `.dxf`, `.emf`, `.wmf`, `.plt`, `.png` (PNG and PNG-8 via `export` format `"png8"`), `.jpg`, `.gif`, `.webp`, `.tif`, `.bmp`, `.tga`, `.psd`, `.txt` (document text), plus any installed exporter plug-in formats.

---

## 4. `perf` Budgets & Measurement Modes

### Default Performance Budgets (`50,000` paths unless `--paths` overrides)

| Operation | Budget |
|---|---|
| `render: fit page, 2880×1800` | `100 ms` |
| `render: background refresh after a pan` | `100 ms` |
| `render: 400% zoom, 2880×1800` | `16 ms` |
| `hit test (per click)` | `2 ms` |
| `save .vectorcraft` | `300 ms` |
| `open .vectorcraft` | `300 ms` |
| `export SVG` | `500 ms` |
| `Pathfinder Unite, 1,000 paths` | `150 ms` |
| `handle drag, 5,000-anchor path (per move)` | `8 ms` |
| `segment drag, 5,000-anchor path (per move)` | `8 ms` |

- **Busy-machine guard:** On Unix, if the 1-minute load average exceeds `cores * 0.75` (or on Windows, busy cores over 1 second exceed `cores * 0.75`), `perf` prints a warning and exits `0` even if budgets are exceeded. Otherwise, exceeding any budget exits non-zero.
- **`--deep`:** Additionally measures whole-selection edits/undo/redo/drag, live effects (`path.offsetPath`, `distort.roughen` on 2,000 paths), all 10 Pathfinder ops on 300 paths, 20k-char area-type typing, hover/hit/marquee/smart-guides/`select.toggle`, 4 embedded 24 MP photos across 3 renderers, embedded-image SVG import, FNV-1a round-trip hashes, and RSS/working-set memory.
- **`--native-io`:** Exercises `file.saveAs` + `document.open` (including base64 encode/decode) for `default options`, `PDF disabled`, `preview+gzip`, and `preview+gzip, PDF disabled`.

---

## 5. Shared User Stores & MCP Server Summary

### Shared User Stores (upstream `apps/vectorcraft/src/prefs_dir.rs`)

Both `run` and unconfined headless `mcp` attach the same stores as the desktop app (unless `VECTORCRAFT_NO_PREFS` is set, or `mcp` uses `--automation-read-root`/`--automation-write-root`):
- `Scripts`, `Script Data`, `Metadata Templates`, `New Document Profiles`, `Proof Setups`, `Color Profiles`, `Color Settings.json`, `Plug-ins`, `PDF Presets`, `Custom Dictionary.txt`, `Arrowheads.vectorcraft`, `Bevels.vectorcraft`.
- `Fonts` is attached at process startup (even when `VECTORCRAFT_NO_PREFS` is set).
- Set `VECTORCRAFT_CONFIG_DIR` to point both `vectorcraft` and `vectorcraft-cli` at an alternate store root.

### MCP Server (`vectorcraft-cli mcp`) Highlights

- **Protocol:** Newline-delimited JSON-RPC 2.0 on stdio (`2025-06-18` default; also accepts `2025-03-26`, `2024-11-05`, and `2026-07-28` caching metadata). Max 16 MiB per input line, 64 messages per JSON-RPC batch, 256 steps per `command_batch`, 8 MiB kept step results.
- **Core tools:** `command_list`/`list_commands`, `command_run`/`run_command`, `command_batch`, `doc_inspect`/`inspect_document`, `render_preview`, `draw_path`, `draw_shape`, `add_text`, `set_paint`, `apply_effect`, `pathfinder`, `transform`, `open_file`, `save_file`, `export`, `screenshot`, `pointer_gesture`, `press_key`, `undo`/`redo`, `select_tool`, `create_graph`, `text_wrap`, `invoke_menu`, and remote-only `ui_inspect`/`inspect_ui`, `ui_screenshot`/`screenshot {window:true}`, `type_text`, `answer_dialog`, `open_panel`.
- **Resources & templates:** `vectorcraft://document`, `vectorcraft://document/json`, `vectorcraft://commands`, `vectorcraft://commands/reference`, `vectorcraft://object/{id}`, `vectorcraft://command/{id}`, `vectorcraft://effect/{id}`, `vectorcraft://swatch/{name}`.
- See `docs/mcp.md` in [`storytold/vectorcraft`](https://github.com/storytold/vectorcraft) for full tool schemas, prompt templates, and confinement behavior.
