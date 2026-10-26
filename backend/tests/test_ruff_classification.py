"""Ruff findings are labelled by what the rule means, not all as high-confidence bugs."""

from app.analyzers.python_tools import RuffAnalyzer, _ruff_category, _ruff_severity

SOURCE = """\
import os


def pair(names, scores):
    return list(zip(names, scores))


def append(item, bucket=[]):
    bucket.append(item)
    return bucket


def broken():
    return undefined_name


def swallow():
    try:
        return 1
    except:
        return 0
"""


def test_real_ruff_run_labels_each_rule_by_its_meaning(tmp_path):
    (tmp_path / "m.py").write_text(SOURCE)
    found = {f.rule_id: f for f in RuffAnalyzer().run(tmp_path, ["m.py"])}
    expected = {
        "B905": ("maintainability", "low"),  # zip() without strict=: a lint concern, not a defect
        "F401": ("maintainability", "low"),  # unused import
        "B006": ("bug", "medium"),  # mutable default argument
        "F821": ("bug", "high"),  # undefined name: fails at runtime
        "E722": ("error_handling", "medium"),  # bare except
    }
    assert {code: (found[code].category, found[code].severity) for code in expected} == expected
    # Ruff does not report a confidence, so none is claimed; rule id, message and source are kept.
    assert all(f.confidence is None and f.source == "static" for f in found.values())
    assert found["B905"].title == "B905: zip-without-explicit-strict" and "strict" in found["B905"].description


def test_unknown_rules_default_to_maintainability_and_known_families_keep_their_meaning():
    assert (_ruff_category("B999", "B"), _ruff_category("F999", "F")) == ("maintainability", "maintainability")
    assert _ruff_category("E999", "E") == "bug" and _ruff_severity("E999", "bug") == "high"
    assert _ruff_category("PLE1142", "PLE") == "bug" and _ruff_category("RUF006", "RUF") == "bug"
    assert _ruff_category("SIM115", "SIM") == "resource" and _ruff_severity("SIM115", "resource") == "medium"
