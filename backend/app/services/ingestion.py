"""Safe repository ingestion: archive extraction, local git export, file discovery.

Security-sensitive. Every path that ends up on disk goes through `_safe_member_path`, and
repository content is never executed. See docs/security.md ("Untrusted repository input").
"""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import stat
import subprocess  # noqa: S404 - git is invoked with fixed argument lists, never a shell
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from app.core.config import Settings


class IngestionError(ValueError):
    """Input was rejected. The message is safe to show to the user."""


LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".php": "php",
    ".kt": "kotlin",
    ".swift": "swift",
    ".sh": "shell",
    ".sql": "sql",
    ".md": "markdown",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".html": "html",
    ".css": "css",
    ".cfg": "ini",
    ".ini": "ini",
    ".txt": "text",
}
EXCLUDED_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".idea",
    ".vscode",
    "target",
    "vendor",
    ".next",
    "coverage",
}
# Files that commonly contain credentials. They are deleted from the snapshot so neither
# analyzers nor the LLM ever see them.
SECRET_PATTERNS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "id_dsa*",
    "id_ed25519*",
    "*.keystore",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "credentials*",
    "*.kdbx",
    "secrets.*",
]
SECRET_ALLOWLIST = {".env.example", ".env.sample", ".env.template"}


@dataclass
class DiscoveredFile:
    path: str  # posix, relative to snapshot root
    language: str
    size: int


@dataclass
class Discovery:
    files: list[DiscoveredFile] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)
    total_bytes: int = 0

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


def _safe_member_path(name: str) -> PurePosixPath | None:
    """Return a normalized relative path, or None if the archive member must be rejected."""
    name = name.replace("\\", "/")
    if not name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts) or not parts:
        return None
    if any(":" in p or "\x00" in p for p in parts):  # NTFS streams, NUL tricks
        return None
    return PurePosixPath(*parts)


def safe_extract_zip(zip_path: Path, dest: Path, settings: Settings, strip_top: bool = False) -> None:
    """Extract an untrusted ZIP into `dest`, enforcing traversal, symlink and size rules.

    strip_top: drop a single wrapping folder (GitHub zipballs, or a user zipping a folder)."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise IngestionError("The file is not a valid ZIP archive.") from e
    with zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        if len(members) > settings.max_files:
            raise IngestionError(f"Archive has more than {settings.max_files} files.")
        declared = sum(m.file_size for m in members)
        if declared > settings.max_repo_bytes:
            raise IngestionError("Archive exceeds the maximum repository size.")
        paths: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
        for m in members:
            rel = _safe_member_path(m.filename)
            if rel is None:
                raise IngestionError(f"Archive contains an unsafe path: {m.filename[:200]!r}")
            mode = m.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise IngestionError("Archive contains symbolic links, which are not allowed.")
            paths.append((m, rel))

        tops = {rel.parts[0] for _, rel in paths}
        strip = strip_top and len(tops) == 1 and all(len(rel.parts) > 1 for _, rel in paths)

        dest_resolved = dest.resolve()
        written = 0
        for m, rel in paths:
            if strip:
                rel = PurePosixPath(*rel.parts[1:])
            target = (dest / rel).resolve()
            if not target.is_relative_to(dest_resolved):
                raise IngestionError("Archive path escapes the extraction directory.")
            if m.file_size > settings.max_file_bytes:
                continue  # oversized files are never written to disk
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(m) as src, open(target, "wb") as out:
                # Count real bytes: the declared size in the header can lie (zip bombs).
                while chunk := src.read(64 * 1024):
                    written += len(chunk)
                    if written > settings.max_repo_bytes:
                        raise IngestionError("Archive exceeds the maximum repository size.")
                    out.write(chunk)


def validate_local_path(raw: str, settings: Settings) -> Path:
    """Only directories beneath DEVPILOT_ALLOWED_LOCAL_ROOTS may be ingested."""
    if not settings.allowed_local_roots:
        raise IngestionError("Local repository import is disabled on this server.")
    path = Path(raw).expanduser().resolve()
    roots = [r.expanduser().resolve() for r in settings.allowed_local_roots]
    if not any(path.is_relative_to(r) for r in roots):
        raise IngestionError("Path is outside the directories this server is allowed to read.")
    if not (path / ".git").exists():
        raise IngestionError("Path is not a Git repository.")
    return path


_REF_RE = re.compile(r"^[A-Za-z0-9._/~^@{}\-]{1,200}$")


def _git(repo: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[bytes]:
    # Disable hooks and fsmonitor: a repository's own config must never cause execution.
    cmd = [
        "git",
        "-c",
        "core.hooksPath=" + os.devnull,
        "-c",
        "core.fsmonitor=false",
        "-c",
        "diff.external=",
        "-C",
        str(repo),
        *args,
    ]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout, check=True)  # noqa: S603
    except subprocess.CalledProcessError as e:
        msg = e.stderr.decode(errors="replace").strip().splitlines()[-1:] or ["git failed"]
        raise IngestionError(f"git: {msg[0][:300]}") from e
    except subprocess.TimeoutExpired as e:
        raise IngestionError("git command timed out.") from e


def resolve_ref(repo: Path, ref: str) -> str:
    if not _REF_RE.match(ref) or ref.startswith("-"):
        raise IngestionError(f"Invalid Git ref: {ref[:100]!r}")
    out = _git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
    return out.stdout.decode().strip()


def export_git_tree(repo: Path, sha: str, dest: Path, settings: Settings) -> None:
    """Export a commit with `git archive` (tracked files only, no hooks, no working tree)."""
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "tree.zip"
        _git(repo, "archive", "--format=zip", "-o", str(zip_path), sha, timeout=120)
        safe_extract_zip(zip_path, dest, settings)


def git_diff(repo: Path, base_sha: str, head_sha: str) -> str:
    out = _git(repo, "diff", "--no-ext-diff", "--no-textconv", "--no-color", "-M", "--unified=3", base_sha, head_sha)
    return out.stdout.decode("utf-8", errors="replace")


def _is_secret(name: str) -> bool:
    if name in SECRET_ALLOWLIST:
        return False
    return any(fnmatch.fnmatch(name.lower(), p) for p in SECRET_PATTERNS)


def _looks_binary(path: Path) -> bool:
    with open(path, "rb") as f:
        head = f.read(8192)
    if b"\x00" in head:
        return True
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as e:
        # A multi-byte char cut at the 8 KiB boundary is fine; anything earlier is not text.
        return e.start < len(head) - 4
    return False


def discover_files(root: Path, settings: Settings) -> Discovery:
    """Walk a snapshot, delete secret files, and list analyzable text files."""
    result = Discovery()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS)
        for name in sorted(filenames):
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            if full.is_symlink():
                full.unlink()
                result.skip("symlink")
                continue
            if _is_secret(name):
                full.unlink()
                result.skip("secret_file")
                continue
            ext = full.suffix.lower()
            language = LANGUAGES.get(ext)
            if language is None:
                result.skip("unsupported_type")
                continue
            size = full.stat().st_size
            if size > settings.max_file_bytes:
                result.skip("too_large")
                continue
            if _looks_binary(full):
                result.skip("binary")
                continue
            result.files.append(DiscoveredFile(rel, language, size))
            result.total_bytes += size
    return result


def new_snapshot_dir(settings: Settings, repo_id: int, label: str) -> Path:
    path = settings.data_dir / "snapshots" / str(repo_id) / label
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def read_text(root: Path, rel: str) -> str:
    """Read a snapshot file by relative path, refusing anything outside the snapshot."""
    target = (root / rel).resolve()
    if not target.is_relative_to(root.resolve()):
        raise IngestionError("Path escapes the repository snapshot.")
    return target.read_text(encoding="utf-8", errors="replace")
