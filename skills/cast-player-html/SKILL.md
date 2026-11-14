---
name: cast-player-html
description: >-
  Edit, scaffold, and manage standalone HTML asciinema cast-player files
  (*-cast-player.html) and their embedded gzip+base64 recordings
  (EMBEDDED_CAST_GZ_B64). Use whenever reviewing or editing a cast-player HTML
  file, adding, moving, removing, or relabeling stop points ("m" chapter
  markers) viewed in an HTML player, shortening cut-and-paste or prompt delays
  (dt), tuning adaptive segment speeds, updating chapter pills or HUD controls,
  or scaffolding a new cast-player HTML prototype for a terminal recording.
---

# Cast-Player HTML (`*-cast-player.html`)

Standalone HTML test-drive harnesses wrap `asciinema-player@3.9.0` inside a 16:9 Slidev `cast-full` stage with two-pass adaptive segment speed compilation (`>= 2x`, `<= 30s` per segment), interactive chapter stepper pills, a live speed HUD, and stage hotkeys (`p`, `[`, `]`).

## File Mapping & Single Source of Truth

Each HTML player embeds a gzipped, base64-encoded copy (`const EMBEDDED_CAST_GZ_B64 = "..."`) of its backing `.cast` file (e.g. in `recordings/final/<name>.cast`) so `file://` URLs load in any browser without CORS errors.

### Core Rules
1. **Treat the backing `.cast` file (e.g. `recordings/final/<name>.cast`) as the single source of truth** for terminal events and `"m"` stop points. Always mutate the `.cast` file first, re-embed `EMBEDDED_CAST_GZ_B64` using `.agents/skills/asciinema/scripts/mark-cast.py --embed-html <html-path>`, and (if working with a Slidev deck) sync `slides/public/casts/` via `npm --prefix slides run sync-casts` so both the standalone HTML player and the Slidev deck stay in sync.
2. **Skip the `EMBEDDED_CAST_GZ_B64` line when reading populated HTML players**: Line ~454 is a single-line base64 string that can exceed the 46 KB `read_file` byte cap when a large recording is embedded. Read the HTML in two ranges around it:
   - Header, CSS, and DOM layout: `StartLine: 1, EndLine: 453`
   - JS compiler, chapter pills, and event handlers: `StartLine: 455`

---

## Workflows

1. [Add, Move, Remove, or Rename Stop Points](#1-add-move-remove-or-rename-stop-points-and-tighten-paste-delays)
2. [Edit HTML/CSS/JS Player Controls or Adaptive Speed Logic](#2-edit-htmlcssjs-player-controls-or-adaptive-speed-logic)
3. [Scaffold a New Cast-Player HTML File](#3-scaffold-a-new-cast-player-html-file)

---

### 1. Add, Move, Remove, or Rename Stop Points (and Tighten Paste Delays)

When the user reviews a `*-cast-player.html` file and asks to add, move, delete, or rename a stop point, or shorten cut-and-paste / input pauses:

#### Step 1: Inspect Current Markers and Target Events
List current markers and search the backing `.cast` file:

```bash
# List existing markers, event indices, 1x times, and adaptive segment speeds
python3 .agents/skills/asciinema/scripts/mark-cast.py recordings/final/session.cast --list

# Search stdout events for the target text with surrounding context
python3 .agents/skills/asciinema/scripts/mark-cast.py recordings/final/session.cast \
  --search "target command or prompt" --context 8

# Inspect exact event boundaries around a candidate index
python3 .agents/skills/asciinema/scripts/mark-cast.py recordings/final/session.cast --inspect 70:85
```

#### Step 2: Apply the Matching Stop-Point Placement Rule
Place every `"m"` marker **immediately after** the `"o"` stdout event that completes the target visual frame:

- **A. Shell Command / TUI Launcher Entry (`flutter create...`, `git init...`, `agy`)**:
  Match the command text itself. With bracketed paste, `mark-cast.py` handles both `bash` (GNU Readline `\x08+...` redraw and `\r\n\x1b[?2004l\r...` split) and `zsh` (`[REV]` `\x1b[7m` highlight -> `[UNREV]` `\x1b[27m` Enter redraw and `\x1b[1B\r\x1b[K` cursor-down split), placing the trailing newline/cursor-down into a post-marker `"o"` event (`dt=0.02s`) so the cursor stays on the command line while paused.
- **B. Two-Stop Pattern for Questions, Typed Prompts, and Slash Commands**:
  Use **two paired stop points** for each question/answer or prompt entry so the presenter can pause on the prompt/question first, step once to reveal the typed response, and step again to submit it:
  1. **Before Typing (`Q: ...` / `Ready for ...`)**: Place immediately after the stdout frame that finishes rendering the question (whether an interactive `ask_user` widget with `enter Select`/`enter Submit` or a prose question ending at `? for shortcuts`) or empty input box, right before the first keystroke/paste event of the user's answer.
  2. **After Typing, Before `Enter` (`Answer: ...` / `/command`)**: Place immediately after the stdout frame that finishes echoing the typed/pasted answer or slash command in the input box, right before the `Enter` submission event (`dt` pause followed by input-box clear `\x1b[\d+D\x1b[K`, `Thinking...`, `Generating...`, or autocomplete dismissal).
  - **Audit for Unpaired Stops**: Verify every "after typing" stop point has a matching "before typing" stop point immediately before the typing sequence begins (especially prose questions that don't render an `ask_user` selector widget).
- **C. `/clear` Calls (Before `Enter` + Session Cleared)**:
  Place a stop point after `/clear` is typed in the input box (before pressing `Enter`), and a second stop point (`Session Cleared`) immediately after `/clear` finishes redrawing the fresh CLI banner and empty prompt box. When `/clear` is followed immediately by another typed slash command, the `Session Cleared` stop point also serves as the "before typing" stop point for that next command.
- **D. Synchronized TUI Frame Flushes**:
  When the TUI writes a synchronized frame (`\x1b[?2026h`…`\x1b[?2026l`) across multiple `dt = 0.0` PTY chunks, `mark-cast.py` automatically advances past trailing `dt = 0.0` `"o"` chunks so the marker sits after the complete frame flush.

#### Step 3: Update the `.cast` File, Relabel Sequentially, and Sync the HTML Player & Slidev Deck
Keep chapter labels numbered sequentially (`1. ...`, `2. ...`, ..., `N. ...`), sync `EMBEDDED_CAST_GZ_B64` into the HTML file, and sync `slides/public/casts/` (if applicable):

```bash
# 1. Insert, move, or remove the stop point in the backing .cast file
python3 .agents/skills/asciinema/scripts/mark-cast.py recordings/final/session.cast \
  --add-pattern "initial prompt text" "3. Initial Prompt" \
  --in-place

# 2. Relabel markers sequentially (1..N) and re-embed gzip+base64 into the HTML player
python3 .agents/skills/asciinema/scripts/mark-cast.py recordings/final/session.cast \
  --relabel \
    "1. Create Project" \
    "2. Launch agy" \
    "3. Initial Prompt" \
    "4. Q1: Clarifying Question" \
    "5. Q1: Options Selected" \
    "6. Build Complete" \
  --in-place \
  --embed-html prototypes/session-cast-player.html

# 3. Sync recordings/final/*.cast into slides/public/casts/ (when paired with Slidev)
npm --prefix slides run sync-casts
```

If you maintain a JSON marker specification file for `--auto-spec <json_file>`, update it when the canonical marker list changes.

#### Step 4: Tighten Cut-and-Paste or Specific Event Delays (`dt`)
Because `asciicast-v3` uses relative event deltas (`dt`) and `prepareCastForPlayer()` dynamically compiles cumulative `asciicast-v2` timestamps and segment speeds, shortening `dt` on individual events never desynchronizes markers.

Default target delays (`--tighten-pastes`):
- **`1.0s` (`0.5s` at `2x` playback)**: Pre-paste wait before `[REV]` shell pastes, `agy` startup banner settle, `agy` pasted/typed prompt starts, and `/clear` execution.
- **`0.15s`**: `[REV]` → `[UNREV]` reverse-video highlight redraw when pressing `Enter` on a pasted shell command.
- **`0.20s`**: Post-marker input-box clear/submit pause (`\x1b[\d+D\x1b[K`) when resuming from an `agy` prompt stop point.

```bash
# Automatically tighten all [REV] shell paste delays (1.0s), [UNREV] Enter redraws (0.15s), and agy prompt paste/submit pauses (0.20s)
python3 .agents/skills/asciinema/scripts/mark-cast.py recordings/final/session.cast \
  --tighten-pastes \
  --in-place \
  --embed-html prototypes/session-cast-player.html

# Or set the relative dt of specific event indices directly
python3 .agents/skills/asciinema/scripts/mark-cast.py recordings/final/session.cast \
  --set-dt 7 1.0 \
  --set-dt 8 0.15 \
  --in-place \
  --embed-html prototypes/session-cast-player.html
```

- **Completion Criterion**: Run `mark-cast.py <cast> --list` and `--inspect <idx-3>:<idx+3>` around the modified marker or event. Confirm markers are numbered `1..N` in chronological order, the marker sits immediately after the target stdout frame and before any newline/clear/spinner event, target event `dt` values reflect the tightened delays, and `mark-cast.py` printed `Updated EMBEDDED_CAST_GZ_B64 in <html-path>`.

---

### 2. Edit HTML/CSS/JS Player Controls or Adaptive Speed Logic

1. Read the HTML file while skipping the `EMBEDDED_CAST_GZ_B64` line (~line 454):
   - Lines `1..453`: CSS variables, `.slidev-frame` (16:9 container), `.slide-header`, `.chapter-pills`, `#player-container`, `.speed-hud-pill`, and `.slide-footer`.
   - Lines `455..end`:
     - `prepareCastForPlayer(castText, idleTimeLimitOverride, minSpeed, maxSegmentSec)`: Two-pass compiler that splits events at `"m"` markers, omits trailing `"x"` exit-hold events (so playback reaches `ended` immediately when the final `"o"` frame renders rather than stalling for 3s of dead air), calculates `segSpeed = max(minSpeed, ceil(segCappedDur / maxSegmentSec))`, and emits warped `asciicast-v2` timestamps. Always snap `endTime = Number(warpedAbs.toFixed(6))`, `warpedAbs = endTime`, `v2Header.duration = warpedAbs`, and `ch.playTime = markerTime` so `player.seek(ch.playTime)` and `player.seek(tailSeg.endTime)` never fall short of 6-decimal rounded `"o"` event timestamps when `.toFixed(6)` rounds up.
     - `renderChapterPills(hitIdx)`: Renders `↺ 0. Start` (`idx = -1`), numbered chapter pills (`idx = 0..chapters.length - 1`) with speed badges, and an interactive `→ End` stop-point button (`idx = chapters.length`). **High Stop-Point Count Layout**: When a cast has dozens of stop points (e.g. 50+ markers), you can omit `<div class="chapter-pills" id="chapter-pills"></div>` from the DOM; `renderChapterPills()` checks `if (!container) return;` so the pill grid does not push `#player-container` off-screen inside the 16:9 `.slidev-frame`.
     - `jumpToStart()`, `jumpToChapter(idx)`, `jumpToEnd()`, `applyEndState()`, `stepPrevChapter()`, `stepNextChapter()`, `togglePlay()`, and `syncLiveSpeedFromPlayer()`: Synchronize all five stop-point indicators (`#status-badge`, `#chapter-pills`, `#live-speed-badge`, `#speed-hud-pill`, and `#marker-detail`) across keyboard jumps (`[` / `]`), pill clicks, natural playback completion (`ended`, `pause` at end, and `t >= tailSeg.endTime - 0.02` in `syncLiveSpeedFromPlayer()`), and paused timeline-scrubber seeks (`lastPolledTime`). `stepPrevChapter()` steps from Stop Point 1 (`idx = 0`) to `0. Start` (`idx = -1`) and from `→ End` (`idx = chapters.length`) back to the final stop point (`idx = chapters.length - 1`); `stepNextChapter()` advances from the final stop point (`idx = chapters.length - 1`) to `→ End` (`idx = chapters.length`); `togglePlay()` replays from `0:00` (`↺ Replay`) when invoked at `→ End`.
     - `initPlayer()`: Mounts `AsciinemaPlayer.create({ data: v2Text }, container, { speed: 1, idleTimeLimit: 999999, ... })`, wires `play`, `pause`, `marker`, and `ended` events, and registers the `window` `keydown` listener in the **capture phase** (`true`) so `[` / `]` / `p` run before `asciinema-player`'s `.ap-wrapper` handler can swallow them when the terminal has focus.
2. Apply edits with `edit_file` targeting lines outside line 454.
3. If the change modifies shared UI/JS behavior, apply the same update to [`resources/cast-player-template.html`](resources/cast-player-template.html) and `.agents/skills/slidev-deck/resources/components/AsciinemaPlayer.vue` to keep all players consistent.

- **Completion Criterion**: Read back the edited line range to verify clean syntax, run `node --check` on the extracted `<script>` block, and confirm `const EMBEDDED_CAST_GZ_B64 = "H4sI...` remains intact.

---

### 3. Scaffold a New Cast-Player HTML File

To scaffold a new standalone HTML player for a `.cast` recording:

1. Copy the bundled template [`resources/cast-player-template.html`](resources/cast-player-template.html) to your target HTML path:
   ```bash
   cp .agents/skills/cast-player-html/resources/cast-player-template.html prototypes/my-session-cast-player.html
   ```
2. Edit the metadata strings in the new HTML file:
   - `<title>`: e.g. `Test Drive — my-session.cast (Slidev cast-full + Stop Points)`
   - `.top-title`: e.g. `recordings/final/my-session.cast · Adaptive Breakpoint Speeds`
   - `.slide-title`: e.g. `Session Title — Interactive Stop Points`
   - Comment above `EMBEDDED_CAST_GZ_B64`: reference the corresponding `.cast` file.
3. Embed the target `.cast` recording into the new HTML file:
   ```bash
   python3 .agents/skills/asciinema/scripts/mark-cast.py recordings/final/my-session.cast \
     --list \
     --embed-html prototypes/my-session-cast-player.html
   ```

- **Completion Criterion**: `mark-cast.py --list --embed-html` outputs `Updated EMBEDDED_CAST_GZ_B64 in <new-html-path>`, and reading lines `1..453` of the new HTML file confirms the updated titles and headers match the target recording.
