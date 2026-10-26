"""Adapters for Ruff (lint/bugs) and Bandit (security). Both are run as subprocesses over the
snapshot; neither imports or executes the analyzed code."""

from __future__ import annotations

import json
from importlib.metadata import version as pkg_version
from pathlib import Path

from app.analyzers.base import AnalyzerError, NormalizedFinding, evidence_from, run_tool

BATCH = 200

# Ruff rule families chosen for likely defects rather than style. Security rules (S) are left
# to Bandit so the same issue is not reported twice.
# SIM115 (open() outside a context manager) was added after the label-blind benchmark showed
# unclosed files were missed; see docs/evaluation.md.
RUFF_SELECT = "F,B,E9,E722,PLE,ASYNC,RUF006,SIM115"
RUFF_HIGH = {"F821", "F811", "F823", "E999", "PLE0101", "PLE0116", "PLE1142"}
# Rule-specific caveats shown with the finding. SIM115 is noisy on mature code (see
# evaluation/reports/experiments/label-blind-static-v2/REPORT.md).
RUFF_LIMITATIONS = {
    "SIM115": "Also fires when the file is closed later, wrapped in `with` a few lines below, or "
    "deliberately kept open for an object's lifetime. Check whether it can leak before changing it.",
}
# Rules in the selected families that indicate a likely runtime defect. Everything else Ruff reports
# (unused imports, B905 zip() without strict=, B904 raise without from, ...) is a code-quality
# concern: category "maintainability", severity "low". Unlisted rules fall there by default.
RUFF_BUG = RUFF_HIGH | {
    # pyflakes: format strings that fail at runtime, impossible comparisons, misplaced statements
    *(f"F{n}" for n in (501, 502, 503, 504, 505, 506, 507, 508, 509, 521, 522, 523, 524, 525)),
    "F601", "F602", "F631", "F632", "F633", "F701", "F702", "F704", "F706", "F707", "F822",
    # bugbear: mutable/call defaults, loop-variable closures, silent no-ops, unreachable handlers
    "B002", "B003", "B006", "B008", "B012", "B015", "B016", "B017", "B018", "B020", "B023", "B025",
    "B026", "B029", "B030", "B031", "B032", "B033", "B034", "B035",
}  # fmt: skip
RUFF_PREFIX_CATEGORY = {"E9": "bug", "PLE": "bug", "ASYNC": "bug", "RUF": "bug"}
RUFF_CATEGORY = {"E722": "error_handling", "SIM115": "resource"}


def _ruff_category(code: str, prefix: str) -> str:
    if code in RUFF_CATEGORY:
        return RUFF_CATEGORY[code]
    if code in RUFF_BUG or code.startswith("E9"):
        return "bug"
    return RUFF_PREFIX_CATEGORY.get(prefix, "maintainability")


def _ruff_severity(code: str, category: str) -> str:
    if code in RUFF_HIGH:
        return "high"
    return "medium" if category in ("bug", "error_handling", "resource") else "low"


def _rel(root: Path, filename: str) -> str:
    # Ruff reports absolute paths, Bandit relative ones; joining handles both.
    return (root / filename).resolve().relative_to(root.resolve()).as_posix()


def _batches(files: list[str]):
    for i in range(0, len(files), BATCH):
        yield files[i : i + BATCH]


class RuffAnalyzer:
    name = "ruff"
    languages = ("python",)

    def version(self) -> str:
        return pkg_version("ruff")

    def run(self, root: Path, files: list[str]) -> list[NormalizedFinding]:
        out: list[NormalizedFinding] = []
        for batch in _batches(files):
            # --isolated: ignore the repository's own ruff config so results are comparable.
            proc = run_tool(
                [
                    "ruff",
                    "check",
                    "--isolated",
                    "--no-cache",
                    "--output-format=json",
                    f"--select={RUFF_SELECT}",
                    "--exit-zero",
                    *batch,
                ],
                cwd=root,
            )
            if proc.returncode != 0:
                raise AnalyzerError(f"ruff failed: {proc.stderr[-500:]}")
            for item in json.loads(proc.stdout or "[]"):
                code = item.get("code") or "E999"
                path = _rel(root, item["filename"])
                start = item["location"]["row"]
                end = max(item["end_location"]["row"], start)
                prefix = code.rstrip("0123456789")
                category = _ruff_category(code, prefix)
                fix = item.get("fix") or {}
                out.append(
                    NormalizedFinding(
                        source="static",
                        analyzer=self.name,
                        analyzer_version=self.version(),
                        rule_id=code,
                        title=f"{code}: {item.get('name', code)}",
                        description=item["message"],
                        severity=_ruff_severity(code, category),
                        category=category,
                        path=path,
                        start_line=start,
                        end_line=end,
                        evidence=evidence_from(root, path, start, end),
                        suggested_fix=fix.get("message"),
                        confidence=None,  # Ruff reports no confidence; do not invent one
                        limitations=RUFF_LIMITATIONS.get(
                            code, "Lint rule matched syntactically; it does not know runtime intent."
                        ),
                        doc_url=item.get("url"),
                    )
                )
        return out


BANDIT_SEVERITY = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
BANDIT_CONFIDENCE = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
# Import-only warnings (B403/B404), asserts (B101), and "subprocess without shell" / "partial
# executable path" (B603/B607), which fire on safe list-form calls. Chosen after the v1
# evaluation run; see docs/evaluation.md.
BANDIT_SKIP = "B403,B404,B101,B603,B607"


class BanditAnalyzer:
    name = "bandit"
    languages = ("python",)

    def version(self) -> str:
        return pkg_version("bandit")

    def run(self, root: Path, files: list[str]) -> list[NormalizedFinding]:
        out: list[NormalizedFinding] = []
        for batch in _batches(files):
            proc = run_tool(["bandit", "-f", "json", "-q", "-s", BANDIT_SKIP, *batch], cwd=root)
            # Bandit exits 1 when it finds issues; anything else with empty stdout is a failure.
            if not proc.stdout.strip():
                raise AnalyzerError(f"bandit failed: {proc.stderr[-500:]}")
            data = json.loads(proc.stdout)
            for item in data.get("results", []):
                path = _rel(root, item["filename"])
                lines = item.get("line_range") or [item["line_number"]]
                start, end = min(lines), max(lines)
                cwe = (item.get("issue_cwe") or {}).get("id")
                out.append(
                    NormalizedFinding(
                        source="static",
                        analyzer=self.name,
                        analyzer_version=self.version(),
                        rule_id=item["test_id"],
                        title=f"{item['test_id']}: {item['test_name']}",
                        description=item["issue_text"] + (f" (CWE-{cwe})" if cwe else ""),
                        severity=BANDIT_SEVERITY.get(item["issue_severity"], "low"),
                        category="security",
                        path=path,
                        start_line=start,
                        end_line=end,
                        evidence=evidence_from(root, path, start, end),
                        confidence=BANDIT_CONFIDENCE.get(item["issue_confidence"]),
                        limitations="Pattern-based check; it cannot see whether input is trusted.",
                        doc_url=item.get("more_info"),
                    )
                )
        return out


def default_analyzers() -> list:
    from app.analyzers.ast_rules import AstRulesAnalyzer

    return [RuffAnalyzer(), BanditAnalyzer(), AstRulesAnalyzer()]
