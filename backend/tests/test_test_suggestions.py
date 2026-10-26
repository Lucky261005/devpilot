"""Test suggestions are either complete or an explicit test gap, never placeholder templates."""

import sys

from app.ai.schema import AITestSuggestion
from app.services.findings import has_placeholder, validate_test_suggestions
from app.services.test_suggestions import is_test_file, suggest_for_changes

MODULE = '''\
def add(a, b):
    """Add two numbers.

    >>> add(2, 3)
    5
    >>> add(-1, 1)
    0
    """
    return a + b


def scale(values, factor):
    if factor <= 0:
        raise ValueError("factor must be positive")
    return [v * factor for v in values]
'''


def _suggest(tmp_path):
    (tmp_path / "calc.py").write_text(MODULE)
    return {s.target: s for s in suggest_for_changes(tmp_path, {"calc.py": None}, [])}


def test_docstring_examples_become_a_complete_test_that_passes(tmp_path, monkeypatch):
    s = _suggest(tmp_path)["calc.py::add"]
    assert not has_placeholder(s.test_code) and "assert add(2, 3) == 5" in s.test_code
    monkeypatch.syspath_prepend(str(tmp_path))
    namespace: dict = {}
    exec(compile(s.test_code, "suggested_test.py", "exec"), namespace)  # noqa: S102 - our own fixture
    namespace["test_add_matches_its_docstring_examples"]()
    sys.modules.pop("calc", None)


def test_without_examples_the_suggestion_is_an_explicit_gap(tmp_path):
    s = _suggest(tmp_path)["calc.py::scale"]
    assert s.test_code == ""
    assert "`scale(values, factor)`" in s.rationale and "`ValueError`" in s.rationale
    assert "cannot infer" in s.rationale


def test_no_suggestion_carries_placeholder_code(tmp_path):
    assert not any(has_placeholder(s.test_code) for s in _suggest(tmp_path).values())


def test_functions_named_in_existing_tests_and_test_files_are_skipped(tmp_path):
    (tmp_path / "calc.py").write_text(MODULE)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text("from calc import add\n")
    out = suggest_for_changes(tmp_path, {"calc.py": None, "tests/test_calc.py": None}, ["tests/test_calc.py"])
    assert [s.target for s in out] == ["calc.py::scale"]
    assert is_test_file("tests/test_calc.py") and is_test_file("pkg/calc_test.py") and not is_test_file("calc.py")


def test_ai_suggestions_with_placeholders_are_dropped():
    def ai(code: str) -> AITestSuggestion:
        return AITestSuggestion(target="t", path="calc.py", start_line=1, rationale="r", test_code=code)

    items = [ai("def test_a():\n    assert add(1, 2) == 3\n"), ai("def test_b():\n    x = ...  # TODO\n")]
    kept = validate_test_suggestions(items, {"calc.py": [(1, 20)]})
    assert [t.test_code.splitlines()[0] for t in kept] == ["def test_a():"]
