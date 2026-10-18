"""Machine-readable output must stay plain when FORCE_COLOR is set.

Rich honours FORCE_COLOR and emits ANSI escapes even when stdout is a pipe, so a
command that prints JSON/CSV through a Rich console produces output that no
parser accepts. The command set is derived from the real click tree.
"""

import csv
import io
import json
import sys

import click
import pytest
from click.testing import CliRunner
from rich.color import ColorSystem
from rich.console import Console

from scrobbledb import cli

MACHINE_FORMATS = ("json", "jsonl", "csv")

# Arguments that make a command succeed against the shared fixture database.
EXTRA_ARGS = {
    ("albums", "search"): ["Album"],
    ("artists", "search"): ["Artist"],
    ("tracks", "search"): ["Track"],
    ("albums", "show"): ["--album-id", "alb1"],
    ("artists", "show"): ["--artist-id", "a1"],
    ("tracks", "show"): ["--track-id", "t1"],
}
# Their --format describes a file being read or written, not rows on stdout.
EXCLUDED = {("import",), ("export",)}


def _walk(command, path=()):
    if isinstance(command, click.Group):
        for name, sub in command.commands.items():
            yield from _walk(sub, path + (name,))
    else:
        yield path, command


def _format_commands():
    found = []
    for path, command in _walk(cli.cli):
        if path in EXCLUDED:
            continue
        fmt = next((p for p in command.params if p.name == "format"), None)
        if fmt is None:
            continue
        for choice in MACHINE_FORMATS:
            if choice in fmt.type.choices:
                found.append((path, choice))
    return found


CASES = _format_commands()


@pytest.fixture
def force_color(monkeypatch):
    """Behave as if the process had been started with FORCE_COLOR=3.

    Rich reads FORCE_COLOR when a Console is constructed, and the commands build
    theirs at import time, so setting the variable inside a test is too late.
    Instead put every module-level Console in scrobbledb into the state the
    variable would have given it.
    """
    monkeypatch.setenv("FORCE_COLOR", "3")
    monkeypatch.delenv("NO_COLOR", raising=False)
    consoles = [
        value
        for name, module in list(sys.modules.items())
        if name.startswith("scrobbledb")
        for value in vars(module).values()
        if isinstance(value, Console)
    ]
    assert len(consoles) >= 5
    for console in consoles:
        monkeypatch.setattr(console, "_force_terminal", True)
        monkeypatch.setattr(console, "_color_system", ColorSystem.TRUECOLOR)
        monkeypatch.setattr(console, "no_color", False)


def test_force_color_fixture_really_colors(force_color):
    console = Console(file=io.StringIO(), force_terminal=True)
    console.print("[red]x[/red]")
    assert "\x1b" in console.file.getvalue()
    from scrobbledb.commands import stats

    with stats.console.capture() as cap:
        stats.console.print("[red]x[/red]")
    assert "\x1b" in cap.get()


def test_derived_case_set_is_not_vacuous():
    paths = {path for path, _ in CASES}
    assert len(paths) >= 14
    assert ("stats", "yearly") in paths


@pytest.mark.parametrize(
    "path,fmt", CASES, ids=[f"{' '.join(p)}-{f}" for p, f in CASES]
)
def test_machine_format_has_no_ansi_under_force_color(
    populated_db, force_color, path, fmt
):
    args = [*path, "-d", str(populated_db), "-f", fmt, *EXTRA_ARGS.get(path, [])]
    result = CliRunner().invoke(cli.cli, args)

    assert result.exit_code == 0, result.output
    assert "\x1b" not in result.output
    text = result.output.strip()
    assert text, "fixture should produce rows for every command"
    if fmt == "json":
        json.loads(text)
    elif fmt == "jsonl":
        for line in text.splitlines():
            json.loads(line)
    else:
        assert list(csv.reader(io.StringIO(text)))
