import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evaluation" / "scripts"))
from scoring import percentile, score  # noqa: E402

EXP = [{"path": "a.py", "lines": [10, 12], "severity": "high"}]


def p(path, s, e, sev="high"):
    return {"path": path, "start_line": s, "end_line": e, "severity": sev}


def test_score_counts_tp_fp_fn_and_duplicates():
    r = score([p("a.py", 13, 13), p("a.py", 11, 11, "low"), p("a.py", 30, 30), p("b.py", 10, 10)], EXP)
    assert (r["tp"], r["fp"], r["fn"], r["duplicates"], r["severity_exact"]) == (1, 2, 0, 1, 1)


def test_score_outside_tolerance_is_miss():
    r = score([p("a.py", 15, 15)], EXP)
    assert (r["tp"], r["fp"], r["fn"]) == (0, 1, 1)


def test_clean_case_with_no_predictions():
    assert score([], [])["fp"] == 0


def test_percentile():
    assert percentile([5, 1, 3], 0.5) == 3 and percentile([], 0.5) is None
