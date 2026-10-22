import stat
import zipfile

import pytest

from app.services import ingestion
from app.services.ingestion import IngestionError, discover_files, safe_extract_zip


def _zip(path, entries):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries:
            z.writestr(name, data)
    return path


@pytest.mark.parametrize(
    "name", ["../evil.py", "a/../../evil.py", "/etc/passwd", "C:/win.py", "..\\evil.py", "a/b:stream.py"]
)
def test_rejects_traversal_and_absolute_paths(tmp_path, settings, name):
    z = _zip(tmp_path / "x.zip", [(name, "x")])
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(IngestionError):
        safe_extract_zip(z, dest, settings)
    assert not (tmp_path / "evil.py").exists()


def test_rejects_symlinks(tmp_path, settings):
    z = tmp_path / "x.zip"
    with zipfile.ZipFile(z, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")
    with pytest.raises(IngestionError, match="symbolic"):
        safe_extract_zip(z, tmp_path, settings)


def test_rejects_non_zip(tmp_path, settings):
    p = tmp_path / "x.zip"
    p.write_bytes(b"not a zip")
    with pytest.raises(IngestionError, match="valid ZIP"):
        safe_extract_zip(p, tmp_path, settings)


def test_enforces_size_and_count_limits(tmp_path, settings):
    small = settings.model_copy(update={"max_repo_bytes": 1000, "max_files": 2})
    z = _zip(tmp_path / "big.zip", [("a.py", "x" * 2000)])
    with pytest.raises(IngestionError, match="maximum repository size"):
        safe_extract_zip(z, tmp_path / "o1", small)
    z2 = _zip(tmp_path / "many.zip", [(f"{i}.py", "x") for i in range(3)])
    with pytest.raises(IngestionError, match="more than 2 files"):
        safe_extract_zip(z2, tmp_path / "o2", small)


def test_strips_single_top_level_folder_and_skips_oversized(tmp_path, settings):
    s = settings.model_copy(update={"max_file_bytes": 10})
    z = _zip(tmp_path / "x.zip", [("repo-sha/a.py", "x=1"), ("repo-sha/big.py", "y" * 50)])
    dest = tmp_path / "out"
    dest.mkdir()
    safe_extract_zip(z, dest, s, strip_top=True)
    assert (dest / "a.py").read_text() == "x=1"
    assert not (dest / "big.py").exists()


def test_discovery_deletes_secrets_and_skips_binary(tmp_path, settings):
    (tmp_path / "app.py").write_text("print(1)\n")
    (tmp_path / ".env").write_text("TOKEN=abc")
    (tmp_path / ".env.example").write_text("TOKEN=")
    (tmp_path / "id_rsa").write_text("key")
    (tmp_path / "blob.py").write_bytes(b"\x00\x01\x02")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("1")
    d = discover_files(tmp_path, settings)
    assert [f.path for f in d.files] == ["app.py"]
    assert not (tmp_path / ".env").exists() and not (tmp_path / "id_rsa").exists()
    assert d.skipped["secret_file"] == 2 and d.skipped["binary"] == 1


def test_local_path_must_be_under_allowed_root(tmp_path, settings):
    with pytest.raises(IngestionError, match="outside"):
        ingestion.validate_local_path(str(tmp_path), settings)
    disabled = settings.model_copy(update={"allowed_local_roots": []})
    with pytest.raises(IngestionError, match="disabled"):
        ingestion.validate_local_path(str(tmp_path), disabled)


@pytest.mark.parametrize("ref", ["--output=/tmp/x", "a b", "$(whoami)", "x;rm"])
def test_rejects_option_like_or_shell_refs(local_git_repo, ref):
    with pytest.raises(IngestionError):
        ingestion.resolve_ref(local_git_repo, ref)


def test_export_and_diff_local_repo(local_git_repo, tmp_path, settings):
    head = ingestion.resolve_ref(local_git_repo, "HEAD")
    base = ingestion.resolve_ref(local_git_repo, "HEAD~1")
    ingestion.export_git_tree(local_git_repo, head, tmp_path / "snap", settings)
    assert "def run" in (tmp_path / "snap" / "pkg" / "util.py").read_text()
    assert not (tmp_path / "snap" / ".git").exists()
    assert "+def run(cmd):" in ingestion.git_diff(local_git_repo, base, head)


def test_read_text_refuses_escape(tmp_path):
    with pytest.raises(IngestionError):
        ingestion.read_text(tmp_path, "../outside.txt")
