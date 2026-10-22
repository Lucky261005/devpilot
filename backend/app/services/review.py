"""The review pipeline: snapshot -> discover -> static analysis -> AI review -> validate ->
deduplicate -> persist. Runs inside the background worker; see docs/architecture.md."""

from __future__ import annotations

import logging
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai.context import SYSTEM_PROMPT, build_context
from app.ai.provider import LLMProvider, ProviderUnavailable, get_provider
from app.analyzers.base import AnalyzerError, NormalizedFinding
from app.analyzers.python_tools import default_analyzers
from app.core.config import Settings
from app.core.security import decrypt_secret
from app.models import (
    ChangedFile,
    Finding,
    GitHubAccount,
    PullRequest,
    Repository,
    ReviewJob,
    TestSuggestion,
)
from app.services import ingestion
from app.services.diff import FilePatch, in_changed_lines, parse_hunks, parse_unified_diff
from app.services.findings import deduplicate, validate_ai_findings, validate_test_suggestions
from app.services.test_suggestions import is_test_file, suggest_for_changes

log = logging.getLogger(__name__)


def review_root(settings: Settings, job: ReviewJob, repo: Repository) -> Path | None:
    if job.kind == "full":
        return Path(repo.snapshot_dir) if repo.snapshot_dir else None
    return settings.data_dir / "snapshots" / str(repo.id) / f"review-{job.id}"


def _prepare_local_diff(job: ReviewJob, repo: Repository, settings: Settings) -> tuple[Path, list[FilePatch]]:
    src = ingestion.validate_local_path(repo.source_ref, settings)
    base = ingestion.resolve_ref(src, job.base_ref or "HEAD~1")
    head = ingestion.resolve_ref(src, job.head_ref or "HEAD")
    job.stats = {**job.stats, "base_sha": base, "head_sha": head}
    root = ingestion.new_snapshot_dir(settings, repo.id, f"review-{job.id}")
    ingestion.export_git_tree(src, head, root, settings)
    return root, parse_unified_diff(ingestion.git_diff(src, base, head))


def _prepare_pull_request(
    db: Session, job: ReviewJob, repo: Repository, settings: Settings, github_factory: Callable
) -> tuple[Path, list[FilePatch]]:
    account = db.query(GitHubAccount).filter_by(user_id=repo.owner_id).one_or_none()
    if account is None:
        raise ingestion.IngestionError("Connect a GitHub account to review pull requests.")
    pr = db.get(PullRequest, job.pull_request_id)
    if pr is None:
        raise ingestion.IngestionError("The pull request record no longer exists.")
    gh = github_factory(decrypt_secret(account.encrypted_token), settings)
    meta = gh.pull(repo.source_ref, pr.number)
    pr.head_sha, pr.base_sha, pr.title = meta["head_sha"], meta["base_sha"], meta["title"]
    files = gh.pull_files(repo.source_ref, pr.number)
    root = ingestion.new_snapshot_dir(settings, repo.id, f"review-{job.id}")
    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / "head.zip"
        gh.download_zipball(repo.source_ref, pr.head_sha, zpath)
        ingestion.safe_extract_zip(zpath, root, settings, strip_top=True)
    patches = []
    for f in files:
        fp = FilePatch(path=f["path"], old_path=f["previous_path"], status=f["status"])
        if f["patch"]:
            parse_hunks(f["patch"], fp)
        fp.additions, fp.deletions = f["additions"], f["deletions"]
        patches.append(fp)
    job.stats = {**job.stats, "base_sha": pr.base_sha, "head_sha": pr.head_sha}
    return root, patches


def run_review(
    db: Session,
    job: ReviewJob,
    settings: Settings,
    provider_factory: Callable[[Settings], LLMProvider] = get_provider,
    github_factory: Callable | None = None,
    analyzers: list | None = None,
    set_stage: Callable[[str], None] = lambda s: None,
) -> None:
    """Execute a claimed job. Raises on fatal errors; the worker records them."""
    from app.integrations.github import GitHubClient

    repo = db.get(Repository, job.repository_id)
    if repo is None:
        raise ingestion.IngestionError("Repository was deleted.")
    timings: dict[str, int] = {}
    t0 = time.monotonic()

    set_stage("preparing")
    patches: list[FilePatch] | None
    if job.kind == "full":
        if not repo.snapshot_dir:
            raise ingestion.IngestionError("Repository has not been indexed yet.")
        root, patches = Path(repo.snapshot_dir), None
    elif job.kind == "diff":
        root, patches = _prepare_local_diff(job, repo, settings)
    elif job.kind == "pull_request":
        root, patches = _prepare_pull_request(db, job, repo, settings, github_factory or GitHubClient)
    else:
        raise ValueError(f"unknown review kind {job.kind}")
    discovery = ingestion.discover_files(root, settings)
    lang = {f.path: f.language for f in discovery.files}
    test_files = [p for p in lang if is_test_file(p) and p.endswith(".py")]
    timings["prepare_ms"] = int((time.monotonic() - t0) * 1000)

    by_path: dict[str, FilePatch] = {}
    if patches is not None:
        for fp in patches:
            db.add(
                ChangedFile(
                    review_id=job.id,
                    path=fp.path,
                    status=fp.status,
                    additions=fp.additions,
                    deletions=fp.deletions,
                    patch=fp.patch[:200_000] if fp.patch else None,
                )
            )
            if fp.status != "deleted" and fp.path in lang:
                by_path[fp.path] = fp
        targets = list(by_path)
    else:
        targets = list(lang)

    # --- deterministic analysis ---------------------------------------------------------
    set_stage("static_analysis")
    t1 = time.monotonic()
    static: list[NormalizedFinding] = []
    analyzer_info: dict[str, dict] = {}
    for analyzer in analyzers if analyzers is not None else default_analyzers():
        files = [p for p in targets if lang[p] in analyzer.languages]
        info = {"version": analyzer.version(), "files": len(files), "status": "ok"}
        if files:
            try:
                found = analyzer.run(root, files)
                info["raw_findings"] = len(found)
                static += found
            except AnalyzerError as e:
                info["status"] = "failed"
                info["error"] = str(e)[:500]
        analyzer_info[analyzer.name] = info
    if patches is not None:
        before = len(static)
        static = [
            f for f in static if f.path in by_path and in_changed_lines(by_path[f.path], f.start_line, f.end_line)
        ]
        analyzer_info["_filtered_outside_changed_lines"] = {"count": before - len(static)}
    timings["static_ms"] = int((time.monotonic() - t1) * 1000)

    # --- AI review -------------------------------------------------------------------------
    ai_findings: list[NormalizedFinding] = []
    ai_tests = []
    ai_stats: dict = {"status": "not_requested"}
    if job.use_ai:
        set_stage("ai_review")
        t2 = time.monotonic()
        if not repo.ai_review_allowed:
            ai_stats = {"status": "skipped", "reason": "AI review is not enabled for this repository."}
        else:
            try:
                provider = provider_factory(settings)
            except ProviderUnavailable as e:
                provider = None
                ai_stats = {"status": "skipped", "reason": str(e)}
            if provider is not None:
                ordered = sorted(
                    targets,
                    key=lambda p: (is_test_file(p), -(by_path[p].additions if p in by_path else 0), p),
                )
                ctx_targets = [
                    (p, lang[p], by_path.get(p)) for p in ordered if lang[p] not in ("markdown", "text", "json")
                ]
                title = f"{repo.name} ({job.kind})"
                ctx = build_context(root, ctx_targets, static, test_files, settings.llm_max_context_chars, title)
                result = provider.review(SYSTEM_PROMPT, ctx.user_prompt)
                ai_stats = {
                    "model": result.model,
                    "provider": provider.name,
                    "latency_ms": result.latency_ms,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "attempts": result.attempts,
                    "context_chars": ctx.chars,
                    "files_in_context": len(ctx.shown),
                    "files_omitted": ctx.omitted_files[:50],
                }
                if result.review is None:
                    ai_stats |= {"status": "failed", "reason": result.error}
                else:
                    report = validate_ai_findings(result.review.findings, root, ctx.shown, result.model)
                    ai_findings = report.accepted
                    ai_tests = validate_test_suggestions(result.review.test_suggestions, ctx.shown)
                    ai_stats |= {
                        "status": "completed",
                        "summary": result.review.summary,
                        "returned": len(result.review.findings),
                        "accepted": len(report.accepted),
                        "rejected": [{"title": t[:120], "reason": r} for t, r in report.rejected],
                    }
        timings["ai_ms"] = int((time.monotonic() - t2) * 1000)

    # --- merge & persist ---------------------------------------------------------------------
    set_stage("saving")
    kept, dropped = deduplicate(static, ai_findings)
    for f in kept:
        db.add(
            Finding(
                review_id=job.id,
                source=f.source,
                analyzer=f.analyzer,
                analyzer_version=f.analyzer_version,
                rule_id=f.rule_id,
                title=f.title[:512],
                description=f.description,
                severity=f.severity,
                category=f.category,
                path=f.path,
                start_line=f.start_line,
                end_line=f.end_line,
                evidence=f.evidence,
                reasoning=f.reasoning,
                suggested_fix=f.suggested_fix,
                suggested_test=f.suggested_test,
                confidence=f.confidence,
                limitations=f.limitations,
                doc_url=f.doc_url,
            )
        )
    changed: dict[str, set[int] | None] = {
        p: (by_path[p].added_lines if patches is not None else None) for p in targets
    }
    for s in suggest_for_changes(root, changed, test_files):
        db.add(
            TestSuggestion(
                review_id=job.id,
                source="static",
                target=s.target,
                path=s.path,
                start_line=s.start_line,
                rationale=s.rationale,
                test_code=s.test_code,
            )
        )
    for t in ai_tests:
        db.add(
            TestSuggestion(
                review_id=job.id,
                source="ai",
                target=t.target[:512],
                path=t.path.removeprefix("./"),
                start_line=t.start_line,
                rationale=t.rationale,
                test_code=t.test_code,
            )
        )
    timings["total_ms"] = int((time.monotonic() - t0) * 1000)
    job.stats = {
        **job.stats,
        "timings": timings,
        "analyzers": analyzer_info,
        "ai": ai_stats,
        "files_reviewed": len(targets),
        "duplicates_dropped": dropped,
        "findings": {"static": sum(f.source == "static" for f in kept), "ai": sum(f.source == "ai" for f in kept)},
    }
