# `scrobbledb about`

Display project information, the installed version, and the default storage paths used by scrobbledb.

## Usage

<!-- [[[cog
from click.testing import CliRunner
from scrobbledb.cli import cli
runner = CliRunner()
result = runner.invoke(cli, ["about", "--help"], prog_name='scrobbledb')
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: scrobbledb about [OPTIONS]

  Display information about the scrobbledb project.

  Shows project summary, version, repository URL, and default storage paths.

Options:
  --help  Show this message and exit.
```
<!-- [[[end]]] -->

## Examples

- Show the project summary and default paths:
  ```bash
  uv run scrobbledb about
  ```

- Use this when you want a quick project overview without querying the database.
