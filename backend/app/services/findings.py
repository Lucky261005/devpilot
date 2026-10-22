"""Validation of model output against the analyzed source, and cross-source deduplication."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.ai.schema import AIFinding, AITestSuggestion
from app.analyzers.base import SEVERITIES, NormalizedFinding

MAX_SPAN = 80
_WS = re.compile(r"\s+")
_LINE_NO = re.compile(r"^[+ ]?\s*\d+\s\|\s?", re.M)


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip()


@dataclass
class ValidationReport:
    accepted: list[NormalizedFinding] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (title, reason)


def validate_ai_findings(
    findings: list[AIFinding],
    root: Path,
    shown: dict[str, list[tuple[int, int]]],
    model: str,
) -> ValidationReport:
    """Keep only findings whose path, line range and evidence match the source shown."""
    report = ValidationReport()
    cache: dict[str, list[str]] = {}
    for f in findings:
        path = f.path.strip().removeprefix("./")
        if path not in shown:
            report.rejected.append((f.title, "path_not_in_context"))
            continue
        lines = cache.setdefault(path, (root / path).read_text(encoding="utf-8", errors="replace").splitlines())
        start, end = f.start_line, f.end_line
        if start > end:
            start, end = end, start
        if end > len(lines) or end - start > MAX_SPAN:
            report.rejected.append((f.title, "line_range_invalid"))
            continue
        if not any(s <= end and start <= e for s, e in shown[path]):
            report.rejected.append((f.title, "lines_not_in_context"))
            continue
        # Evidence must actually appear near the cited lines (2 lines of slack either side).
        evidence = _norm(_LINE_NO.sub("", f.evidence))
        window = _norm("\n".join(lines[max(0, start - 3) : end + 2]))
        if not evidence or evidence not in window:
            report.rejected.append((f.title, "evidence_mismatch"))
            continue
        start, end = _realign(lines, start, end, evidence)
        report.accepted.append(
            NormalizedFinding(
                source="ai",
                analyzer=f"llm:{model}",
                analyzer_version=model,
                rule_id=None,
                title=f.title,
                description=f.description,
                severity=f.severity,
                category=f.category,
                path=path,
                start_line=start,
                end_line=end,
                evidence="\n".join(lines[start - 1 : end]),
                reasoning=f.reasoning,
                suggested_fix=f.suggested_fix,
                suggested_test=f.suggested_test,
                confidence=f.confidence,
                limitations="Model-generated hypothesis; verify before acting on it.",
            )
        )
    return report


def _realign(lines: list[str], start: int, end: int, evidence: str) -> tuple[int, int]:
    """Models are often off by a line or two; snap the range to where the evidence is."""
    span = end - start
    for s in sorted(range(max(1, start - 2), min(len(lines), start + 2) + 1), key=lambda x: abs(x - start)):
        for e in range(s, min(len(lines), s + span + 3) + 1):
            if evidence in _norm("\n".join(lines[s - 1 : e])):
                return s, e
    return start, end


def validate_test_suggestions(
    items: list[AITestSuggestion], shown: dict[str, list[tuple[int, int]]]
) -> list[AITestSuggestion]:
    return [t for t in items if t.path.removeprefix("./") in shown]


def _overlaps(a: NormalizedFinding, b: NormalizedFinding) -> bool:
    return a.path == b.path and a.start_line <= b.end_line and b.start_line <= a.end_line


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if len(t) > 2}


def _similar(a: NormalizedFinding, b: NormalizedFinding) -> bool:
    if a.category == b.category:
        return True
    ta, tb = _tokens(a.title + " " + a.description), _tokens(b.title + " " + b.description)
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.4


def deduplicate(static: list[NormalizedFinding], ai: list[NormalizedFinding]) -> tuple[list[NormalizedFinding], int]:
    """Static findings win over overlapping AI findings; among AI findings the more severe
    one wins. Returns (kept, number_dropped)."""
    kept: list[NormalizedFinding] = []
    seen_static = set()
    for f in static:
        key = (f.analyzer, f.rule_id, f.path, f.start_line)
        if key not in seen_static:
            seen_static.add(key)
            kept.append(f)
    dropped = len(static) - len(kept)
    ai_sorted = sorted(ai, key=lambda f: SEVERITIES.index(f.severity))
    for f in ai_sorted:
        if any(_overlaps(f, k) and _similar(f, k) for k in kept):
            dropped += 1
            continue
        kept.append(f)
    return kept, dropped
