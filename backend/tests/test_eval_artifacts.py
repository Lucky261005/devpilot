"""Evaluation artifacts: the details.json export and the comparison script's input checks."""

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.models import Finding, Repository, ReviewJob, User

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evaluation" / "scripts"))
import compare_runs  # noqa: E402
from run_details import export  # noqa: E402
from scoring import opaque_repo_name  # noqa: E402


def _make_db(path: Path, *, blind: bool) -> None:
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="eval-combined-123@example.invalid", password_hash="!")
        db.add(user)
        db.flush()
        name = opaque_repo_name("boundary-last-index") if blind else "combined-boundary-last-index"
        repo = Repository(
            owner_id=user.id,
            name=name,
            source_type="local",
            source_ref="C:\\Users\\someone\\AppData\\Local\\Temp\\x\\repo",
            index_status="ready",
        )
        db.add(repo)
        db.flush()
        job = ReviewJob(
            repository_id=repo.id,
            kind="diff",
            use_ai=True,
            status="completed",
            stats={
                "base_sha": "a" * 40,
                "head_sha": "b" * 40,
                "duplicates_dropped": 1,
                "ai": {"status": "completed", "attempts": 2, "input_tokens": 10, "returned": 1},
            },
        )
        db.add(job)
        db.flush()
        db.add(
            Finding(
                review_id=job.id,
                source="static",
                analyzer="devpilot-ast",
                analyzer_version="1.0",
                rule_id="DP001",
                title="t",
                description="d",
                severity="high",
                category="bug",
                path="util/seq.py",
                start_line=6,
                end_line=6,
                evidence="return xs[len(xs)]",
            )
        )
        db.commit()
    engine.dispose()


@pytest.mark.parametrize("blind", [True, False])
def test_export_is_path_free_and_maps_cases(tmp_path, blind):
    db = tmp_path / "eval.db"
    _make_db(db, blind=blind)
    data = export(db)
    text = json.dumps(data)
    assert "Users" not in text and "AppData" not in text and "example.invalid" not in text
    (case,) = data["cases"]
    assert (case["config"], case["case_id"], case["label_blind"]) == ("combined", "boundary-last-index", blind)
    assert "base_sha" not in case["stats"] and case["stats"]["ai"]["attempts"] == 2
    assert case["findings"][0]["rule_id"] == "DP001" and "id" not in case["findings"][0]
    assert export(db) == data  # deterministic


def _run_dir(tmp_path: Path, *, blind=True, status="completed", n_preds=1, n_findings=1) -> Path:
    d = tmp_path / "run"
    d.mkdir()
    per_case = [
        {"id": "boundary-last-index", "expected": 1, "fp": 0, "tp": 1, "predictions": [{"source": "static"}] * n_preds}
    ]
    (d / "latest.json").write_text(
        json.dumps(
            {"label_blind": blind, "configs": [{"status": status, "cases": 1, "per_case": per_case, "metrics": {}}]}
        ),
        encoding="utf-8",
    )
    (d / "details.json").write_text(
        json.dumps(
            {
                "jobs": 1,
                "cases": [
                    {"case_id": "boundary-last-index", "label_blind": blind, "findings": [{}] * n_findings, "stats": {}}
                ],
            }
        ),
        encoding="utf-8",
    )
    return d


def test_compare_accepts_consistent_run(tmp_path):
    compare_runs.load(_run_dir(tmp_path))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"blind": False}, "not a label-blind run"),
        ({"status": "failed"}, "not completed"),
        ({"n_findings": 2}, "differ between"),
    ],
)
def test_compare_rejects_bad_runs(tmp_path, kwargs, message):
    with pytest.raises(compare_runs.ArtifactError, match=message):
        compare_runs.load(_run_dir(tmp_path, **kwargs))


def test_compare_rejects_missing_details(tmp_path):
    d = _run_dir(tmp_path)
    (d / "details.json").unlink()
    with pytest.raises(compare_runs.ArtifactError, match="missing"):
        compare_runs.load(d)
