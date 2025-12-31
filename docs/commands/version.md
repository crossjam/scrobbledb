# `scrobbledb version`

Print the installed package version (also available via `-V/--version` on any command).

## Usage

<!-- [[[cog
from click.testing import CliRunner
from scrobbledb.cli import cli
runner = CliRunner()
result = runner.invoke(cli, ["version", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli version [OPTIONS]

  Display the scrobbledb version.

  Shows the currently installed version of scrobbledb.

Options:
  --help  Show this message and exit.
```
<!-- [[[end]]] -->
