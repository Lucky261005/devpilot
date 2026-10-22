"""Index a repository snapshot into `code_chunks` and search it."""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import CodeChunk, Repository, utcnow
from app.services.chunking import chunk_file
from app.services.ingestion import discover_files


def index_snapshot(db: Session, repo: Repository, root: Path, settings: Settings) -> None:
    """Replace the repository's chunks with those from `root`. Commits on success."""
    discovery = discover_files(root, settings)
    if discovery.total_bytes > settings.max_repo_bytes:
        raise ValueError("Repository exceeds the maximum indexed size.")
    db.execute(delete(CodeChunk).where(CodeChunk.repository_id == repo.id))
    for f in discovery.files:
        text = (root / f.path).read_text(encoding="utf-8", errors="replace")
        for c in chunk_file(f.path, text, f.language):
            db.add(
                CodeChunk(
                    repository_id=repo.id,
                    path=c.path,
                    language=f.language,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    content=c.content,
                    # Padded with spaces so a whole-word match is LIKE '% name %'.
                    symbols=" " + " ".join(c.symbols) + " ",
                )
            )
    repo.file_count = len(discovery.files)
    repo.total_bytes = discovery.total_bytes
    repo.skipped = discovery.skipped
    repo.snapshot_dir = str(root)
    repo.index_status = "ready"
    repo.index_error = None
    repo.indexed_at = utcnow()
    db.commit()


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search(db: Session, repo_id: int, q: str, mode: str = "text", limit: int = 50) -> list[dict]:
    """Lexical search. `identifier` matches defined names exactly; `text` is a substring
    match over chunk content (case-insensitive)."""
    # shortcut: LIKE scans every chunk of the repo; fine for MVP-sized repos, switch to
    # Postgres tsvector/pg_trgm (or SQLite FTS5) if repos grow past ~100k chunks.
    q = q.strip()
    if not q:
        return []
    base = select(CodeChunk).where(CodeChunk.repository_id == repo_id)
    if mode == "identifier":
        stmt = base.where(CodeChunk.symbols.like(f"% {_like_escape(q)} %", escape="\\"))
    else:
        terms = q.split()[:5]
        stmt = base.where(
            *[func.lower(CodeChunk.content).like(f"%{_like_escape(t.lower())}%", escape="\\") for t in terms]
        )
    rows = db.scalars(stmt.order_by(CodeChunk.path, CodeChunk.start_line).limit(limit * 2)).all()

    pattern = re.compile(
        r"\b" + re.escape(q) + r"\b" if mode == "identifier" else re.escape(q.split()[0]),
        re.I,
    )
    results, seen = [], set()
    for c in rows:
        for offset, line in enumerate(c.content.splitlines()):
            ln = c.start_line + offset
            if (c.path, ln) in seen or not pattern.search(line):
                continue
            seen.add((c.path, ln))
            results.append(
                {
                    "path": c.path,
                    "line": ln,
                    "text": line[:300],
                    "language": c.language,
                    "chunk_start": c.start_line,
                    "chunk_end": c.end_line,
                }
            )
            if len(results) >= limit:
                return results
    return results


def list_paths(db: Session, repo_id: int, prefix: str = "") -> list[str]:
    stmt = select(CodeChunk.path).where(CodeChunk.repository_id == repo_id).distinct()
    if prefix:
        stmt = stmt.where(or_(CodeChunk.path.like(f"{_like_escape(prefix)}%", escape="\\")))
    return sorted(db.scalars(stmt).all())
