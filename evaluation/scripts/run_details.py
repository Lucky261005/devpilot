"""Export the evidence an evaluation database holds beyond the run's JSON report.

`eval.db` files are throwaway SQLite databases (git-ignored by `*.db`). They contain absolute temp
paths, generated user emails and regenerable bulk (diff patches, suggested tests). This module
keeps only what is unique and useful for auditing a run:

- per case: status, failure reason, model call attempts, tokens, latency, model findings
  returned / accepted / rejected (with reasons), the model's summary, duplicates removed,
  analyzer versions and raw counts, and timing per pipeline stage;
- every persisted finding with its full text (title, description, evidence, category,
  confidence), but no database IDs or timestamps.

Output is deterministic: sorted, no absolute paths, no run-time IDs. Uses only the standard
library so it can run without the backend environment.

Usage (any Python):  python evaluation/scripts/run_details.py <eval.db or run folder> [...]
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DROP_STATS = {"base_sha", "head_sha"}  # commit hashes of throwaway repos; differ every run
DROP_AI = set()  # everything in stats["ai"] is kept


def _case_ids(dataset: str = "v1") -> list[str]:
    spec = importlib.util.spec_from_file_location("cases", ROOT / "evaluation" / "datasets" / dataset / "cases.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return [c["id"] for c in mod.CASES]


def _opaque(case_id: str) -> str:  # same formula as scoring.opaque_repo_name
    return "repo-" + hashlib.sha256(f"devpilot-eval:{case_id}".encode()).hexdigest()[:8]


def _identify(repo_name: str, owner_email: str, ids: list[str]) -> tuple[str, str, bool]:
    """(config, case_id, label_blind) from a repository name.

    Label-blind runs use opaque names and one owner per configuration (eval-<config>-...).
    Pre-fix runs named repositories "<config>-<case id>"."""
    for cid in ids:
        if repo_name == _opaque(cid):
            return owner_email.split("-")[1], cid, True
        if repo_name.endswith("-" + cid):
            return repo_name[: -len(cid) - 1], cid, False
    raise ValueError(f"cannot map repository {repo_name!r} to a dataset case")


def export(db_path: Path, dataset: str = "v1") -> dict:
    ids = _case_ids(dataset)
    db = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    rows = db.execute(
        "select j.id, r.name, u.email, j.status, j.error, j.kind, j.use_ai, j.stats "
        "from review_jobs j join repositories r on r.id = j.repository_id join users u on u.id = r.owner_id"
    ).fetchall()
    cases = []
    for job_id, name, email, status, error, kind, use_ai, stats_json in rows:
        config, case_id, blind = _identify(name, email, ids)
        stats = {k: v for k, v in json.loads(stats_json or "{}").items() if k not in DROP_STATS}
        findings = [
            dict(zip(cols, rec, strict=True))
            for cols, recs in [
                (
                    [
                        "source",
                        "analyzer",
                        "analyzer_version",
                        "rule_id",
                        "title",
                        "description",
                        "severity",
                        "category",
                        "path",
                        "start_line",
                        "end_line",
                        "evidence",
                        "confidence",
                    ],
                    db.execute(
                        "select source, analyzer, analyzer_version, rule_id, title, description, severity, "
                        "category, path, start_line, end_line, evidence, confidence from findings where review_id = ? "
                        "order by path, start_line, end_line, analyzer, rule_id, title",
                        (job_id,),
                    ).fetchall(),
                )
            ]
            for rec in recs
        ]
        n_tests = db.execute("select count(*) from test_suggestions where review_id = ?", (job_id,)).fetchone()[0]
        cases.append(
            {
                "config": config,
                "case_id": case_id,
                "repo_name": name,
                "label_blind": blind,
                "kind": kind,
                "use_ai": bool(use_ai),
                "job_status": status,
                "job_error": error,
                "stats": stats,
                "findings": findings,
                "test_suggestions": n_tests,
            }
        )
    cases.sort(key=lambda c: (c["config"], ids.index(c["case_id"])))
    return {
        "format": "devpilot-run-details/1",
        "source_db": db_path.name,
        "dataset": dataset,
        "jobs": len(cases),
        "cases": cases,
    }


def write(db_path: Path, out: Path | None = None, dataset: str = "v1") -> Path:
    out = out or db_path.with_name("details.json" if db_path.name == "eval.db" else db_path.stem + "-details.json")
    out.write_text(
        json.dumps(export(db_path, dataset), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return out


def main(argv: list[str]) -> None:
    if not argv:
        sys.exit(__doc__)
    for arg in argv:
        p = Path(arg)
        dbs = sorted(p.rglob("*eval.db")) if p.is_dir() else [p]
        if not dbs:
            sys.exit(f"no eval databases under {p}")
        for db_path in dbs:
            print(f"{db_path} -> {write(db_path)}")


if __name__ == "__main__":
    main(sys.argv[1:])
