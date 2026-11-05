---
name: ios-simulator-screenshot
description: Plan, walk through, capture, and verify iOS Simulator screen captures using xcrun simctl io booted screenshot with absolute paths. Use when the user asks where to store mobile app screenshots, which screens to capture for an iOS or Flutter app run, wants a step-by-step simctl screenshot walkthrough, or asks to verify captured simulator screenshots.
compatibility: macOS with Xcode / Command Line Tools (xcrun simctl) and Python 3.9+ (integrates with /crop-image and /slidev-deck)
---

# iOS Simulator Screenshot

Procedural runbook for inventorying an app's screens (from source views or exported **Session Traces**), generating a step-by-step `xcrun simctl io booted screenshot` walkthrough with **full absolute output paths**, staging captures under `artifacts/screenshots/<project_name>/`, and verifying captured PNGs.

Works alongside `/crop-image` (inspecting dimensions and bounding boxes) and `/slidev-deck` (copying verified assets into `slides/public/images/`).

## Workflows

Choose the matching workflow based on your objective:

1. [Stage Per-Run Screenshot Directories](#1-stage-per-run-screenshot-directories)
2. [Inventory App Views & Generate a `simctl` Walkthrough](#2-inventory-app-views--generate-a-simctl-walkthrough)
3. [Verify Captured Screenshots](#3-verify-captured-screenshots)

---

### 1. Stage Per-Run Screenshot Directories

Store raw simulator screenshots in `artifacts/screenshots/<project_name>/` at the repository root, mirroring `artifacts/traces/<project_name>/`:

1. Create the target directory before issuing capture commands (`xcrun simctl` fails with `NSCocoaErrorDomain code=4` if the parent directory does not exist):
   ```bash
   mkdir -p "/abs/path/to/repo/artifacts/screenshots/<project_name>"
   ```
2. Name files sequentially with two-digit prefixes and kebab-case view names (`01-home-screen.png`, `02-item-detail.png`, `03-add-item-sheet.png`).
3. *Completion Criterion*: Target directory `artifacts/screenshots/<project_name>/` exists on disk before any `xcrun simctl` command is presented to the user.

---

### 2. Inventory App Views & Generate a `simctl` Walkthrough

When the user asks which screenshots to capture or requests a walkthrough for an app run:

1. **Discover Actual Built Screens**:
   - Inspect the app source files (e.g., `lib/**/views/*.dart` / `lib/**/screens/*.dart` in Flutter, or `*View.swift` / `*ViewController.swift` in iOS) or any exported session traces (e.g., in `artifacts/traces/<project_name>/`) so every screenshot maps to a real screen, tab, or modal sheet built in that app.
2. **Use Full Absolute Output Paths**:
   - The user's active terminal is often inside an external app workspace (e.g., `~/Projects/<app_workspace>`) rather than the target repository root.
   - Always emit `xcrun simctl io booted screenshot` commands with **full absolute paths** (`/Users/.../artifacts/screenshots/<project_name>/01-...png`) so copy-pasting succeeds from any working directory.
3. **Pair Each Command with Navigation Context**:
   - Present the commands in natural navigation order (Home tab → Detail push → Back → FAB modal sheet → Dismiss → Secondary tabs → App bar sheets).
   - For each step, state **Where you are** (what to tap before running the command, and how to return/dismiss afterwards):
     ```bash
     # 1. Home / Primary Tab (default launch screen)
     xcrun simctl io booted screenshot /abs/path/to/repo/artifacts/screenshots/<project_name>/01-home-list.png

     # 2. Detail Screen (tap a row in the list, capture, then tap '<' back)
     xcrun simctl io booted screenshot /abs/path/to/repo/artifacts/screenshots/<project_name>/02-item-detail.png
     ```
4. *Completion Criterion*: Every distinct screen/tab/sheet in the app is covered by a numbered step with a "Where you are" navigation cue and a copy-pasteable `xcrun simctl io booted screenshot /abs/path/...` command.

---

### 3. Verify Captured Screenshots

When the user confirms they have run the capture commands:

1. **Check Files on Disk**:
   ```bash
   ls -lh "/abs/path/to/repo/artifacts/screenshots/<project_name>/"
   ```
2. **Inspect Visual Content**:
   - Call `read_file` on each captured `.png` file to visually confirm that the expected UI state (tabs, modal sheets, sample data, and any notable UI quirks worth highlighting in slides) was captured.
3. **Verify Framebuffer Dimensions & Margins (`/crop-image`)**:
   - Run `crop.py --inspect` on a sample capture:
     ```bash
     python3 .agents/skills/crop-image/scripts/crop.py "/abs/path/to/repo/artifacts/screenshots/<project_name>/01-home-list.png" --inspect
     ```
   - `xcrun simctl io booted screenshot` captures the exact iOS device framebuffer (`0px` outer transparent margin), unlike macOS window captures (`Cmd+Shift+4`).
4. *Completion Criterion*: Every expected PNG is non-empty, visually verified via `read_file`, and confirmed to have clean framebuffer dimensions via `crop.py --inspect`.
