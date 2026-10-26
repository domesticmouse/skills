# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "typer>=0.12.0",
# ]
# ///

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer


def clean_path_str(p_val: Any) -> str | None:
    """Clean and strip quotation marks, whitespace, and formatting from a path string."""
    if not p_val or not isinstance(p_val, str):
        return None
    val = p_val.strip("\"' \t\r\n")
    return val if val else None


def extract_workspace_from_tool_call(tc: dict[str, Any]) -> str | None:
    """Infer workspace or project root directory from a single tool call."""
    args = tc.get("args", {})
    if not isinstance(args, dict):
        return None

    # 1. Cwd in run_command or other tools
    cwd = clean_path_str(args.get("Cwd"))
    if cwd and cwd != ".":
        return cwd

    # 2. DirectoryPath in list_dir
    if tc.get("name") == "list_dir":
        dp = clean_path_str(args.get("DirectoryPath"))
        if dp and dp != ".":
            home_gemini = str(Path.home() / ".gemini")
            if not dp.startswith(home_gemini) and not dp.startswith("/tmp"):
                return dp

    # 3. AbsolutePath / TargetFile
    for k in ("AbsolutePath", "TargetFile"):
        val = clean_path_str(args.get(k))
        if val and val.startswith("/"):
            home_gemini = str(Path.home() / ".gemini")
            if not val.startswith(home_gemini) and not val.startswith("/tmp"):
                p = Path(val)
                for parent in p.parents:
                    if (parent / ".git").is_dir() or (parent / ".agents").is_dir():
                        return str(parent)
                return str(p.parent)

    return None


def get_project_name(workspace: str | None) -> str:
    """Derive a friendly project name from a workspace directory path."""
    if not workspace or workspace == "(unknown)":
        return "(no workspace)"
    clean = workspace.strip("\"' \t\r\n")
    if not clean or clean == ".":
        return "(no workspace)"
    p = Path(clean)
    name = p.name
    if name in ("src", "lib", "bin", "test", "tests", "scripts") and len(p.parents) > 1:
        name = p.parent.name
    return name or clean


@dataclass
class SessionData:
    session_dir: Path
    session_id: str
    transcript_path: Path
    transcript_full_path: Path
    steps: list[dict[str, Any]]
    full_steps: list[dict[str, Any]]
    steps_by_index: dict[int, dict[str, Any]]
    full_steps_by_index: dict[int, dict[str, Any]]

    @classmethod
    def load(cls, session_dir: Path) -> SessionData:
        session_dir = session_dir.resolve()
        if not session_dir.exists() or not session_dir.is_dir():
            raise typer.BadParameter(
                f"Directory '{session_dir}' does not exist or is not a directory."
            )

        logs_dir = session_dir / ".system_generated" / "logs"
        transcript_path = logs_dir / "transcript.jsonl"
        transcript_full_path = logs_dir / "transcript_full.jsonl"

        if not transcript_path.exists() and not transcript_full_path.exists():
            raise typer.BadParameter(
                f"Directory '{session_dir}' does not appear to be an Antigravity session "
                f"(missing {transcript_path})."
            )

        steps: list[dict[str, Any]] = []
        if transcript_path.exists():
            with open(transcript_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        steps.append(json.loads(line))

        full_steps: list[dict[str, Any]] = []
        if transcript_full_path.exists():
            with open(transcript_full_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        full_steps.append(json.loads(line))
        else:
            full_steps = steps

        if not steps and full_steps:
            steps = full_steps

        steps_by_index = {s["step_index"]: s for s in steps if "step_index" in s}
        full_steps_by_index = {
            s["step_index"]: s for s in full_steps if "step_index" in s
        }

        return cls(
            session_dir=session_dir,
            session_id=session_dir.name,
            transcript_path=transcript_path,
            transcript_full_path=transcript_full_path,
            steps=steps,
            full_steps=full_steps,
            steps_by_index=steps_by_index,
            full_steps_by_index=full_steps_by_index,
        )

    def get_step_output_file(self, step_index: int) -> Path | None:
        p = (
            self.session_dir
            / ".system_generated"
            / "steps"
            / str(step_index)
            / "output.txt"
        )
        return p if p.exists() else None

    def get_user_request_clean(self) -> str:
        for s in self.steps:
            if s.get("type") == "USER_INPUT":
                content = s.get("content", "")
                m = re.search(
                    r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", content, re.DOTALL
                )
                if m:
                    return m.group(1).strip()
                return content.strip()
        return "(none)"

    def get_user_requests(self) -> list[str]:
        reqs: list[str] = []
        for s in self.steps:
            if s.get("type") == "USER_INPUT":
                content = s.get("content", "")
                m = re.search(
                    r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", content, re.DOTALL
                )
                if m:
                    reqs.append(m.group(1).strip())
                elif content.strip():
                    reqs.append(content.strip())
        return reqs

    def get_last_model_response(self) -> str:
        for s in reversed(self.steps):
            if s.get("type") == "PLANNER_RESPONSE":
                content = s.get("content", "")
                if content and content.strip():
                    return content.strip()
        return "(none)"

    def get_tool_counts(self) -> dict[str, int]:
        tool_counts: dict[str, int] = {}
        for s in self.full_steps:
            for tc in s.get("tool_calls", []):
                name = tc.get("name", "unknown")
                tool_counts[name] = tool_counts.get(name, 0) + 1
        return tool_counts

    def get_start_and_end_times(self) -> tuple[datetime | None, datetime | None, str]:
        start_time: datetime | None = None
        end_time: datetime | None = None
        if self.steps:
            with contextlib.suppress(ValueError, TypeError):
                start_time = datetime.fromisoformat(self.steps[0].get("created_at", ""))
                end_time = datetime.fromisoformat(self.steps[-1].get("created_at", ""))
        duration_str = (
            str(end_time - start_time) if (start_time and end_time) else "unknown"
        )
        return start_time, end_time, duration_str

    def get_modified_files(self) -> list[str]:
        files: list[str] = []
        for s in self.full_steps:
            for tc in s.get("tool_calls", []):
                if tc.get("name") in ("write_to_file", "replace_file_content"):
                    args = tc.get("args", {})
                    tgt = args.get("TargetFile")
                    if tgt and tgt not in files:
                        files.append(tgt)
        return files

    def get_metadata_info(self) -> dict[str, str]:
        meta: dict[str, str] = {}
        for s in self.steps:
            if s.get("type") == "USER_INPUT":
                content = s.get("content", "")
                # Model selection
                m_model = re.search(
                    r"setting `Model Selection` from .*? to ([^\n\r]+?)\.\s*No need",
                    content,
                )
                if m_model:
                    meta["Model"] = m_model.group(1).strip()
                # Local time
                m_time = re.search(r"The current local time is:\s*([^\n\r.]+)", content)
                if m_time:
                    meta["Local Time"] = m_time.group(1).strip()
                # Mentions (exclude template keyword 'ITEM' and deduplicate)
                all_mentions = re.findall(r"@\[([^\]]+)\]", content)
                filtered_mentions = list(
                    dict.fromkeys(m for m in all_mentions if m != "ITEM")
                )
                if filtered_mentions:
                    meta["Mentioned Items"] = ", ".join(filtered_mentions)
                break

        # Workspace & Project detection from tool calls
        for s in self.full_steps:
            for tc in s.get("tool_calls", []):
                ws = extract_workspace_from_tool_call(tc)
                if ws:
                    meta["Workspace"] = ws
                    meta["Project"] = get_project_name(ws)
                    break
            if "Workspace" in meta:
                break
        return meta


def sanitize_md_cell(text: str | None) -> str:
    """Sanitize text for use inside a Markdown table cell."""
    if not text:
        return ""
    return (
        text.replace("\r\n", " ")
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("|", "\\|")
        .strip()
    )


@dataclass
class TraceSummary:
    session_id: str
    source_brain: str
    session_dir: Path
    created_at: str
    created_dt: datetime | None
    updated_at: str
    step_count: int
    user_request: str
    full_user_request: str = ""
    model: str | None = None
    workspace: str | None = None
    project: str | None = None


def extract_snippet(text: str, query: str, max_length: int = 120) -> str:
    """Extract an excerpt of text surrounding the query match."""
    if not text:
        return ""
    clean = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").strip()
    idx = clean.lower().find(query.lower())
    if idx == -1:
        return clean[:max_length] + ("..." if len(clean) > max_length else "")
    start = max(0, idx - 35)
    end = min(len(clean), idx + len(query) + 55)
    snippet = clean[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(clean):
        snippet = snippet + "..."
    return snippet


def step_matches_query(step: dict[str, Any], query: str) -> tuple[bool, str]:
    """Check if a step matches the query and return (matched, description/snippet)."""
    q = query.lower()

    # Check tool calls
    for tc in step.get("tool_calls", []):
        name = tc.get("name", "")
        args = tc.get("args", {})
        cmd = args.get("CommandLine", "")
        path = args.get("AbsolutePath", "") or args.get("TargetFile", "")
        action = args.get("toolAction", "")
        summary = args.get("toolSummary", "")
        args_dump = json.dumps(args, ensure_ascii=False)
        if (
            q in name.lower()
            or q in cmd.lower()
            or q in path.lower()
            or q in action.lower()
            or q in summary.lower()
            or q in args_dump.lower()
        ):
            target = cmd or path or action or summary or name
            snippet = extract_snippet(target, query, max_length=100)
            return True, f"`{name}`: {snippet}"

    # Check content
    content = step.get("content", "")
    if content and q in content.lower():
        m = re.search(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", content, re.DOTALL)
        text = m.group(1).strip() if m else content
        return True, extract_snippet(text, query, max_length=120)

    # Check thinking
    thinking = step.get("thinking", "")
    if thinking and q in thinking.lower():
        return True, f"[thinking] {extract_snippet(thinking, query, max_length=120)}"

    return False, ""


def format_datetime_display(dt: datetime | None, raw_str: str) -> str:
    """Format datetime for Markdown display in user local time if possible."""
    if dt is not None:
        with contextlib.suppress(ValueError, OSError):
            if dt.tzinfo is not None:
                local_dt = dt.astimezone()
                return local_dt.strftime("%Y-%m-%d %H:%M")
            return dt.strftime("%Y-%m-%d %H:%M")
    return raw_str.replace("T", " ")[:16]


def find_all_brain_directories() -> list[Path]:
    """Discover all brain directories under ~/.gemini/ (e.g. antigravity, antigravity-cli, antigravity-acp)."""
    gemini_dir = Path.home() / ".gemini"
    if not gemini_dir.is_dir():
        return []

    found: dict[Path, None] = {}
    # First search for antigravity*/brain
    for ag_dir in sorted(gemini_dir.glob("antigravity*")):
        brain = ag_dir / "brain"
        if brain.is_dir():
            found[brain.resolve()] = None

    # Also search for any other brain directories under ~/.gemini
    try:
        for brain in gemini_dir.glob("**/brain"):
            if brain.is_dir():
                found[brain.resolve()] = None
    except OSError:
        pass

    return list(found.keys())


def discover_traces(
    brain_filter: str | None = None,
    project_filter: str | None = None,
    asc: bool = False,
    query: str | None = None,
) -> list[TraceSummary]:
    """Scan all brain directories under ~/.gemini and return traces sorted chronologically by creation date/time."""
    brain_dirs = find_all_brain_directories()
    traces: list[TraceSummary] = []

    for brain in brain_dirs:
        source_brain = brain.parent.name
        if brain_filter and brain_filter.lower() not in source_brain.lower():
            continue

        try:
            entries = list(brain.iterdir())
        except OSError:
            continue

        for s in entries:
            if not s.is_dir():
                continue
            logs = s / ".system_generated" / "logs"
            t_compact = logs / "transcript.jsonl"
            t_full = logs / "transcript_full.jsonl"

            # Prefer compact for quick indexing, fallback to full
            t_file = (
                t_compact
                if t_compact.exists()
                else (t_full if t_full.exists() else None)
            )
            if not t_file:
                continue

            first_created_str: str | None = None
            last_created_str: str | None = None
            first_created_dt: datetime | None = None
            user_req: str | None = None
            model_name: str | None = None
            ws_path: str | None = None
            step_count = 0

            with (
                contextlib.suppress(json.JSONDecodeError, OSError, UnicodeDecodeError),
                open(t_file, encoding="utf-8") as f,
            ):
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    step_count += 1
                    d = json.loads(line)

                    if "created_at" in d:
                        last_created_str = d["created_at"]
                        if first_created_str is None:
                            first_created_str = d["created_at"]

                    if user_req is None and d.get("type") == "USER_INPUT":
                        content = d.get("content", "")
                        m = re.search(
                            r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>",
                            content,
                            re.DOTALL,
                        )
                        if m:
                            user_req = m.group(1).strip()
                        else:
                            lines = content.strip().splitlines()
                            user_req = lines[0].strip() if lines else "(none)"
                        m_model = re.search(
                            r"setting `Model Selection` from .*? to ([^\n\r]+?)\.\s*No need",
                            content,
                        )
                        if m_model:
                            model_name = m_model.group(1).strip()

                    if ws_path is None:
                        for tc in d.get("tool_calls", []):
                            ws_path = extract_workspace_from_tool_call(tc)
                            if ws_path:
                                break

            clean_full_req = (user_req or "(none)").replace("\n", " ").strip()
            if query and query.lower() not in clean_full_req.lower():
                continue

            proj_name = get_project_name(ws_path)
            if project_filter:
                pf = project_filter.lower().strip()
                matches_proj = pf in proj_name.lower() or (
                    ws_path is not None and pf in ws_path.lower()
                )
                if not matches_proj:
                    continue

            if first_created_str:
                with contextlib.suppress(ValueError, TypeError):
                    first_created_dt = datetime.fromisoformat(first_created_str)

            if first_created_dt is None:
                with contextlib.suppress(OSError, ValueError):
                    st = s.stat()
                    first_created_dt = datetime.fromtimestamp(st.st_ctime, tz=UTC)
                    first_created_str = first_created_dt.isoformat()

            if last_created_str is None:
                with contextlib.suppress(OSError, ValueError):
                    last_created_str = datetime.fromtimestamp(
                        s.stat().st_mtime, tz=UTC
                    ).isoformat()

            traces.append(
                TraceSummary(
                    session_id=s.name,
                    source_brain=source_brain,
                    session_dir=s,
                    created_at=first_created_str or "",
                    created_dt=first_created_dt,
                    updated_at=last_created_str or "",
                    step_count=step_count,
                    user_request=clean_full_req[:90],
                    full_user_request=clean_full_req,
                    model=model_name,
                    workspace=ws_path,
                    project=proj_name,
                )
            )

    def sort_key(t: TraceSummary) -> float:
        if t.created_dt:
            return t.created_dt.timestamp()
        return 0.0

    traces.sort(key=sort_key, reverse=not asc)
    return traces


def find_session_directory(session_arg: str) -> Path:
    """Resolve session_arg to a directory by checking:

    1. Explicit path (relative or absolute, expanded)
    2. Local directory in CWD
    3. Exact and prefix matches in all ~/.gemini/**/brain/ directories
    """
    raw_path = Path(session_arg).expanduser()
    try:
        resolved_path = raw_path.resolve()
    except OSError:
        resolved_path = raw_path

    # Check direct path first
    if resolved_path.is_dir():
        logs_dir = resolved_path / ".system_generated" / "logs"
        if (logs_dir / "transcript.jsonl").exists() or (
            logs_dir / "transcript_full.jsonl"
        ).exists():
            return resolved_path

    # Check relative to CWD
    local_path = (Path.cwd() / session_arg).resolve()
    if local_path.is_dir():
        logs_dir = local_path / ".system_generated" / "logs"
        if (logs_dir / "transcript.jsonl").exists() or (
            logs_dir / "transcript_full.jsonl"
        ).exists():
            return local_path

    # Search across all brain directories in ~/.gemini
    brain_dirs = find_all_brain_directories()

    # 1. Exact match in brain directories
    exact_matches: list[Path] = []
    for brain in brain_dirs:
        target = brain / session_arg
        if target.is_dir():
            exact_matches.append(target)

    if len(exact_matches) == 1:
        return exact_matches[0]
    elif len(exact_matches) > 1:
        return max(exact_matches, key=lambda p: p.stat().st_mtime)

    # 2. Prefix / partial match in brain directories
    clean_arg = session_arg.lower().strip()
    partial_matches: list[Path] = []
    for brain in brain_dirs:
        try:
            for entry in brain.iterdir():
                if entry.is_dir() and entry.name.lower().startswith(clean_arg):
                    partial_matches.append(entry)
        except PermissionError:
            continue

    if len(partial_matches) == 1:
        return partial_matches[0]
    elif len(partial_matches) > 1:
        match_list = "\n  - ".join(
            f"{p.name} ({p.parent.parent.name})" for p in partial_matches[:10]
        )
        raise typer.BadParameter(
            f"Multiple sessions matched '{session_arg}':\n  - {match_list}\n"
            "Please specify the full session ID or an explicit path."
        )

    # If resolved_path exists as a dir, return it so SessionData.load can give a specific missing transcript error
    if resolved_path.is_dir():
        return resolved_path

    searched_dirs = (
        "\n  - ".join(str(b) for b in brain_dirs) if brain_dirs else "(none found)"
    )
    raise typer.BadParameter(
        f"Session '{session_arg}' could not be found as a directory path or inside Antigravity brain folders.\n"
        f"Checked path: {resolved_path}\n"
        f"Searched brain folders:\n  - {searched_dirs}"
    )


# ---------------------------------------------------------------------------
# Explorer Presentation & CLI
# ---------------------------------------------------------------------------


def run_interactive_session_picker(traces: list[TraceSummary]) -> None:
    """Allow interactive selection and exploration of traces."""
    print("\nInteractive Trace Explorer")
    while True:
        try:
            choice = input(
                f"\nEnter trace #[1-{len(traces)}] or session ID to inspect (q to quit): "
            ).strip()
        except (KeyboardInterrupt, EOFError):
            break

        if choice.lower() in ("q", "quit", "exit"):
            break
        if not choice:
            continue

        selected_trace: TraceSummary | None = None
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(traces):
                selected_trace = traces[idx - 1]
            else:
                print(
                    f"Error: Index {idx} out of range (1-{len(traces)}).",
                    file=sys.stderr,
                )
                continue
        else:
            matches = [
                t for t in traces if t.session_id.lower().startswith(choice.lower())
            ]
            if len(matches) == 1:
                selected_trace = matches[0]
            elif len(matches) > 1:
                print(
                    f"Error: Multiple traces match '{choice}'. Please provide more characters.",
                    file=sys.stderr,
                )
                continue
            else:
                print(
                    f"Error: No trace matches '{choice}'.",
                    file=sys.stderr,
                )
                continue

        print(
            f"\nSelected session: {selected_trace.session_id} ({selected_trace.source_brain})"
        )
        session_data = SessionData.load(selected_trace.session_dir)

        action = (
            input(
                "Action: [1] Summary (default), [2] Steps, [3] Tools, [4] Commands, [b] Back: "
            )
            .strip()
            .lower()
        )

        if action in ("b", "back"):
            continue
        elif action in ("2", "steps", "s"):
            show_steps(session_data, limit=30)
        elif action in ("3", "tools", "t"):
            show_tools(session_data)
        elif action in ("4", "commands", "c"):
            show_commands(session_data)
        else:
            show_summary(session_data)


def run_explorer(
    limit: int | None = 30,
    asc: bool = False,
    brain_filter: str | None = None,
    project_filter: str | None = None,
    query: str | None = None,
    by_project: bool = False,
    interactive: bool = False,
) -> None:
    """List all traces in Markdown ordered chronologically or grouped by project."""
    traces = discover_traces(
        brain_filter=brain_filter,
        project_filter=project_filter,
        asc=asc,
        query=query,
    )

    if not traces:
        print("*No Antigravity conversation traces found under ~/.gemini.*")
        filters = []
        if brain_filter:
            filters.append(f"`--brain {brain_filter}`")
        if project_filter:
            filters.append(f"`--project {project_filter}`")
        if query:
            filters.append(f"`--query {query}`")
        if filters:
            print(f"\n*Filters applied: {', '.join(filters)}*")
        return

    if by_project:
        # Group traces by project
        project_groups: dict[str, list[TraceSummary]] = {}
        for t in traces:
            p_name = t.project or "(no workspace)"
            project_groups.setdefault(p_name, []).append(t)

        def proj_sort_key(item: tuple[str, list[TraceSummary]]) -> float:
            _, p_traces = item
            times = [t.created_dt.timestamp() for t in p_traces if t.created_dt]
            return max(times) if times else 0.0

        sorted_groups = sorted(
            project_groups.items(), key=proj_sort_key, reverse=not asc
        )

        header = f"### Antigravity Conversation Traces Grouped by Project ({len(traces)} sessions across {len(sorted_groups)} projects"
        if brain_filter:
            header += f", brain: `{brain_filter}`"
        if project_filter:
            header += f", project: `{project_filter}`"
        if query:
            header += f", query: `{query}`"
        header += ")\n"
        print(header)

        total_shown = 0
        for p_name, p_traces in sorted_groups:
            if limit and total_shown >= limit:
                print(f"*(Remaining projects/sessions omitted due to limit {limit})*\n")
                break

            ws_candidates = [t.workspace for t in p_traces if t.workspace]
            primary_ws = ws_candidates[0] if ws_candidates else None
            ws_link = (
                f"[`{primary_ws}`](file://{primary_ws})"
                if primary_ws
                else "*(no workspace)*"
            )
            latest_dt = (
                p_traces[0].created_dt
                if (p_traces and p_traces[0].created_dt)
                else None
            )
            latest_str = (
                format_datetime_display(latest_dt, p_traces[0].created_at)
                if p_traces
                else "unknown"
            )

            print(f"#### Project: `{p_name}` ({len(p_traces)} sessions)")
            print(f"- **Workspace**: {ws_link}")
            print(f"- **Latest Activity**: {latest_str}\n")

            traces_to_show = p_traces
            if limit:
                remaining_budget = limit - total_shown
                traces_to_show = p_traces[:remaining_budget]

            print("| # | Created | Brain | Session ID | Steps | User Request |")
            print("| :--- | :--- | :--- | :--- | :---: | :--- |")
            for idx, t in enumerate(traces_to_show, 1):
                created_display = format_datetime_display(t.created_dt, t.created_at)
                if query:
                    req_display = extract_snippet(
                        t.full_user_request or t.user_request, query, max_length=120
                    )
                else:
                    req_display = t.user_request[:100]
                req_sanitized = sanitize_md_cell(req_display)
                session_link = (
                    f"`{t.session_id[:8]}` [↗](conversation://{t.session_id})"
                )
                print(
                    f"| {idx} | {created_display} | {t.source_brain} | {session_link} | {t.step_count} | {req_sanitized} |"
                )
            print()
            total_shown += len(traces_to_show)

        if limit and len(traces) > limit:
            print(
                f"*Showing {total_shown} of {len(traces)} traces. Use `--all` or `--limit` to show more.*"
            )

        if interactive:
            run_interactive_session_picker(traces[:limit] if limit else traces)
        return

    traces_to_show = traces[:limit] if limit else traces
    order_str = "oldest first" if asc else "newest first"
    header = f"### Antigravity Conversation Traces ({len(traces)} total"
    if brain_filter:
        header += f", filter: `{brain_filter}`"
    if project_filter:
        header += f", project: `{project_filter}`"
    if query:
        header += f", query: `{query}`"
    header += f", {order_str})\n"
    print(header)
    print("| # | Created | Brain | Project | Session ID | Steps | User Request |")
    print("| :--- | :--- | :--- | :--- | :--- | :---: | :--- |")
    for idx, t in enumerate(traces_to_show, 1):
        created_display = format_datetime_display(t.created_dt, t.created_at)
        if query:
            req_display = extract_snippet(
                t.full_user_request or t.user_request, query, max_length=120
            )
        else:
            req_display = t.user_request[:100]
        req_sanitized = sanitize_md_cell(req_display)
        session_link = f"`{t.session_id[:8]}` [↗](conversation://{t.session_id})"
        proj_display = f"`{t.project}`" if t.project else "*(none)*"
        print(
            f"| {idx} | {created_display} | {t.source_brain} | {proj_display} | {session_link} | {t.step_count} | {req_sanitized} |"
        )
    if limit and len(traces) > limit:
        print(
            f"\n*Showing {len(traces_to_show)} of {len(traces)} traces. Use `--all` or `--limit` to show more.*"
        )

    if interactive:
        run_interactive_session_picker(traces_to_show)


def run_projects_overview(
    brain_filter: str | None = None,
    project_query: str | None = None,
    limit: int | None = None,
    asc: bool = False,
) -> None:
    """Display an overview table of all discovered projects across sessions."""
    traces = discover_traces(brain_filter=brain_filter, asc=asc)
    if not traces:
        print("*No Antigravity conversation traces found under ~/.gemini.*")
        return

    # If project_query is passed, filter and show grouped traces directly
    if project_query:
        run_explorer(
            limit=limit,
            asc=asc,
            brain_filter=brain_filter,
            project_filter=project_query,
            by_project=True,
        )
        return

    groups: dict[str, list[TraceSummary]] = {}
    for t in traces:
        p_name = t.project or "(no workspace)"
        groups.setdefault(p_name, []).append(t)

    def proj_sort_key(item: tuple[str, list[TraceSummary]]) -> float:
        _, p_traces = item
        times = [t.created_dt.timestamp() for t in p_traces if t.created_dt]
        return max(times) if times else 0.0

    sorted_groups = sorted(groups.items(), key=proj_sort_key, reverse=not asc)
    groups_to_show = sorted_groups[:limit] if limit else sorted_groups

    header = f"### Discovered Projects Across Antigravity Sessions ({len(sorted_groups)} projects, {len(traces)} sessions total"
    if brain_filter:
        header += f", brain: `{brain_filter}`"
    header += ")\n"
    print(header)

    print("| # | Project | Workspace Path | Sessions | Last Active | Latest Session |")
    print("| :--- | :--- | :--- | :---: | :--- | :--- |")
    for idx, (p_name, p_traces) in enumerate(groups_to_show, 1):
        ws_candidates = [t.workspace for t in p_traces if t.workspace]
        primary_ws = ws_candidates[0] if ws_candidates else None
        ws_display = (
            f"[`{primary_ws}`](file://{primary_ws})"
            if primary_ws
            else "*(no workspace)*"
        )
        latest_t = p_traces[0]
        latest_dt = latest_t.created_dt
        last_active = format_datetime_display(latest_dt, latest_t.created_at)
        latest_link = (
            f"`{latest_t.session_id[:8]}` [↗](conversation://{latest_t.session_id})"
        )
        print(
            f"| {idx} | `{p_name}` | {ws_display} | {len(p_traces)} | {last_active} | {latest_link} |"
        )

    if limit and len(sorted_groups) > limit:
        print(
            f"\n*Showing {len(groups_to_show)} of {len(sorted_groups)} projects. Use `--all` or `--limit` to show more.*"
        )

    print(
        "\n*Tip: Run `projects <project_name>` or `--project <project_name> --by-project` to view sessions in a project.*"
    )


explorer_app = typer.Typer(
    help=(
        "Antigravity Session & Trace Exploration CLI: explore all conversation traces across "
        "~/.gemini brain directories, or inspect specific session transcripts, tool calls, and execution steps."
    ),
    no_args_is_help=False,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@explorer_app.callback(invoke_without_command=True)
def explorer_callback(
    ctx: typer.Context,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            "-n",
            help="Limit number of traces displayed (default: 30).",
        ),
    ] = 30,
    all_traces: Annotated[
        bool,
        typer.Option(
            "--all",
            "-a",
            help="Show all discovered traces without pagination limit.",
        ),
    ] = False,
    asc: Annotated[
        bool,
        typer.Option(
            "--asc",
            help="Order traces oldest first (default: newest first).",
        ),
    ] = False,
    brain: Annotated[
        str | None,
        typer.Option(
            "--brain",
            "-b",
            help="Filter traces by brain root directory name (e.g. 'antigravity-cli').",
        ),
    ] = None,
    project: Annotated[
        str | None,
        typer.Option(
            "--project",
            "-p",
            help="Filter traces by project/workspace name or path.",
        ),
    ] = None,
    by_project: Annotated[
        bool,
        typer.Option(
            "--by-project",
            "--group-by-project",
            help="Group discovered traces by project in the Markdown output.",
        ),
    ] = False,
    query: Annotated[
        str | None,
        typer.Option(
            "--query",
            "-q",
            "--search",
            "-s",
            help="Filter traces by text occurring in the initial user request.",
        ),
    ] = None,
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output trace listing as Markdown formatted content.",
        ),
    ] = True,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive",
            "-i",
            help="Interactively select a session from the list to inspect.",
        ),
    ] = False,
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    effective_limit = None if all_traces else limit
    run_explorer(
        limit=effective_limit,
        asc=asc,
        brain_filter=brain,
        project_filter=project,
        query=query,
        by_project=by_project,
        interactive=interactive,
    )


@explorer_app.command(name="projects")
def cmd_explorer_projects(
    project_query: Annotated[
        str | None,
        typer.Argument(
            help="Optional project name or keyword to inspect sessions for.",
        ),
    ] = None,
    brain: Annotated[
        str | None,
        typer.Option(
            "--brain",
            "-b",
            help="Filter traces by brain root directory name (e.g. 'antigravity-cli').",
        ),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            "-n",
            help="Limit number of projects or sessions displayed.",
        ),
    ] = None,
    all_projects: Annotated[
        bool,
        typer.Option(
            "--all",
            "-a",
            help="Show all projects and sessions without pagination limit.",
        ),
    ] = False,
    asc: Annotated[
        bool,
        typer.Option(
            "--asc",
            help="Order projects oldest first (default: newest first).",
        ),
    ] = False,
) -> None:
    """List all projects across discovered sessions, or inspect sessions within a specific project."""
    effective_limit = None if all_projects else limit
    run_projects_overview(
        brain_filter=brain,
        project_query=project_query,
        limit=effective_limit,
        asc=asc,
    )


@explorer_app.command(name="search")
def cmd_explorer_search(
    query: Annotated[
        str,
        typer.Argument(help="Search query text or keyword."),
    ],
    all_steps: Annotated[
        bool,
        typer.Option(
            "--all-steps",
            "-s",
            help="Deep search across all conversation steps (user requests, model responses, tool invocations, commands). Default searches initial user request only.",
        ),
    ] = False,
    brain: Annotated[
        str | None,
        typer.Option(
            "--brain",
            "-b",
            help="Filter search to specific brain root directory (e.g. 'antigravity-cli').",
        ),
    ] = None,
    project: Annotated[
        str | None,
        typer.Option(
            "--project",
            "-p",
            help="Filter search to specific project name or workspace path.",
        ),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            "-n",
            help="Limit number of results returned (default: 30).",
        ),
    ] = 30,
    all_results: Annotated[
        bool,
        typer.Option(
            "--all",
            "-a",
            help="Return all results without pagination limit.",
        ),
    ] = False,
) -> None:
    """Search conversation sessions by initial prompt, or deeply across all steps."""
    effective_limit = None if all_results else limit

    if not all_steps:
        traces = discover_traces(
            brain_filter=brain, project_filter=project, query=query
        )
        header = f'### Session Search Results for "{query}" in Initial User Requests ({len(traces)} sessions found'
        if brain:
            header += f", brain: `{brain}`"
        if project:
            header += f", project: `{project}`"
        header += ")\n"
        print(header)

        if not traces:
            print("*No sessions matched your query in their initial user prompt.*")
            return

        traces_to_show = traces[:effective_limit] if effective_limit else traces
        print("| # | Created | Brain | Session ID | Steps | Matched User Request |")
        print("| :--- | :--- | :--- | :--- | :---: | :--- |")
        for idx, t in enumerate(traces_to_show, 1):
            created_display = format_datetime_display(t.created_dt, t.created_at)
            req_text = t.full_user_request or t.user_request
            snippet = extract_snippet(req_text, query, max_length=120)
            session_link = f"`{t.session_id[:8]}` [↗](conversation://{t.session_id})"
            print(
                f"| {idx} | {created_display} | {t.source_brain} | {session_link} | {t.step_count} | {sanitize_md_cell(snippet)} |"
            )

        if effective_limit and len(traces) > effective_limit:
            print(
                f"\n*Showing {len(traces_to_show)} of {len(traces)} sessions. Use `--all` or `--limit` to show more.*"
            )
    else:
        brain_dirs = find_all_brain_directories()
        step_matches: list[dict[str, Any]] = []

        for b in brain_dirs:
            source_brain = b.parent.name
            if brain and brain.lower() not in source_brain.lower():
                continue
            try:
                entries = list(b.iterdir())
            except OSError:
                continue

            for s_dir in entries:
                if not s_dir.is_dir():
                    continue
                logs = s_dir / ".system_generated" / "logs"
                t_compact = logs / "transcript.jsonl"
                t_full = logs / "transcript_full.jsonl"
                t_file = (
                    t_compact
                    if t_compact.exists()
                    else (t_full if t_full.exists() else None)
                )
                if not t_file:
                    continue

                with (
                    contextlib.suppress(
                        json.JSONDecodeError, OSError, UnicodeDecodeError
                    ),
                    open(t_file, encoding="utf-8") as f,
                ):
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        step_data = json.loads(line)
                        matched, desc = step_matches_query(step_data, query)
                        if matched:
                            step_matches.append(
                                {
                                    "session_id": s_dir.name,
                                    "source_brain": source_brain,
                                    "step_index": step_data.get("step_index", 0),
                                    "type": step_data.get("type", ""),
                                    "created_at": step_data.get("created_at", ""),
                                    "desc": desc,
                                }
                            )

        header = f'### Deep Search Results for "{query}" across All Steps ({len(step_matches)} steps matched'
        if brain:
            header += f", brain: `{brain}`"
        header += ")\n"
        print(header)

        if not step_matches:
            print("*No steps matched your query across discovered sessions.*")
            return

        to_show = step_matches[:effective_limit] if effective_limit else step_matches
        print("| # | Session ID | Brain | Step | Type | Matched Excerpt |")
        print("| :--- | :--- | :--- | :---: | :--- | :--- |")
        for idx, m in enumerate(to_show, 1):
            session_link = (
                f"`{m['session_id'][:8]}` [↗](conversation://{m['session_id']})"
            )
            clean_desc = sanitize_md_cell(m["desc"])
            print(
                f"| {idx} | {session_link} | {m['source_brain']} | {m['step_index']} | {m['type']} | {clean_desc} |"
            )

        if effective_limit and len(step_matches) > effective_limit:
            print(
                f"\n*Showing {len(to_show)} of {len(step_matches)} matches. Use `--all` or `--limit` to show more.*"
            )


@explorer_app.command(name="compare")
def cmd_explorer_compare(
    session1: Annotated[
        str,
        typer.Argument(help="First session ID or directory path."),
    ],
    session2: Annotated[
        str,
        typer.Argument(help="Second session ID or directory path."),
    ],
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output results as Markdown formatted content.",
        ),
    ] = True,
) -> None:
    """Compare two sessions side-by-side (timing, steps, tools, prompts, outcomes)."""
    dir1 = find_session_directory(session1)
    dir2 = find_session_directory(session2)
    s1 = SessionData.load(dir1)
    s2 = SessionData.load(dir2)
    show_comparison(s1, s2)


@explorer_app.command(name="paths")
def cmd_explorer_paths(
    sessions: Annotated[
        list[str],
        typer.Argument(
            metavar="SESSIONS...",
            help="One or more session IDs or directory paths.",
        ),
    ],
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output results as Markdown formatted content.",
        ),
    ] = True,
) -> None:
    """Show on-disk directory paths and transcript file locations for one or more sessions."""
    sessions_data = []
    for s_arg in sessions:
        s_dir = find_session_directory(s_arg)
        sessions_data.append(SessionData.load(s_dir))

    if len(sessions_data) > 1:
        show_paths_multi(sessions_data)
    elif sessions_data:
        show_paths(sessions_data[0])


def move_session_to_trash(session_dir: Path) -> Path:
    """Move session directory to macOS ~/.Trash or fallback ~/.gemini/.trash with collision avoidance."""
    trash_dir = Path.home() / ".Trash"
    if not (trash_dir.exists() and trash_dir.is_dir()):
        trash_dir = Path.home() / ".gemini" / ".trash"
        trash_dir.mkdir(parents=True, exist_ok=True)

    dest = trash_dir / session_dir.name
    count = 1
    while dest.exists():
        dest = trash_dir / f"{session_dir.name}_{count}"
        count += 1

    shutil.move(str(session_dir), str(dest))
    return dest


def resolve_sessions_for_deletion(
    targets: list[str] | None = None,
    project_filter: str | None = None,
    brain_filter: str | None = None,
) -> tuple[list[tuple[Path, TraceSummary | None]], list[str]]:
    """Resolve targets (session IDs, hashes, paths, or project names) and/or project_filter to matching session directories."""
    all_traces = discover_traces(brain_filter=brain_filter)
    trace_by_dir: dict[Path, TraceSummary] = {
        t.session_dir.resolve(): t for t in all_traces
    }
    trace_by_id: dict[str, TraceSummary] = {t.session_id: t for t in all_traces}

    # Map project names and workspaces (case-insensitive) to traces
    traces_by_project: dict[str, list[TraceSummary]] = {}
    for t in all_traces:
        p_name = (t.project or "(no workspace)").lower().strip()
        traces_by_project.setdefault(p_name, []).append(t)
        if t.workspace:
            traces_by_project.setdefault(t.workspace.lower().strip(), []).append(t)

    resolved: dict[Path, TraceSummary | None] = {}
    not_found: list[str] = []

    # 1. Handle explicit project_filter option
    if project_filter:
        pf_clean = project_filter.lower().strip()
        matched_traces: list[TraceSummary] = []
        if pf_clean in traces_by_project:
            matched_traces = traces_by_project[pf_clean]
        else:
            # Substring match across project names and workspaces
            matched_traces = [
                t
                for t in all_traces
                if pf_clean in (t.project or "").lower()
                or (t.workspace and pf_clean in t.workspace.lower())
            ]
        if matched_traces:
            for t in matched_traces:
                resolved[t.session_dir.resolve()] = t
        else:
            not_found.append(f"Project '{project_filter}'")

    # 2. Handle positional targets
    if targets:
        for target in targets:
            target_clean = target.strip()
            # Try 1: Is target a valid session path or ID / prefix?
            s_dir_resolved: Path | None = None
            with contextlib.suppress(typer.BadParameter, OSError):
                s_dir = find_session_directory(target_clean)
                s_dir_resolved = s_dir.resolve()
                tr = trace_by_dir.get(s_dir_resolved) or trace_by_id.get(s_dir.name)
                if tr is None and s_dir_resolved.exists():
                    with contextlib.suppress(
                        typer.BadParameter, OSError, json.JSONDecodeError
                    ):
                        s_data = SessionData.load(s_dir_resolved)
                        meta = s_data.get_metadata_info()
                        tr = TraceSummary(
                            session_id=s_dir_resolved.name,
                            source_brain=s_dir_resolved.parent.parent.name,
                            session_dir=s_dir_resolved,
                            created_at="",
                            created_dt=None,
                            updated_at="",
                            step_count=len(s_data.steps),
                            user_request=s_data.get_user_request_clean()[:90],
                            full_user_request=s_data.get_user_request_clean(),
                            project=meta.get("Project", "(no workspace)"),
                            workspace=meta.get("Workspace"),
                        )
                resolved[s_dir_resolved] = tr
            if s_dir_resolved is not None and s_dir_resolved in resolved:
                continue

            # Try 2: Does target match a project name or workspace path?
            t_low = target_clean.lower()
            proj_matches: list[TraceSummary] = []
            if t_low in traces_by_project:
                proj_matches = traces_by_project[t_low]
            else:
                proj_matches = [
                    t
                    for t in all_traces
                    if t_low in (t.project or "").lower()
                    or (t.workspace and t_low in t.workspace.lower())
                ]
            if proj_matches:
                for t in proj_matches:
                    resolved[t.session_dir.resolve()] = t
                continue

            # Neither session nor project found
            not_found.append(target_clean)

    return list(resolved.items()), not_found


def execute_deletion(
    sessions: list[tuple[Path, TraceSummary | None]],
    permanent: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> None:
    """Execute deletion or move to trash for a list of resolved sessions with Markdown logging."""
    if not sessions:
        print("*No matching sessions found to delete.*")
        return

    # Check for active conversation
    active_conv_id = (
        os.environ.get("CONVERSATION_ID") or os.environ.get("AGY_CONVERSATION_ID") or ""
    ).strip()

    filtered_sessions: list[tuple[Path, TraceSummary | None]] = []
    skipped_active: list[Path] = []
    for s_path, tr in sessions:
        sid = tr.session_id if tr else s_path.name
        if (
            active_conv_id
            and (sid == active_conv_id or sid.startswith(active_conv_id))
            and not force
        ):
            skipped_active.append(s_path)
        else:
            filtered_sessions.append((s_path, tr))

    if skipped_active:
        print(
            "> [!WARNING]\n"
            f"> Skipped active conversation session `{active_conv_id}` to prevent terminating the current session. "
            "Pass `--force` if you genuinely intend to delete the active conversation.\n"
        )

    if not filtered_sessions:
        print("*No sessions remaining to delete after filtering.*")
        return

    action_label = "permanently delete (rm -rf)" if permanent else "move to macOS Trash"

    if dry_run:
        print(
            f"### [Dry Run] Antigravity Sessions Targeted for Deletion ({len(filtered_sessions)} sessions)\n"
        )
        print("| # | Session ID | Project | Steps | Action | Location |")
        print("| :--- | :--- | :--- | :---: | :--- | :--- |")
        for idx, (s_path, tr) in enumerate(filtered_sessions, 1):
            sid = tr.session_id if tr else s_path.name
            s_link = f"`{sid[:8]}` [↗](conversation://{sid})"
            proj = tr.project if tr and tr.project else "(unknown)"
            steps = tr.step_count if tr else "?"
            loc_link = f"[`{s_path}`](file://{s_path})"
            action = f"Would {action_label}"
            print(f"| {idx} | {s_link} | `{proj}` | {steps} | {action} | {loc_link} |")
        print("\n*Dry run mode: No sessions were deleted or moved.*")
        return

    if not force:
        if sys.stdin.isatty():
            confirm = typer.confirm(
                f"Are you sure you want to {action_label} {len(filtered_sessions)} session(s)?",
                default=False,
            )
            if not confirm:
                print("Deletion cancelled by user.")
                raise typer.Exit(code=0)
        else:
            print(
                f"Error: Non-interactive execution detected. To delete {len(filtered_sessions)} session(s), pass `--force` / `-f`.",
                file=sys.stderr,
            )
            raise typer.Exit(code=1)

    # Perform deletion
    header_action = "Permanently Deleted" if permanent else "Moved to Trash"
    print(
        f"### {header_action} Antigravity Sessions ({len(filtered_sessions)} sessions)\n"
    )
    print("| # | Session ID | Project | Steps | Status | Destination / Location |")
    print("| :--- | :--- | :--- | :---: | :--- | :--- |")

    for idx, (s_path, tr) in enumerate(filtered_sessions, 1):
        sid = tr.session_id if tr else s_path.name
        s_link = f"`{sid[:8]}` [↗](conversation://{sid})"
        proj = tr.project if tr and tr.project else "(unknown)"
        steps = tr.step_count if tr else "?"

        try:
            if not s_path.exists():
                print(
                    f"| {idx} | {s_link} | `{proj}` | {steps} | `Skipped` | Directory does not exist |"
                )
                continue

            if permanent:
                shutil.rmtree(str(s_path))
                print(
                    f"| {idx} | {s_link} | `{proj}` | {steps} | `Deleted` | *(Permanently deleted from disk)* |"
                )
            else:
                dest = move_session_to_trash(s_path)
                dest_link = f"[`{dest}`](file://{dest})"
                print(
                    f"| {idx} | {s_link} | `{proj}` | {steps} | `Moved to Trash` | {dest_link} |"
                )
        except OSError as e:
            print(
                f"| {idx} | {s_link} | `{proj}` | {steps} | `Error` | {sanitize_md_cell(str(e))} |"
            )


@explorer_app.command(name="delete")
def cmd_explorer_delete(
    targets: Annotated[
        list[str] | None,
        typer.Argument(
            metavar="TARGETS...",
            help="One or more session IDs, hashes, directory paths, or project names to delete.",
        ),
    ] = None,
    project: Annotated[
        str | None,
        typer.Option(
            "--project",
            "-p",
            help="Delete all sessions associated with this project name.",
        ),
    ] = None,
    brain: Annotated[
        str | None,
        typer.Option(
            "--brain",
            "-b",
            help="Filter deletion to a specific brain root directory (e.g. 'antigravity-cli').",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            "--yes",
            "-y",
            help="Force deletion without interactive confirmation.",
        ),
    ] = False,
    permanent: Annotated[
        bool,
        typer.Option(
            "--permanent",
            help="Permanently delete from disk (rm -rf) instead of moving to macOS Trash.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-n",
            help="Show what sessions would be deleted without actually deleting.",
        ),
    ] = False,
) -> None:
    """Delete sessions by session ID/hash, path, or project name (moves to macOS Trash by default)."""
    if not targets and not project:
        print(
            "Error: Please specify one or more session IDs, hashes, project names, or use `--project <name>`.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    sessions, not_found = resolve_sessions_for_deletion(
        targets=targets,
        project_filter=project,
        brain_filter=brain,
    )

    if not_found:
        not_found_str = ", ".join(f"`{nf}`" for nf in not_found)
        print(
            f"> [!WARNING]\n> Could not find session or project for: {not_found_str}\n"
        )

    execute_deletion(
        sessions,
        permanent=permanent,
        dry_run=dry_run,
        force=force,
    )


@explorer_app.command(name="rm", hidden=True)
def cmd_explorer_rm(
    targets: Annotated[list[str] | None, typer.Argument(metavar="TARGETS...")] = None,
    project: Annotated[str | None, typer.Option("--project", "-p")] = None,
    brain: Annotated[str | None, typer.Option("--brain", "-b")] = None,
    force: Annotated[bool, typer.Option("--force", "-f", "--yes", "-y")] = False,
    permanent: Annotated[bool, typer.Option("--permanent")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", "-n")] = False,
) -> None:
    """Alias for delete."""
    cmd_explorer_delete(
        targets=targets,
        project=project,
        brain=brain,
        force=force,
        permanent=permanent,
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# Single Session Inspection CLI
# ---------------------------------------------------------------------------

session_app = typer.Typer(
    help="Inspect a specific Antigravity session transcript, steps, and tool execution.",
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def show_summary(data: SessionData) -> None:
    """Render session summary as Markdown."""
    start_time, end_time, duration_str = data.get_start_and_end_times()
    meta = data.get_metadata_info()
    scratch_items = (
        list((data.session_dir / "scratch").glob("*"))
        if (data.session_dir / "scratch").exists()
        else []
    )
    uploaded_items = (
        list((data.session_dir / ".user_uploaded").glob("*"))
        if (data.session_dir / ".user_uploaded").exists()
        else []
    )
    user_req = data.get_user_request_clean()
    tool_counts = data.get_tool_counts()

    print(f"### Session Overview: `{data.session_id}`\n")
    print("| Property | Value |")
    print("| :--- | :--- |")
    print(
        f"| **Session ID** | `{data.session_id}` [↗](conversation://{data.session_id}) |"
    )
    print(f"| **Directory** | [`{data.session_dir}`](file://{data.session_dir}) |")
    if data.transcript_path.exists():
        print(
            f"| **Transcript** | [`{data.transcript_path.name}`](file://{data.transcript_path}) |"
        )
    if (
        data.transcript_full_path.exists()
        and data.transcript_full_path != data.transcript_path
    ):
        print(
            f"| **Full Transcript** | [`{data.transcript_full_path.name}`](file://{data.transcript_full_path}) |"
        )
    print(
        f"| **Started At** | {format_datetime_display(start_time, str(start_time)) if start_time else 'unknown'} |"
    )
    print(
        f"| **Ended At** | {format_datetime_display(end_time, str(end_time)) if end_time else 'unknown'} |"
    )
    print(f"| **Duration** | {duration_str} |")
    print(f"| **Total Steps** | {len(data.steps)} |")
    for k, v in meta.items():
        if k == "Workspace":
            print(
                f"| **{sanitize_md_cell(k)}** | [`{sanitize_md_cell(str(v))}`](file://{v}) |"
            )
        else:
            print(f"| **{sanitize_md_cell(k)}** | {sanitize_md_cell(str(v))} |")
    print(f"| **Scratch Files** | {len(scratch_items)} |")
    print(f"| **Uploaded Files** | {len(uploaded_items)} |\n")

    print("#### Initial User Request")
    print(f"> {sanitize_md_cell(user_req)}\n")

    if tool_counts:
        print("#### Tool Invocations")
        print("| Tool Name | Count |")
        print("| :--- | :---: |")
        for tool, count in sorted(
            tool_counts.items(), key=lambda item: item[1], reverse=True
        ):
            print(f"| `{tool}` | {count} |")
        print()


def show_paths(data: SessionData) -> None:
    """Render on-disk locations and key files for a session as Markdown."""
    print(f"### On-Disk Locations for Session `{data.session_id}`\n")
    print("| Component | Path / Location | Details |")
    print("| :--- | :--- | :--- |")
    print(
        f"| **Session Directory** | [`{data.session_dir}`](file://{data.session_dir}) | Directory |"
    )

    logs_dir = data.session_dir / ".system_generated" / "logs"
    if logs_dir.exists():
        print(f"| **Logs Directory** | [`{logs_dir}`](file://{logs_dir}) | Directory |")

    if data.transcript_path.exists():
        size_kb = data.transcript_path.stat().st_size / 1024
        print(
            f"| **Transcript** | [`{data.transcript_path.name}`](file://{data.transcript_path}) | {len(data.steps)} steps ({size_kb:.1f} KB) |"
        )

    if (
        data.transcript_full_path.exists()
        and data.transcript_full_path != data.transcript_path
    ):
        size_kb = data.transcript_full_path.stat().st_size / 1024
        print(
            f"| **Full Transcript** | [`{data.transcript_full_path.name}`](file://{data.transcript_full_path}) | {len(data.full_steps)} steps ({size_kb:.1f} KB) |"
        )

    steps_dir = data.session_dir / ".system_generated" / "steps"
    if steps_dir.exists():
        outputs = list(steps_dir.glob("*/output.txt"))
        print(
            f"| **Step Outputs** | [`{steps_dir}`](file://{steps_dir}) | {len(outputs)} output files |"
        )

    meta = data.get_metadata_info()
    if "Workspace" in meta:
        ws_path = Path(meta["Workspace"])
        print(
            f"| **Workspace** | [`{ws_path}`](file://{ws_path}) | Working directory |"
        )

    scratch_dir = data.session_dir / "scratch"
    if scratch_dir.exists():
        scratch_files = list(scratch_dir.glob("*"))
        if scratch_files:
            files_desc = ", ".join(f"[{f.name}](file://{f})" for f in scratch_files[:5])
            if len(scratch_files) > 5:
                files_desc += f" (+{len(scratch_files) - 5} more)"
            print(
                f"| **Scratch Files** | [`{scratch_dir}`](file://{scratch_dir}) | {files_desc} |"
            )
        else:
            print(
                f"| **Scratch Directory** | [`{scratch_dir}`](file://{scratch_dir}) | 0 files |"
            )

    uploaded_dir = data.session_dir / ".user_uploaded"
    if uploaded_dir.exists():
        up_files = list(uploaded_dir.glob("*"))
        if up_files:
            files_desc = ", ".join(f"[{f.name}](file://{f})" for f in up_files[:5])
            if len(up_files) > 5:
                files_desc += f" (+{len(up_files) - 5} more)"
            print(
                f"| **User Uploaded** | [`{uploaded_dir}`](file://{uploaded_dir}) | {files_desc} |"
            )
        else:
            print(
                f"| **User Uploaded** | [`{uploaded_dir}`](file://{uploaded_dir}) | 0 files |"
            )
    print()


def show_paths_multi(sessions_data: list[SessionData]) -> None:
    """Render on-disk paths for multiple sessions."""
    print(
        f"### On-Disk Locations for Discovered Sessions ({len(sessions_data)} sessions)\n"
    )
    print("| Session ID | Project | Session Directory | Transcript | Workspace |")
    print("| :--- | :--- | :--- | :--- | :--- |")
    for data in sessions_data:
        s_link = f"`{data.session_id[:8]}` [↗](conversation://{data.session_id})"
        dir_link = f"[`{data.session_dir}`](file://{data.session_dir})"
        t_link = (
            f"[`{data.transcript_path.name}`](file://{data.transcript_path})"
            if data.transcript_path.exists()
            else "(none)"
        )
        meta = data.get_metadata_info()
        ws = meta.get("Workspace", "(none)")
        proj = meta.get("Project", "(no workspace)")
        ws_link = f"[`{ws}`](file://{ws})" if ws != "(none)" else "(none)"
        print(f"| {s_link} | `{proj}` | {dir_link} | {t_link} | {ws_link} |")
    print()
    for data in sessions_data:
        show_paths(data)


def show_comparison(s1: SessionData, s2: SessionData) -> None:
    """Render side-by-side comparison of two sessions as Markdown."""
    start1, end1, dur1 = s1.get_start_and_end_times()
    start2, end2, dur2 = s2.get_start_and_end_times()
    meta1 = s1.get_metadata_info()
    meta2 = s2.get_metadata_info()

    user_reqs1 = s1.get_user_requests()
    user_reqs2 = s2.get_user_requests()

    tools1 = s1.get_tool_counts()
    tools2 = s2.get_tool_counts()
    all_tools = sorted(set(tools1.keys()) | set(tools2.keys()))

    files1 = s1.get_modified_files()
    files2 = s2.get_modified_files()

    s1_label = f"`{s1.session_id[:8]}`"
    s2_label = f"`{s2.session_id[:8]}`"

    print(f"### Session Comparison: {s1_label} vs {s2_label}\n")

    # Overview table
    print(f"| Metric / Property | Session 1 ({s1_label}) | Session 2 ({s2_label}) |")
    print("| :--- | :--- | :--- |")
    print(
        f"| **Session ID** | `{s1.session_id}` [↗](conversation://{s1.session_id}) | `{s2.session_id}` [↗](conversation://{s2.session_id}) |"
    )
    print(
        f"| **Directory** | [`{s1.session_dir}`](file://{s1.session_dir}) | [`{s2.session_dir}`](file://{s2.session_dir}) |"
    )
    print(
        f"| **Transcript** | [`{s1.transcript_path.name}`](file://{s1.transcript_path}) | [`{s2.transcript_path.name}`](file://{s2.transcript_path}) |"
    )
    print(
        f"| **Started At** | {format_datetime_display(start1, str(start1)) if start1 else 'unknown'} | {format_datetime_display(start2, str(start2)) if start2 else 'unknown'} |"
    )
    print(
        f"| **Ended At** | {format_datetime_display(end1, str(end1)) if end1 else 'unknown'} | {format_datetime_display(end2, str(end2)) if end2 else 'unknown'} |"
    )
    print(f"| **Duration** | {dur1} | {dur2} |")
    print(f"| **Total Steps** | {len(s1.steps)} | {len(s2.steps)} |")
    print(f"| **User Turns** | {len(user_reqs1)} | {len(user_reqs2)} |")
    print(f"| **Total Tool Calls** | {sum(tools1.values())} | {sum(tools2.values())} |")
    print(f"| **Files Written** | {len(files1)} | {len(files2)} |")
    print(
        f"| **Model** | {sanitize_md_cell(meta1.get('Model', 'unknown'))} | {sanitize_md_cell(meta2.get('Model', 'unknown'))} |"
    )
    proj1 = meta1.get("Project", "unknown")
    proj2 = meta2.get("Project", "unknown")
    print(f"| **Project** | `{proj1}` | `{proj2}` |")
    ws1 = meta1.get("Workspace", "unknown")
    ws2 = meta2.get("Workspace", "unknown")
    ws1_cell = f"[`{ws1}`](file://{ws1})" if ws1 != "unknown" else "unknown"
    ws2_cell = f"[`{ws2}`](file://{ws2})" if ws2 != "unknown" else "unknown"
    print(f"| **Workspace** | {ws1_cell} | {ws2_cell} |\n")

    # Initial User Requests
    init1 = user_reqs1[0] if user_reqs1 else "(none)"
    init2 = user_reqs2[0] if user_reqs2 else "(none)"
    if init1.strip() == init2.strip():
        print("#### Initial User Request (Identical)")
        print(f"> {sanitize_md_cell(init1)}\n")
    else:
        print(f"#### Initial User Request - Session 1 ({s1_label})")
        print(f"> {sanitize_md_cell(init1)}\n")
        print(f"#### Initial User Request - Session 2 ({s2_label})")
        print(f"> {sanitize_md_cell(init2)}\n")

    # Subsequent user turns if any
    if len(user_reqs1) > 1 or len(user_reqs2) > 1:
        print("#### Subsequent User Turns")
        if len(user_reqs1) > 1:
            turns1 = "; ".join(f'"{sanitize_md_cell(r)}"' for r in user_reqs1[1:])
            print(f"- **Session 1 ({s1_label})**: {turns1}")
        if len(user_reqs2) > 1:
            turns2 = "; ".join(f'"{sanitize_md_cell(r)}"' for r in user_reqs2[1:])
            print(f"- **Session 2 ({s2_label})**: {turns2}")
        print()

    # Tool Invocations
    if all_tools:
        print("#### Tool Invocations Breakdown")
        print(f"| Tool Name | Session 1 ({s1_label}) | Session 2 ({s2_label}) |")
        print("| :--- | :---: | :---: |")
        for tool in all_tools:
            c1 = tools1.get(tool, 0)
            c2 = tools2.get(tool, 0)
            print(f"| `{tool}` | {c1} | {c2} |")
        print(
            f"| **Total Calls** | **{sum(tools1.values())}** | **{sum(tools2.values())}** |\n"
        )

    # Files created or modified
    if files1 or files2:
        print("#### Files Created or Modified")
        if files1:
            print(f"- **Session 1 ({s1_label})**:")
            for f in files1:
                print(f"  - [`{Path(f).name}`](file://{f}) (`{f}`)")
        else:
            print(f"- **Session 1 ({s1_label})**: *(none)*")
        if files2:
            print(f"- **Session 2 ({s2_label})**:")
            for f in files2:
                print(f"  - [`{Path(f).name}`](file://{f}) (`{f}`)")
        else:
            print(f"- **Session 2 ({s2_label})**: *(none)*")
        print()

    # Final responses / outcomes
    resp1 = s1.get_last_model_response()
    resp2 = s2.get_last_model_response()
    print(f"#### Outcome / Last Response - Session 1 ({s1_label})")
    first_lines1 = "\n".join(resp1.splitlines()[:6])
    if len(resp1.splitlines()) > 6:
        first_lines1 += "\n..."
    print(f"```\n{first_lines1}\n```\n")

    print(f"#### Outcome / Last Response - Session 2 ({s2_label})")
    first_lines2 = "\n".join(resp2.splitlines()[:6])
    if len(resp2.splitlines()) > 6:
        first_lines2 += "\n..."
    print(f"```\n{first_lines2}\n```\n")


def find_triggering_step(
    data: SessionData, step_index: int
) -> tuple[int, dict[str, Any]] | None:
    """Find the preceding step that dispatched tool calls resulting in step_index."""
    s = data.full_steps_by_index.get(step_index)
    if not s or s.get("type") != "GENERIC":
        return None
    for idx in range(step_index - 1, -1, -1):
        candidate = data.full_steps_by_index.get(idx)
        if candidate and candidate.get("tool_calls"):
            return idx, candidate
        if candidate and candidate.get("type") in ("USER_INPUT", "PLANNER_RESPONSE"):
            break
    return None


def show_steps(
    data: SessionData,
    tools_only: bool = False,
    user_only: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> None:
    """Render conversation timeline steps as Markdown."""
    matched = 0
    md_results: list[tuple[int, str, str, str, str]] = []

    for s in data.full_steps:
        idx = s.get("step_index", 0)
        source = s.get("source", "")
        tp = s.get("type", "")
        tool_calls = s.get("tool_calls", [])

        if tools_only and not tool_calls:
            continue
        if user_only and tp != "USER_INPUT":
            continue

        if matched < offset:
            matched += 1
            continue

        if limit is not None and matched >= offset + limit:
            break

        time_str = ""
        try:
            time_str = datetime.fromisoformat(s.get("created_at", "")).strftime(
                "%H:%M:%S"
            )
        except (ValueError, TypeError):
            pass

        # Build preview string
        if tool_calls:
            calls_desc = []
            for tc in tool_calls:
                name = tc.get("name", "tool")
                args = tc.get("args", {})
                action = (
                    args.get("toolAction")
                    or args.get("CommandLine")
                    or args.get("AbsolutePath")
                    or ""
                )
                if action:
                    calls_desc.append(f"{name} ({action})")
                else:
                    calls_desc.append(name)
            clean_preview = "; ".join(calls_desc)
        elif tp == "USER_INPUT":
            content = s.get("content", "")
            m = re.search(
                r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", content, re.DOTALL
            )
            clean_text = m.group(1).strip() if m else content.strip()
            clean_preview = clean_text.replace("\n", " ")[:90]
        elif tp == "GENERIC":
            trigger = find_triggering_step(data, idx)
            if trigger:
                parent_idx, parent_step = trigger
                parent_tools = parent_step.get("tool_calls", [])
                tools_desc = ", ".join(tc.get("name", "tool") for tc in parent_tools)
                clean_preview = f"Result of Step {parent_idx} ({tools_desc})"
            else:
                content = s.get("content", "")
                first_line = (
                    content.strip().splitlines()[0] if content.strip() else "(empty)"
                )
                clean_preview = first_line[:90]
        else:
            content = s.get("content", "")
            clean_preview = content.replace("\n", " ")[:90]

        md_results.append((idx, time_str, source, tp, sanitize_md_cell(clean_preview)))
        matched += 1

    print(f"### Timeline for `{data.session_id}`\n")
    print("| Step | Time | Source | Type | Preview / Action |")
    print("| :---: | :--- | :--- | :--- | :--- |")
    for s_idx, t_str, src, s_type, p_view in md_results:
        print(f"| {s_idx} | {t_str} | `{src}` | `{s_type}` | {p_view} |")


def show_tools(data: SessionData) -> None:
    """Render list of all tool invocations as Markdown."""
    print(f"### Tool Invocations for `{data.session_id}`\n")
    print("| Step | Tool | Action / Summary | Parameters / Target |")
    print("| :---: | :--- | :--- | :--- |")
    for s in data.full_steps:
        idx = s.get("step_index", 0)
        for tc in s.get("tool_calls", []):
            name = tc.get("name", "")
            args = tc.get("args", {})
            action = args.get("toolAction") or args.get("toolSummary") or ""
            target = ""
            if "CommandLine" in args:
                target = f"`{args['CommandLine']}` (cwd: `{args.get('Cwd', '')}`)"
            elif "AbsolutePath" in args:
                target = f"`{args['AbsolutePath']}`"
            elif "DirectoryPath" in args:
                target = f"`{args['DirectoryPath']}`"
            elif "TargetFile" in args:
                target = f"`{args['TargetFile']}`"
            else:
                target = json.dumps(
                    {k: v for k, v in args.items() if not k.startswith("tool")}
                )[:80]
            print(
                f"| {idx} | `{name}` | {sanitize_md_cell(action)} | {sanitize_md_cell(target)} |"
            )


def show_commands(data: SessionData) -> None:
    """Render list of all executed shell commands as Markdown."""
    print(f"### Executed Shell Commands for `{data.session_id}`\n")
    print("| Step | Working Directory (Cwd) | Command Line |")
    print("| :---: | :--- | :--- |")
    for s in data.full_steps:
        idx = s.get("step_index", 0)
        for tc in s.get("tool_calls", []):
            if tc.get("name") == "run_command":
                args = tc.get("args", {})
                cmd = args.get("CommandLine", "")
                cwd = args.get("Cwd", "")
                print(
                    f"| {idx} | `{sanitize_md_cell(cwd)}` | `{sanitize_md_cell(cmd)}` |"
                )


@session_app.callback(invoke_without_command=True)
def session_callback(
    ctx: typer.Context,
    session: Annotated[
        str,
        typer.Argument(
            metavar="SESSION",
            help="Path to session directory OR session ID (searched in ~/.gemini/**/brain).",
        ),
    ],
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output results as Markdown formatted content.",
        ),
    ] = True,
) -> None:
    """Initialize session data from a path or session ID (defaults to summary if no subcommand)."""
    session_dir = find_session_directory(session)
    ctx.obj = SessionData.load(session_dir)

    if ctx.invoked_subcommand is None:
        show_summary(ctx.obj)


@session_app.command(name="summary")
def cmd_summary(
    ctx: typer.Context,
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output results as Markdown formatted content.",
        ),
    ] = True,
) -> None:
    """Show high-level overview of the session, metadata, timing, and tool statistics as Markdown."""
    data: SessionData = ctx.obj
    show_summary(data)


@session_app.command(name="steps")
def cmd_steps(
    ctx: typer.Context,
    tools_only: Annotated[
        bool,
        typer.Option(
            "--tools-only",
            "-t",
            help="Only show steps with tool calls.",
        ),
    ] = False,
    user_only: Annotated[
        bool,
        typer.Option(
            "--user-only",
            "-u",
            help="Only show user input steps.",
        ),
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            "-n",
            help="Limit number of steps shown.",
        ),
    ] = None,
    offset: Annotated[
        int,
        typer.Option(
            "--offset",
            help="Number of steps to skip.",
        ),
    ] = 0,
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output results as Markdown formatted content.",
        ),
    ] = True,
) -> None:
    """List timeline of conversation steps as Markdown."""
    data: SessionData = ctx.obj
    show_steps(
        data,
        tools_only=tools_only,
        user_only=user_only,
        limit=limit,
        offset=offset,
    )


@session_app.command(name="step")
def cmd_step(
    ctx: typer.Context,
    step_index: Annotated[
        int,
        typer.Argument(help="Step index to inspect."),
    ],
    max_lines: Annotated[
        int,
        typer.Option(
            "--lines",
            "-l",
            help="Max lines of output to display.",
        ),
    ] = 50,
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output results as Markdown formatted content.",
        ),
    ] = True,
) -> None:
    """Inspect detailed information, tool calls, and output of a specific step in Markdown."""
    data: SessionData = ctx.obj

    s = data.full_steps_by_index.get(step_index)
    if not s:
        print(
            f"Error: Step index {step_index} not found in session.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    step_out_file = data.get_step_output_file(step_index)
    step_output_str: str | None = None
    if step_out_file:
        step_output_str = step_out_file.read_text(encoding="utf-8", errors="replace")

    trigger = find_triggering_step(data, step_index)
    parent_idx: int | None = None
    parent_tools: list[dict[str, Any]] = []
    if trigger:
        parent_idx, parent_step = trigger
        parent_tools = parent_step.get("tool_calls", [])

    source = s.get("source", "")
    tp = s.get("type", "")
    created_at = s.get("created_at", "")
    status = s.get("status", "")

    print(f"### Step {step_index} Details\n")
    print(f"- **Source**: `{source}`")
    print(f"- **Type**: `{tp}`")
    print(f"- **Status**: `{status}`")
    print(f"- **Time**: `{created_at}`")
    if trigger and parent_idx is not None:
        tool_names_str = ", ".join(f"`{tc.get('name', 'tool')}`" for tc in parent_tools)
        print(f"- **Result of**: Step {parent_idx} ({tool_names_str})")
    print()

    if trigger and parent_idx is not None:
        print(f"#### Triggering Action (Step {parent_idx})")
        for tc in parent_tools:
            tname = tc.get("name", "unknown")
            targs = tc.get("args", {})
            action = targs.get("toolAction") or targs.get("toolSummary") or ""
            print(f"- **Tool**: `{tname}`")
            if action:
                print(f"  - **Action**: {action}")
            if "CommandLine" in targs:
                print(
                    f"  - **Command**: `{targs['CommandLine']}` (cwd: `{targs.get('Cwd', '')}`)"
                )
            elif "AbsolutePath" in targs:
                print(f"  - **Path**: `{targs['AbsolutePath']}`")
            elif "TargetFile" in targs:
                print(f"  - **File**: `{targs['TargetFile']}`")
        print()

    content = s.get("content")
    if content:
        print("#### Content")
        print("```")
        print(content)
        print("```\n")

    thinking = s.get("thinking")
    if thinking:
        print("#### Thinking")
        print("```")
        print(thinking)
        print("```\n")

    tool_calls = s.get("tool_calls", [])
    if tool_calls:
        print("#### Tool Calls")
        for tc_idx, tc in enumerate(tool_calls, 1):
            name = tc.get("name", "unknown")
            args = tc.get("args", {})
            print(f"**Tool Call #{tc_idx}: `{name}`**")
            print("```json")
            print(json.dumps(args, indent=2))
            print("```\n")

    if step_output_str is not None and step_out_file:
        is_duplicate = bool(content and step_output_str.strip() in content.strip())
        if not is_duplicate:
            lines = step_output_str.splitlines()
            truncated = False
            if len(lines) > max_lines:
                display_text = (
                    "\n".join(lines[:max_lines])
                    + f"\n\n... [truncated {len(lines) - max_lines} lines; use --lines to show more] ..."
                )
                truncated = True
            else:
                display_text = step_output_str
            print(
                f"#### Step Output (`{step_out_file.name}`)"
                + (" *(truncated)*" if truncated else "")
            )
            print("```")
            print(display_text)
            print("```\n")


@session_app.command(name="tools")
def cmd_tools(
    ctx: typer.Context,
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output results as Markdown formatted content.",
        ),
    ] = True,
) -> None:
    """List all tool calls executed throughout the entire session as Markdown."""
    data: SessionData = ctx.obj
    show_tools(data)


@session_app.command(name="commands")
def cmd_commands(
    ctx: typer.Context,
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output results as Markdown formatted content.",
        ),
    ] = True,
) -> None:
    """List all shell commands run via run_command with details and working directories as Markdown."""
    data: SessionData = ctx.obj
    show_commands(data)


@session_app.command(name="raw")
def cmd_raw(
    ctx: typer.Context,
    step_index: Annotated[
        int,
        typer.Argument(help="Step index to dump."),
    ],
    full: Annotated[
        bool,
        typer.Option(
            "--full/--compact",
            help="Use transcript_full vs compact transcript.",
        ),
    ] = True,
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output results as Markdown formatted content.",
        ),
    ] = True,
) -> None:
    """Print the raw JSON record of a specific step in a Markdown code block."""
    data: SessionData = ctx.obj

    lookup = data.full_steps_by_index if full else data.steps_by_index
    s = lookup.get(step_index)
    if not s:
        print(f"Error: Step {step_index} not found.", file=sys.stderr)
        raise typer.Exit(code=1)

    json_str = json.dumps(s, indent=2)
    print(f"### Raw Step {step_index} Record\n")
    print("```json")
    print(json_str)
    print("```")


@session_app.command(name="search")
def cmd_session_search(
    ctx: typer.Context,
    query: Annotated[
        str,
        typer.Argument(help="Search query text or keyword within this session."),
    ],
    full: Annotated[
        bool,
        typer.Option(
            "--full/--compact",
            help="Search in full transcript vs compact transcript.",
        ),
    ] = True,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            "-n",
            help="Limit number of matching steps displayed.",
        ),
    ] = None,
) -> None:
    """Search for matching steps, tool invocations, or content within this session."""
    data: SessionData = ctx.obj
    steps_to_search = data.full_steps if full else data.steps

    matches: list[tuple[int, str, str, str, str]] = []
    for s in steps_to_search:
        matched, desc = step_matches_query(s, query)
        if matched:
            idx = s.get("step_index", 0)
            tp = s.get("type", "")
            source = s.get("source", "")
            time_str = ""
            with contextlib.suppress(ValueError, TypeError):
                time_str = datetime.fromisoformat(s.get("created_at", "")).strftime(
                    "%H:%M:%S"
                )
            matches.append((idx, time_str, source, tp, desc))

    print(
        f'### Search Results in Session `{data.session_id}` for "{query}" ({len(matches)} matching steps)\n'
    )
    if not matches:
        print("*No matching steps found.*")
        return

    items_to_show = matches[:limit] if limit else matches
    print("| Step | Time | Source | Type | Matching Excerpt |")
    print("| :---: | :--- | :--- | :--- | :--- |")
    for idx, time_str, source, tp, desc in items_to_show:
        clean_desc = sanitize_md_cell(desc)
        print(f"| {idx} | {time_str} | {source} | {tp} | {clean_desc} |")

    if limit and len(matches) > limit:
        print(f"\n*Showing {len(items_to_show)} of {len(matches)} matching steps.*")


@session_app.command(name="paths")
def cmd_session_paths(
    ctx: typer.Context,
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output results as Markdown formatted content.",
        ),
    ] = True,
) -> None:
    """Show on-disk directory and file locations for this session with clickable links."""
    data: SessionData = ctx.obj
    show_paths(data)


@session_app.command(name="compare")
def cmd_session_compare(
    ctx: typer.Context,
    other_session: Annotated[
        str,
        typer.Argument(help="Other session ID or directory path to compare against."),
    ],
    as_markdown: Annotated[
        bool,
        typer.Option(
            "--markdown",
            "--md",
            "-m",
            help="Output results as Markdown formatted content.",
        ),
    ] = True,
) -> None:
    """Compare this session with another session side-by-side."""
    data: SessionData = ctx.obj
    other_dir = find_session_directory(other_session)
    other_data = SessionData.load(other_dir)
    show_comparison(data, other_data)


@session_app.command(name="delete")
def cmd_session_delete(
    ctx: typer.Context,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            "--yes",
            "-y",
            help="Force deletion without interactive confirmation.",
        ),
    ] = False,
    permanent: Annotated[
        bool,
        typer.Option(
            "--permanent",
            help="Permanently delete from disk (rm -rf) instead of moving to macOS Trash.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-n",
            help="Show what session would be deleted without actually deleting.",
        ),
    ] = False,
) -> None:
    """Delete this session (moves to macOS Trash by default)."""
    data: SessionData = ctx.obj
    meta = data.get_metadata_info()
    tr = TraceSummary(
        session_id=data.session_id,
        source_brain=data.session_dir.parent.parent.name,
        session_dir=data.session_dir,
        created_at="",
        created_dt=None,
        updated_at="",
        step_count=len(data.steps),
        user_request=data.get_user_request_clean()[:90],
        full_user_request=data.get_user_request_clean(),
        project=meta.get("Project", "(no workspace)"),
        workspace=meta.get("Workspace"),
    )
    execute_deletion(
        [(data.session_dir, tr)],
        permanent=permanent,
        dry_run=dry_run,
        force=force,
    )


@session_app.command(name="rm", hidden=True)
def cmd_session_rm(
    ctx: typer.Context,
    force: Annotated[bool, typer.Option("--force", "-f", "--yes", "-y")] = False,
    permanent: Annotated[bool, typer.Option("--permanent")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", "-n")] = False,
) -> None:
    """Alias for delete."""
    cmd_session_delete(ctx, force=force, permanent=permanent, dry_run=dry_run)


# ---------------------------------------------------------------------------
# CLI Routing Entrypoint
# ---------------------------------------------------------------------------


def is_explorer_invocation(args: list[str]) -> bool:
    """Determine whether the invocation targets the trace explorer or a single session."""
    explorer_cmds = {
        "list",
        "explore",
        "traces",
        "search",
        "compare",
        "paths",
        "projects",
        "delete",
        "rm",
        "remove",
    }
    val_flags = {
        "--limit",
        "-n",
        "--brain",
        "-b",
        "--project",
        "-p",
        "--offset",
        "--lines",
        "-l",
        "--query",
        "-q",
        "--search",
        "-s",
    }
    non_opts: list[str] = []
    skip_next = False

    for a in args:
        if skip_next:
            skip_next = False
            continue
        if a in val_flags:
            skip_next = True
            continue
        if not a.startswith("-"):
            non_opts.append(a)

    if not non_opts:
        # No arguments or only flags (e.g. `agy-brain-explorer.py` or `--md`)
        return True

    return non_opts[0] in explorer_cmds


def main() -> None:
    """Unified entrypoint that routes between trace explorer and session inspection."""
    args = sys.argv[1:]
    help_flags = {"-h", "--help"}

    if is_explorer_invocation(args):
        # Explorer mode
        alias_cmds = {"list", "explore", "traces"}
        filtered_args: list[str] = []
        stripped_cmd = False
        for a in args:
            if not stripped_cmd and a in alias_cmds:
                stripped_cmd = True
                continue
            filtered_args.append(a)
        sys.argv = [sys.argv[0]] + filtered_args
        explorer_app()
    else:
        # Session inspection mode
        session_subcommands = {
            "summary",
            "steps",
            "step",
            "tools",
            "commands",
            "raw",
            "search",
            "paths",
            "compare",
            "delete",
            "rm",
            "remove",
        }
        has_subcommand = any(arg in session_subcommands for arg in args)
        final_args = list(args)
        if not has_subcommand and not any(arg in help_flags for arg in args):
            for i, arg in enumerate(final_args):
                if not arg.startswith("-"):
                    final_args.insert(i + 1, "summary")
                    break
        sys.argv = [sys.argv[0]] + final_args
        session_app()


if __name__ == "__main__":
    main()
