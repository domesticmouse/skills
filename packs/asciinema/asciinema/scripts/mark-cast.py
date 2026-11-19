#!/usr/bin/env python3
"""
mark-cast.py: Inspect, search, add, move/replace, or remove asciicast ("m")
chapter markers in .cast files (v2 & v3).

Capabilities:
1. --list: Display all existing "m" marker events with raw, 1x, and adaptive
   time-warped playback timestamps.
2. --inspect START[:END]: Print a table of events in range [START, END] with
   dt, raw, 1x, code, and stripped text.
3. --search REGEX [--context N]: Search stdout ("o") events for REGEX and print
   event index, timestamps, and N surrounding events.
4. --set TARGET WHERE LABEL: Move/replace existing marker TARGET (1-based index
   or label substring) to WHERE (regex pattern, regex#N, @event:IDX, @time:SEC,
   or @1x:SEC) with new LABEL.
5. --remove TARGET: Remove existing marker(s) matching 1-based index or label
   substring.
6. --add-pattern REGEX LABEL: Insert an "m" marker immediately after (or
   --before) the stdout frame matching REGEX (or REGEX#N).
7. --add-time SECONDS LABEL [--effective-time]: Insert an "m" marker at raw or
   1x timestamp SECONDS.
8. --add-event EVENT_IDX LABEL: Insert an "m" marker immediately after (or
   --before) event #EVENT_IDX.
9. --relabel LABEL1 LABEL2 ...: Rename existing "m" markers in sequence.
10. --clear: Remove all existing "m" markers before applying additions.
11. --auto-spec JSON_PATH: Auto-inject chapter markers from a JSON specification
    file (list of {"label": "...", "pattern": "..."} or ["label", "pattern"]).
12. --set-dt EVENT_IDX SECONDS: Set the relative delay (dt) of a specific event
    index (adjusting subsequent timestamps automatically in v2).
13. --tighten-pastes: Automatically shorten pre-paste delays ([REV] -> 1.0s),
    Enter highlight pauses ([UNREV] -> 0.15s), and prompt paste/submit delays.
14. --embed-html HTML_PATH: Re-compress the saved .cast file (gzip+base64) into
    EMBEDDED_CAST_GZ_B64 inside HTML_PATH.
15. --render EVENT_IDX: Render the 2D terminal screen and (cursor.y, cursor.x) at
    one or more event indices using pyte (run via `uv run --with pyte`).
16. --verify-strip START:END: Simulate the terminal screen with pyte across a
    candidate cut START:END, comparing cursor coordinates (y, x) at START - 1
    vs. END and checking post-cut frames (END + 1 onwards) for scrollback redraws.
17. --strip-range START:END: Excise events in inclusive 0-based range START:END
    (shifting subsequent timestamps in asciicast v2 and preserving relative dt
    in asciicast v3).
"""

from __future__ import annotations

import argparse
import base64
import gzip
import itertools
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, ClassVar


def load_auto_spec(spec_path: str) -> list[tuple[str, re.Pattern[str]]]:
    """
    Load marker specifications from a JSON file.
    Accepts either:
      - A list of objects: [{"label": "1. Setup", "pattern": "npm init"}, ...]
      - A list of 2-element arrays: [["1. Setup", "npm init"], ...]
    """
    data = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise TypeError(
            f"Expected a JSON list in {spec_path}, got {type(data).__name__}"
        )
    specs: list[tuple[str, re.Pattern[str]]] = []
    for idx, item in enumerate(data):
        if isinstance(item, dict) and "label" in item and "pattern" in item:
            label = str(item["label"])
            pat_str = str(item["pattern"])
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            label = str(item[0])
            pat_str = str(item[1])
        else:
            raise ValueError(
                f"Invalid spec entry at index {idx} in {spec_path}: "
                "expected {'label': ..., 'pattern': ...} or [label, pattern]"
            )
        specs.append((label, re.compile(pat_str, re.DOTALL)))
    return specs


ANSI_ESCAPE_RE = re.compile(
    r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07\x1B]*(?:\x07|\x1B\\))"
)


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


UNREV_CURSOR_DOWN_RE = re.compile(r"(\x1b\[\d*B\r\x1b\[K)$")
BASH_UNREV_SPLIT_RE = re.compile(
    r"^((?:\x08+|\r(?:\x1b\[\d*[A-D])*|\x1b\[\d*[A-D])+(?:\x1b\[27m)*[^\x00-\x1f\x7f](?:(?!\x1b\[\?2004l\r)[^\r\n])*)((?:\x1b\[\?2004l)?\r+\n[\s\S]*)$"
)
BASH_UNREV_ALREADY_SPLIT_RE = re.compile(
    r"^(?:\x08+|\r(?:\x1b\[\d*[A-D])*|\x1b\[\d*[A-D])+(?:\x1b\[27m)*[^\x00-\x1f\x7f][^\r\n]*$"
)


def is_rev_paste_payload(s: str) -> bool:
    return "\x1b[7m" in s and not s.startswith("\x1b[1m\x1b[7m%\x1b[27m")


def is_bash_unrev_payload(s: str, prev_is_rev: bool = False) -> bool:
    if BASH_UNREV_SPLIT_RE.match(s) and ("\x1b[?2004l" in s or prev_is_rev):
        return True
    return bool(prev_is_rev and BASH_UNREV_ALREADY_SPLIT_RE.match(s))


def _prev_event_is_rev(events: list[list[Any]], idx: int) -> bool:
    return (
        idx > 0
        and len(events[idx - 1]) >= 3
        and events[idx - 1][1] == "o"
        and is_rev_paste_payload(str(events[idx - 1][2]))
    )


def _prev_timing_is_rev(
    timings: list[tuple[int, float, float, float, str, Any]], idx: int
) -> bool:
    return (
        idx > 0
        and timings[idx - 1][4] == "o"
        and is_rev_paste_payload(str(timings[idx - 1][5]))
    )


def describe_ansi_tags(code: str, data: Any, prev_is_rev: bool | None = None) -> str:
    """
    Return compact diagnostic tags for stdout ('o') events so --inspect and --search
    distinguish bracketed-paste reverse video ([REV]), Enter un-reverse redraw
    ([UNREV]), and prompt/preexec OSC metadata ([OSC]).
    """
    if code != "o":
        return ""
    s = str(data)
    tags: list[str] = []
    if is_rev_paste_payload(s):
        tags.append("REV")
    else:
        effective_prev_rev = (
            s.startswith("\x08") or ("\x1b[27m" in s and s.startswith("\x1b["))
            if prev_is_rev is None
            else prev_is_rev
        )
        if ("\x1b[27m" in s and "\x1b[A" in s) or is_bash_unrev_payload(
            s, prev_is_rev=effective_prev_rev
        ):
            tags.append("UNREV")
    if any(osc in s for osc in ("\x1b]0;", "\x1b]2;", "\x1b]7;", "\x1b]3008;")):
        tags.append("OSC")
    return f"[{','.join(tags)}] " if tags else ""


def advance_past_paste_redraw(
    events: list[list[Any]], match_idx: int, version: int
) -> int:
    """
    When a stdout pattern matches a shell bracketed-paste frame in reverse video
    (\\x1b[7m) or its immediate Enter un-reverse redraw (\\x1b[27m in zsh or
    Readline backspace/redraw in bash):
      1. Advance from the [REV] paste frame to the [UNREV] redraw frame
         (\\x1b[A...\\x1b[27m... in zsh, or \\x08+... in bash).
      2. If the [UNREV] frame ends with a cursor-down newline sequence
         (\\x1b[1B\\r\\x1b[K in zsh) or trailing newline/output (\\r\\n... in bash),
         split that trailing sequence into a follow-up 'o' event (dt=0.02s) so
         that at the 'm' marker the command is in normal video with the cursor
         still on the same line at the end of the command.
    """
    if match_idx < 0 or match_idx >= len(events):
        return match_idx
    ev = events[match_idx]
    if len(ev) < 3 or ev[1] != "o":
        return match_idx

    payload = str(ev[2])
    is_rev_paste = is_rev_paste_payload(payload)
    prev_is_rev = _prev_event_is_rev(events, match_idx)
    is_unrev_redraw = (
        "\x1b[27m" in payload and "\x1b[A" in payload
    ) or is_bash_unrev_payload(payload, prev_is_rev=prev_is_rev)
    if not (is_rev_paste or is_unrev_redraw):
        idx = match_idx
        while idx + 1 < len(events):
            next_ev = events[idx + 1]
            if len(next_ev) < 3 or next_ev[1] != "o":
                break
            dt = (
                float(next_ev[0])
                if version == 3
                else max(0.0, float(next_ev[0]) - float(events[idx][0]))
            )
            next_clean = strip_ansi(str(next_ev[2])).strip()
            if dt > 0.0 and not (dt <= 0.025 and next_clean == "G"):
                break
            idx += 1
        return idx

    idx = match_idx
    # Step 1: If matched on [REV] paste frame, advance to [UNREV] redraw frame
    if is_rev_paste and idx + 1 < len(events):
        next_ev = events[idx + 1]
        if (
            len(next_ev) >= 3
            and next_ev[1] == "o"
            and (
                "\x1b[27m" in str(next_ev[2])
                or is_bash_unrev_payload(str(next_ev[2]), prev_is_rev=True)
            )
        ):
            idx += 1

    # Step 2: If [UNREV] has a trailing cursor-down (\x1b[1B\r\x1b[K in zsh) or
    # newline (\r\n... in bash), split it into a separate 'o' event after the
    # marker so cursor stays on command line.
    unrev_ev = events[idx]
    if len(unrev_ev) >= 3 and unrev_ev[1] == "o":
        unrev_s = str(unrev_ev[2])
        m = UNREV_CURSOR_DOWN_RE.search(unrev_s)
        m_bash = None if m else BASH_UNREV_SPLIT_RE.match(unrev_s)
        split_parts: tuple[str, str] | None = None
        if m:
            split_parts = (unrev_s[: -len(m.group(1))], m.group(1))
        elif m_bash:
            split_parts = (m_bash.group(1), m_bash.group(2))
        if split_parts is not None:
            prefix, suffix = split_parts
            unrev_ev[2] = prefix
            split_dt = 0.02
            if version == 3:
                follow_time = split_dt
                # Deduct split_dt from next positive-dt event to preserve duration
                for look_idx in range(idx + 1, min(len(events), idx + 6)):
                    if float(events[look_idx][0]) >= split_dt:
                        events[look_idx][0] = round(
                            float(events[look_idx][0]) - split_dt, 6
                        )
                        break
            else:
                follow_time = round(float(unrev_ev[0]) + split_dt, 6)
            events.insert(idx + 1, [follow_time, "o", suffix])

    return idx


def load_cast(path: str) -> tuple[dict[str, Any], list[list[Any]], int]:
    with open(path, encoding="utf-8") as f:
        lines = [
            line.strip()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        ]
    if not lines:
        raise ValueError(f"Empty cast file: {path}")
    header = json.loads(lines[0])
    version = int(header.get("version", 2))
    events = [json.loads(line) for line in lines[1:]]
    return header, events, version


def compute_timings(
    header: dict[str, Any], events: list[list[Any]], version: int
) -> list[tuple[int, float, float, float, str, Any]]:
    """
    Returns list of (index, dt, raw_abs_time, effective_playback_time,
    event_code, payload). Handles both v2 and v3 formats.
    """
    idle_limit = header.get("idle_time_limit")
    idle_cap = float(idle_limit) if idle_limit is not None else None

    result: list[tuple[int, float, float, float, str, Any]] = []
    raw_abs = 0.0
    eff_abs = 0.0
    prev_raw = 0.0

    for idx, ev in enumerate(events):
        t_val = float(ev[0])
        code = str(ev[1])
        data = ev[2] if len(ev) > 2 else ""
        if version == 3:
            dt = t_val
            raw_abs += dt
        else:
            raw_abs = t_val
            dt = raw_abs - prev_raw
            prev_raw = raw_abs
        eff_dt = min(dt, idle_cap) if idle_cap is not None else dt
        eff_abs += eff_dt
        result.append((idx, dt, raw_abs, eff_abs, code, data))
    return result


def list_markers(
    header: dict[str, Any],
    events: list[list[Any]],
    version: int,
    min_speed: float = 2.0,
    max_segment_sec: float = 30.0,
) -> None:
    timings = compute_timings(header, events, version)
    markers = [row for row in timings if row[4] == "m"]
    print(
        f"Format: asciicast-v{version} | Total events: {len(events)} | "
        f"Markers: {len(markers)}"
    )
    if not markers:
        print("  (no 'm' marker events found)")
        return
    prev_eff = 0.0
    warped_abs = 0.0
    prev_label = "0. Start"
    for num, (idx, _dt, raw_t, eff_t, _, label) in enumerate(markers, start=1):
        seg_dur = max(0.0, eff_t - prev_eff)
        spd = (
            max(min_speed, float(math.ceil(seg_dur / max_segment_sec)))
            if seg_dur / min_speed > max_segment_sec
            else min_speed
        )
        warped_dur = seg_dur / spd
        warped_abs += warped_dur
        print(
            f"  [{num}] event #{idx:04d} | raw={raw_t:6.2f}s | 1x={eff_t:6.2f}s | "
            f"seg={warped_dur:4.1f}s @ {spd:g}x | warped={warped_abs:5.1f}s | "
            f"label={label!r}"
        )
        prev_eff = eff_t
        prev_label = str(label)
    non_exit = [row for row in timings if row[4] != "x"]
    if non_exit and non_exit[-1][3] > prev_eff + 0.05:
        tail_eff = non_exit[-1][3]
        seg_dur = max(0.0, tail_eff - prev_eff)
        spd = (
            max(min_speed, float(math.ceil(seg_dur / max_segment_sec)))
            if seg_dur / min_speed > max_segment_sec
            else min_speed
        )
        warped_dur = seg_dur / spd
        warped_abs += warped_dur
        print(
            f"  [End] after {prev_label!r} | 1x_seg={seg_dur:6.2f}s | "
            f"seg={warped_dur:4.1f}s @ {spd:g}x | total_warped={warped_abs:5.1f}s"
        )


def inspect_range(
    header: dict[str, Any],
    events: list[list[Any]],
    version: int,
    spec: str,
) -> None:
    timings = compute_timings(header, events, version)
    if ":" in spec:
        start_s, end_s = spec.split(":", 1)
        start_idx = int(start_s) if start_s else 0
        end_idx = int(end_s) if end_s else start_idx + 40
    else:
        center = int(spec)
        start_idx = max(0, center - 10)
        end_idx = center + 10
    start_idx = max(0, start_idx)
    end_idx = min(len(timings) - 1, end_idx)
    print(f"Inspecting events #{start_idx:04d}..#{end_idx:04d} (of {len(timings)}):")
    for idx in range(start_idx, end_idx + 1):
        _, dt, raw_t, eff_t, code, data = timings[idx]
        clean = " ".join(strip_ansi(str(data)).split())
        tags = describe_ansi_tags(
            code, data, prev_is_rev=_prev_timing_is_rev(timings, idx)
        )
        marker_flag = " <-- MARKER" if code == "m" else ""
        print(
            f"  #{idx:04d} | dt={dt:5.2f}s | raw={raw_t:7.2f}s | 1x={eff_t:7.2f}s | "
            f"{code} | {tags}{clean[:95]!r}{marker_flag}"
        )


def search_events(
    header: dict[str, Any],
    events: list[list[Any]],
    version: int,
    pattern_str: str,
    context: int = 0,
    limit: int = 30,
) -> None:
    pattern = re.compile(pattern_str, re.IGNORECASE | re.DOTALL)
    timings = compute_timings(header, events, version)
    matches = 0
    rolling = ""
    print(f"Searching for pattern {pattern_str!r} across {len(events)} events...")
    for idx, _dt, raw_t, eff_t, code, data in timings:
        if code != "o":
            continue
        clean = strip_ansi(str(data))
        rolling = (rolling + clean)[-800:]
        if pattern.search(clean) or pattern.search(rolling):
            snippet = " ".join(clean.split())
            if not snippet:
                snippet = " ".join(rolling[-120:].split())
            tags = describe_ansi_tags(
                code, data, prev_is_rev=_prev_timing_is_rev(timings, idx)
            )
            print(
                f"  event #{idx:04d} | raw={raw_t:6.2f}s | 1x={eff_t:6.2f}s | "
                f"{tags}{snippet[:90]!r}"
            )
            if context > 0:
                c_start = max(0, idx - context)
                c_end = min(len(timings) - 1, idx + context)
                for c_idx in range(c_start, c_end + 1):
                    _, c_dt, c_raw, c_eff, c_code, c_data = timings[c_idx]
                    c_clean = " ".join(strip_ansi(str(c_data)).split())
                    c_tags = describe_ansi_tags(
                        c_code, c_data, prev_is_rev=_prev_timing_is_rev(timings, c_idx)
                    )
                    prefix = "    >>>" if c_idx == idx else "       "
                    print(
                        f"{prefix} #{c_idx:04d} dt={c_dt:5.2f}s raw={c_raw:6.2f}s "
                        f"1x={c_eff:6.2f}s {c_code} -> {c_tags}{c_clean[:80]!r}"
                    )
            matches += 1
            rolling = ""
            if matches >= limit:
                print(
                    f"  ... stopped at {limit} matches "
                    "(use a more specific regex to narrow)"
                )
                break
    if matches == 0:
        print("  (no matching stdout events found)")


def relabel_markers(events: list[list[Any]], labels: list[str]) -> int:
    label_idx = 0
    updated = 0
    for ev in events:
        if len(ev) >= 3 and ev[1] == "m" and label_idx < len(labels):
            ev[2] = labels[label_idx]
            label_idx += 1
            updated += 1
    return updated


def auto_inject_markers(
    _header: dict[str, Any],
    events: list[list[Any]],
    version: int,
    marker_specs: list[tuple[str, re.Pattern[str]]],
    insert_after: bool = True,
    raw_match: bool = False,
) -> tuple[list[list[Any]], list[str]]:
    """
    Scan stdout ('o') events for the patterns in marker_specs and insert 'm' markers
    with dt=0.0 (v3) or same timestamp (v2). When matching a bracketed-paste
    reverse-video command, automatically advances past the Enter un-reverse redraw
    and pre-exec title.
    """
    canonical_labels = {label for label, _ in marker_specs}
    events = [
        ev
        for ev in events
        if not (len(ev) >= 3 and ev[1] == "m" and ev[2] in canonical_labels)
    ]

    placements: dict[int, list[str]] = {}
    target_idx = 0
    injected: list[str] = []
    rolling_window = ""

    idx = 0
    while idx < len(events):
        ev = events[idx]
        if target_idx < len(marker_specs) and len(ev) >= 3 and ev[1] == "o":
            clean_chunk = strip_ansi(str(ev[2]))
            rolling_window = (rolling_window + clean_chunk)[-1500:]
            for lookahead in range(target_idx, min(len(marker_specs), target_idx + 2)):
                label, pattern = marker_specs[lookahead]
                if pattern.search(rolling_window):
                    place_idx = (
                        advance_past_paste_redraw(events, idx, version)
                        if (insert_after and not raw_match)
                        else idx
                    )
                    placements.setdefault(place_idx, []).append(label)
                    injected.append(label)
                    target_idx = lookahead + 1
                    rolling_window = ""
                    idx = max(idx, place_idx)
                    break
        idx += 1

    new_events: list[list[Any]] = []
    for idx, ev in enumerate(events):
        if not insert_after and idx in placements:
            for label in placements[idx]:
                marker_time = 0.0 if version == 3 else ev[0]
                new_events.append([marker_time, "m", label])
        new_events.append(ev)
        if insert_after and idx in placements:
            for label in placements[idx]:
                marker_time = 0.0 if version == 3 else ev[0]
                new_events.append([marker_time, "m", label])

    return new_events, injected


def add_pattern_marker(
    events: list[list[Any]],
    version: int,
    pattern_str: str,
    label: str,
    occurrence: int = 1,
    insert_after: bool = True,
    raw_match: bool = False,
) -> tuple[list[list[Any]], int | None]:
    if pattern_str.startswith("@cmd:"):
        pattern_str = pattern_str[5:]
        raw_match = False
    pattern = re.compile(pattern_str, re.DOTALL)
    rolling_window = ""
    seen = 0
    matched_at: int | None = None

    for idx, ev in enumerate(events):
        if len(ev) >= 3 and ev[1] == "o":
            clean_chunk = strip_ansi(str(ev[2]))
            rolling_window = (rolling_window + clean_chunk)[-1500:]
            if pattern.search(rolling_window):
                seen += 1
                rolling_window = ""
                if seen == occurrence:
                    matched_at = (
                        advance_past_paste_redraw(events, idx, version)
                        if (insert_after and not raw_match)
                        else idx
                    )
                    break

    if matched_at is None:
        return events, None

    updated_events, _ = add_event_marker(
        events, version, matched_at, label, insert_after=insert_after
    )
    return updated_events, matched_at


def add_event_marker(
    events: list[list[Any]],
    version: int,
    target_idx: int,
    label: str,
    insert_after: bool = True,
) -> tuple[list[list[Any]], bool]:
    if target_idx < 0 or target_idx >= len(events):
        return events, False
    new_events: list[list[Any]] = []
    for idx, ev in enumerate(events):
        if idx == target_idx and not insert_after:
            marker_time = 0.0 if version == 3 else ev[0]
            new_events.append([marker_time, "m", label])
        new_events.append(ev)
        if idx == target_idx and insert_after:
            marker_time = 0.0 if version == 3 else ev[0]
            new_events.append([marker_time, "m", label])
    return new_events, True


def add_time_marker(
    header: dict[str, Any],
    events: list[list[Any]],
    version: int,
    target_sec: float,
    label: str,
    use_effective_time: bool = False,
) -> tuple[list[list[Any]], int]:
    timings = compute_timings(header, events, version)
    chosen_idx = 0
    for idx, _dt, raw_t, eff_t, _, _ in timings:
        t_compare = eff_t if use_effective_time else raw_t
        if t_compare <= target_sec:
            chosen_idx = idx
        else:
            break
    events, _ = add_event_marker(events, version, chosen_idx, label, insert_after=True)
    return events, chosen_idx


def remove_marker_by_target(
    events: list[list[Any]], target: str
) -> tuple[list[list[Any]], list[str]]:
    """
    Remove marker(s) matching 1-based marker number (e.g. '1') or
    case-insensitive label substring.
    """
    is_num = target.isdigit()
    target_num = int(target) if is_num else -1
    target_lower = target.lower()

    new_events: list[list[Any]] = []
    removed_labels: list[str] = []
    marker_num = 0
    for ev in events:
        if len(ev) >= 2 and ev[1] == "m":
            marker_num += 1
            label = str(ev[2]) if len(ev) > 2 else ""
            if (is_num and marker_num == target_num) or (
                not is_num and target_lower in label.lower()
            ):
                removed_labels.append(f"[{marker_num}] {label}")
                continue
        new_events.append(ev)
    return new_events, removed_labels


def set_marker_by_target(
    header: dict[str, Any],
    events: list[list[Any]],
    version: int,
    target: str,
    where_spec: str,
    new_label: str,
    insert_after: bool = True,
    raw_match: bool = False,
) -> tuple[list[list[Any]], str]:
    """
    Replace/move an existing marker identified by 1-based index or label substring,
    placing the updated marker at WHERE_SPEC:
      - '@event:123' -> event index #123
      - '@time:12.5' -> raw timestamp 12.5s
      - '@1x:12.5'   -> idle-capped 1x timestamp 12.5s
      - '@cmd:regex' or 'regex' or 'regex#2' -> stdout pattern match
        (auto-advances past reverse-video paste redraw unless --raw-match)
    """
    events_without, removed = remove_marker_by_target(events, target)
    removed_desc = (
        ", ".join(removed) if removed else f"(no existing marker matched {target!r})"
    )

    if where_spec.startswith("@event:"):
        ev_idx = int(where_spec.split(":", 1)[1])
        updated_events, ok = add_event_marker(
            events_without, version, ev_idx, new_label, insert_after=insert_after
        )
        loc_desc = f"event #{ev_idx:04d}" if ok else f"FAILED event #{ev_idx}"
    elif where_spec.startswith("@time:"):
        sec = float(where_spec.split(":", 1)[1])
        updated_events, idx = add_time_marker(
            header, events_without, version, sec, new_label, use_effective_time=False
        )
        loc_desc = f"raw={sec:.2f}s (event #{idx:04d})"
    elif where_spec.startswith("@1x:"):
        sec = float(where_spec.split(":", 1)[1])
        updated_events, idx = add_time_marker(
            header, events_without, version, sec, new_label, use_effective_time=True
        )
        loc_desc = f"1x={sec:.2f}s (event #{idx:04d})"
    else:
        occ = 1
        pat = where_spec
        if "#" in where_spec and where_spec.rsplit("#", 1)[1].isdigit():
            pat, occ_str = where_spec.rsplit("#", 1)
            occ = int(occ_str)
        updated_events, idx = add_pattern_marker(
            events_without,
            version,
            pat,
            new_label,
            occurrence=occ,
            insert_after=insert_after,
            raw_match=raw_match,
        )
        loc_desc = (
            f"event #{idx:04d} (pattern={pat!r}, occ={occ})"
            if idx is not None
            else f"WARNING: pattern {pat!r} not found"
        )

    return updated_events, f"Replaced {removed_desc} -> {new_label!r} at {loc_desc}"


def set_event_dt(
    events: list[list[Any]], version: int, target_idx: int, new_dt: float
) -> tuple[bool, float]:
    """
    Set the relative delay (dt) of event #target_idx to new_dt.
    In v3, events[i][0] is relative dt directly.
    In v2, events[i][0] is cumulative timestamp, so subsequent events shift by
    (new_dt - old_dt).
    """
    if target_idx < 0 or target_idx >= len(events):
        return False, 0.0
    new_dt = max(0.0, round(float(new_dt), 6))
    if version == 3:
        old_dt = float(events[target_idx][0])
        events[target_idx][0] = new_dt
        return True, old_dt

    prev_abs = float(events[target_idx - 1][0]) if target_idx > 0 else 0.0
    old_dt = max(0.0, float(events[target_idx][0]) - prev_abs)
    delta = new_dt - old_dt
    for idx in range(target_idx, len(events)):
        events[idx][0] = round(max(0.0, float(events[idx][0]) + delta), 6)
    return True, old_dt


def tighten_paste_delays(
    events: list[list[Any]],
    version: int,
    pre_paste_dt: float = 1.0,
    unrev_dt: float = 0.15,
    submit_dt: float = 0.20,
) -> list[str]:
    """
    Shorten cut-and-paste, prompt-entry, and prompt-submit delays without
    affecting markers or output:
      1. Shell bracketed-paste [REV] frames (\\x1b[7m): cap dt to pre_paste_dt.
      2. Shell Enter [UNREV] redraw frames (\\x1b[A...\\x1b[27m): cap dt to unrev_dt.
      3. agy startup model header settle before initial prompt: cap dt to pre_paste_dt.
      4. TUI pasted prompts or first typed prompt character: cap dt to pre_paste_dt.
      5. Slash-command execution frame after '(/clear)' marker or ask_question '✓ ' confirmation after marker: cap dt to pre_paste_dt.
      6. Input-box clear/submit events after an 'm' marker: cap dt to submit_dt.
    """
    notes: list[str] = []
    input_clear_re = re.compile(
        r"^\x1b\[\?2026h(?:\x1b\[\d+D\x1b\[K|\r\x1b\[2C\x1b\[K|\r\n\n\n\x1b\[J\x1b\[3A\x1b\[2C\x1b\[K)"
    )
    agy_footer_badges = (
        " \x1b[2mG\x1b[m\x1b[2A",
        "\x1b[1K \x1b[33ma\x1b[m\x1b[2A",
    )

    for idx, ev in enumerate(events):
        if len(ev) < 3 or ev[1] != "o":
            continue
        s = str(ev[2])
        old_dt = (
            float(ev[0])
            if version == 3
            else (float(ev[0]) - (float(events[idx - 1][0]) if idx > 0 else 0.0))
        )

        is_rev = is_rev_paste_payload(s)
        prev_is_rev = _prev_event_is_rev(events, idx)
        is_unrev = ("\x1b[27m" in s and "\x1b[A" in s) or is_bash_unrev_payload(
            s, prev_is_rev=prev_is_rev
        )
        next_is_marker = idx + 1 < len(events) and events[idx + 1][1] == "m"
        prev_is_marker = idx > 0 and events[idx - 1][1] == "m"
        prev_marker_label = (
            str(events[idx - 1][2]).lower()
            if prev_is_marker and len(events[idx - 1]) >= 3
            else ""
        )
        has_footer_badge = any(b in s for b in agy_footer_badges)
        next_has_footer_badge = (
            idx + 1 < len(events)
            and len(events[idx + 1]) >= 3
            and events[idx + 1][1] == "o"
            and any(b in str(events[idx + 1][2]) for b in agy_footer_badges)
        )

        target_dt: float | None = None
        reason = ""
        if is_rev and old_dt > pre_paste_dt:
            target_dt = pre_paste_dt
            reason = "[REV] shell paste"
        elif is_unrev and old_dt > unrev_dt:
            target_dt = unrev_dt
            reason = "[UNREV] Enter redraw"
        elif (
            "Gemini " in s
            and idx > 0
            and "Welcome to the"
            in strip_ansi(
                str(events[idx - 2][2])
                if idx >= 2 and len(events[idx - 2]) >= 3
                else ""
            )
            and old_dt > pre_paste_dt
        ):
            target_dt = pre_paste_dt
            reason = "agy banner settle"
        elif next_is_marker and has_footer_badge and old_dt > pre_paste_dt:
            target_dt = pre_paste_dt
            reason = "agy pasted prompt"
        elif (
            next_has_footer_badge
            or (
                prev_is_marker and "ready for" in prev_marker_label and has_footer_badge
            )
        ) and old_dt > pre_paste_dt:
            target_dt = pre_paste_dt
            reason = "agy typed prompt start"
        elif prev_is_marker and "/clear" in prev_marker_label and old_dt > pre_paste_dt:
            target_dt = pre_paste_dt
            reason = "agy /clear execution"
        elif prev_is_marker and input_clear_re.match(s) and old_dt > submit_dt:
            target_dt = submit_dt
            reason = "agy prompt submit"
        elif prev_is_marker and "✓ " in strip_ansi(s) and old_dt > pre_paste_dt:
            target_dt = pre_paste_dt
            reason = "agy question selection"

        if target_dt is not None:
            set_event_dt(events, version, idx, target_dt)
            clean_preview = " ".join(strip_ansi(s).split())[:55]
            notes.append(
                f"#{idx:04d} ({reason}): dt {old_dt:.2f}s -> "
                f"{target_dt:.2f}s | {clean_preview!r}"
            )
    return notes


def save_cast(path: str, header: dict[str, Any], events: list[list[Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
        f.writelines(json.dumps(ev, ensure_ascii=False) + "\n" for ev in events)


def _require_pyte() -> Any:
    try:
        import pyte  # type: ignore[import-not-found]
    except ImportError:
        sys.stderr.write(
            "Error: 'pyte' is required for terminal screen emulation. Run with:\n"
            "  uv run --with pyte python3 .agents/skills/asciinema/scripts/mark-cast.py ...\n"
        )
        sys.exit(1)
    return pyte


def _cast_dimensions(header: dict[str, Any]) -> tuple[int, int]:
    term = header.get("term")
    if isinstance(term, dict):
        cols = int(term.get("cols") or 120)
        rows = int(term.get("rows") or 36)
        return cols, rows
    cols = int(header.get("width") or 120)
    rows = int(header.get("height") or 36)
    return cols, rows


def _parse_range_spec(spec: str, total_events: int) -> tuple[int, int]:
    if ":" not in spec:
        raise ValueError(f"Expected START:END range, got {spec!r}")
    start_s, end_s = spec.split(":", 1)
    if not start_s.strip().isdigit() or not end_s.strip().isdigit():
        raise ValueError(f"Expected integer START:END range, got {spec!r}")
    start_idx = int(start_s.strip())
    end_idx = int(end_s.strip())
    if not (0 <= start_idx <= end_idx < total_events):
        raise ValueError(
            f"Range {start_idx}:{end_idx} out of bounds (0..{total_events - 1})"
        )
    return start_idx, end_idx


OSC_COMPLETE_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
DECST8C_RE = re.compile(r"\x1b\[\?5W")


def _strip_osc_chunk(text: str, state: dict[str, bool]) -> str:
    """
    Strip OSC sequences (\\x1b]...\\x07 or \\x1b]...\\x1b\\\\) across chunk
    boundaries so split OSC 8 hyperlinks never leak path tails into pyte.
    """
    out: list[str] = []
    i = 0
    n = len(text)

    if state["pending_esc"]:
        state["pending_esc"] = False
        if state["in_osc"]:
            if text.startswith("\\"):
                state["in_osc"] = False
                i = 1
        elif text.startswith("]"):
            state["in_osc"] = True
            i = 1
        else:
            out.append("\x1b")

    while i < n:
        if state["in_osc"]:
            bel = text.find("\x07", i)
            esc = text.find("\x1b", i)
            if bel == -1 and esc == -1:
                break
            if bel != -1 and (esc == -1 or bel < esc):
                state["in_osc"] = False
                i = bel + 1
            else:
                if esc + 1 >= n:
                    state["pending_esc"] = True
                    break
                if text[esc + 1] == "\\":
                    state["in_osc"] = False
                    i = esc + 2
                elif text[esc + 1] == "]":
                    i = esc + 2
                else:
                    i = esc + 1
        else:
            esc = text.find("\x1b", i)
            if esc == -1:
                out.append(text[i:])
                break
            if esc > i:
                out.append(text[i:esc])
            if esc + 1 >= n:
                state["pending_esc"] = True
                break
            if text[esc + 1] == "]":
                state["in_osc"] = True
                i = esc + 2
            else:
                out.append("\x1b")
                i = esc + 1

    return "".join(out)


def _preprocess_for_pyte(text: str, osc_state: dict[str, bool] | None = None) -> str:
    """
    Normalize OSC sequences and DECST8C (\\x1b[?5W) before feeding pyte.Stream.
    """
    if osc_state is not None:
        cleaned = _strip_osc_chunk(text, osc_state)
    else:
        cleaned = OSC_COMPLETE_RE.sub("", text)
    # Rewrite DECST8C (\x1b[?5W) to an unused non-private W parameter because pyte
    # ignores or omits private=True on non-h/l CSI sequences.
    return DECST8C_RE.sub("\x1b[1005W", cleaned)


def _make_ghostty_emulator(pyte: Any, cols: int, rows: int) -> tuple[Any, Any]:
    """
    Create a (screen, stream) pair subclassing pyte.Screen and pyte.Stream
    with ECMA-48 CBT (Z), REP (b), and DECST8C (?5W) support for xterm-ghostty.
    """

    class GhosttyScreen(pyte.Screen):
        def __init__(self, columns: int, lines: int) -> None:
            super().__init__(columns, lines)
            self._last_drawn_char = " "

        def draw(self, data: str) -> None:
            if data:
                self._last_drawn_char = data[-1]
            super().draw(data)

        def cursor_backward_tab(self, count: int = 1) -> None:
            steps = count or 1
            stops = sorted(self.tabstops)
            x = self.cursor.x
            for _ in range(steps):
                prev = [s for s in stops if s < x]
                x = prev[-1] if prev else 0
            self.cursor.x = x

        def repeat_char(self, count: int = 1) -> None:
            repeats = count or 1
            if self._last_drawn_char:
                super().draw(self._last_drawn_char * repeats)

        def handle_tab_control(self, *args: int, private: bool = False) -> None:
            if (private and args == (5,)) or args == (1005,):
                self.tabstops = set(range(8, self.columns, 8))

    class GhosttyStream(pyte.Stream):
        csi: ClassVar[dict[str, str]] = dict(
            pyte.Stream.csi,
            Z="cursor_backward_tab",
            b="repeat_char",
            W="handle_tab_control",
        )

    screen = GhosttyScreen(cols, rows)
    stream = GhosttyStream(screen)
    return screen, stream


def simulate_screen_at_events(
    header: dict[str, Any],
    events: list[list[Any]],
    target_indices: list[int],
    skip_ranges: list[tuple[int, int]] | None = None,
) -> dict[int, tuple[int, int, list[str]]]:
    """
    Simulate the terminal screen up to max(target_indices) and return
    {idx: (cursor.y, cursor.x, display_lines)} for every index in target_indices.
    Supports idx == -1 for the initial empty screen state.
    """
    pyte = _require_pyte()
    cols, rows = _cast_dimensions(header)
    screen, stream = _make_ghostty_emulator(pyte, cols, rows)
    osc_state = {"in_osc": False, "pending_esc": False}

    results: dict[int, tuple[int, int, list[str]]] = {}
    targets = set(target_indices)
    if -1 in targets:
        results[-1] = (0, 0, [""] * rows)
    positive_targets = [idx for idx in targets if idx >= 0]
    if not positive_targets:
        return results

    max_target = max(positive_targets)
    skips = skip_ranges or []

    for idx, ev in enumerate(events):
        if idx > max_target:
            break
        if any(s <= idx <= e for s, e in skips):
            continue
        if len(ev) >= 3:
            code = ev[1]
            data = ev[2]
            if code == "o" and isinstance(data, str):
                cleaned = _preprocess_for_pyte(data, osc_state=osc_state)
                if cleaned:
                    stream.feed(cleaned)
            elif code == "r" and isinstance(data, str) and "x" in data:
                c_str, r_str = data.split("x", 1)
                if c_str.isdigit() and r_str.isdigit():
                    screen.resize(lines=int(r_str), columns=int(c_str))
        if idx in targets:
            results[idx] = (
                screen.cursor.y,
                screen.cursor.x,
                [line.rstrip() for line in screen.display],
            )
    return results


def render_events(
    header: dict[str, Any], events: list[list[Any]], specs: list[str]
) -> None:
    indices: list[int] = []
    for raw in specs:
        if not raw.strip().isdigit():
            raise ValueError(f"Invalid --render event index: {raw!r}")
        idx = int(raw.strip())
        if not (0 <= idx < len(events)):
            raise ValueError(
                f"--render event #{idx} out of range (0..{len(events) - 1})"
            )
        indices.append(idx)

    snapshots = simulate_screen_at_events(header, events, indices)
    for idx in indices:
        y, x, disp = snapshots[idx]
        print(f"=== Event #{idx:04d} (cursor y={y}, x={x}) ===")
        for row_idx, line in enumerate(disp):
            print(f"{row_idx:02d}: {line}")


def _next_sync_frame_end(
    events: list[list[Any]], version: int, after_idx: int
) -> int | None:
    start: int | None = None
    for idx in range(after_idx + 1, len(events)):
        ev = events[idx]
        if len(ev) >= 3 and ev[1] == "o":
            start = idx
            break
    if start is None:
        return None

    end_idx = start
    first_payload = str(events[start][2])
    in_sync = "\x1b[?2026h" in first_payload and "\x1b[?2026l" not in first_payload
    prev_abs = float(events[start][0]) if version != 3 else 0.0

    for idx in range(start + 1, len(events)):
        ev = events[idx]
        if len(ev) < 3 or ev[1] != "o":
            if in_sync:
                continue
            break
        dt = float(ev[0]) if version == 3 else max(0.0, float(ev[0]) - prev_abs)
        if version != 3:
            prev_abs = float(ev[0])
        if dt > 0.0 and not in_sync:
            break
        end_idx = idx
        payload = str(ev[2])
        if "\x1b[?2026h" in payload:
            in_sync = True
        if "\x1b[?2026l" in payload:
            in_sync = False
    return end_idx


def verify_strip_range(
    header: dict[str, Any],
    events: list[list[Any]],
    version: int,
    spec: str,
) -> None:
    start_idx, end_idx = _parse_range_spec(spec, len(events))
    before_idx = start_idx - 1
    next_end_idx = _next_sync_frame_end(events, version, end_idx)

    timings = compute_timings(header, events, version)
    before_raw = timings[before_idx][2] if before_idx >= 0 else 0.0
    end_raw = timings[end_idx][2]
    cut_raw = max(0.0, end_raw - before_raw)
    removed_markers = [
        (idx, str(ev[2]) if len(ev) > 2 else "")
        for idx, ev in enumerate(events[start_idx : end_idx + 1], start=start_idx)
        if len(ev) >= 2 and ev[1] == "m"
    ]

    orig_targets = [before_idx, end_idx]
    if next_end_idx is not None:
        orig_targets.append(next_end_idx)
    orig_snaps = simulate_screen_at_events(header, events, orig_targets)

    y_before, x_before, disp_before = orig_snaps[before_idx]
    y_end, x_end, disp_end = orig_snaps[end_idx]
    cursor_match = (y_before, x_before) == (y_end, x_end)

    print(
        f"Verify Strip #{start_idx:04d}..#{end_idx:04d} "
        f"({end_idx - start_idx + 1} events, raw={cut_raw:.2f}s)"
    )
    if removed_markers:
        marker_desc = ", ".join(f"#{idx:04d} {lbl!r}" for idx, lbl in removed_markers)
        print(f"  Markers inside range: {marker_desc}")
    else:
        print("  Markers inside range: (none)")
    print(
        f"  Cursor at #{before_idx if before_idx >= 0 else -1}: (y={y_before}, x={x_before}) "
        f"vs #{end_idx}: (y={y_end}, x={x_end}) -> "
        f"{'MATCH' if cursor_match else 'MISMATCH'}"
    )

    if next_end_idx is None:
        print("  Post-cut frame: (no stdout events after excised range)")
        return

    cut_snaps = simulate_screen_at_events(
        header, events, [next_end_idx], skip_ranges=[(start_idx, end_idx)]
    )
    y_next_orig, x_next_orig, disp_next_orig = orig_snaps[next_end_idx]
    y_next_cut, x_next_cut, disp_next_cut = cut_snaps[next_end_idx]

    cursor_next_ok = (y_next_orig, x_next_orig) == (y_next_cut, x_next_cut)
    screen_next_ok = disp_next_orig == disp_next_cut
    print(
        f"  Post-cut frame #{next_end_idx:04d}: "
        f"cursor orig=(y={y_next_orig}, x={x_next_orig}) "
        f"cut=(y={y_next_cut}, x={x_next_cut}) -> "
        f"{'MATCH' if cursor_next_ok else 'MISMATCH'}; "
        f"display={'IDENTICAL' if screen_next_ok else 'DIFFERS'}"
    )
    if not screen_next_ok:
        diff_rows = [
            r
            for r in range(min(len(disp_next_orig), len(disp_next_cut)))
            if disp_next_orig[r] != disp_next_cut[r]
        ]
        print(f"  Post-cut display diff rows (orig vs cut): {diff_rows}")

    before_lines = {line for line in disp_before if line}
    excised_lines = {line for line in disp_end if line} - before_lines
    leaked_rows = [
        (r, line)
        for r, line in enumerate(disp_next_cut)
        if line and line in excised_lines
    ]
    if leaked_rows:
        print(
            f"  Scrollback notice: {len(leaked_rows)} row(s) in post-cut frame "
            f"#{next_end_idx:04d} explicitly redraw text from inside #{start_idx}..#{end_idx}:"
        )
        for r, line in leaked_rows[:8]:
            print(f"    row {r:02d}: {line[:90]!r}")
        if len(leaked_rows) > 8:
            print(f"    ... (+{len(leaked_rows) - 8} more rows)")
    else:
        print(
            f"  Scrollback check: no excised lines redrawn in post-cut frame #{next_end_idx:04d}"
        )


def strip_event_range(
    events: list[list[Any]], version: int, start_idx: int, end_idx: int
) -> tuple[list[list[Any]], int, list[str], float]:
    """
    Remove events in inclusive 0-based range [start_idx, end_idx].
    Preserves relative deltas in v3 and shifts subsequent timestamps in v2.
    """
    if not (0 <= start_idx <= end_idx < len(events)):
        raise ValueError(
            f"Range {start_idx}:{end_idx} out of bounds (0..{len(events) - 1})"
        )
    removed_events = events[start_idx : end_idx + 1]
    removed_markers = [
        str(ev[2]) if len(ev) > 2 else ""
        for ev in removed_events
        if len(ev) >= 2 and ev[1] == "m"
    ]
    if version == 3:
        cut_raw = sum(float(ev[0]) for ev in removed_events)
        updated = events[:start_idx] + events[end_idx + 1 :]
    else:
        prev_abs = float(events[start_idx - 1][0]) if start_idx > 0 else 0.0
        end_abs = float(events[end_idx][0])
        cut_raw = max(0.0, end_abs - prev_abs)
        updated = events[:start_idx] + [
            [round(max(0.0, float(ev[0]) - cut_raw), 6), *ev[1:]]
            for ev in events[end_idx + 1 :]
        ]
    return updated, len(removed_events), removed_markers, cut_raw


def embed_cast_in_html(cast_path: str, html_path: str) -> None:
    cast_bytes = Path(cast_path).read_bytes()
    gz_b64 = base64.b64encode(gzip.compress(cast_bytes, compresslevel=9)).decode(
        "ascii"
    )
    target_html = Path(html_path)
    content = target_html.read_text(encoding="utf-8")
    new_content, count = re.subn(
        r'const EMBEDDED_CAST_GZ_B64 = "[^"]+";',
        f'const EMBEDDED_CAST_GZ_B64 = "{gz_b64}";',
        content,
        count=1,
    )
    if count == 0:
        raise ValueError(f"Could not find EMBEDDED_CAST_GZ_B64 in {html_path}")
    target_html.write_text(new_content, encoding="utf-8")
    print(f"Updated EMBEDDED_CAST_GZ_B64 in {html_path} ({len(gz_b64)} chars)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect, search, add, move/replace, or remove 'm' chapter markers "
            "in .cast files."
        )
    )
    parser.add_argument("input", help="Input .cast file path")
    parser.add_argument(
        "-o", "--output", help="Output .cast file path (or use --in-place)"
    )
    parser.add_argument(
        "-i", "--in-place", action="store_true", help="Modify input .cast file in place"
    )
    parser.add_argument(
        "--list", action="store_true", help="List existing 'm' markers and timestamps"
    )
    parser.add_argument(
        "--inspect",
        action="append",
        metavar="START[:END]",
        help=(
            "Inspect events in range START:END (or around event index START) "
            "with dt, raw, 1x, and stripped stdout (repeatable)"
        ),
    )
    parser.add_argument(
        "--search",
        metavar="REGEX",
        help="Search stdout events for REGEX and print event indices/timestamps",
    )
    parser.add_argument(
        "-C",
        "--context",
        type=int,
        default=0,
        metavar="N",
        help="Print N surrounding events before and after each --search match",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Remove all existing 'm' markers before adding new ones",
    )
    parser.add_argument(
        "--remove",
        action="append",
        metavar="NUM_OR_LABEL",
        help=(
            "Remove a specific marker by 1-based number (e.g. 1) or label "
            "substring (repeatable)"
        ),
    )
    parser.add_argument(
        "--set",
        nargs=3,
        action="append",
        metavar=("NUM_OR_LABEL", "WHERE", "NEW_LABEL"),
        help=(
            "Move/replace marker NUM_OR_LABEL to WHERE (regex, regex#N, "
            "@event:IDX, @time:SEC, @1x:SEC) with NEW_LABEL"
        ),
    )
    parser.add_argument(
        "--relabel", nargs="+", help="Relabel existing 'm' markers in sequence"
    )
    parser.add_argument(
        "--auto-spec",
        metavar="JSON_PATH",
        help=(
            "Auto-inject chapter markers from a JSON file "
            "(list of {'label': ..., 'pattern': ...} or [label, pattern])"
        ),
    )
    parser.add_argument(
        "--add-pattern",
        nargs=2,
        action="append",
        metavar=("REGEX", "LABEL"),
        help=(
            "Insert a marker labeled LABEL right after stdout matches REGEX "
            "(repeatable; use regex#N for Nth match)"
        ),
    )
    parser.add_argument(
        "--add-time",
        nargs=2,
        action="append",
        metavar=("SECONDS", "LABEL"),
        help=(
            "Insert a marker labeled LABEL at timestamp SECONDS "
            "(repeatable; raw time by default, or 1x with --effective-time)"
        ),
    )
    parser.add_argument(
        "--effective-time",
        action="store_true",
        help=(
            "Interpret --add-time SECONDS as idle-capped 1x playback time "
            "instead of raw elapsed time"
        ),
    )
    parser.add_argument(
        "--add-event",
        nargs=2,
        action="append",
        metavar=("EVENT_IDX", "LABEL"),
        help="Insert a marker labeled LABEL after event #EVENT_IDX (repeatable)",
    )
    parser.add_argument(
        "--before",
        action="store_true",
        help=(
            "Insert --add-pattern / --add-event / --set markers immediately "
            "before the target event instead of after"
        ),
    )
    parser.add_argument(
        "--raw-match",
        action="store_true",
        help=(
            "Disable automatic fast-forward past bracketed-paste reverse-video "
            "redraws (\\x1b[7m -> \\x1b[27m)"
        ),
    )
    parser.add_argument(
        "--set-dt",
        nargs=2,
        action="append",
        metavar=("EVENT_IDX", "SECONDS"),
        help="Set the relative delay (dt) of event #EVENT_IDX to SECONDS (repeatable)",
    )
    parser.add_argument(
        "--tighten-pastes",
        action="store_true",
        help=(
            "Shorten cut-and-paste delays ([REV] -> 1.0s, [UNREV] -> 0.15s) "
            "and agy prompt paste/submit pauses"
        ),
    )
    parser.add_argument(
        "--render",
        action="append",
        metavar="EVENT_IDX",
        help=(
            "Render the 2D terminal screen and cursor position at EVENT_IDX "
            "using pyte (repeatable; invoke with uv run --with pyte)"
        ),
    )
    parser.add_argument(
        "--verify-strip",
        action="append",
        metavar="START:END",
        help=(
            "Simulate terminal screens across candidate cut START:END using pyte "
            "and check cursor/scrollback continuity (repeatable)"
        ),
    )
    parser.add_argument(
        "--strip-range",
        action="append",
        metavar="START:END",
        help=(
            "Excise inclusive 0-based event range START:END from the stream "
            "(repeatable; shifts timestamps in v2, preserves dt in v3)"
        ),
    )
    parser.add_argument(
        "--embed-html",
        metavar="HTML_PATH",
        help=(
            "Also update EMBEDDED_CAST_GZ_B64 in the given standalone HTML player file"
        ),
    )
    args = parser.parse_args()

    header, events, version = load_cast(args.input)

    mutating = bool(
        args.clear
        or args.remove
        or args.set
        or args.relabel
        or args.auto_spec
        or args.add_pattern
        or args.add_time
        or args.add_event
        or args.set_dt
        or args.tighten_pastes
        or args.strip_range
    )

    if args.inspect:
        for spec in args.inspect:
            inspect_range(header, events, version, spec)
        if (
            not mutating
            and not args.search
            and not args.list
            and not args.render
            and not args.verify_strip
        ):
            return 0

    if args.search:
        search_events(header, events, version, args.search, context=args.context)
        if not mutating and not args.list and not args.render and not args.verify_strip:
            return 0

    if args.verify_strip:
        for spec in args.verify_strip:
            verify_strip_range(header, events, version, spec)
        if not mutating and not args.list and not args.render:
            return 0

    if args.strip_range:
        parsed_ranges = sorted(
            (_parse_range_spec(spec, len(events)) for spec in args.strip_range),
            key=lambda r: r[0],
            reverse=True,
        )
        for prev_r, next_r in itertools.pairwise(parsed_ranges):
            if next_r[1] >= prev_r[0]:
                raise ValueError(
                    f"Overlapping --strip-range specs: {next_r[0]}:{next_r[1]} and {prev_r[0]}:{prev_r[1]}"
                )
        for start_idx, end_idx in parsed_ranges:
            events, removed_cnt, removed_markers, cut_raw = strip_event_range(
                events, version, start_idx, end_idx
            )
            marker_note = (
                f", removed markers={removed_markers}" if removed_markers else ""
            )
            print(
                f"[strip-range] Removed #{start_idx:04d}..#{end_idx:04d} "
                f"({removed_cnt} events, raw={cut_raw:.2f}s{marker_note})"
            )
        if version == 2 and "duration" in header and events:
            header["duration"] = round(float(events[-1][0]), 3)

    if args.render:
        render_events(header, events, args.render)
        if not mutating and not args.list:
            return 0

    if args.list and not mutating:
        list_markers(header, events, version)
        if args.embed_html:
            embed_cast_in_html(args.input, args.embed_html)
        return 0

    if args.clear:
        before_count = sum(1 for ev in events if len(ev) >= 2 and ev[1] == "m")
        events = [ev for ev in events if not (len(ev) >= 2 and ev[1] == "m")]
        print(f"Cleared {before_count} existing marker(s).")

    if args.remove:
        for target in args.remove:
            events, removed = remove_marker_by_target(events, target)
            if removed:
                print(f"[remove] - {', '.join(removed)}")
            else:
                print(f"[remove] WARNING: no marker matched {target!r}")

    if args.set:
        for target, where_spec, new_label in args.set:
            events, msg = set_marker_by_target(
                header,
                events,
                version,
                target,
                where_spec,
                new_label,
                insert_after=not args.before,
                raw_match=args.raw_match,
            )
            print(f"[set] {msg}")

    if args.auto_spec:
        spec_markers = load_auto_spec(args.auto_spec)
        events, notes = auto_inject_markers(
            header,
            events,
            version,
            spec_markers,
            insert_after=not args.before,
            raw_match=args.raw_match,
        )
        for note in notes:
            print(f"[auto-spec] + {note}")

    if args.add_pattern:
        for raw_pat, label in args.add_pattern:
            occ = 1
            pat = raw_pat
            if "#" in raw_pat and raw_pat.rsplit("#", 1)[1].isdigit():
                pat, occ_str = raw_pat.rsplit("#", 1)
                occ = int(occ_str)
            events, idx = add_pattern_marker(
                events,
                version,
                pat,
                label,
                occurrence=occ,
                insert_after=not args.before,
                raw_match=args.raw_match,
            )
            if idx is not None:
                print(
                    f"[add-pattern] + {label!r} at event #{idx:04d} "
                    f"(pattern={pat!r}, occurrence={occ})"
                )
            else:
                print(
                    f"[add-pattern] WARNING: pattern {pat!r} "
                    f"(occurrence={occ}) not found for {label!r}"
                )

    if args.add_event:
        orig_len = len(events)
        results: dict[int, tuple[int, str, bool]] = {}
        ordered_add_events = sorted(
            enumerate(args.add_event),
            key=lambda item: (int(item[1][0]), item[0]),
            reverse=True,
        )
        for pos, (idx_str, label) in ordered_add_events:
            target_idx = int(idx_str)
            events, ok = add_event_marker(
                events, version, target_idx, label, insert_after=not args.before
            )
            results[pos] = (target_idx, label, ok)
        for pos in range(len(args.add_event)):
            target_idx, label, ok = results[pos]
            if ok:
                print(f"[add-event] + {label!r} at event #{target_idx:04d}")
            else:
                print(
                    f"[add-event] WARNING: event #{target_idx} out of range "
                    f"(0..{orig_len - 1})"
                )

    if args.add_time:
        for sec_str, label in args.add_time:
            target_sec = float(sec_str)
            events, idx = add_time_marker(
                header,
                events,
                version,
                target_sec,
                label,
                use_effective_time=args.effective_time,
            )
            mode = "1x" if args.effective_time else "raw"
            print(
                f"[add-time] + {label!r} at {mode}={target_sec:.2f}s (event #{idx:04d})"
            )

    if args.relabel:
        count = relabel_markers(events, args.relabel)
        print(f"Relabeled {count} marker(s).")

    if args.tighten_pastes:
        notes = tighten_paste_delays(events, version)
        if notes:
            for note in notes:
                print(f"[tighten-pastes] {note}")
        else:
            print("[tighten-pastes] (all paste/submit delays already tightened)")

    if args.set_dt:
        for idx_str, sec_str in args.set_dt:
            ev_idx = int(idx_str)
            new_dt = float(sec_str)
            ok, old_dt = set_event_dt(events, version, ev_idx, new_dt)
            if ok:
                print(
                    f"[set-dt] event #{ev_idx:04d}: dt {old_dt:.3f}s -> {new_dt:.3f}s"
                )
            else:
                print(f"[set-dt] WARNING: event #{ev_idx} out of range")

    list_markers(header, events, version)

    out_path = args.input if args.in_place else args.output
    if out_path:
        save_cast(out_path, header, events)
        print(f"Saved updated cast to {out_path}")
        if args.embed_html:
            embed_cast_in_html(out_path, args.embed_html)
    elif args.embed_html:
        embed_cast_in_html(args.input, args.embed_html)
    return 0


if __name__ == "__main__":
    sys.exit(main())
