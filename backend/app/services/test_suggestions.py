"""Deterministic test suggestions for changed Python functions that no test file mentions.

The skeletons are derived from the function signature and its `raise` statements; they are
previews for a developer to complete, and are never executed by DevPilot."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass
class StaticTestSuggestion:
    target: str
    path: str
    start_line: int
    rationale: str
    test_code: str


def is_test_file(path: str) -> bool:
    p = PurePosixPath(path)
    return p.name.startswith("test_") or p.name.endswith("_test.py") or "tests" in p.parts


def _module_name(path: str) -> str:
    p = PurePosixPath(path).with_suffix("")
    parts = [x for x in p.parts if x not in ("src",)]
    return ".".join(parts)


def _skeleton(module: str, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [a.arg for a in fn.args.args if a.arg not in ("self", "cls")]
    call = f"{fn.name}({', '.join(args)})"
    raises = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Raise) and node.exc is not None:
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if isinstance(target, ast.Name) and target.id not in raises:
                raises.append(target.id)
    is_async = isinstance(fn, ast.AsyncFunctionDef)
    prefix = "async " if is_async else ""
    aw = "await " if is_async else ""
    lines = []
    if raises:
        lines.append("import pytest\n")
    lines.append(f"from {module} import {fn.name}\n\n")
    lines.append(f"{prefix}def test_{fn.name}_returns_expected_value():")
    for a in args:
        lines.append(f"    {a} = ...  # TODO: representative input")
    lines.append(f"    assert {aw}{call} == ...  # TODO: expected result\n")
    for exc in raises:
        lines.append(f"\n{prefix}def test_{fn.name}_raises_{exc.lower()}():")
        for a in args:
            lines.append(f"    {a} = ...  # TODO: input that triggers {exc}")
        lines.append(f"    with pytest.raises({exc}):")
        lines.append(f"        {aw}{call}")
    return "\n".join(lines) + "\n"


def suggest_for_changes(
    root: Path,
    changed: dict[str, set[int] | None],  # path -> added lines (None = whole file)
    test_files: list[str],
    limit: int = 10,
) -> list[StaticTestSuggestion]:
    test_text = ""
    for t in test_files[:200]:
        try:
            test_text += (root / t).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    out: list[StaticTestSuggestion] = []
    for path, added in changed.items():
        if not path.endswith(".py") or is_test_file(path):
            continue
        try:
            tree = ast.parse((root / path).read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name.startswith("_"):
                continue
            end = node.end_lineno or node.lineno
            if added is not None and not any(node.lineno <= ln <= end for ln in added):
                continue
            if node.name in test_text:
                continue
            out.append(
                StaticTestSuggestion(
                    target=f"{path}::{node.name}",
                    path=path,
                    start_line=node.lineno,
                    rationale=(
                        f"`{node.name}` was changed and no existing test file references it."
                        if added is not None
                        else f"No existing test file references `{node.name}`."
                    ),
                    test_code=_skeleton(_module_name(path), node),
                )
            )
            if len(out) >= limit:
                return out
    return out
