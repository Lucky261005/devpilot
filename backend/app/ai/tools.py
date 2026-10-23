"""Read-only repository tools used to build repository-aware review context.

Scope and safety:
- One instance per review, rooted at that review's snapshot directory: the exact commit being
  reviewed, already stripped of secret files and symlinks at import. Nothing outside the root is
  readable (paths are resolved and checked), so context cannot leak across users, repositories
  or commits, and there is nothing to invalidate when a later commit is reviewed.
- Tools only read and parse files (ast). They never execute repository code, run commands,
  write files or touch the network.
- Budgets: at most MAX_FILES files and MAX_FILE_BYTES per file are scanned.

The tools are called deterministically by context.py (search a symbol, read a snippet, follow
calls), not by the model: a 3B local model cannot drive tool calls reliably.
"""

from __future__ import annotations

import ast
import builtins
import re
from functools import cached_property
from pathlib import Path

from app.services.chunking import python_definitions
from app.services.ingestion import EXCLUDED_DIRS

MAX_FILES = 2000
MAX_FILE_BYTES = 256 * 1024
_BUILTINS = set(dir(builtins))


class RepoTools:
    def __init__(self, root: Path):
        self.root = root.resolve()

    # -- tool 2: read --------------------------------------------------------------------
    def _safe(self, rel: str) -> Path | None:
        p = (self.root / rel).resolve()
        if not p.is_relative_to(self.root) or not p.is_file() or p.is_symlink():
            return None
        return p

    def read_lines(self, rel: str) -> list[str]:
        p = self._safe(rel)
        if p is None or p.stat().st_size > MAX_FILE_BYTES:
            return []
        return p.read_text(encoding="utf-8", errors="replace").splitlines()

    # -- tool 1: search symbols ----------------------------------------------------------
    @cached_property
    def python_files(self) -> list[str]:
        out: list[str] = []
        for p in sorted(self.root.rglob("*.py")):
            rel = p.relative_to(self.root)
            if any(part in EXCLUDED_DIRS for part in rel.parts[:-1]) or p.is_symlink():
                continue
            out.append(rel.as_posix())
            if len(out) >= MAX_FILES:
                break
        return out

    @cached_property
    def definitions(self) -> dict[str, list[tuple[str, int, int]]]:
        """Short name -> [(path, start, end)] for every Python function and class."""
        index: dict[str, list[tuple[str, int, int]]] = {}
        for rel in self.python_files:
            source = "\n".join(self.read_lines(rel))
            for qualified, start, end in python_definitions(source):
                index.setdefault(qualified.rsplit(".", 1)[-1], []).append((rel, start, end))
        return index

    def find_definition(self, name: str) -> list[tuple[str, int, int]]:
        return self.definitions.get(name, [])

    # -- tool 3: call relationships ------------------------------------------------------
    def calls_in(self, rel: str, ranges: list[tuple[int, int]]) -> list[str]:
        """Names called on the given lines, in order of first use, without builtins."""
        try:
            tree = ast.parse("\n".join(self.read_lines(rel)))
        except SyntaxError:
            return []
        seen: dict[str, None] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not any(s <= node.lineno <= e for s, e in ranges):
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if name and name not in _BUILTINS:
                seen.setdefault(name, None)
        return list(seen)

    def callers_of(self, name: str, exclude: str, limit: int = 3) -> list[tuple[str, int]]:
        """Up to `limit` call sites of `name` in other files: (path, line)."""
        pattern = re.compile(rf"\b{re.escape(name)}\s*\(")
        hits: list[tuple[str, int]] = []
        for rel in self.python_files:
            if rel == exclude:
                continue
            for i, line in enumerate(self.read_lines(rel), start=1):
                stripped = line.lstrip()
                if pattern.search(line) and not stripped.startswith(("def ", "async def ", "#")):
                    hits.append((rel, i))
                    if len(hits) >= limit:
                        return hits
        return hits
