"""Create a two-commit Git repository from the sample fixture for demos.

Commit 1 contains a correct pricing module; commit 2 introduces the seeded pricing defects.
Usage: python scripts/make_demo_repo.py <target-dir>
The target must not exist. All content is SAMPLE DATA."""

import shutil
import subprocess
import sys
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_repositories" / "inventory_service"
CLEAN_PRICING = '''BULK_THRESHOLD = 100


def apply_discount(price, quantity):
    """Orders of 100 units or more get 10% off."""
    if quantity >= BULK_THRESHOLD:
        return round(price * quantity * 0.9, 2)
    return round(price * quantity, 2)
'''


def git(cwd: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-c", "user.name=DevPilot Demo", "-c", "user.email=demo@example.invalid", *args],  # noqa: S607
        cwd=cwd, check=True,
    )


def main(target: Path) -> None:
    if target.exists():
        sys.exit(f"{target} already exists")
    shutil.copytree(FIXTURE, target, ignore=shutil.ignore_patterns("__pycache__"))
    final = (target / "inventory" / "pricing.py").read_text()
    (target / "inventory" / "pricing.py").write_text(CLEAN_PRICING)
    git(target, "init", "-q", "-b", "main")
    git(target, "add", ".")
    git(target, "commit", "-qm", "Initial inventory service (sample)")
    (target / "inventory" / "pricing.py").write_text(final)
    git(target, "commit", "-qam", "Add pagination; refactor discount check (sample with seeded defects)")
    print(f"created {target}: review HEAD~1..HEAD to see the seeded pricing defects")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]).resolve())
