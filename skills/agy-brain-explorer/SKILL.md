---
name: agy-brain-explorer
description: >-
  Discover, list, inspect, compare, audit, export, and safely delete Google Antigravity session trajectories,
  transcripts, disk paths, tool invocations, and execution steps across all brain storage
  directories under ~/.gemini. Use whenever asked to list recent/past sessions,
  review session histories, export per-conversation Markdown logs (e.g. into a prompts/ folder),
  compare sessions, inspect disk locations, debug trajectory steps, or delete sessions and projects.
---

# Antigravity Brain Explorer Skill

This skill provides procedures and commands to discover, inspect, and audit Antigravity session trajectories and conversation logs using the helper script [`agy-brain-explorer.py`](scripts/agy-brain-explorer.py).

## Execution Environment & Prerequisites

### 1. Always Run via `uv`
Run Python scripts using [`uv`](https://docs.astral.sh/uv/) so PEP 723 inline script dependencies (`typer>=0.12.0`) are automatically resolved and cached without manual virtual environment management.

From the workspace root:
```bash
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py [OPTIONS] [COMMAND]
```

Or from the skill folder:
```bash
uv run scripts/agy-brain-explorer.py [OPTIONS] [COMMAND]
```

### 2. Mandatory Bypass Sandbox (`BypassSandbox: true`)
> [!IMPORTANT]
> **Always set `BypassSandbox: true` when executing `run_command`.**
> 1. Running `uv run` inside Antigravity's standard sandbox fails with `Operation not permitted (os error 1)` when attempting to spawn the Python process.
> 2. Discovering and inspecting session trajectories requires reading directory structures and JSONL transcripts located in user storage at `~/.gemini/**/brain/`, which reside outside the workspace sandbox boundary.

### 3. Native Markdown Rendering
> [!TIP]
> **All results render directly as GitHub Flavored Markdown.**
> Session IDs are formatted with copyable code plus Antigravity UI navigation links (`` `<short_id>` [↗](conversation://<full_session_uuid>) ``) so the user can easily copy the session ID to ask follow-up questions or click directly into past conversations from chat.

---

## Workflows & Command Reference

### 1. Discover and List Recent Sessions

Scan all brain directories under `~/.gemini` and display conversation traces ordered chronologically (newest first):

```bash
# List most recent 10 sessions formatted as Markdown with clickable conversation links (default)
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py --limit 10

# Group discovered sessions by project
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py --by-project

# Filter sessions by project name or workspace path
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py --project "spring-petclinic"

# Filter by a specific brain root (e.g., 'antigravity-cli' or 'antigravity')
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py --brain antigravity --limit 10

# Filter sessions by initial user prompt query
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py -q "Please build a unified static HTML"
```

### 2. Discover Projects Across Sessions (`projects`)

View a project overview table listing all discovered projects, workspace paths, session counts, and latest active times:

```bash
# List all discovered projects across ~/.gemini brain folders
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py projects

# Inspect all sessions within a specific project
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py projects "spring-petclinic"
```

### 3. Search Sessions by Prompt or Deep Transcript (`search`)

Find sessions matching a prompt keyword or search across conversation turns and tool calls:

```bash
# Search sessions by initial prompt across all brain directories
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py search "Please build a unified static HTML"

# Filter search by brain root
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py search "build static docs" --brain antigravity-cli

# Deep search across all conversation steps (user requests, model responses, tool args, commands)
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py search "build-docs-site.js" --all-steps

# Search within a single specific session
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> search "node --test"
```

### 4. Inspect Session Overview (`summary`)

Pass a session UUID, partial prefix (e.g. `c1e9ba23`), or directory path to view metadata, timing, duration, model, workspace, and tool usage frequencies:

```bash
# Markdown formatted overview (default)
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION_ID_OR_PREFIX>
```

### 5. Browse Conversation Timeline (`steps`)

Display conversation turns with step numbers, timestamps, sources (`USER_EXPLICIT`, `MODEL`), types, and preview/actions:

```bash
# Markdown table of conversation steps (default)
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> steps --limit 20

# Filter to steps that called tools
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> steps --tools-only

# Filter to user prompt steps only
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> steps --user-only
```

### 6. Drill Down into a Specific Step (`step`)

Inspect the user prompt, model thinking, exact tool call parameters, triggering action, and step output logs:

```bash
# View step 5 details formatted in Markdown
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> step 5

# Limit step output log preview to 100 lines
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> step 5 --lines 100
```

### 7. Audit Tool & Command Executions

Quickly review all tool invocations or shell commands run during a session:

```bash
# List all tool invocations with targets and parameters in Markdown
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> tools

# Audit all shell commands run via run_command with working directories in Markdown
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> commands
```

### 8. Inspect Raw JSON Records (`raw`)

Retrieve untruncated JSON step data from `transcript_full.jsonl`:

```bash
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> raw 1 --full
```

### 9. Compare Two Sessions Side-by-Side (`compare`)

Compare two sessions side-by-side to review timing, duration, step counts, user turns, tool invocations, files written, and outcomes:

```bash
# Compare two sessions by IDs or prefixes
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py compare <SESSION_1> <SESSION_2>

# Or via session inspection syntax
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION_1> compare <SESSION_2>
```

### 10. Inspect On-Disk Paths and Transcripts (`paths`)

Display exact disk locations and clickable file links (`file://`) for session directories, transcripts (`transcript.jsonl`, `transcript_full.jsonl`), logs, step outputs, and scratch files:

```bash
# Show disk paths for a single session
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> paths

# Show disk paths for multiple sessions simultaneously
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py paths <SESSION_1> <SESSION_2>
```

### 11. Delete Sessions and Projects (`delete` / `rm`)

Safely delete sessions by individual ID/hash, path, or project name. By default, sessions are moved to the macOS Trash (`~/.Trash`) to enable recovery if needed:

```bash
# Delete sessions by short hash or full session ID (moved to Trash by default)
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py delete <SESSION_ID_OR_HASH>... --force

# Delete all sessions associated with a specific project
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py delete --project "spring-petclinic" --force

# Or delete by project name directly as a positional argument
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py delete "Buffered-Mult-Demo" --force

# Delete sessions not associated with any project
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py delete --project "(no workspace)" --force

# Preview matching sessions and targeted actions without deleting (dry run)
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py delete --project "gpui-testing" --dry-run

# Permanently delete from disk (rm -rf) instead of moving to Trash
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py delete <SESSION> --permanent --force

# Delete a session using single-session syntax
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> delete --force
```

### 12. Export Per-Conversation Markdown Logs (`export` / `prompts`)

Generate one detailed Markdown document per conversation (recording session metadata, user prompts, interactive `ask_question` Q&A selections, `thinking` summaries, Antigravity's file/tool actions, and executed shell commands) along with an index `README.md`:

```bash
# Export all sessions for the current workspace project into ./prompts/ (default)
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py export
# Or using the 'prompts' alias:
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py prompts

# Export all sessions for a specific project into a custom directory
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py export --project "NuttX" -o ./prompts

# Export specific session(s) by ID or prefix into ./prompts/
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py export <SESSION_1> <SESSION_2> -o ./prompts

# Render a single session's Markdown log to stdout or to a specific file
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> export
uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py <SESSION> export -o ./prompts/session.md
```

#### Multi-Take Recording Audit & Cleanup
When an operator takes multiple attempts to record an `asciinema` `.cast` session in the same project workspace, `~/.gemini/**/brain/` accumulates every aborted or superseded session under that project (including sessions started from subdirectories like `<project>/lib`). Exporting by `--project` will include all takes (`01-...`, `02-...`, etc.). To isolate the canonical session(s):
1. **Correlate Timestamps**: Read the `.cast` header `"timestamp"` (Unix epoch start time) and raw duration (`trim-cast.py <file> --info`), then compare against the `Created (Local)` and `Duration` fields in the exported `README.md` (or `agy-brain-explorer.py --project <proj>`).
2. **Trash Superseded Takes**: Move earlier aborted or superseded sessions to macOS Trash by short ID:
   ```bash
   uv run .agents/skills/agy-brain-explorer/scripts/agy-brain-explorer.py delete <OLD_ID_1> <OLD_ID_2> --force
   ```
3. **Clean & Re-Export**: Wipe the target export folder (`rm -rf <out_dir> && mkdir -p <out_dir>`) before re-running `export --project <proj> -o <out_dir>` so stale `02-...`/`03-...` files do not linger and the canonical trace is numbered cleanly starting at `01-`.


