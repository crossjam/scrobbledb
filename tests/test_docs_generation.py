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
    env["COLUMNS"] = "100"

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


def test_every_command_is_documented_and_listed():
    """Each CLI command has a page and appears in both command indexes."""
    from scrobbledb.cli import cli

    repo_root = Path(__file__).resolve().parents[1]
    cli_index = (repo_root / "docs" / "cli.md").read_text()
    readme = (repo_root / "README.md").read_text()

    commands = sorted(cli.commands)
    assert len(commands) >= 15, "command discovery found too few commands"

    missing = []
    for name in commands:
        page = f"docs/commands/{name}.md"
        if not (repo_root / page).exists():
            missing.append(f"{name}: no {page}")
        if f"(commands/{name}.md)" not in cli_index:
            missing.append(f"{name}: not in the docs/cli.md command index")
        if f"(docs/commands/{name}.md)" not in readme:
            missing.append(f"{name}: not in the README command overview")
    assert not missing, missing
