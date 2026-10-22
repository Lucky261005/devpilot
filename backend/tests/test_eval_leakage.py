"""The benchmark must not leak case IDs, defect labels or clean/defective status into prompts."""

import copy
import importlib.util
import re
import sys
from pathlib import Path

from app.ai.context import build_context

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluation" / "scripts"))
from scoring import opaque_repo_name  # noqa: E402

_spec = importlib.util.spec_from_file_location("cases_v1", ROOT / "evaluation" / "datasets" / "v1" / "cases.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
CASES = _mod.CASES


def _prompt(case: dict, tmp_path: Path, name: str | None = None) -> str:
    """Render the user prompt the way the review pipeline does (title = f"{repo.name} ({kind})")."""
    root = tmp_path / opaque_repo_name(case["id"])
    for rel, text in case["after"].items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    targets = [(rel, "python", None) for rel in case["after"]]
    title = f"{name or opaque_repo_name(case['id'])} (diff)"
    return build_context(root, targets, [], [], 60_000, title).user_prompt


def test_names_are_opaque_unique_and_stable():
    names = [opaque_repo_name(c["id"]) for c in CASES]
    assert len(set(names)) == len(CASES)
    assert names == [opaque_repo_name(c["id"]) for c in CASES]  # deterministic
    for c, n in zip(CASES, names, strict=True):
        assert re.fullmatch(r"repo-[0-9a-f]{8}", n)
        for word in re.split(r"[-_]", c["id"]):
            assert word not in n


def test_name_ignores_hidden_labels():
    case = copy.deepcopy(CASES[0])
    before = opaque_repo_name(case["id"])
    case["label"] = "synthetic-clean"
    case["expected"] = []
    assert opaque_repo_name(case["id"]) == before


def test_prompt_metadata_reveals_nothing(tmp_path):
    headers = set()
    for case in CASES:
        prompt = _prompt(case, tmp_path)
        name = opaque_repo_name(case["id"])
        title = prompt.splitlines()[0]
        assert title == f"Review: {name} (diff)"
        # Everything outside the repository content is the same template for every case.
        headers.add(prompt.split("<repository_content>")[0].replace(name, "<NAME>"))
        assert case["id"] not in prompt
        for word in re.split(r"[-_]", case["id"]) + ["clean", "synthetic", "expected", "seeded", "defect"]:
            assert word not in title.lower(), (case["id"], word)
        for exp in case["expected"]:
            assert exp["description"] not in prompt
    assert len(headers) == 1


def test_prompt_unchanged_when_labels_change(tmp_path):
    for case in CASES:
        original = _prompt(case, tmp_path / "a")
        relabelled = copy.deepcopy(case)
        relabelled["label"] = "synthetic" if case["label"] == "synthetic-clean" else "synthetic-clean"
        relabelled["expected"] = (
            []
            if case["expected"]
            else [
                {
                    "path": "x.py",
                    "lines": [1, 1],
                    "category": "bug",
                    "severity": "high",
                    "description": "d",
                    "rationale": "r",
                }
            ]
        )
        assert _prompt(relabelled, tmp_path / "b") == original


def test_old_naming_scheme_would_fail(tmp_path):
    """Guards the test itself: the pre-fix name `ai-<case id>` is caught by the check above."""
    case = next(c for c in CASES if c["id"].startswith("security-"))
    title = _prompt(case, tmp_path, name=f"ai-{case['id']}").splitlines()[0]
    assert "security" in title.lower() and case["id"] in title
