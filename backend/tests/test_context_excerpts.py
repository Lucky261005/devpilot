"""LLM context packing for files larger than the remaining budget (app/ai/context.py).

Whole-repository reviews used to drop any file that did not fit whole; a large app.py with an
analyzer finding was never shown to the model. Oversized files now get a bounded excerpt."""

import re

from app.ai.context import EXCERPT_NOTE, MIN_EXCERPT_LINES, TAG, build_context
from app.analyzers.base import NormalizedFinding

BUDGET = 6_000


def _finding(path: str, line: int) -> NormalizedFinding:
    return NormalizedFinding(
        source="static", analyzer="ruff", analyzer_version="0", title="B905: zip-without-explicit-strict",
        description="zip() without an explicit strict= parameter", severity="low", category="maintainability",
        path=path, start_line=line, end_line=line, evidence="", rule_id="B905",
    )  # fmt: skip


def _repo(tmp_path, big_lines=600, marker_line=590):
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / name).write_text(f"def {name[0]}():\n    return 1\n")
    big = [f"value_{i} = {i}" for i in range(1, big_lines + 1)]
    big[marker_line - 1] = "pairs = list(zip(names, scores))  # MARKER"
    (tmp_path / "app.py").write_text("\n".join(big) + "\n")
    targets = [(p, "python", None) for p in ("app.py", "a.py", "b.py", "c.py")]  # big file first
    return targets


def _code_chars(ctx) -> int:
    return len(ctx.user_prompt.split(f"<{TAG}>")[1].split(f"</{TAG}>")[0])


def test_oversized_file_is_excerpted_not_dropped_and_small_files_still_fit(tmp_path):
    ctx = build_context(tmp_path, _repo(tmp_path), [_finding("app.py", 590)], [], BUDGET, "t")
    assert set(ctx.shown) == {"app.py", "a.py", "b.py", "c.py"}
    assert ctx.partial_files == ["app.py"] and ctx.omitted_files == []
    assert EXCERPT_NOTE in ctx.user_prompt and "shown only in part" in ctx.user_prompt


def test_excerpt_contains_the_finding_with_its_real_line_number(tmp_path):
    ctx = build_context(tmp_path, _repo(tmp_path), [_finding("app.py", 590)], [], BUDGET, "t")
    assert "  590 | pairs = list(zip(names, scores))  # MARKER" in ctx.user_prompt
    assert any(s <= 590 <= e for s, e in ctx.shown["app.py"])
    assert "app.py:590 [ruff B905]" in ctx.user_prompt  # the finding is listed because its file is shown
    # Line numbers in the excerpt are the file's own, never renumbered.
    for n, text in re.findall(r"^[ +]\s*(\d+) \| (value_\d+) = ", ctx.user_prompt, re.M):
        assert text == f"value_{n}"


def test_code_stays_within_the_budget_including_the_excerpt_header(tmp_path):
    for budget in (1_500, 3_000, BUDGET, 20_000):
        ctx = build_context(tmp_path, _repo(tmp_path), [_finding("app.py", 590)], [], budget, "t")
        assert _code_chars(ctx) <= budget + 2 * 4  # blocks plus the "\n\n" joins between 4 files


def test_without_findings_the_start_of_the_file_is_shown(tmp_path):
    ctx = build_context(tmp_path, _repo(tmp_path), [], [], BUDGET, "t")
    assert ctx.shown["app.py"][0][0] == 1 and "app.py" in ctx.partial_files


def test_too_little_room_omits_the_file_and_says_so(tmp_path):
    ctx = build_context(tmp_path, _repo(tmp_path), [_finding("app.py", 590)], [], 400, "t")
    assert "app.py" in ctx.omitted_files and "app.py" not in ctx.shown
    assert "omitted for size" in ctx.user_prompt


def test_huge_file_is_bounded(tmp_path):
    ctx = build_context(tmp_path, _repo(tmp_path, big_lines=200_000, marker_line=150_000),
                        [_finding("app.py", 150_000)], [], BUDGET, "t")  # fmt: skip
    shown = sum(e - s + 1 for s, e in ctx.shown["app.py"])
    assert MIN_EXCERPT_LINES <= shown < 1_000 and _code_chars(ctx) <= BUDGET + 8
    assert "150000 | pairs = list(zip(names, scores))" in ctx.user_prompt


def test_whole_repository_prompt_does_not_describe_a_change(tmp_path):
    ctx = build_context(tmp_path, _repo(tmp_path), [], [], BUDGET, "Whole repository")
    assert "Scope: whole-repository review" in ctx.user_prompt
    assert "were added or changed in this review" not in ctx.user_prompt


def test_diff_prompt_keeps_the_changed_line_marker(tmp_path):
    from app.services.diff import FilePatch

    (tmp_path / "a.py").write_text("x = 1\ny = 2\n")
    fp = FilePatch("a.py")
    fp.added_lines, fp.hunks = {2}, [(2, 2)]
    ctx = build_context(tmp_path, [("a.py", "python", fp)], [], [], BUDGET, "diff")
    assert "were added or changed in this review" in ctx.user_prompt and "Scope:" not in ctx.user_prompt
