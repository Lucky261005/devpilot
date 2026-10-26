"""Deterministic test suggestions for changed Python functions that no test file mentions.

DevPilot cannot infer representative inputs or expected results from source alone, so by default a
suggestion is a test gap: the rationale names the function, its signature and the exceptions it
raises, and `test_code` is empty. Complete code is generated only from doctest examples in the
docstring, where the author already wrote the input and the expected result. Nothing is executed."""

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
    test_code: str  # empty for a test gap


def is_test_file(path: str) -> bool:
    p = PurePosixPath(path)
    return p.name.startswith("test_") or p.name.endswith("_test.py") or "tests" in p.parts


def _module_name(path: str) -> str:
    p = PurePosixPath(path).with_suffix("")
    parts = [x for x in p.parts if x not in ("src",)]
    return ".".join(parts)


def _raises(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    out: list[str] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Raise) and node.exc is not None:
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if isinstance(target, ast.Name) and target.id not in out:
                out.append(target.id)
    return out


def _doctest_cases(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[str, str]]:
    """(call, expected) pairs from single-line `>>> name(...)` examples whose expected output is a
    Python literal. Anything else (prints, multi-line output, objects without a literal repr) is skipped."""
    lines = [line.strip() for line in (ast.get_docstring(fn) or "").splitlines()]
    cases = []
    for line, expected in zip(lines, lines[1:], strict=False):
        call = line.removeprefix(">>> ")
        if not line.startswith(">>> ") or not call.startswith(f"{fn.name}(") or expected.startswith(">>>"):
            continue
        try:
            ast.parse(call, mode="eval")
            ast.literal_eval(expected)
        except (SyntaxError, ValueError):
            continue
        cases.append((call, expected))
    return cases


def _doctest_test(module: str, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    cases = _doctest_cases(fn)
    if not cases or isinstance(fn, ast.AsyncFunctionDef):
        return None
    asserts = "\n".join(f"    assert {call} == {expected}" for call, expected in cases)
    return f"from {module} import {fn.name}\n\n\ndef test_{fn.name}_matches_its_docstring_examples():\n{asserts}\n"


def _gap(fn: ast.FunctionDef | ast.AsyncFunctionDef, why: str) -> str:
    args = ", ".join(a.arg for a in fn.args.args if a.arg not in ("self", "cls"))
    cover = "its normal result" + "".join(f", the `{e}` it raises" for e in _raises(fn))
    return (
        f"{why} Write a test for `{fn.name}({args})` covering {cover}. DevPilot cannot infer "
        "representative inputs or the expected result from the code alone, so no test code is generated."
    )


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
            why = (
                f"`{node.name}` was changed and no existing test file references it."
                if added is not None
                else f"No existing test file references `{node.name}`."
            )
            code = _doctest_test(_module_name(path), node)
            out.append(
                StaticTestSuggestion(
                    target=f"{path}::{node.name}",
                    path=path,
                    start_line=node.lineno,
                    rationale=(
                        f"{why} Built from the examples in its docstring; review it before adding it."
                        if code
                        else _gap(node, why)
                    ),
                    test_code=code or "",
                )
            )
            if len(out) >= limit:
                return out
    return out
