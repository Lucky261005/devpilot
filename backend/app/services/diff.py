"""Unified-diff parsing: which files changed and which new-side lines were touched."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class FilePatch:
    path: str
    old_path: str | None = None
    status: str = "modified"
    added_lines: set[int] = field(default_factory=set)  # new-side line numbers
    hunks: list[tuple[int, int]] = field(default_factory=list)  # (new_start, new_end)
    additions: int = 0
    deletions: int = 0
    patch: str = ""


def parse_hunks(patch: str, fp: FilePatch) -> FilePatch:
    """Fill added lines and hunk ranges from the hunk section of a patch (GitHub `patch` field)."""
    new_line = 0
    for line in patch.splitlines():
        m = _HUNK_RE.match(line)
        if m:
            new_line = int(m.group(3))
            length = int(m.group(4)) if m.group(4) is not None else 1
            fp.hunks.append((new_line, new_line + max(length, 1) - 1))
            continue
        if not fp.hunks:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            fp.added_lines.add(new_line)
            fp.additions += 1
            new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            fp.deletions += 1
        elif line.startswith("\\"):
            continue  # "\ No newline at end of file"
        else:
            new_line += 1
    fp.patch = patch
    return fp


def parse_unified_diff(text: str) -> list[FilePatch]:
    """Parse `git diff` output into per-file patches."""
    files: list[FilePatch] = []
    blocks = re.split(r"^diff --git ", text, flags=re.M)
    for block in blocks[1:]:
        header, _, _ = block.partition("\n@@")
        old = new = None
        status = "modified"
        for line in header.splitlines():
            if line.startswith("--- "):
                old = None if line[4:] == "/dev/null" else line[4:].removeprefix("a/")
            elif line.startswith("+++ "):
                new = None if line[4:] == "/dev/null" else line[4:].removeprefix("b/")
            elif line.startswith("rename from "):
                old, status = line[12:], "renamed"
            elif line.startswith("rename to "):
                new = line[10:]
            elif line.startswith("new file mode"):
                status = "added"
            elif line.startswith("deleted file mode"):
                status = "deleted"
        if new is None and old is None:
            # Binary or mode-only change: take the path from the "a/x b/x" line.
            first = header.splitlines()[0]
            new = first.split(" b/", 1)[-1]
        path = new or old or ""
        fp = FilePatch(path=path, old_path=old if old != new else None, status=status)
        hunk_start = block.find("\n@@")
        if hunk_start != -1:
            parse_hunks(block[hunk_start + 1 :], fp)
        files.append(fp)
    return files


def in_changed_lines(fp: FilePatch, start: int, end: int, slack: int = 0) -> bool:
    """True if [start, end] touches an added line (with optional context slack)."""
    return any(start - slack <= ln <= end + slack for ln in fp.added_lines)
