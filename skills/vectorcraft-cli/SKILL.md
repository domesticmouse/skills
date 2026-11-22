---
name: vectorcraft-cli
description: >-
  Use this skill when running or automating VectorCraft from the command line with
  `vectorcraft-cli`, or when working with `.vectorcraft` files and headless vector
  generation or conversion: executing headless batch commands or scripts (`run`),
  converting between vector/raster/document formats (`convert`), inspecting document
  metadata and import warnings (`info`), discovering engine commands (`commands`),
  running or configuring the MCP stdio server (`mcp`, including
  `--automation-read-root` and `--automation-write-root`), or measuring render
  timings and performance budgets (`bench` and `perf`).
compatibility: Requires the vectorcraft-cli binary (built from storytold/vectorcraft via Rust/Cargo)
---

# VectorCraft CLI (`vectorcraft-cli`)

`vectorcraft-cli` provides headless batch execution, format conversion, document inspection, benchmarking, and a stdio MCP server for VectorCraft.

## Invoking `vectorcraft-cli`

- **Installed binary (default outside a VectorCraft checkout):** Verify `vectorcraft-cli --version` is on `PATH` (check `$CARGO_HOME/bin/vectorcraft-cli`, typically `~/.cargo/bin/vectorcraft-cli`, if Cargo's bin directory isn't on a non-interactive shell's `PATH`):
  ```sh
  vectorcraft-cli --version
  ```
- **Install standalone binary** (to `$CARGO_HOME/bin`, survives `cargo clean`) from a local clone of [`storytold/vectorcraft`](https://github.com/storytold/vectorcraft):
  ```sh
  cargo install --path apps/vectorcraft-cli --locked
  vectorcraft-cli --version
  ```
- **From a VectorCraft workspace checkout:**
  ```sh
  cargo run --release -p vectorcraft-cli -- <subcommand> ...
  ```
- **Safe Mode (global prefix):** Pass `--safe-mode` *before* the subcommand (`vectorcraft-cli --safe-mode <subcommand> ...`) to disable loading and running plug-ins. With `mcp`, `--safe-mode` forces a headless session and rejects `--connect`.
- **Help & version:** `vectorcraft-cli --help` (`help`, `-h`), or `--help`/`-h` after any subcommand, prints usage plus the live lists of readable and writable formats (together with `commands`, these are the live source of truth for the installed build). `-V`/`--version` prints the package version.

## Common Workflows

### 1. Discover Commands (`commands`)

Print the full engine command catalogue as pretty JSON before authoring `run` batches:

```sh
vectorcraft-cli commands
vectorcraft-cli commands | jq '.[] | select(.id | startswith("shape."))'
```

The engine validates every `params` object against the command catalogue before running; unknown parameter keys fail immediately with a suggestion.

### 2. Headless Batch Runs (`run`)

Open an optional `--in` file (or start with a blank document unless the first step is `file.new`), execute commands and exports in order, and print one JSON line per step to `stdout`.

```sh
vectorcraft-cli run \
  --cmd file.new --params '{"width":800,"height":600}' \
  --cmd shape.star --params '{"cx":400,"cy":300,"radius1":200,"radius2":90}' \
  --cmd paint.setFill --params '{"color":"#3366ff"}' \
  --export star.svg --export star.png --scale 2
```

Or stream a batch over `stdin` (`--commands -`):

```sh
vectorcraft-cli run --commands - --export star.svg <<'EOF'
{"command": "file.new", "params": {"width": 800, "height": 600}}
{"command": "shape.star", "params": {"cx": 400, "cy": 300, "radius1": 200, "radius2": 90}}
{"command": "paint.setFill", "params": {"color": "#3366ff"}}
EOF
```

- **Short flags:** `-i` (`--in`), `-c` (`--cmd`), `-p` (`--params`), `-o` (`--export`), `-s` (`--scale`).
- **`--params` placement:** Must immediately follow a `--cmd` and be a JSON object.
- **File or stdin batches (`--commands FILE` or `--commands -`):** Reads a UTF-8 JSON array or JSON Lines of `{"command": ID, "params": {...}}` (or `"id"` in place of `"command"`, max 64 MiB and 100,000 steps; `-` may be passed once). Prefer `--commands` over `--params` for large payloads (e.g., `dataBase64` or long ID lists). `--commands` executes in place wherever it appears among `--cmd` and `--export`.
- **Step references:** Any parameter string equal to `"$N"`, `"$N.key"`, `"$N.arr.0"`, `"$N.arr[0]"`, or `"$last..."` substitutes the corresponding value from an earlier step's result (0-based across all `--cmd`, `--commands`, and `--export` steps; `--in` and the implicit blank-document initialization both happen before step `0`). Because `--export` steps increment the 0-based index and overwrite `$last`, avoid placing `--export` between a `--cmd` and a later step using `"$last..."` (use an explicit `"$N..."` index instead). Escape a literal leading dollar sign as `"$$..."` (e.g., `"$$1.99"`).
- **Headless JavaScript:** Run inline scripts via `--cmd script.run --params '{"source": "...", "name": "...", "args": {...}}'` (passed to the script as `vc.args`).
- **Raster resolution:** `--scale` and `--ppi` are run-wide flags that apply to all raster `--export` steps in the invocation (not bound per `--export`). `--ppi` overrides `--scale` (pixels per point); without either, raster exports use the document's raster effects resolution. Both flags are ignored for non-raster formats (SVG, PDF, DXF, etc.).
- **Templates:** Exporting to `.ait` calls `file.saveAsTemplate`.
- **Plug-in grants:** `--allow-plugin-grants` enables `plugin.install`'s `grant` and `allowHeavy` parameters during the run (same as `mcp`).

### 3. Format Conversion (`convert IN OUT`)

Open `IN` (any readable format), write `OUT` (format inferred from extension), and print a JSON summary (including any import/export warnings) to `stdout`:

```sh
vectorcraft-cli convert input.pdf output.svg --outline-text --decimals 4
vectorcraft-cli convert artwork.vectorcraft print.pdf --preserve-editing
vectorcraft-cli convert poster.vectorcraft thumb.png --ppi 300 --artboard 0
```

- **Artboard selection:** `--artboard`/`-a I` (0-based) or `--range`/`-r R` (1-based, e.g., `"1-3,5"`). Defaults: PDF writes every artboard, EPS writes visible art bounds, other formats write artboard `0`. `.ait` writes a template of every artboard and cannot be combined with `--artboard` or `--range`.
- **SVG / PSD:** Hidden layers and objects are kept hidden (`hiddenLayers: true`). SVG also accepts `--outline-text` and `--decimals N` (`1`–`7`, default `3`).
- **PDF:** Omits embedded VectorCraft editing data unless `--preserve-editing` is passed (embedded only when all artboards are exported; otherwise omitted with a warning).
- **`.ai` / EPS options:**
  - On read: `--editing-data` prefers the editing copy even when it differs from the PDF/page stream; `--legacy-name-encoding ENC` decodes non-UTF-8 names (`windows-1252` default, `macintosh`, `windows-949`, `shift_jis`, `gbk`, `big5`).
  - On write: `--ai-version 7` writes legacy version 7 `.ai` (one file per artboard), paired with `--hidden-objects layer|omit|visible`, `--transparent-images flatten|omit`, and `--outline-text`. Default is `pdf` (PDF-compatible `.ai`).
- **Lossy overwrite guard:** Overwriting `IN` (`IN == OUT`) when opening `IN` dropped content requires `--replace-lossy`.

### 4. Inspect Metadata & Import Warnings (`info FILE`)

Print pretty JSON with `file`, `warnings` (import warnings), `info`, `artboards`, `kinds` (object counts excluding ruler guides), and `fonts`:

```sh
vectorcraft-cli info artwork.vectorcraft
```

### 5. MCP Server (`mcp`)

Run a newline-delimited JSON-RPC 2.0 MCP server on stdio (protocol messages on `stdout`, logs on `stderr`):

```sh
vectorcraft-cli mcp [--connect ADDR | --headless] \
  [--automation-read-root DIR]... [--automation-write-root DIR]... \
  [--allow-plugin-grants]
```

- **Backends:** Without flags, tries `127.0.0.1:7979` (`vectorcraft --control 7979`) and falls back to `--headless`. `--connect ADDR` fails if unreachable. `--headless` uses an in-process session with CPU rendering (UI-only tools like `ui_inspect`, `ui_screenshot`, `type_text`, `answer_dialog`, and `open_panel` return errors).
- **Confining file access:** Pass neither flag for an unconfined headless session. Passing either `--automation-read-root DIR` or `--automation-write-root DIR` (repeatable, also `--flag=DIR`) enables confinement to existing folders (symlinks resolved); once confined, omitting the other kind grants no access of that kind. Both imply `--headless` and conflict with `--connect` and `--allow-plugin-grants`. For a live app, pass those flags to `vectorcraft --control <port>` instead.
- **Plug-in permissions:** `--allow-plugin-grants` allows `plugin.install`'s `grant` and `allowHeavy` parameters in headless mode (recorded in `grants.json` unless `VECTORCRAFT_NO_PREFS` is set).

### 6. Benchmarking (`bench` and `perf`)

- **Render a specific document (`bench`):** Fits `FILE` to 95% of `WxH` (default `2880x1800`) and prints warm ms/frame, drawn count, and culled count for default multithreaded and single-threaded (`threads 0`) renders:
  ```sh
  vectorcraft-cli bench artwork.vectorcraft --size 1920x1080 --iters 10
  ```
- **Synthetic performance budgets (`perf`):** Benchmarks a synthetic `N`-path document (default `50000`) and exits non-zero if any budget is exceeded (unless high system load is detected):
  ```sh
  vectorcraft-cli perf [--paths N] [--deep] [--native-io [--artboards 1..4]]
  ```
  `--deep` adds untracked measurements, output hashes, and memory readings; `--native-io` (max `50000` paths, mutually exclusive with `--deep`) benchmarks in-memory `file.saveAs`/`document.open` across PDF and preview/compression variants.

## Environment Variables & Reproducibility

- `VECTORCRAFT_NO_PREFS=1`: Disable reading/writing shared user stores (recommended for CI and isolated automation tests; `Fonts` are still attached at startup).
- `VECTORCRAFT_CONFIG_DIR`: Override the folder for shared user settings and stores.
- `VECTORCRAFT_CONTROL_PORT`: TCP port for the desktop app's control server (`vectorcraft --control <port>`), used with `vectorcraft-cli mcp --connect`.
- `SOURCE_DATE_EPOCH`: Non-negative Unix timestamp (seconds) for byte-reproducible PNG, unencrypted PDF, EPS, legacy `.ai`, `.vectorcraft`, and packaged ZIP exports (password-protected PDF 1.4+ still uses random encryption seeds).

## Verification Checklist

1. **Confirm exit status & JSON lines:** `run` exits non-zero on the first failing step, naming the 0-based step and command on `stderr`. Closing `stdout` early (e.g., `| head -n 5`) exits cleanly with status `0`, and `run` continues executing later steps such as `--export`.
2. **Check warnings:** Inspect `warnings` and `importWarnings` in `convert`, `info`, and `run` JSON output to verify no unexpected loss or missing fonts/links occurred.
3. **Verify exported artifacts:** Run `vectorcraft-cli info <OUT>` on generated documents to confirm artboard dimensions, object counts, fonts, and clean reload.
4. **Inspect rendered visuals:** When generating or editing artwork, export a raster preview (`--export preview.png --scale 2` or MCP `render_preview`) and visually inspect the rendered image to catch geometry, alignment, or clipping errors.
5. **Validate commands before batching:** Run `vectorcraft-cli commands` whenever unsure of a command ID or exact parameter keys.

## Reference

- [Detailed CLI Reference](./references/reference.md) — complete flag tables, conflict rules, step-reference syntax, full readable/writable format lists, `perf` budget thresholds, shared stores, and MCP protocol summary.
- Source & full MCP spec in [`storytold/vectorcraft`](https://github.com/storytold/vectorcraft): `apps/vectorcraft-cli/src/main.rs`, `apps/vectorcraft-cli/src/perf.rs`, `docs/mcp.md`.
