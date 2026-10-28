# Skills

A collection of AI agent skills by [@domesticmouse](https://github.com/domesticmouse), compatible with [skills.sh](https://skills.sh).

## Installation

Install all default skills or pick interactively:

```bash
npx skills add domesticmouse/skills
```

Install a specific skill:

```bash
npx skills add domesticmouse/skills --skill <skill-name>
```

Install an optional skill pack (not installed by default):

```bash
npx skills add domesticmouse/skills/packs/<pack-name>
```

## Available Skills

### [`agy-brain-explorer`](skills/agy-brain-explorer/SKILL.md)

Discovers, lists, inspects, compares, audits, exports, and safely deletes Google Antigravity session trajectories, transcripts, disk paths, tool invocations, and execution steps across all brain storage directories under `~/.gemini`.

**Origin:** Built around a zero-setup [`uv`](https://docs.astral.sh/uv/) Python CLI script ([`agy-brain-explorer.py`](skills/agy-brain-explorer/scripts/agy-brain-explorer.py)) to make navigating local Antigravity `transcript.jsonl` and `transcript_full.jsonl` session logs fast and readable directly inside chat via GitHub Flavored Markdown tables and clickable `conversation://` and `file://` links.

**Intended Usage:** Ask the agent to list recent sessions, group or search sessions by project or prompt keyword, inspect step timelines and tool calls, export per-conversation Markdown logs (e.g., into a `prompts/` folder), compare two sessions side-by-side, or clean up old sessions (moving them to the macOS Trash by default).

### [`asciinema`](skills/asciinema/SKILL.md)

Records, replays, converts, sanitizes, trims, and embeds terminal sessions using the asciinema ecosystem.

**Origin:** Built with reference guides ([`FORMAT.md`](skills/asciinema/FORMAT.md), [`EMBEDDING.md`](skills/asciinema/EMBEDDING.md), [`SELF-HOSTING.md`](skills/asciinema/SELF-HOSTING.md)) and zero-dependency Python helper scripts ([`sanitize-cast.py`](skills/asciinema/scripts/sanitize-cast.py) and [`trim-cast.py`](skills/asciinema/scripts/trim-cast.py)) to streamline preparing clean `.cast` recordings for documentation, slides, and web players.

**Intended Usage:** Activated when recording terminal demos, converting `.cast` files to animated GIF (`agg`) or SVG (`svg-term`), stripping `stdin` keystrokes and redacting secrets, trimming trailing `Ctrl+D` exit sequences with a clean final-frame hold, or embedding `asciinema-player` in web apps.

### [`bjm-voice`](skills/bjm-voice/SKILL.md)

Guides the agent in writing, editing, or reviewing blog posts, tutorials, articles, and social media updates in Brett Morgan's authentic writing voice.

**Origin:** Distilled from analysis of Brett's existing articles, technical write-ups, and social posts to capture recurring linguistic signatures, Australian English spelling, and conversational cadence.

**Intended Usage:** Activated when drafting, editing, or reviewing blog posts, tutorials, articles, or social media updates that should sound like Brett.

### [`crop-image`](skills/crop-image/SKILL.md)

Crops, trims, and adjusts image framing by removing transparent whitespace margins, trimming solid color borders, or extracting specific pixel bounding boxes.

**Origin:** Built around a zero-dependency Python 3 utility ([`crop.py`](skills/crop-image/scripts/crop.py)) that decodes and re-encodes PNGs using only the Python standard library (with automatic fallback to Pillow for JPEG/WebP) to inspect subject bounding boxes and perform lossless crops.

**Intended Usage:** Activated when inspecting image dimensions and subject margins, autocropping transparent or solid-color borders with configurable padding, or cropping images to exact pixel coordinates.

### [`slidev-deck`](skills/slidev-deck/SKILL.md)

Scaffolds, authors, styles, previews, and deploys dark-theme [Slidev](https://sli.dev/) presentation decks (`slides/`) with modular act files, custom Vue layouts, and embedded `asciinema-player` terminal recordings.

**Origin:** Extracted from building technical presentation decks combining modular Slidev acts, high-contrast Tokyo Night / Dracula terminal themes, SSR-safe `AsciinemaPlayer.vue` wrappers with `BASE_URL` asset resolution, custom zoom-in and visual callout layouts, background dev-server management ([`slides-server.sh`](skills/slidev-deck/scripts/slides-server.sh)), and GitHub Pages CI deployment.

**Intended Usage:** Activated when creating a new Slidev deck, authoring or refactoring slides and conversational presenter notes, embedding `.cast` terminal recordings or visual callouts, running the local Slidev dev server, or configuring GitHub Pages deployment.

### [`teach-code`](skills/teach-code/SKILL.md)

An interactive, stateful code-teaching workflow that builds self-contained HTML lessons (compiled from Markdown via `build.py`), printable reference sheets, learning records, and runnable per-lesson companion projects in `apps/` verified with automated tests and linters.

**Origin:** Derived from Matt Pocock's original [`teach` skill](https://www.aihero.dev/skills-teach) and refined across multiple hands-on technical courses to incorporate Tufte-inspired dark/print typography, Prism.js `keep-markup` fill-in-the-blank exercises, Mermaid.js diagrams, equal-length retrieval quizzes, block-by-block code walkthroughs, and automated verification gates.

**Intended Usage:** Invoke with `/teach-code` (or ask the agent to teach a programming language, framework, or engineering tool) to establish a `MISSION.md`, curate `RESOURCES.md`, and progressively build interactive lessons backed by verified, runnable code.

## Skill Packs

Skill packs live under [`packs/`](packs/) so they are excluded from default `npx skills add domesticmouse/skills` installs, while remaining installable as a group via subpath.

### [`packs/egui`](packs/egui) — Engine-First Rust & `egui` Application Pack

A cohesive set of 5 skills for architecting, building, driving, and verifying multi-crate Rust + `egui`/`eframe`/`wgpu` applications across native desktop, headless CLI/MCP, and WebAssembly targets:

```bash
npx skills add domesticmouse/skills/packs/egui
```

- **[`egui-app-architecture`](packs/egui/egui-app-architecture/SKILL.md):** Strict acyclic `L0`–`L7` workspace crate layering (`xtask/src/layers.rs`), UI containment at `L6+`, panic-free/unsafe-free Clippy gates, and Cargo profile tuning for responsive dev builds and size-optimized Wasm bundles.
- **[`egui-app-runner`](packs/egui/egui-app-runner/SKILL.md):** Running and debugging the native `eframe` desktop app, headless CLI, offscreen `egui` visual snapshots, authenticated loopback TCP control channel (`--control`), headless/bridged MCP servers, and Trunk Wasm builds.
- **[`egui-command-engine`](packs/egui/egui-command-engine/SKILL.md):** Three-tier command taxonomy (Engine `CommandSpec`s, Shell/Tool UI commands, and CLI/JSON-RPC/MCP/TCP transports), declarative menu wiring, schema-driven `egui` dialogs, and adversarial input validation.
- **[`egui-cow-document-model`](packs/egui/egui-cow-document-model/SKILL.md):** Pure serializable `L1` domain models, sparse `Arc` copy-on-write chunk/tile storage with fallible allocation, zero-copy snapshot undo/redo history with selection target restoration, and compile-time complete content-addressed persistence (`blake3` + Zstandard).
- **[`egui-testing-infrastructure`](packs/egui/egui-testing-infrastructure/SKILL.md):** 7-tier verification architecture covering `cargo-mutants` mutation testing, `egui_kittest` headless UI harnesses, GPU test serialization (`gpu_lock`), pinned real-file corpus oracles, `panic_hunt` command fuzzing, performance budgets (`xtask perf`), and self-auditing scorecards (`xtask scorecard`).

### [`packs/hardware`](packs/hardware) — Embedded & Hardware Development Pack

Skills for electronic circuit design, PCB/PCBA workflows, Eurorack front panels, embedded systems, RTOS development, and board bring-up:

```bash
npx skills add domesticmouse/skills/packs/hardware
```

> **Recommended Companion Skills:** Pair this pack with [`aklofas/kicad-happy`](https://github.com/aklofas/kicad-happy) (`npx skills add aklofas/kicad-happy`) for comprehensive KiCad schematic/PCB/Gerber analysis, footprint/symbol inspection, and fabrication verification.

- **[`eurorack-panel`](packs/hardware/eurorack-panel/SKILL.md):** Design, inspect, and generate mated Doepfer A-100 3U Eurorack front panels in KiCad (`.kicad_pcb`) from a main circuit PCB ([`generate_eurorack_panel.py`](packs/hardware/eurorack-panel/scripts/generate_eurorack_panel.py)), including footprint-to-bushing mechanical offset compensation, M3 mounting slots, silkscreen callouts, grounded `F.Cu`/`B.Cu` copper shield planes, DRC checks, and Gerber/Excellon drill exports.
- **[`nuttx-architecture`](packs/hardware/nuttx-architecture/SKILL.md):** Architectural guide and development workflows for the Apache NuttX RTOS (`nuttx`) and user-space application suite (`apps`) repositories, including board porting (Renesas RA4M1 targets), device drivers, kernel subsystems, and NuttShell (`nsh`) applications.
- **[`skidl`](packs/hardware/skidl/SKILL.md):** Circuit design in Python with SKiDL for generating KiCad netlists (`.net`), PCBs, XML BOMs, hierarchical subcircuits, Electrical Rules Checking (`ERC`), and live-verified JLCPCB/LCSC PCBA BOM CSVs ([`jlcpcb_search.py`](packs/hardware/skidl/scripts/jlcpcb_search.py)).

## Repository Structure

Default skills live under `skills/`, and optional skill groups live under `packs/<pack-name>/`:

```text
├── skills/
│   └── <skill-name>/
│       ├── SKILL.md        # Required: YAML frontmatter (name, description) + instructions
│       ├── references/     # Optional: additional documentation loaded on demand
│       ├── scripts/        # Optional: helper scripts and utilities
│       └── resources/      # Optional: templates, components, and static assets
└── packs/
    └── <pack-name>/
        └── <skill-name>/
            ├── SKILL.md
            ├── references/
            └── scripts/
```

## License

See [LICENSE](LICENSE) for details.

## Disclaimer

This is not an officially supported Google product.

