#!/usr/bin/env python3
"""Synchronize or verify Complete Listing fenced code blocks in lesson Markdown files."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

COMMON_ENTRYPOINTS = (
    "src/main.rs",
    "src/lib.rs",
    "main.rs",
    "main.py",
    "app.py",
    "src/main.c",
    "main.c",
    "src/main.cpp",
    "main.cpp",
    "src/index.ts",
    "index.ts",
    "src/main.go",
    "main.go",
)

COMPLETE_LISTING_RE = re.compile(
    r"(^#{2,3}\s+(?:Step\s+\d+:\s+)?Complete\b[^\n]*\bListing(?:\s+\{#[-A-Za-z0-9_:]+\})?\s*\n"
    r"(?:(?!^```|^#{1,3}\s)[^\n]*\n)*?"
    r"```[^\n]*\n)"
    r"(.*?)"
    r"(^```\s*$)",
    re.MULTILINE | re.DOTALL,
)
HEADING_ENTRY_RE = re.compile(
    r"^#{2,3}\s+(?:Step\s+\d+:\s+)?Complete\b([^\n]*)\bListing(?:\s+\{#[-A-Za-z0-9_:]+\})?\s*$",
    re.MULTILINE,
)


def _rel(path: Path, root_dir: Path) -> Path:
    try:
        return path.relative_to(root_dir)
    except ValueError:
        return path


def resolve_root_dir(explicit_root: Path | None, lesson_path: Path | None = None) -> Path:
    if explicit_root is not None:
        return explicit_root.resolve()
    cwd = Path.cwd().resolve()
    if (cwd / "lessons").is_dir():
        return cwd
    if (cwd / "tutorial" / "lessons").is_dir():
        return (cwd / "tutorial").resolve()
    if lesson_path is not None:
        resolved_lesson = lesson_path.resolve()
        if resolved_lesson.parent.name == "lessons" and (resolved_lesson.parent.parent / "apps").is_dir():
            return resolved_lesson.parent.parent
    return cwd


def default_source_for_lesson(
    lesson_path: Path,
    apps_dir: Path,
    lesson_text: str | None = None,
) -> Path:
    stem = lesson_path.stem
    app_dir = apps_dir / stem

    text = lesson_text if lesson_text is not None else lesson_path.read_text(encoding="utf-8")
    heading_match = HEADING_ENTRY_RE.search(text)
    if heading_match:
        for raw_token in heading_match.group(1).split():
            token = raw_token.strip("`(),:;\"'")
            if not token or token in {".", ".."}:
                continue
            rel_candidate = Path(token)
            if rel_candidate.is_absolute() or ".." in rel_candidate.parts:
                continue
            for candidate in (app_dir / rel_candidate, app_dir / "src" / rel_candidate):
                if candidate.is_file():
                    return candidate

    for entrypoint in COMMON_ENTRYPOINTS:
        candidate = app_dir / entrypoint
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(f"Could not infer companion source file for {lesson_path}")


def process_pair(lesson_path: Path, source_path: Path, root_dir: Path, write: bool) -> bool:
    lesson_text = lesson_path.read_text(encoding="utf-8")
    source_text = source_path.read_text(encoding="utf-8").rstrip("\n") + "\n"

    match = COMPLETE_LISTING_RE.search(lesson_text)
    if not match:
        print(
            f"[ERROR] {_rel(lesson_path, root_dir)}: no Complete Listing fenced block found",
            file=sys.stderr,
        )
        return False

    current_body = match.group(2)
    if current_body == source_text:
        line_count = len(source_text.splitlines())
        print(
            f"[OK] {lesson_path.name} == {_rel(source_path, root_dir)} ({line_count} lines)"
        )
        return True

    if write:
        updated = (
            lesson_text[: match.start(2)]
            + source_text
            + lesson_text[match.end(2) :]
        )
        lesson_path.write_text(updated, encoding="utf-8")
        line_count = len(source_text.splitlines())
        print(
            f"[UPDATED] {lesson_path.name} <- {_rel(source_path, root_dir)} ({line_count} lines)"
        )
        return True

    print(
        f"[MISMATCH] {_rel(lesson_path, root_dir)} differs from {_rel(source_path, root_dir)}",
        file=sys.stderr,
    )
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check or update Complete Listing code blocks in lessons/*.md from companion files in apps/."
    )
    parser.add_argument("--root", type=Path, help="Course workspace root (defaults to cwd or ./tutorial)")
    parser.add_argument("--lesson", type=Path, help="Single lesson Markdown file")
    parser.add_argument("--source", type=Path, help="Companion source file for --lesson")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Rewrite mismatched Complete Listing blocks from companion source files",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify Complete Listing blocks match companion source files (default)",
    )
    args = parser.parse_args()

    if args.source and not args.lesson:
        parser.error("--source requires --lesson")

    root_dir = resolve_root_dir(args.root, args.lesson)
    lessons_dir = root_dir / "lessons"
    apps_dir = root_dir / "apps"

    pairs: list[tuple[Path, Path]] = []
    if args.lesson:
        lesson = args.lesson.resolve()
        lesson_text = lesson.read_text(encoding="utf-8")
        source = (
            args.source.resolve()
            if args.source
            else default_source_for_lesson(lesson, apps_dir, lesson_text=lesson_text)
        )
        pairs.append((lesson, source))
    else:
        for lesson in sorted(lessons_dir.glob("[0-9][0-9][0-9][0-9]-*.md")):
            pairs.append((lesson, default_source_for_lesson(lesson, apps_dir)))

    if not pairs:
        print(f"No lesson files found in {lessons_dir}.", file=sys.stderr)
        return 1

    all_ok = True
    for lesson, source in pairs:
        if not process_pair(lesson, source, root_dir=root_dir, write=args.write):
            all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
