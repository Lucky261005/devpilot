"""Common analyzer interface and the normalized finding shape shared by static and AI sources."""

from __future__ import annotations

import subprocess  # noqa: S404
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

SEVERITIES = ("critical", "high", "medium", "low", "info")


@dataclass
class NormalizedFinding:
    source: str  # "static" | "ai"
    analyzer: str
    analyzer_version: str
    title: str
    description: str
    severity: str
    category: str
    path: str
    start_line: int
    end_line: int
    evidence: str
    rule_id: str | None = None
    reasoning: str | None = None
    suggested_fix: str | None = None
    suggested_test: str | None = None
    confidence: str | None = None
    limitations: str | None = None
    doc_url: str | None = None
    extra: dict = field(default_factory=dict)


class AnalyzerError(RuntimeError):
    pass


class Analyzer(Protocol):
    name: str
    languages: tuple[str, ...]

    def version(self) -> str: ...

    def run(self, root: Path, files: list[str]) -> list[NormalizedFinding]: ...


def run_tool(args: list[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    """Run an analyzer CLI from the current interpreter's environment, never via a shell."""
    try:
        return subprocess.run(  # noqa: S603
            [sys.executable, "-m", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise AnalyzerError(f"{args[0]} timed out after {timeout}s") from e


def evidence_from(root: Path, rel: str, start: int, end: int) -> str:
    try:
        lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[start - 1 : end])[:2000]
