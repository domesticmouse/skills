# Skills

A collection of AI agent skills by [@domesticmouse](https://github.com/domesticmouse), compatible with [skills.sh](https://skills.sh).

## Installation

Install all skills or pick interactively:

```bash
npx skills add domesticmouse/skills
```

Install a specific skill:

```bash
npx skills add domesticmouse/skills --skill <skill-name>
```

## Available Skills

### [`agy-brain-explorer`](skills/agy-brain-explorer/SKILL.md)

Discovers, lists, inspects, compares, audits, exports, and safely deletes Google Antigravity session trajectories, transcripts, disk paths, tool invocations, and execution steps across all brain storage directories under `~/.gemini`.

**Origin:** Built around a zero-setup [`uv`](https://docs.astral.sh/uv/) Python CLI script ([`agy-brain-explorer.py`](skills/agy-brain-explorer/scripts/agy-brain-explorer.py)) to make navigating local Antigravity `transcript.jsonl` and `transcript_full.jsonl` session logs fast and readable directly inside chat via GitHub Flavored Markdown tables and clickable `conversation://` and `file://` links.

**Intended Usage:** Ask the agent to list recent sessions, group or search sessions by project or prompt keyword, inspect step timelines and tool calls, export per-conversation Markdown logs (e.g., into a `prompts/` folder), compare two sessions side-by-side, or clean up old sessions (moving them to the macOS Trash by default).

### [`bjm-voice`](skills/bjm-voice/SKILL.md)

Guides the agent in writing, editing, or reviewing blog posts, tutorials, articles, and social media updates in Brett Morgan's authentic writing voice.

**Origin:** Distilled from analysis of Brett's existing articles, technical write-ups, and social posts to capture recurring linguistic signatures, Australian English spelling, and conversational cadence.

**Intended Usage:** Explicitly invoke with `/bjm-voice` (or ask the agent to use `bjm-voice`) when drafting, editing, or reviewing a Medium post, LinkedIn update, or article that should sound like Brett. Configured as opt-in only so it won't bleed into everyday documentation, READMEs, or general writing tasks uninvited.

### [`nuttx-architecture`](skills/nuttx-architecture/SKILL.md)

Architectural guide and development workflows for the Apache NuttX RTOS (`nuttx`) and user-space application suite (`apps`) repositories.

**Origin:** Distilled from porting boards (including Renesas RA4M1 targets like the Seeed Studio XIAO RA4M1, Arduino UNO R4 Minima, and Arduino Nano R4), drivers, and user-space applications in Apache NuttX.

**Intended Usage:** Automatically activated when navigating, configuring, building, debugging, or adding device drivers, board support packages, kernel features, or NuttShell (`nsh`) applications in a NuttX workspace.

### [`teach-code`](skills/teach-code/SKILL.md)

An interactive, stateful code-teaching workflow that builds self-contained HTML lessons (compiled from Markdown via `build.py`), printable reference sheets, learning records, and runnable per-lesson companion projects in `apps/` verified with automated tests and linters.

**Origin:** Derived from Matt Pocock's original [`teach` skill](https://www.aihero.dev/skills-teach) and refined across multiple hands-on technical courses to incorporate Tufte-inspired dark/print typography, Prism.js `keep-markup` fill-in-the-blank exercises, Mermaid.js diagrams, equal-length retrieval quizzes, block-by-block code walkthroughs, and automated verification gates.

**Intended Usage:** Invoke with `/teach-code` (or ask the agent to teach a programming language, framework, or engineering tool) to establish a `MISSION.md`, curate `RESOURCES.md`, and progressively build interactive lessons backed by verified, runnable code.

## Repository Structure

Each skill lives in its own directory under `skills/`:

```text
skills/
└── <skill-name>/
    ├── SKILL.md        # Required: YAML frontmatter (name, description) + instructions
    ├── references/     # Optional: additional documentation loaded on demand
    ├── scripts/        # Optional: helper scripts and utilities
    └── assets/         # Optional: templates and static resources
```

## License

See [LICENSE](LICENSE) for details.

## Disclaimer

This is not an officially supported Google product.

