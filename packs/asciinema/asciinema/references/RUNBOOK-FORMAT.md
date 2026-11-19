# Operator Recording Runbook Format (`RUNSHEET.md` / `EXPERIMENT_RUNBOOK.md`)

Reference structure and templates for authoring repeatable `asciinema` recording runbooks that coordinate live terminal captures, Antigravity **Session Trajectory** correlation (`/agy-brain-explorer`), and `/asciinema` post-processing.

---

## 1. Choosing `RUNSHEET.md` vs. `EXPERIMENT_RUNBOOK.md`

| Document Type | When to Use | Extra Sections Included |
| :--- | :--- | :--- |
| **Presentation / Talk Runsheet (`RUNSHEET.md`)** | Multi-cast recording plan feeding a Slidev deck or demo talk (`TODO.md` + slide blueprint) | Slide Act / Slide ID manifest, paired **Before / After** `"m"` stop points, `npm run sync-casts`, `slides-server.sh` rehearsal, `[` / `]` / `p` stage hotkeys |
| **Comparative / Multi-Phase Experiment Runbook (`EXPERIMENT_RUNBOOK.md`)** | Head-to-head agent runs or multi-phase builds comparing baselines | Experimental design matrix, isolated workspace/submodule provisioning, stop criteria, off-screen artifact capture, standalone HTML player builds (`--embed-html`), and defect scorecards |

---

## 2. Core Design Rules

1. **Separate Raw from Final Captures**: Write unedited `asciinema rec` output to `recordings/raw/<name>.cast` and write sanitised, trimmed, and marked output to `recordings/final/<name>.cast`. Keep `recordings/raw/` immutable so every trim, paste-tighten, or mid-stream strip can be re-run cleanly.
2. **Enforce an Incremental `Record → Correlate → Post-Process → Verify` Gate**: Complete trace correlation, dead-take cleanup, `pyte` frame inspection, and chapter marking on recording `N` before starting recording `N+1`. Recording multi-part casts back-to-back mixes takes inside `~/.gemini/**/brain/` and hides TUI/prompt defects until late.
3. **Standardise Terminal Geometry & Capture Flags**: Always lock dimensions and idle capping across a runbook with:
   ```bash
   asciinema rec -i 2.0 --window-size 120x36 --overwrite recordings/raw/<name>.cast
   ```
   Omit `-I` / `--stdin` so raw keystrokes and credentials never enter the `.cast` stream.
4. **Reset Camera-Visible State Explicitly**: Before each recording, check and remove/reset any plugins, skills, or output directories that must be installed or created fresh on camera, and state the exact git commit anchor or clean worktree baseline.
5. **Preserve Multi-Exit Casts**: Whenever a recording exits `agy` mid-stream—either to relaunch a cold `agy` session (`way-3-agy-customizations.cast`) or to run final shell verification commands (`make test`, `git status -s`)—add an explicit `> [!WARNING]` noting that `trim-cast.py --info` will flag the mid-stream `press ctrl+d again to exit` sequence, and instruct the operator to trim only at the final exit via `--cut-index <FINAL_EXIT_IDX> --hold 3.0`.
6. **Copy Prompts Verbatim**: Quote every shell command, slash command, and agent prompt inside fenced code blocks exactly as defined in the source `TODO.md` or experiment spec, paired with **Before** (settled `? for shortcuts` frame with `dt > 1s` or clean shell prompt, skipping transient `Loading...` redraws) and **After** (`[UNREV]` normal-video command/prompt prior to `Enter` / output) stop points.

---

## 3. Runbook Section Templates

### Section 1 — Recording Manifest & Incremental Loop

```markdown
## 1. Recording Manifest & Incremental Workflow

Store unedited captures in `recordings/raw/` and post-processed outputs in `recordings/final/`.

| # | Recording (`recordings/raw/` → `recordings/final/`) | Act / Slide or Phase | Target Session Trajectory | `"m"` Stop Points | Status |
| :---: | :--- | :--- | :--- | :---: | :--- |
| 1 | `<name>.cast` | `<Act / Slide or Phase>` | `<Trajectory description>` | `<N>` (`m1`–`mN`) | Pending |

### Incremental `Record → Correlate → Post-Process → Verify` Loop

Complete all four steps after each recording before starting the next:
1. Correlate `recordings/raw/<name>.cast` (`timestamp` + `trim-cast.py --info`) against `~/.gemini/**/brain/` and Trash aborted takes.
2. Verify expected Skill Activations (e.g., `way_1_plugin`, `way_2_community`, `way_3_bespoke`) or build outputs.
3. Sanitise, trim, tighten pastes, place `"m"` markers, and verify with `pyte` (`--render`) into `recordings/final/<name>.cast`.
4. Fill in the recording's `Cast ↔ Trajectory Correlation` ledger.
```

---

### Section 2 — Phase 0: Pre-Flight Checklist & Post-Processing Pipeline

Include these four subsections:

1. **Toolchain & Repo Verification**:
   ```bash
   mkdir -p recordings/raw recordings/final
   asciinema --version
   agy --version
   npx --version
   uv --version
   python3 --version
   node --version
   git status -sb
   ```
   Add project-specific test/lint checks (e.g., `uv run ruff check src tests`, `uv run mypy src`, `uv run pytest -v`, or toolchain checks).
2. **Pre-Flight Checklist**: Checkable list covering terminal geometry (`120x36` Ghostty), CLI versions, `.agents/skills/asciinema/scripts/` availability + `uv run --with pyte`, git commit anchors, and workspace isolation / state resets.
3. **`asciinema rec` Guardrails & Live Hotkeys**:
   - Required flags: `-i 2.0 --window-size 120x36 --overwrite` (no `-I` / `--stdin`).
   - Controls: `Ctrl+\` pause/resume, `Ctrl+x` live marker, `Ctrl+D` twice inside `agy` + `Ctrl+D` / `exit` in shell.
4. **Standard 6-Step Post-Processing Pipeline**:
   ```bash
   # 1. Sanitise OSC sequences & drop stdin events (preserves #0000..#NNNN indices)
   python3 .agents/skills/asciinema/scripts/sanitize-cast.py \
     recordings/raw/<name>.cast recordings/final/<name>.cast

   # 2. Inspect durations & trailing exit sequences (use --cut-index <IDX> --hold 3.0 for multi-exit casts)
   python3 .agents/skills/asciinema/scripts/trim-cast.py recordings/final/<name>.cast --info
   python3 .agents/skills/asciinema/scripts/trim-cast.py recordings/final/<name>.cast --in-place

   # 3. Search & inspect [REV] / [UNREV] / [OSC] event boundaries
   python3 .agents/skills/asciinema/scripts/mark-cast.py recordings/final/<name>.cast --search "<pattern>" --context 2
   python3 .agents/skills/asciinema/scripts/mark-cast.py recordings/final/<name>.cast --inspect <START>:<END>

   # 4. Verify 2D screen frames (and any mid-stream cuts) with pyte via uv
   uv run --with pyte python3 .agents/skills/asciinema/scripts/mark-cast.py \
     recordings/final/<name>.cast --render <EVENT_IDX>

   # 5. Tighten paste/typing delays & place Before/After "m" markers
   python3 .agents/skills/asciinema/scripts/mark-cast.py recordings/final/<name>.cast --tighten-pastes --in-place

   # 6. Verify sequential markers, adaptive segment speeds, and warped duration
   python3 .agents/skills/asciinema/scripts/mark-cast.py recordings/final/<name>.cast --list
   ```

---

### Section 3 — Per-Recording Runbook Entry Template

Repeat this block for every planned `.cast` file:

```markdown
### Recording K: `<name>.cast`

- **Act & Slide / Phase**: `<target>`
- **Target Trajectory**: `<name>`
- **Expected Skill Activations / Outputs**: `<tier: skills or artifacts>`
- **Stop Points**: `<N>` (`m1`–`mN`)

#### Pre-Step State Checks

- <Required git commit/branch, installed or uninstalled plugins/skills, clean directories>

#### Start Recording

```bash
asciinema rec -i 2.0 --window-size 120x36 --overwrite \
  recordings/raw/<name>.cast
```

#### Action Sequence & Copy-Pasteable Prompts

1. <Step with `(m1)` anchor>
2. <Paste command/prompt with `(m2)` anchor in a fenced code block>
...

#### Chapter Stop Points (`m1`–`mN`)

| Marker | Chapter Label | Terminal State at Marker |
| :--- | :--- | :--- |
| `m1` | `Before: ...` | <Settled empty prompt state> |
| `m2` | `After: ...` | `<Exact command or prompt text>` |

#### Post-Recording Verification Checklist

- [ ] `recordings/raw/<name>.cast` saved (`120x36`, `asciicast v3`, no `-I`/`--stdin`).
- [ ] Correlated with canonical session(s) in `~/.gemini/**/brain/`; aborted takes trashed.
- [ ] Expected **Skill Activations** / build artifacts verified.
- [ ] `recordings/final/<name>.cast` sanitised, trimmed, paste-tightened, `pyte`-rendered at `m1`–`mN`, and verified with `mark-cast.py --list`.

#### Cast ↔ Trajectory Correlation (Fill After Capture)

- **AGY Session(s)**: `<UUID>` (`<brain-root>`, `<model>`), active `<HH:MM:SS>`–`<HH:MM:SS>`, `<N>` steps, `<N>` tool calls, Skill Activations / `README.md` reads: `<summary>`.
- **Final Cast**: `<raw>` raw / `<1x>` 1x / `<warped>` warped (`m1` `#idx`, `m2` `#idx`, ...).
```

---

### Section 4 — Post-Recording Audit Prompt & Canonical Curation

Include a copy-pasteable `/agy-brain-explorer /asciinema` prompt tailored to the project so the operator runs one consistent audit after each recording:

```text
/agy-brain-explorer /asciinema I just finished capturing `recordings/raw/<name>.cast` in `<workspace-path>`. Before I move to the next recording:

1. Discover all `~/.gemini/**/brain/` Session Trajectories for `<project-name>`, read the `.cast` header `timestamp` and duration (`trim-cast.py --info`), and correlate `recordings/raw/<name>.cast` to the canonical parent + subagent trajectory IDs.
2. Flag any aborted takes or out-of-scope meta-planning sessions and ask confirmation before moving them to Trash via `agy-brain-explorer.py delete ... --force`.
3. Verify the expected Skill Activations (e.g., `way_1_plugin`, `way_2_community`, `way_3_bespoke`) or artifact/contract reads and print a concise telemetry summary for the `Cast ↔ Trajectory Correlation` ledger.
4. Sanitise (`sanitize-cast.py`), trim (`trim-cast.py`, preserving any intentional mid-recording exits with `--cut-index`), tighten pastes (`--tighten-pastes`), place `"m"` stop points (`mark-cast.py`), verify key frames with `uv run --with pyte ... --render`, and output `recordings/final/<name>.cast` plus `mark-cast.py --list`.
```

When a follow-up recording opens **Brain Explorer** or exports final traces, include the expected canonical dataset table and `agy-brain-explorer.py` cleanup commands before that recording.

---

### Section 5 — Player Sync & Stage Verification

- **For Slidev decks**: `npm --prefix slides run sync-casts`, start `.agents/skills/slidev-deck/scripts/slides-server.sh start`, check `showChapterBar: true` stepper pills and `[` / `]` / `p` stage hotkeys, reset `showChapterBar: false`, and run `npm --prefix slides run build`.
- **For standalone HTML players**: Pass `--embed-html prototypes/<name>-cast-player.html` to `mark-cast.py` and verify inline JS with `node --check`.
