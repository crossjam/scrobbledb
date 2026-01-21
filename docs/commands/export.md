# `scrobbledb export`

Run preset or custom queries against the database and write the results in JSONL, JSON, CSV, or TSV formats. Presets cover plays, tracks, albums, and artists; `--sql` and `--sql-file` allow custom read-only queries.

## Usage

<!-- [[[cog
from click.testing import CliRunner
from scrobbledb.cli import cli
runner = CliRunner()
result = runner.invoke(cli, ["export", "--help"], prog_name='scrobbledb')
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: scrobbledb export [OPTIONS] [[plays|tracks|albums|artists]]

  Export scrobble data in various formats.

  Export using presets (plays, tracks, albums, artists) or custom SQL queries.
  Supports multiple output formats and sampling options.

  Examples:

          # Export all plays to JSONL
          scrobbledb export plays --output plays.jsonl

      # Export 1000 most recent plays to CSV     scrobbledb export plays
      --format csv --limit 1000 --output recent.csv

      # Export 10% sample of tracks     scrobbledb export tracks --sample 0.1
      --format json --output sample.json

      # Export with custom SQL     scrobbledb export --sql "SELECT * FROM plays
      WHERE timestamp > '2025-01-01'" --format csv

      # Export from SQL file     scrobbledb export --sql-file query.sql --format
      jsonl --output results.jsonl

      # Dry run to preview query     scrobbledb export plays --limit 100 --dry-
      run

      # Select specific columns     scrobbledb export plays --columns
      "timestamp,artist_name,track_title" --format csv

Options:
  -d, --database FILE             Database path (default: scrobbledb database in
                                  XDG data dir)
  --sql TEXT                      Custom SQL query to export
  --sql-file FILE                 File containing SQL query to export
  -f, --format [jsonl|json|csv|tsv]
                                  Output format (default: jsonl)
  -o, --output FILE               Output file (use '-' for stdout, default:
                                  stdout)
  --limit INTEGER                 Maximum number of rows to export
  --sample FLOAT                  Random sample probability (0.0-1.0)
  --seed INTEGER                  Random seed for reproducible sampling (use
                                  with --sample)
  -c, --columns TEXT              Comma-separated list of columns to include
  --no-headers                    Omit headers in CSV/TSV output
  --dry-run                       Show SQL query without executing
  --help                          Show this message and exit.
```
<!-- [[[end]]] -->

## Examples

- Export recent plays to stdout in JSONL:
  ```bash
  uv run scrobbledb export plays --limit 100 --format jsonl
  ```
- Run a custom query from a file and write TSV output without headers:
  ```bash
  uv run scrobbledb export --sql-file query.sql --format tsv --no-headers > results.tsv
  ```
