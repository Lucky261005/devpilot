import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="devpilot-test-"))
os.environ.update(
    {
        "DEVPILOT_DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
        "DEVPILOT_DATA_DIR": str(_TMP / "data"),
        "DEVPILOT_RUN_WORKER_IN_PROCESS": "false",
        "DEVPILOT_ALLOWED_LOCAL_ROOTS": str(_TMP / "local"),
        "DEVPILOT_GITHUB_CLIENT_ID": "test-client",
        "DEVPILOT_GITHUB_CLIENT_SECRET": "test-secret",
        "ANTHROPIC_API_KEY": "",
        # Pin the provider so a developer's backend/.env (e.g. ollama) never leaks into tests.
        "DEVPILOT_LLM_PROVIDER": "anthropic",
    }
)
(_TMP / "local").mkdir()

from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from alembic import command  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal, engine  # noqa: E402
from app.core.ratelimit import limiter  # noqa: E402
from app.models import ReviewJob  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[2] / "fixtures" / "sample_repositories" / "inventory_service"
BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")  # tests run against the real migration, not create_all
    yield
    engine.dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


@pytest.fixture(autouse=True)
def _empty_queue():
    """The queue is shared by the test database; start each test with nothing pending."""
    with SessionLocal() as db:
        db.query(ReviewJob).filter(ReviewJob.status.in_(["queued", "running"])).update(
            {"status": "failed", "error": "cleared by test fixture"}, synchronize_session=False
        )
        db.commit()


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def db():
    with SessionLocal() as s:
        yield s


@pytest.fixture
def tmp_root(tmp_path):
    return tmp_path


def make_client() -> TestClient:
    from app.main import app

    c = TestClient(app)
    c.headers["x-devpilot-csrf"] = "1"
    return c


_counter = iter(range(10_000))


@pytest.fixture
def client():
    c = make_client()
    email = f"user{next(_counter)}@example.com"
    r = c.post("/api/auth/register", json={"email": email, "password": "correct-horse-1"})
    assert r.status_code == 201, r.text
    c.email = email  # type: ignore[attr-defined]
    return c


@pytest.fixture
def other_client():
    c = make_client()
    r = c.post(
        "/api/auth/register", json={"email": f"other{next(_counter)}@example.com", "password": "correct-horse-2"}
    )
    assert r.status_code == 201
    return c


def zip_dir(src: Path, dest: Path, prefix: str = "") -> Path:
    with zipfile.ZipFile(dest, "w") as z:
        for p in src.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                z.write(p, prefix + p.relative_to(src).as_posix())
    return dest


@pytest.fixture
def sample_zip(tmp_path):
    return zip_dir(SAMPLE, tmp_path / "sample.zip", prefix="inventory_service-abc123/")


def git(cwd: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@e.x",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@e.x",
    }
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout.strip()


@pytest.fixture
def local_git_repo():
    """A git repo under the allowed local root: commit 1 is clean, commit 2 adds defects."""
    root = Path(os.environ["DEVPILOT_ALLOWED_LOCAL_ROOTS"]) / f"repo{next(_counter)}"
    (root / "pkg").mkdir(parents=True)
    git(root, "init", "-q")
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "util.py").write_text("def add(a, b):\n    return a + b\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "init")
    (root / "pkg" / "util.py").write_text(
        "import subprocess\n\n\ndef add(a, b):\n    return a + b\n\n\n"
        "def run(cmd):\n    try:\n        return subprocess.call(cmd, shell=True)\n"
        "    except:\n        return None\n"
    )
    git(root, "commit", "-qam", "add run")
    return root
