# Asciinema & Asset Integration Reference

Architecture and troubleshooting reference for embedding `asciinema-player` v3 and static assets inside Slidev (`slides/`) for both local development and GitHub Pages subpath builds.

---

## 1. Why `AsciinemaPlayer.vue` Uses Dynamic Client Imports

Slidev pre-renders slides in Node.js during `slidev build`. Importing `asciinema-player` at module top-level fails during SSR because the player accesses browser DOM globals (`window`, `document`).

[`resources/components/AsciinemaPlayer.vue`](../resources/components/AsciinemaPlayer.vue) solves this with four mechanisms:

1. **Dynamic Import in `onMounted`**:
   ```ts
   const AsciinemaPlayer = await import('asciinema-player')
   playerInstance = AsciinemaPlayer.create(resolvedSrc, containerRef.value, playerOptions)
   ```
2. **Vite SSR Configuration (`slides/vite.config.ts`)**:
   ```ts
   export default defineConfig({
     optimizeDeps: {
       include: ['asciinema-player'],
     },
     ssr: {
       noExternal: ['asciinema-player'],
     },
   })
   ```
3. **`ResizeObserver` Reflow**:
   Slidev scales slides using CSS transforms. Attaching a `ResizeObserver` on the container element and calling `playerInstance.render()` ensures terminal geometry stays crisp across view transitions and presenter-console previews.
4. **Adaptive Per-Segment Playback Speeds & HUD**:
   `AsciinemaPlayer.vue` divides the recording into segments between `"m"` chapter markers and assigns each segment a speed of `max(speed, ceil(cappedDuration / maxSegmentDuration))` (defaulting to `>= 2.0x` minimum speed and `<= 30s` per segment). By default (`showChapterBar: false`), it renders a clean minimalist `Playback speed: Nx` badge beneath the terminal for the final presentation slide deck; setting `showChapterBar: true` enables the development header with a live speed badge (`⚡ Speed: Nx`), chapter stepper pills, and segment HUD details (`Segment K/N`).
5. **`asciicast v3` → `v2` Normalization & Chapter Marker Stepper Bar**:
   `asciinema` CLI 3.x records in `asciicast v3` (`{"version": 3, "term": {...}}` with relative `dt` intervals and `"x"` exit holds), whereas `asciinema-player` `< 3.10.0` (including `^3.8.0` / `3.9.0`) only parses `asciicast v1/v2` and displays the explosion emoji (`💥`) on v3 headers. `AsciinemaPlayer.vue` fetches the `.cast` file, converts `v3` streams to time-warped `v2` in memory via `prepareCastForPlayer()`, omits synthetic `"x"` exit-hold events (so playback reaches `ended` immediately when the final `"o"` frame renders), snaps each segment's `endTime`, `v2Header.duration`, and chapter `playTime` to the exact 6-decimal rounded `markerTime = Number(warpedAbs.toFixed(6))` emitted into the v2 stream (so `player.seek(ch.playTime)` and `player.seek(tailSeg.endTime)` never land before the rounded timestamp of the frame-completing `"o"` event when `.toFixed(6)` rounds up), passes `{ data: v2Text }` to `AsciinemaPlayer.create()` with `speed: 1`, auto-extracts embedded `"m"` chapter markers, defaults `pauseOnMarkers` to `true` when markers exist, and registers conflict-free `[` / `]` / `p` stage shortcuts in the **capture phase** (`window.addEventListener('keydown', handleStageKeydown, true)` with `event.stopPropagation()`) so `asciinema-player`'s `.ap-wrapper` keydown handler cannot swallow `[` and `]` when the terminal has focus. When `showChapterBar: true` is passed, it also renders compact Variant A chapter stepper pills (`↺ 0. Start`, `1..N`, and `→ End`). Jumping via `[` / `]`, pill clicks, natural playback completion (`applyEndState('ended')`), or timeline-scrubber seeks synchronizes all stop-point UI indicators (`status-pill`, `.hit` chapter pill, live speed badge, and segment HUD), steps back from Stop Point 1 (`idx = 0`) to `0. Start` (`idx = -1`), and advances from the final marker (`idx = chapters.length - 1`) to `→ End` (`idx = chapters.length`).
6. **Command-Entry & Synchronized-Frame Stop Point Placement (`mark-cast.py`)**:
   In `zsh` with bracketed paste, pressing `Enter` emits a reverse-video paste frame (`[REV]`) followed by an un-reverse redraw frame (`[UNREV]`, `\x1b[A...\x1b[27m...`) that ends with a cursor-down sequence (`\x1b[1B\r\x1b[K`). When placing `"m"` markers via `.agents/skills/asciinema/scripts/mark-cast.py`, the script splits `\x1b[1B\r\x1b[K` into a follow-up `"o"` event (`dt=0.02s`) after the marker so that when paused or seeked to `T_m`, the command is in normal video with the cursor resting on the same line at the end of the command. For non-paste TUI frames flushed across multiple `dt = 0.0` PTY chunks (`\x1b[?2026h`…`\x1b[?2026l`), `mark-cast.py` advances past consecutive `dt = 0.0` `"o"` events so the marker sits after the complete frame flush.

---

## 2. Base URL Resolution for GitHub Pages (`resolveUrl`)

When building for GitHub Pages with `slidev build --base /<repo-name>/`, root-relative URLs like `/casts/demo.cast` or `/images/photo.png` passed as Vue props will 404 at `https://<user>.github.io/casts/demo.cast` unless prefixed with Vite's `import.meta.env.BASE_URL`.

Both `AsciinemaPlayer.vue` and `layouts/hardware-callout.vue` normalize local paths via `resolveUrl`:

```ts
function resolveUrl(rawSrc: string | undefined): string {
  if (!rawSrc) return ''
  if (
    rawSrc.startsWith('http://') ||
    rawSrc.startsWith('https://') ||
    rawSrc.startsWith('data:') ||
    rawSrc.startsWith('blob:')
  ) {
    return rawSrc
  }
  const base = import.meta.env.BASE_URL || '/'
  const normalizedBase = base.endsWith('/') ? base : `${base}/`
  const cleanPath = rawSrc.replace(/^\.?\//, '')
  return `${normalizedBase}${cleanPath}`
}
```

Always include `resolveUrl()` in any new custom Vue layout or component that renders local files from `slides/public/`.

---

## 3. High-Contrast Terminal Theme Overrides (`slides/style.css`)

Default terminal palettes often render dim gray comments (`--term-color-8`) or dark blue prompts (`--term-color-4`) with low contrast on projectors. [`resources/style.css`](../resources/style.css) overrides `.ap-player` and `.asciinema-player-theme-dracula` with high-contrast Tokyo Night / Dracula colors:

- `--term-color-4: #7aa2f7` (Vibrant blue for prompt text)
- `--term-color-8: #9aa5ce` (Readable bright slate for secondary labels and timestamps)
- `--term-color-background: #1a1b26` (Distinct terminal surface against the `#121317` slide background)

---

## 4. Recommended Playback Settings by Recording Type

| Recording Type | Recommended `speed` | `idleTimeLimit` | `fit` | Notes |
| :--- | :--- | :--- | :--- | :--- |
| Short Q&A or single command (~15–30s) | `1.5` – `2.0` | `1.0` | `both` | Easy to read live while keeping talk pacing tight |
| Multi-step build or test run (~1–2m) | `3.0` – `5.0` | `1.0` | `both` | Shows full progress without stalling the presentation |
| Deep codebase audit or multi-file generation (3–10m) | `10.0` – `20.0` | `1.0` | `both` | Compresses a 5-minute agent run into a 15–25s visual beat |

Before copying a `.cast` file into `slides/public/casts/`, run the `/asciinema` skill's trim utility so the player stops cleanly on the final output frame instead of showing `exit` or shell termination prompts:

```bash
python3 .agents/skills/asciinema/scripts/trim-cast.py slides/public/casts/demo.cast --in-place
```
