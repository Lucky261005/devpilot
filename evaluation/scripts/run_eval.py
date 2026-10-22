"""Run the DevPilot review pipeline over the benchmark and score it against reference labels.

Usage (from backend/):
    uv run python ../evaluation/scripts/run_eval.py --configs static,ai,combined

Each case becomes a two-commit Git repository and is reviewed as a `diff` job through the real
pipeline (`app.workers.queue.process_job`) against a throwaway SQLite database. Configurations:
    static    analyzers only
    ai        LLM only (no analyzers)            - needs ANTHROPIC_API_KEY
    combined  analyzers + LLM                    - needs ANTHROPIC_API_KEY
A configuration that cannot run is reported as not run; nothing is simulated.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(tempfile.mkdtemp(prefix="devpilot-eval-"))
os.environ.update({
    "DEVPILOT_DATABASE_URL": f"sqlite:///{(WORK / 'eval.db').as_posix()}",
    "DEVPILOT_DATA_DIR": str(WORK / "data"),
    "DEVPILOT_ALLOWED_LOCAL_ROOTS": str(WORK / "repos"),
    "DEVPILOT_RUN_WORKER_IN_PROCESS": "false",
})
sys.path.insert(0, str(ROOT / "backend"))

from app.analyzers.python_tools import default_analyzers  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Finding, Repository, ReviewJob, User  # noqa: E402
from app.workers.queue import process_job  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from scoring import TOLERANCE, opaque_repo_name, pct, percentile, score  # noqa: E402

PRICES_PER_MTOK = {  # USD (input, output). Source: Anthropic pricing table, cached 2026-10-06.
    "claude-opus-5-5": (4.00, 20.00), "claude-sonnet-5-5": (2.00, 10.00), "claude-haiku-5-5": (0.10, 0.50),
}


def load_cases(version: str) -> list[dict]:
    spec = importlib.util.spec_from_file_location("cases", ROOT / "evaluation" / "datasets" / version / "cases.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.CASES


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=eval", "-c", "user.email=eval@example.invalid", *args],  # noqa: S603,S607
                   cwd=cwd, check=True, capture_output=True)


def materialize(case: dict) -> Path:
    repo = WORK / "repos" / opaque_repo_name(case["id"])
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    for files in (case["before"], case["after"]):
        for rel, text in files.items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(text, encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "step", "--allow-empty")
    return repo


def prompt_dump_factory(out: Path):
    """Provider that records the prompt the pipeline builds and returns a failure (no model call)."""
    from app.ai.provider import LLMResult

    out.mkdir(parents=True, exist_ok=True)

    class PromptDump:
        name, model = "prompt-dump", "none"

        def review(self, system: str, user: str):
            header = user.splitlines()[0]  # "Review: <repo name> (<kind>)"
            (out / f"{header.split()[1]}.txt").write_text(
                f"=== SYSTEM ===\n{system}\n\n=== USER ===\n{user}\n", encoding="utf-8")
            return LLMResult(None, "none", 0, error="dry run: prompt dumped, no model called")

    return lambda settings: PromptDump()


def run_config(name: str, cases: list[dict], repos: dict[str, Path], provider_factory=None) -> dict:
    settings = get_settings()
    use_ai = name in ("ai", "combined")
    if use_ai and not settings.llm_configured:
        return {"config": name, "status": "not_run", "reason": "no LLM provider configured (DEVPILOT_LLM_PROVIDER / ANTHROPIC_API_KEY)"}
    analyzers = [] if name == "ai" else default_analyzers()
    per_case, latencies, tokens_in, tokens_out = [], [], [], []
    failures = timeouts = citations_returned = citations_valid = 0
    with SessionLocal() as db:
        # One owner per configuration so every configuration can use the same opaque repo names.
        user = User(email=f"eval-{name}-{time.monotonic_ns()}@example.invalid", password_hash="!")
        db.add(user)
        db.commit()
        for case in cases:
            # Label-blind: the case ID stays in this script's scoring data; the model only ever
            # sees the opaque repository name.
            repo = Repository(owner_id=user.id, name=opaque_repo_name(case["id"]), source_type="local",
                              source_ref=str(repos[case["id"]]), index_status="ready", ai_review_allowed=use_ai)
            db.add(repo)
            db.commit()
            job = ReviewJob(repository_id=repo.id, kind="diff", base_ref="HEAD~1", head_ref="HEAD",
                            use_ai=use_ai, status="running", stats={})
            db.add(job)
            db.commit()
            started = time.monotonic()
            extra = {"provider_factory": provider_factory} if provider_factory else {}
            process_job(db, job, settings, analyzers=analyzers, **extra)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            db.refresh(job)
            ai = job.stats.get("ai", {})
            if job.status == "failed" or ai.get("status") == "failed":
                failures += 1
                timeouts += "timed out" in (job.error or "") + str(ai.get("reason", ""))
            if ai.get("status") == "completed":
                citations_returned += ai.get("returned", 0)
                citations_valid += ai.get("accepted", 0)
                tokens_in.append(ai.get("input_tokens") or 0)
                tokens_out.append(ai.get("output_tokens") or 0)
            latencies.append(elapsed_ms)
            preds = [{"path": f.path, "start_line": f.start_line, "end_line": f.end_line,
                      "severity": f.severity, "source": f.source, "title": f.title, "rule_id": f.rule_id}
                     for f in db.query(Finding).filter_by(review_id=job.id)]
            s = score(preds, case["expected"])
            per_case.append({"id": case["id"], "label": case["label"], "status": job.status,
                             "error": job.error, "ai_status": ai.get("status"), "ai_reason": ai.get("reason"),
                             "latency_ms": elapsed_ms, "expected": len(case["expected"]),
                             "predictions": preds, **s})

    if use_ai and per_case and all(c["ai_status"] != "completed" for c in per_case):
        # Every model call failed: the "scores" would only measure the outage, so report it as such.
        return {"config": name, "status": "failed", "reason": f"all LLM calls failed: {per_case[0]['ai_reason']}",
                "per_case": per_case}
    tp = sum(c["tp"] for c in per_case)
    fp = sum(c["fp"] for c in per_case)
    fn = sum(c["fn"] for c in per_case)
    dup = sum(c["duplicates"] for c in per_case)
    n_pred = tp + fp + dup
    clean = [c for c in per_case if c["expected"] == 0]
    model = settings.active_llm_model if use_ai else None
    cost = None
    if use_ai and settings.llm_provider == "ollama":
        cost = 0.0  # local inference: no API charge (electricity and hardware not counted)
    elif use_ai and model in PRICES_PER_MTOK and tokens_in:
        pin, pout = PRICES_PER_MTOK[model]
        cost = round((sum(tokens_in) * pin + sum(tokens_out) * pout) / 1e6 / len(tokens_in), 5)
    return {
        "config": name, "status": "completed", "provider": settings.llm_provider if use_ai else None, "model": model, "cases": len(per_case),
        "metrics": {
            "tp": tp, "fp": fp, "fn": fn, "duplicates": dup,
            "precision": pct(tp, tp + fp), "recall": pct(tp, tp + fn),
            "clean_case_false_positive_rate": pct(sum(c["fp"] > 0 for c in clean), len(clean)),
            "duplicate_rate": pct(dup, n_pred),
            "severity_exact_match": pct(sum(c["severity_exact"] for c in per_case), tp),
            "valid_citation_rate": pct(citations_valid, citations_returned) if use_ai else None,
            "useful_findings_per_review": pct(tp, len(per_case)),
            "latency_ms_p50": percentile(latencies, 0.5),
            "latency_ms_p95": percentile(latencies, 0.95) if len(latencies) >= 20 else None,
            "mean_input_tokens": statistics.mean(tokens_in) if tokens_in else None,
            "mean_output_tokens": statistics.mean(tokens_out) if tokens_out else None,
            "mean_cost_usd_per_review": cost,
            "failure_rate": pct(failures, len(per_case)), "timeout_rate": pct(timeouts, len(per_case)),
        },
        "per_case": per_case,
    }


def render_markdown(result: dict) -> str:
    lines = [f"# Evaluation report — {result['run_at']}", "",
             f"Dataset `{result['dataset']}`: {result['n_cases']} cases "
             f"({result['n_defect_cases']} with seeded defects, {result['n_clean_cases']} clean). "
             "All cases are synthetic.", "",
             f"Environment: Python {result['env']['python']}, {result['env']['platform']}, "
             f"analyzers {result['env']['analyzers']}. Match tolerance ±{TOLERANCE} lines.", "",
             f"System prompt: {result['system_prompt']['source']} (sha256 {result['system_prompt']['sha256']}). "
             f"Strategy: {result.get('strategy', 'single')}. "
             f"Label-blind: {'yes' if result.get('label_blind') else 'NO (pre-fix run)'}.", "",
             "| Config | Status | Precision | Recall | TP | FP | FN | Dup | Clean-case FP rate | Severity match | Valid citations | p50 latency (ms) | Cost/review (USD) | Failure rate |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in result["configs"]:
        if c["status"] != "completed":
            lines.append(f"| {c['config']} | {c['status'].replace('_', ' ')}: {c['reason']} |" + " — |" * 12)
            continue
        m = c["metrics"]
        def f(v):
            return "—" if v is None else v
        label = f"{c['config']} ({c['provider']}: {c['model']})" if c.get("model") else c["config"]
        lines.append(f"| {label} | completed | {f(m['precision'])} | {f(m['recall'])} | {m['tp']} | {m['fp']} | "
                     f"{m['fn']} | {m['duplicates']} | {f(m['clean_case_false_positive_rate'])} | "
                     f"{f(m['severity_exact_match'])} | {f(m['valid_citation_rate'])} | {f(m['latency_ms_p50'])} | "
                     f"{f(m['mean_cost_usd_per_review'])} | {f(m['failure_rate'])} |")
    lines += ["", "p95 latency is omitted below 20 observations.", "", "## Per-case results", ""]
    for c in result["configs"]:
        if c["status"] != "completed":
            continue
        lines += [f"### {c['config']}", "", "| Case | Expected | TP | FP | FN | Predictions |", "|---|---|---|---|---|---|"]
        for pc in c["per_case"]:
            preds = "; ".join(f"{p['rule_id'] or p['source']}@{p['path']}:{p['start_line']}" for p in pc["predictions"]) or "—"
            lines.append(f"| {pc['id']} | {pc['expected']} | {pc['tp']} | {pc['fp']} | {pc['fn']} | {preds} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="static,ai,combined")
    ap.add_argument("--dataset", default="v1")
    ap.add_argument("--out", default=str(ROOT / "evaluation" / "reports"))
    ap.add_argument("--system-prompt-file", help="experiment: replace the system prompt for this run only")
    ap.add_argument("--dump-prompts", metavar="DIR",
                    help="dry run: write the exact prompts the model would get, call no model")
    ap.add_argument("--strategy", choices=["single", "two-step"], default="single",
                    help="experiment: two-step = plain-text analysis call, then the structured call")
    args = ap.parse_args()

    import app.services.review as review_module  # the pipeline reads SYSTEM_PROMPT from here

    prompt_source = "production (app/ai/context.py)"
    if args.system_prompt_file:
        # Only this benchmark process is affected; the application code is not changed.
        review_module.SYSTEM_PROMPT = Path(args.system_prompt_file).read_text(encoding="utf-8")
        prompt_source = Path(args.system_prompt_file).name
    system_prompt = {"source": prompt_source,
                     "sha256": hashlib.sha256(review_module.SYSTEM_PROMPT.encode()).hexdigest()[:16]}

    cases = load_cases(args.dataset)
    Base.metadata.create_all(engine)
    repos = {c["id"]: materialize(c) for c in cases}
    provider_factory = None
    if args.strategy == "two-step":
        from two_step import TwoStepOllamaProvider  # benchmark-only; requires the ollama provider

        if get_settings().llm_provider != "ollama":
            sys.exit("--strategy two-step needs DEVPILOT_LLM_PROVIDER=ollama")
        provider_factory = TwoStepOllamaProvider
    if args.dump_prompts:
        provider_factory = prompt_dump_factory(Path(args.dump_prompts))
    configs = [run_config(name.strip(), cases, repos, provider_factory) for name in args.configs.split(",")]
    analyzers = {a.name: a.version() for a in default_analyzers()}
    result = {
        "run_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "dataset": args.dataset,
        "n_cases": len(cases), "n_defect_cases": sum(bool(c["expected"]) for c in cases),
        "n_clean_cases": sum(not c["expected"] for c in cases), "match_tolerance_lines": TOLERANCE,
        "system_prompt": system_prompt,
        "strategy": args.strategy,
        "label_blind": True,  # repo names are opaque hashes; case IDs never reach the prompt
        "env": {"python": platform.python_version(), "platform": platform.platform(), "analyzers": analyzers},
        "configs": configs,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = result["run_at"].replace(":", "").replace("-", "")
    (out / f"{stamp}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (out / "latest.md").write_text(render_markdown(result), encoding="utf-8")
    (out / "latest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    # Portable, path-free export of the per-case evidence held only in the throwaway database.
    from run_details import write as write_details

    engine.dispose()
    write_details(WORK / "eval.db", out / f"{stamp}-details.json", args.dataset)
    write_details(WORK / "eval.db", out / "details.json", args.dataset)
    print(render_markdown(result).split("## Per-case")[0])
    print(f"wrote {out / (stamp + '.json')}")


if __name__ == "__main__":
    main()
