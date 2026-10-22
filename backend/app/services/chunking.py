"""Split source files into searchable chunks that keep exact file/line provenance."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

WINDOW = 60
OVERLAP = 10
_DEF_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:def|class|function|func|fn|interface|type|const|let|var)"
    r"\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.M,
)


@dataclass(frozen=True)
class Chunk:
    path: str
    start_line: int  # 1-based, inclusive
    end_line: int  # inclusive
    content: str
    symbols: tuple[str, ...]


def _symbols(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_DEF_RE.findall(text)))


def _windows(lines: list[str], path: str, start: int, end: int) -> list[Chunk]:
    """Fixed-size overlapping windows over lines[start-1:end]."""
    out = []
    s = start
    while s <= end:
        e = min(s + WINDOW - 1, end)
        text = "\n".join(lines[s - 1 : e])
        if text.strip():
            out.append(Chunk(path, s, e, text, _symbols(text)))
        if e == end:
            break
        s = e - OVERLAP + 1
    return out


def python_definitions(source: str) -> list[tuple[str, int, int]]:
    """(qualified_name, start, end) for every function/method, including decorators."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out: list[tuple[str, int, int]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                start = min([d.lineno for d in child.decorator_list] + [child.lineno])
                name = f"{prefix}{child.name}"
                if not isinstance(child, ast.ClassDef):
                    out.append((name, start, child.end_lineno or child.lineno))
                visit(child, name + ".")

    visit(tree, "")
    return out


def chunk_file(path: str, text: str, language: str) -> list[Chunk]:
    lines = text.splitlines()
    if not lines:
        return []
    if language == "python":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        if tree is not None:
            chunks: list[Chunk] = []
            cursor = 1
            for node in tree.body:
                start = min([d.lineno for d in getattr(node, "decorator_list", [])] + [node.lineno])
                end = node.end_lineno or node.lineno
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                    continue
                if start > cursor:
                    chunks += _windows(lines, path, cursor, start - 1)
                chunks += _windows(lines, path, start, end)
                cursor = end + 1
            if cursor <= len(lines):
                chunks += _windows(lines, path, cursor, len(lines))
            return chunks
    return _windows(lines, path, 1, len(lines))
