---
name: asciinema
description: Record, replay, convert, sanitize, trim, tighten paste/input delays, and manage chapter markers ("m" stop points) in terminal sessions. Use when recording terminal demos, converting .cast files to animated GIF or SVG, embedding asciinema-player in web apps, sanitizing terminal recordings, inspecting cast durations, shortening cut-and-paste or prompt pauses, trimming trailing exit sequences, or adding/moving/inspecting chapter stop-point markers.
---

# Asciinema

Tools and procedures to record, replay, export, sanitize, trim, and manage chapter stop points in terminal sessions using the asciinema ecosystem.

## Workflows

Identify the user's objective and choose the matching workflow:

1. [Record a Terminal Session](#1-record-a-terminal-session)
2. [Replay or Inspect a Recording](#2-replay-or-inspect-a-recording)
3. [Convert and Export (GIF / SVG / Text)](#3-convert-and-export)
4. [Sanitize and Redact Sensitive Data](#4-sanitize-and-redact-sensitive-data)
5. [Trim Exit Sequences and Inspect Timing](#5-trim-exit-sequences-and-inspect-timing)
6. [Manage Chapter Markers (`"m"` Stop Points)](#6-manage-chapter-markers-m-stop-points)
7. [Embed in Web Applications](#7-embed-in-web-applications)
8. [Self-Host an asciinema Server](#8-self-host-an-asciinema-server)

---

### 1. Record a Terminal Session

Launch an intercepted PTY session using `asciinema rec`:

```bash
# Basic interactive recording
asciinema rec session.cast

# Record with idle-time cap (recommended: 2.0s) and non-interactive overwrite
asciinema rec -i 2.0 --overwrite session.cast

# Record a specific command and exit immediately upon completion
asciinema rec -c "pnpm test" -i 2.0 test-run.cast

# Headless recording in CI/automation with fixed dimensions
asciinema rec --headless --window-size 100x30 -c "./build.sh" build.cast
```

#### Core Flags & Rules:
- **`-i, --idle-time-limit <sec>`**: Limits pauses between terminal events. Always specify this for tutorials and documentation (recommended: `1.5` to `2.0`).
- **`-c, --command <cmd>`**: Executes a command directly and terminates recording when done.
- **`--overwrite`**: Overwrites the target file without an interactive confirmation prompt.
- **`--window-size <cols>x<rows>`**: Sets explicit terminal dimensions (e.g. `80x24`, `120x30`).
- **Security Guardrail**: Do **not** use `-I` or `--stdin` unless explicitly required. Capturing keyboard input logs raw keystrokes and can expose passwords, tokens, and credentials in plaintext.

#### Interactive Hotkeys During Recording:
- **`Ctrl+\`**: Pause and resume recording (acts like a microphone mute).
- **`Ctrl+x`**: Insert chapter marker (`"m"` event) at current timestamp.
- **`Ctrl+d`** or `exit`: Terminate session and save recording.

---

### 2. Replay or Inspect a Recording

#### Terminal Replay
```bash
# Replay local cast
asciinema play session.cast

# Accelerated playback (2x speed) with 1s max pause
asciinema play -s 2.0 -i 1.0 session.cast

# Pause automatically on markers (slide mode; required to observe "m" stop points in CLI playback)
asciinema play -m session.cast

# Accelerated marker-pause playback (2x speed, 1s idle cap)
asciinema play -m -s 2.0 -i 1.0 session.cast

# Loop continuously
asciinema play -l session.cast
```

**Playback Controls**: `Space` (pause/resume), `.` (step frame), `]` (next marker), `Ctrl+c` (quit).

#### Fast Inspection & Text Extraction
```bash
# Dump raw terminal stdout without timing pauses (pipeable)
asciinema cat session.cast | grep "ERROR"

# Convert cast to plain text (CLI 3.x)
asciinema convert session.cast output.txt -f txt

# Convert format between v3 and v2 (CLI 3.x)
asciinema convert session.v3.cast session.v2.cast -f asciicast-v2
```

For schema details on v1, v2, and v3 files, see [FORMAT.md](FORMAT.md).

---

### 3. Convert and Export

#### A. Compile to Animated GIF (`agg`)
Use `agg` (asciinema GIF generator) for high-quality, lightweight GIFs:

```bash
# Compact, web-ready documentation GIF
agg --theme monokai --fps-cap 15 --speed 1.5 --idle-time-limit 2 session.cast demo.gif
```

**Optimization options**:
- `--theme <name>`: `dracula` (default), `monokai`, `solarized-dark`, `solarized-light`, `gruvbox-dark`, `nord`, `github-dark`, `github-light`.
- `--fps-cap <num>`: Cap FPS to `15` or `12` to drastically reduce file size.
- `--font-size <px>`: Default `14`.
- `--last-frame-duration <sec>`: Pause on final frame before loop (default `3.0`).

#### B. Vector / SVG Export
- **Self-contained animated SVG** (`svg-term` only parses `asciicast v1`/`v2`, so `asciinema` 3.x recordings must be converted to `asciicast-v2` first):
  ```bash
  # asciinema 3.x (v3 default): convert to v2 on stdout and pipe to svg-term
  asciinema convert -f asciicast-v2 session.cast - | svg-term --out demo.svg --window --width 80 --height 24

  # If session.cast is already asciicast v2:
  cat session.cast | svg-term --out demo.svg --window --width 80 --height 24
  ```
- **asciinema.org SVG Badge** (Safe for GitHub READMEs):
  ```markdown
  [![asciicast](https://asciinema.org/a/<id>.svg)](https://asciinema.org/a/<id>)
  ```

---

### 4. Sanitize and Redact Sensitive Data

Before publishing or sharing `.cast` files, strip secrets and credential keystrokes:

1. **Verify stdin is stripped**: Default recordings do not capture keystrokes, but if `-I`/`--stdin` was used, `"i"` events must be deleted.
2. **Scrub Environment Metadata**: Verify `env` in header line 1 contains only safe values (`TERM`, `SHELL`).
3. **Strip Linux/systemd OSC Metadata**: `sanitize-cast.py` strips Linux/systemd `OSC 3008` (`machineid`, `bootid`, `user`, `hostname`, `cwd`) and `OSC 7` escape sequences from `"o"` stdout events by default (pass `--keep-osc` to preserve them).
4. **Redact Output Patterns**: Replace API keys, tokens, or internal URLs in `"o"` events.

Use the bundled utility script [scripts/sanitize-cast.py](scripts/sanitize-cast.py):

```bash
# Strip stdin events and clean environment metadata
python3 .agents/skills/asciinema/scripts/sanitize-cast.py session.cast sanitized.cast

# Strip stdin and redact custom sensitive patterns
python3 .agents/skills/asciinema/scripts/sanitize-cast.py session.cast sanitized.cast \
  --redact "ghp_123456=REDACTED" "internal.corp=example.com"
```

Quick regex redaction with `sed`:
```bash
sed -E 's/(ghp_[a-zA-Z0-9]{36}|AKIA[0-9A-Z]{16})/REDACTED/g' session.cast > sanitized.cast
```

---

### 5. Trim Exit Sequences and Inspect Timing

Interactive recordings frequently capture trailing `Ctrl+D` keystrokes, warning prompts (e.g. `press ctrl+d again to exit`), resume text, or dropping back into the shell prompt before session termination.

Use the bundled utility script [scripts/trim-cast.py](scripts/trim-cast.py):

#### A. Inspect Durations and Detect Exit Sequences
Inspect recording duration (both raw elapsed time and `idle_time_limit` playback time) and auto-detect trailing exit prompts without modifying the file:

```bash
# Print timing analysis and trailing pattern detection
python3 .agents/skills/asciinema/scripts/trim-cast.py session.cast --info
```

#### B. Strip Exit Sequences and Hold Final Frame
Cut off the trailing exit sequence and append a clean exit event (`"x"`) holding on the final frame (default: 3.0s pause before exit) so that video exports and looping web players don't immediately restart:

```bash
# Trim in place with default 3.0s final frame hold
python3 .agents/skills/asciinema/scripts/trim-cast.py session.cast --in-place

# Trim and write to a new file with custom 2.0s hold
python3 .agents/skills/asciinema/scripts/trim-cast.py session.cast trimmed.cast --hold 2.0

# Trim at an explicit pattern or regex
python3 .agents/skills/asciinema/scripts/trim-cast.py session.cast --in-place --cut-at "press ctrl+d"

# Trim and convert asciicast v3 -> v2 for asciinema-player <3.10 web compatibility
python3 .agents/skills/asciinema/scripts/trim-cast.py session.cast --in-place --to-v2
```

- **Checkable Completion Criterion**: Run `python3 .agents/skills/asciinema/scripts/trim-cast.py <file> --info`. Confirm that no trailing exit sequence is detected and duration matches the expected trimmed time.

---

### 6. Manage Chapter Markers (`"m"` Stop Points)

Use the bundled utility script [scripts/mark-cast.py](scripts/mark-cast.py) to list, search, inspect, add, move/replace, or remove `"m"` chapter markers in `asciicast` v2 and v3 files, and optionally re-embed updated `.cast` files into standalone HTML players.

#### A. List Markers & Adaptive Segment Timings
```bash
python3 .agents/skills/asciinema/scripts/mark-cast.py session.cast --list
```
Prints every `"m"` event with its 1-based `[N]` index, 0-based event `#idx`, `raw` elapsed time, `1x` idle-capped time, adaptive segment speed (`>= 2x`, `<= 30s` per segment), and cumulative `warped` time.

#### B. Search Output & Inspect Event Boundaries
Before placing or moving a stop point, locate the exact stdout (`"o"`) event index. Both `--search` and `--inspect` annotate stdout events with diagnostic tags so shell paste/redraw phases are visible at a glance:
- **`[REV]`**: Bracketed-paste echo in reverse video (`\x1b[7m...\x1b[27m` in `bash`, `\x1b[7m...` in `zsh`).
- **`[UNREV]`**: `Enter` key redraw that strips reverse video (`\x08+...<cmd>\r\n\x1b[?2004l` in `bash` Readline; `\x1b[A...\x1b[27m...\x1b[1B\r\x1b[K` in `zsh`).
- **`[OSC]`**: Prompt/pre-exec OSC metadata (`\x1b]0;`, `\x1b]2;`, `\x1b]7;`, and Linux systemd `\x1b]3008;`).

```bash
# Search stdout for a pattern and show 2 surrounding events before/after each match
python3 .agents/skills/asciinema/scripts/mark-cast.py session.cast --search "flutter create" --context 2

# Inspect a specific event range (e.g. events #0..#25) with dt, raw, 1x, code, tags, and ANSI-stripped text
python3 .agents/skills/asciinema/scripts/mark-cast.py session.cast --inspect 0:25
```

#### C. Placement Rules: Command-Entry Hold vs. Command-Completion Hold vs. Two-Stop Prompt/Question Hold
Always place `"m"` markers (`[0.0, "m", "<label>"]` in v3, `[abs_time, "m", "<label>"]` in v2) **immediately after** the `"o"` stdout event that finishes drawing the target frame (default behavior of `mark-cast.py`):
- **Command-Entry Hold (pause after a shell command or TUI launcher is typed/pasted and reverse video is cleared, with the cursor still on the command line, *before* command output or TUI startup)**: Match the command text itself (e.g. `flutter create --platforms=ios my_app`, `git init && git add . && git commit -m "Initial scaffold"`, or `agy`—not the post-launch `Antigravity CLI` welcome banner). With bracketed paste (`\x1b[?2004h`), pasting and running a command emits `[REV]` (reverse-video paste: `\x1b[7m...\x1b[27m` in `bash`, `\x1b[7m...` in `zsh`) → `[UNREV]` (`Enter` redraw clearing reverse video: `\x08+...<cmd>\r\n\x1b[?2004l\r...` in `bash` Readline, or `\x1b[A...\x1b[27m...` plus `\x1b[1B\r\x1b[K` in `zsh`) → `[OSC]` (`3008`/`2` shell/command metadata). By default, `mark-cast.py` advances from `[REV]` to `[UNREV]` and splits trailing `\r\n\x1b[?2004l\r...` (`bash`) or `\x1b[1B\r\x1b[K` (`zsh`) into a post-marker `"o"` event (`dt=0.02s`). Giving the split post-marker `"o"` event a positive `dt` (`0.02s`) ensures its `asciicast-v2` timestamp is strictly greater than the marker timestamp `T_m`, preventing `asciinema-player` (`pauseOnMarkers` or `player.seek(T_m)`) from executing the newline/cursor-down sequence while paused at the stop point (pass `--raw-match` only if you explicitly want the raw `[REV]` paste frame).
- **Command-Completion / `/clear` Hold (pause *after* a command or `/clear` finishes running)**: Match the final stdout frame of the command's output (e.g. `"All done!"`, `"root-commit.*Initial scaffold"`, or the fresh `Antigravity CLI` banner redraw after `/clear`).
- **Two-Stop Interactive Prompt / Question Hold (Before Typing + After Typing Before `Enter`)**:
  1. **Stop 1 — Before Typing (`Q: ...` / `Ready for ...`)**: Match the bottom status/footer of the TUI prompt frame (whether an `ask_user` selector widget with `enter Submit`/`enter Select` or a prose question ending with `? for shortcuts`), right before the first typed/pasted character of the user's response (`dt > 0`).
  2. **Stop 2 — After Typing, Before `Enter` (`Answer: ...` / `/command`)**: Match the final stdout frame that echoes the user's complete typed/pasted response or slash command in the input box, right before the `Enter` submission event (`\x1b[\d+D\x1b[K` input clear or `Thinking...`/`Generating...` spinner). Always verify that every "after typing" stop point has a matching "before typing" stop point preceding the typing sequence.
  - When a synchronized TUI redraw (`\x1b[?2026h`…`\x1b[?2026l`) spans multiple `dt = 0.0` PTY chunks, `mark-cast.py` automatically advances across consecutive `dt = 0.0` `"o"` events so the marker sits after the complete frame flush.

#### D. Move/Replace, Add, or Remove Markers, and Tighten Paste Delays
```bash
# Move/replace an existing marker (by 1-based number or label substring) to a command/pattern, @event:IDX, @time:SEC, or @1x:SEC
# (Automatically advances from [REV] bracketed-paste highlight to [UNREV] and splits trailing cursor-down so the cursor stays on the command line)
python3 .agents/skills/asciinema/scripts/mark-cast.py session.cast \
  --set 1 "flutter create --platforms=ios my_app" "1. Create Project" \
  --set 2 'git init && git add . && git commit -m "Initial scaffold"' "2. Initial Git Commit" \
  --set 3 "agy" "3. Launch agy" \
  --in-place

python3 .agents/skills/asciinema/scripts/mark-cast.py session.cast \
  --set "Create Project" "@event:11" "1. Create Project" --in-place

# Add a new marker right after a stdout pattern (use pattern#2 for 2nd occurrence)
python3 .agents/skills/asciinema/scripts/mark-cast.py session.cast \
  --add-pattern "> please fix" "11. Apply Review Fixes" --in-place

# Auto-inject a batch of markers from a JSON specification file
python3 .agents/skills/asciinema/scripts/mark-cast.py session.cast \
  --auto-spec markers.json --in-place

# Remove a specific marker by number or label substring
python3 .agents/skills/asciinema/scripts/mark-cast.py session.cast --remove 1 --in-place

# Automatically tighten cut-and-paste delays ([REV]/prompt paste -> 1.0s, [UNREV] Enter -> 0.15s, prompt submit -> 0.20s)
python3 .agents/skills/asciinema/scripts/mark-cast.py session.cast \
  --tighten-pastes --in-place --embed-html player.html

# Set the relative delay (dt) of specific event indices directly (shifts subsequent timestamps automatically in v2)
python3 .agents/skills/asciinema/scripts/mark-cast.py session.cast \
  --set-dt 7 1.0 --set-dt 8 0.15 --in-place --embed-html player.html

# Update markers AND sync gzip+base64 EMBEDDED_CAST_GZ_B64 in a standalone HTML player in one step
python3 .agents/skills/asciinema/scripts/mark-cast.py session.cast \
  --set 1 "flutter create --platforms=ios my_app" "1. Create Project" \
  --set 2 'git init && git add . && git commit -m "Initial scaffold"' "2. Initial Git Commit" \
  --set 3 "agy" "3. Launch agy" \
  --in-place --embed-html player.html
```

- **Checkable Completion Criterion**: Run `python3 .agents/skills/asciinema/scripts/mark-cast.py <file> --list` and `--inspect <idx>` around modified markers to confirm every command-entry marker sits immediately after `[UNREV]` (reverse video cleared, cursor on the same line as the command) and before the split `\r\n\x1b[?2004l...` (`bash`) or `\x1b[1B\r\x1b[K` (`zsh`) newline/cursor-down and command output frames.
- **Standalone HTML Cast Players (`*-cast-player.html`)**: When editing, reviewing, or scaffolding standalone HTML cast-player harnesses, read [`../cast-player-html/SKILL.md`](../cast-player-html/SKILL.md).

---

### 7. Embed in Web Applications

Integrate interactive virtual terminal playback using `asciinema-player` v3 (WASM/Rust driven).

Consult [EMBEDDING.md](EMBEDDING.md) for complete copy-pasteable code examples:
- **Vanilla HTML / JS**: `AsciinemaPlayer.create(src, container, options)`
- **React / Next.js / Docusaurus**: SSR-safe dynamic import inside `useEffect`
- **Vue 3 / VitePress**: Client-only dynamic mount with Vite SSR exclusion
- **Hugo**: Reusable shortcode
- **asciinema.org Embeds**: Direct `<script>` widget or responsive `<iframe>`

---

### 8. Self-Host an asciinema Server

For private session repositories, air-gapped networks, or corporate compliance:
- Run `asciinema-server` via Docker Compose (Phoenix + PostgreSQL).
- Configure CLI clients with `export ASCIINEMA_SERVER_URL="https://asciinema.corp.internal"`.
- Run `asciinema auth` to link local CLI installations to private accounts.

Full Docker Compose configuration, environment variables, and bootstrap steps are documented in [SELF-HOSTING.md](SELF-HOSTING.md).
