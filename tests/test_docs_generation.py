import os
import subprocess
import sys
from pathlib import Path


def test_cli_docs_are_up_to_date():
    """Ensure cog can regenerate CLI docs and they are already in sync."""

    repo_root = Path(__file__).resolve().parents[1]
    command_docs = sorted((repo_root / "docs" / "commands").glob("*.md"))
    assert command_docs, "Expected CLI documentation files under docs/commands"

    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")

    subprocess.run(
        [sys.executable, "-m", "cogapp", "-r", *map(str, command_docs)],
        cwd=repo_root,
        env=env,
        check=True,
    )

    diff = subprocess.run(
        ["git", "diff", "--name-only", "docs/commands"],
        cwd=repo_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert diff.stdout.strip() == "", "CLI docs were regenerated; commit the updated files"
