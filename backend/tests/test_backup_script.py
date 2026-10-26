"""scripts/backup.sh, run against a fake `docker` on PATH: no containers, databases or real backups."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backup.sh"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")

# Prints a fake dump for pg_dump and a fake archive for tar; FAIL_ON=<word> makes that call fail.
FAKE_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "$CALLS"
case "$*" in *"$FAIL_ON"*) [ -n "$FAIL_ON" ] && { echo "boom" >&2; exit 1; } ;; esac
case "$*" in *pg_dump*) printf 'PGDMP-fake' ;; *tar*) printf 'tar-fake' ;; esac
"""


def _run(tmp_path: Path, fail_on: str = "") -> tuple[subprocess.CompletedProcess, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "docker"
    fake.write_text(FAKE_DOCKER, newline="\n")
    fake.chmod(0o755)
    dest = tmp_path / "backups"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAIL_ON": fail_on,
        "CALLS": str(tmp_path / "calls.txt"),
    }
    proc = subprocess.run([BASH, str(SCRIPT), str(dest)], env=env, capture_output=True, text=True, timeout=60)
    return proc, dest


def test_success_writes_both_files_under_final_names(tmp_path):
    proc, dest = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr
    names = sorted(p.name for p in dest.iterdir())
    assert len(names) == 2 and names[0].endswith(".dump") and names[1].endswith(".tar.gz")
    assert (dest / names[0]).read_text() == "PGDMP-fake"
    calls = (tmp_path / "calls.txt").read_text()
    assert "exec -T db pg_dump -U devpilot -d devpilot -Fc" in calls
    assert "exec -T backend tar -czf - -C /data ." in calls  # container path not rewritten
    assert "password" not in calls.lower()


@pytest.mark.parametrize("fail_on", ["pg_dump", "tar"])
def test_failure_leaves_no_backup_and_no_partial_file(tmp_path, fail_on):
    proc, dest = _run(tmp_path, fail_on)
    assert proc.returncode != 0
    assert list(dest.iterdir()) == []


def test_existing_backups_are_never_touched(tmp_path):
    dest = tmp_path / "backups"
    dest.mkdir()
    old = dest / "devpilot-20200101-000000.dump"
    old.write_text("old")
    _run(tmp_path, "tar")
    _run(tmp_path)
    assert old.read_text() == "old" and len(list(dest.iterdir())) == 3
