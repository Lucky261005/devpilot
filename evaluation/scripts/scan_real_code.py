"""False-positive scan of DevPilot's static rules on real, mature Python code.

This is NOT a recall measurement: the corpus has no labelled bugs. It counts how often each rule
fires on code that ships in widely used libraries, and lists every hit for manual review.

Usage (from backend/):
    uv run python ../evaluation/scripts/scan_real_code.py --out ../evaluation/reports/experiments/label-blind-static-v2/realcode-scan

Corpus:
- DP001: every .py file in the backend's installed dependencies (.venv site-packages) plus `app/`.
- SIM115: the source of the PACKAGES below, copied to a temporary folder first because Ruff
  refuses to scan anything inside a virtual environment. Nothing is imported or executed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))
from app.analyzers.ast_rules import VERSION as DP_VERSION  # noqa: E402
from app.analyzers.ast_rules import find_index_equals_length  # noqa: E402

PACKAGES = {  # import folder -> distribution name (for the version)
    "sqlalchemy": "sqlalchemy",
    "pydantic": "pydantic",
    "httpx": "httpx",
    "anthropic": "anthropic",
    "fastapi": "fastapi",
    "starlette": "starlette",
    "alembic": "alembic",
    "bandit": "bandit",
    "email_validator": "email-validator",
    "uvicorn": "uvicorn",
    "_pytest": "pytest",
}


def py_files(root: Path):
    return sorted(p for p in root.rglob("*.py") if p.is_file())


def count_lines(files) -> int:
    return sum(p.read_text(encoding="utf-8", errors="replace").count("\n") for p in files)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    site = next((BACKEND / ".venv").glob("Lib/site-packages"), None) or next(
        (BACKEND / ".venv").glob("lib/python*/site-packages")
    )

    # DP001 over all installed dependencies plus DevPilot's own code.
    started = time.monotonic()
    dp_files = py_files(site) + py_files(BACKEND / "app")
    dp_hits = []
    for p in dp_files:
        for start, _end, expr in find_index_equals_length(p.read_text(encoding="utf-8", errors="replace")):
            dp_hits.append(
                {
                    "file": str(p.relative_to(site) if p.is_relative_to(site) else p.relative_to(BACKEND)),
                    "line": start,
                    "expr": expr,
                }
            )
    dp = {
        "rule": "DP001",
        "rule_version": DP_VERSION,
        "files": len(dp_files),
        "lines": count_lines(dp_files),
        "hits": dp_hits,
        "seconds": round(time.monotonic() - started, 1),
    }

    # SIM115 over copied library sources.
    with tempfile.TemporaryDirectory() as tmp:
        corpus = Path(tmp)
        versions = {}
        for folder, dist in PACKAGES.items():
            if (site / folder).is_dir():
                shutil.copytree(site / folder, corpus / folder)
                try:
                    versions[folder] = version(dist)
                except PackageNotFoundError:
                    versions[folder] = "unknown"
        sim_files = py_files(corpus)
        proc = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--isolated",
                "--select",
                "SIM115",
                "--output-format",
                "json",
                "--exit-zero",
                ".",
            ],
            cwd=corpus,
            capture_output=True,
            text=True,
            check=True,
        )
        sim_hits = [
            {
                "file": Path(h["filename"]).resolve().relative_to(corpus.resolve()).as_posix(),
                "line": h["location"]["row"],
            }
            for h in json.loads(proc.stdout or "[]")
        ]
        sim = {
            "rule": "SIM115",
            "ruff_version": version("ruff"),
            "packages": versions,
            "files": len(sim_files),
            "lines": count_lines(sim_files),
            "hits": sorted(sim_hits, key=lambda h: (h["file"], h["line"])),
        }

    result = {"run_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "dp001": dp, "sim115": sim}
    (out / "scan.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    md = (
        [
            f"# Real-code false-positive scan ({result['run_at']})",
            "",
            "Not a recall measurement: the corpus has no labelled bugs.",
            "",
            f"- DP001 v{DP_VERSION}: {dp['files']:,} files, {dp['lines']:,} lines, **{len(dp_hits)} hits** ({dp['seconds']} s)",
            f"- SIM115 (Ruff {sim['ruff_version']}): {sim['files']:,} files, {sim['lines']:,} lines, **{len(sim['hits'])} hits**",
            "",
            "Packages scanned for SIM115: " + ", ".join(f"{k} {v}" for k, v in versions.items()),
            "",
            "## SIM115 hits",
            "",
        ]
        + [f"- `{h['file']}:{h['line']}`" for h in sim["hits"]]
        + ["", "## DP001 hits", ""]
        + ([f"- `{h['file']}:{h['line']}` `{h['expr']}`" for h in dp_hits] or ["(none)"])
    )
    (out / "scan.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[:6]))


if __name__ == "__main__":
    main()
