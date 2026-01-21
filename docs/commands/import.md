# `scrobbledb import`

Load scrobbles from JSONL, CSV, or TSV files (or stdin) into the database. The command validates rows, can skip duplicates, and optionally refreshes the FTS5 index.

## Usage

<!-- [[[cog
from click.testing import CliRunner
from scrobbledb.cli import cli
runner = CliRunner()
result = runner.invoke(cli, ["import", "--help"], prog_name='scrobbledb')
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: scrobbledb import [OPTIONS] [DATABASE]

  Import scrobbles to the database from a file or stdin.

  Supports JSONL (JSON Lines) and CSV/TSV formats with automatic detection. Each
  scrobble requires: artist, track, and timestamp. Album is optional (defaults
  to "(unknown album)").

  Examples:
      # Import from file
      scrobbledb import --file scrobbles.jsonl

      # Import from stdin     cat scrobbles.jsonl | scrobbledb import

      # Limit to first 100 records     scrobbledb import --file data.jsonl
      --limit 100

      # Sample 10% of records     scrobbledb import --file data.jsonl --sample
      0.1

      # Validate without importing     scrobbledb import --file data.csv --dry-
      run

Options:
  -f, --file FILE                 Read from file (use '-' for stdin)
  --format [jsonl|csv|tsv|auto]   Input format  [default: auto]
  --skip-errors                   Continue on errors instead of aborting
  --dry-run                       Validate input without saving to database
  --no-duplicates                 Skip scrobbles with duplicate timestamp+track
  --update-index / --no-update-index
                                  Update FTS5 search index after importing
  --limit INTEGER                 Import at most N records
  --sample FLOAT                  Sample probability 0.0-1.0
  --seed INTEGER                  Random seed for reproducible sampling (use
                                  with --sample)
  --help                          Show this message and exit.
```
<!-- [[[end]]] -->

## Examples

- Import JSONL data from stdin while skipping duplicates:
  ```bash
  cat plays.jsonl | uv run scrobbledb import --file - --format jsonl --no-duplicates
  ```
- Sample 10% of a CSV file and update the search index after loading:
  ```bash
  uv run scrobbledb import --file data.csv --format csv --sample 0.1 --update-index
  ```
