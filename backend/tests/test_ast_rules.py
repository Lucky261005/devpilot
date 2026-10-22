"""DP001 index-equals-length and the SIM115 Ruff rule."""

from app.analyzers.ast_rules import AstRulesAnalyzer, find_index_equals_length
from app.analyzers.python_tools import RuffAnalyzer, default_analyzers

POSITIVE = """
def last(xs):
    return xs[len(xs)]

def past(self):
    return self.items[len(self.items) + 1] + self.items[2 + len(self.items)]
"""

NEGATIVE = """
def ok(xs, ys, d):
    a = xs[len(xs) - 1]        # correct last element
    b = xs[len(ys)]            # different sequences: cannot tell
    c = xs[-1]
    d[len(d)] = "next"         # assignment: common for int-keyed dicts
    e = xs[len(xs):]           # slicing past the end is legal
    f = get()[len(get())]      # calls may return different objects
    g = xs[len(xs) - 0 + 0]    # not the simple form; not flagged
    h = len(xs)
    return a, b, c, e, f, g, h
"""


def test_dp001_flags_reads_at_or_past_length():
    hits = find_index_equals_length(POSITIVE)
    assert [(h[0], h[2]) for h in hits] == [
        (3, "xs[len(xs)]"),
        (6, "self.items[len(self.items) + 1]"),
        (6, "self.items[2 + len(self.items)]"),
    ]


def test_dp001_ignores_valid_or_uncertain_code():
    assert find_index_equals_length(NEGATIVE) == []


def test_dp001_ignores_unparseable_source():
    assert find_index_equals_length("def broken(:\n") == []


def test_analyzer_produces_normalized_finding(tmp_path):
    (tmp_path / "seq.py").write_text("def last(xs):\n    return xs[len(xs)]\n")
    (f,) = AstRulesAnalyzer().run(tmp_path, ["seq.py"])
    assert (f.rule_id, f.severity, f.category, f.path, f.start_line, f.source) == (
        "DP001",
        "high",
        "bug",
        "seq.py",
        2,
        "static",
    )
    assert f.evidence.strip() == "return xs[len(xs)]" and f.limitations


def test_sim115_reports_unclosed_open_as_resource(tmp_path):
    (tmp_path / "io_x.py").write_text(
        "def read(p):\n    f = open(p)\n    return f.read()\n\n\ndef good(p):\n    with open(p) as f:\n        return f.read()\n"
    )
    found = [f for f in RuffAnalyzer().run(tmp_path, ["io_x.py"]) if f.rule_id == "SIM115"]
    assert [(f.start_line, f.category) for f in found] == [(2, "resource")]


def test_registered_by_default():
    assert "devpilot-ast" in [a.name for a in default_analyzers()]


REALISTIC_SAFE = """
def tail(lines):
    if not lines:
        return None
    return lines[len(lines) - 1]

def walk(xs):
    for i in range(len(xs)):
        print(xs[i])
    i = 0
    while i < len(xs):
        i += 1
    return xs[len(xs) // 2], xs[-1], xs[: len(xs)]

def register(registry, item):
    registry[len(registry)] = item  # int-keyed dict append idiom
"""

REALISTIC_BUG = """
class Stack:
    def peek(self):
        return self.items[len(self.items)]

def last_line(text):
    lines = text.splitlines()
    return lines[len(lines)]
"""


def test_dp001_realistic_safe_code_is_not_flagged():
    assert find_index_equals_length(REALISTIC_SAFE) == []


def test_dp001_realistic_bugs_are_flagged():
    assert [h[2] for h in find_index_equals_length(REALISTIC_BUG)] == [
        "self.items[len(self.items)]",
        "lines[len(lines)]",
    ]


def test_dp001_known_limitation_int_keyed_mapping_read_is_flagged():
    # Documented limitation: a read from an int-keyed dict looks identical to a list bug.
    assert len(find_index_equals_length("def f(d):\n    return d[len(d)]\n")) == 1


def test_sim115_known_noise_and_safe_forms(tmp_path):
    (tmp_path / "a.py").write_text(
        "from pathlib import Path\n\n"
        "def later_with(p):\n    fp = open(p)\n    with fp:\n        return fp.read()\n\n"  # flagged (known noise)
        "def closed_manually(p):\n    f = open(p)\n    try:\n        return f.read()\n    finally:\n        f.close()\n\n"  # flagged
        "def safe(p):\n    with open(p) as f:\n        return f.read()\n\n"
        "def pathlib_read(p):\n    return Path(p).read_text()\n"
    )
    found = [f for f in RuffAnalyzer().run(tmp_path, ["a.py"]) if f.rule_id == "SIM115"]
    assert [f.start_line for f in found] == [4, 9]
    assert all("closed later" in f.limitations for f in found)
