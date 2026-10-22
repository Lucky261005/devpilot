"""DevPilot's own deterministic Python checks, for defects no installed analyzer covers.

Rules are added only when they are (1) always or almost always a real defect, (2) detectable from
the syntax tree of one file, and (3) not specific to any benchmark case. Code is parsed with `ast`;
nothing from the repository is imported or executed.

DP001  index-equals-length  `seq[len(seq)]` or `seq[len(seq) + k]` with k >= 0 in a read.
       For lists, tuples and strings the largest valid index is len(seq) - 1, so this always
       raises IndexError. Limitation: a mapping keyed by integers (or a custom __getitem__) can
       legitimately accept len(seq) as a key; assignments (`d[len(d)] = x`) are therefore not
       flagged, only reads.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.analyzers.base import NormalizedFinding, evidence_from

VERSION = "1.0"


def _same_object(a: ast.expr, b: ast.expr) -> bool:
    """True for the same plain name or attribute chain (`xs`, `self.items`). Calls and subscripts
    are excluded: evaluating them twice may not give the same object."""

    def plain(node: ast.expr) -> bool:
        while isinstance(node, ast.Attribute):
            node = node.value
        return isinstance(node, ast.Name)

    return plain(a) and plain(b) and ast.dump(a) == ast.dump(b)


def _len_of(node: ast.expr) -> ast.expr | None:
    """Return X for `len(X)` or `len(X) + k` / `k + len(X)` with an int constant k >= 0."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        for side, other in ((node.left, node.right), (node.right, node.left)):
            if isinstance(other, ast.Constant) and type(other.value) is int and other.value >= 0:
                return _len_of(side)
        return None
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "len"
        and len(node.args) == 1
        and not node.keywords
    ):
        return node.args[0]
    return None


def find_index_equals_length(source: str) -> list[tuple[int, int, str]]:
    """(start_line, end_line, expression) for each DP001 match. Unparseable source yields []."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    hits: list[tuple[tuple[int, int], tuple[int, int, str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
            target = _len_of(node.slice)
            if target is not None and _same_object(node.value, target):
                hits.append(
                    ((node.lineno, node.col_offset), (node.lineno, node.end_lineno or node.lineno, ast.unparse(node)))
                )
    return [h for _, h in sorted(hits)]  # ast.walk is breadth-first; report in source order


class AstRulesAnalyzer:
    name = "devpilot-ast"
    languages = ("python",)

    def version(self) -> str:
        return VERSION

    def run(self, root: Path, files: list[str]) -> list[NormalizedFinding]:
        out: list[NormalizedFinding] = []
        for rel in files:
            try:
                source = (root / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for start, end, expr in find_index_equals_length(source):
                out.append(
                    NormalizedFinding(
                        source="static",
                        analyzer=self.name,
                        analyzer_version=VERSION,
                        rule_id="DP001",
                        title="DP001: index-equals-length",
                        description=f"`{expr}` reads one past the last element; it raises IndexError "
                        "for lists, tuples and strings. The last element is at len(...) - 1.",
                        severity="high",
                        category="bug",
                        path=rel,
                        start_line=start,
                        end_line=end,
                        evidence=evidence_from(root, rel, start, end),
                        suggested_fix="Use seq[-1] (or seq[len(seq) - 1]) and handle the empty case.",
                        confidence="high",
                        limitations="Syntax-based: an int-keyed mapping or a custom __getitem__ could accept "
                        "this key. Only reads are checked.",
                    )
                )
        return out
