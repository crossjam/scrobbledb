# `scrobbledb ingest`

Fetch recent plays from Last.fm/Libre.fm using saved credentials and insert them into the database. The command can limit the time window, batch inserts, emit verbose logging, and optionally dry-run to validate access without writing.

## Usage

<!-- [[[cog
from click.testing import CliRunner
from scrobbledb.cli import cli
runner = CliRunner()
result = runner.invoke(cli, ["ingest", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli ingest [OPTIONS] [DATABASE]

  Ingest play history from last.fm/libre.fm to a SQLite database.

  This command fetches your listening history and saves it to DATABASE,
  including artist, album, track, and play data with timestamps. If DATABASE is
  not specified, uses the default location in the XDG data directory.

Options:
  -a, --auth FILE       Path to read auth token from (default: XDG data
                        directory)
  --since-date DATE     Pull new posts since DATE
  --until-date DATE     Pull new posts until DATE
  --limit INTEGER       Maximum number of tracks to import
  --batch-size INTEGER  Number of records to insert in each batch (default: 100)
                        [default: 100]
  --no-batch            Disable batch inserts and insert records one at a time
  -v, --verbose         Enable verbose logging output
  --dry-run             Disable actual execution of ingest and db mods
  --help                Show this message and exit.
```
<!-- [[[end]]] -->

## Examples

- Ingest all new plays with batch inserts:
  ```bash
  uv run scrobbledb ingest
  ```
- Pull plays from a date window with verbose logging and no writes:
  ```bash
  uv run scrobbledb ingest --since-date 2024-01-01 --until-date 2024-12-31 --verbose --dry-run
  ```
