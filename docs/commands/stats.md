# `scrobbledb stats`

Summaries of your listening history. All subcommands default to the standard database path and support table or machine-readable formats.

## Group usage

<!-- [[[cog
from click.testing import CliRunner
from scrobbledb.cli import cli
runner = CliRunner()
result = runner.invoke(cli, ["stats", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli stats [OPTIONS] COMMAND [ARGS]...

  Descriptive statistics about your scrobbles.

  View overview metrics, monthly rollups, and yearly summaries of your listening
  history.

  Examples:

      # View overall statistics     scrobbledb stats overview

      # View monthly rollup     scrobbledb stats monthly

      # View yearly rollup     scrobbledb stats yearly

      # Export to JSON     scrobbledb stats monthly --format json

Options:
  --help  Show this message and exit.

Commands:
  monthly   Display scrobble statistics rolled up by month.
  overview  Display overall scrobble statistics.
  yearly    Display scrobble statistics rolled up by year.
```
<!-- [[[end]]] -->

## Subcommands

### `overview`
Totals for scrobbles, unique artists/albums/tracks, and the listen date range.

<!-- [[[cog
result = runner.invoke(cli, ["stats", "overview", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli stats overview [OPTIONS]

  Display overall scrobble statistics.

  Shows total scrobbles, unique artists, albums, and tracks, plus the date range
  of your listening history.

  Examples:

      # View statistics as a table     scrobbledb stats overview

      # Export to JSON     scrobbledb stats overview --format json

Options:
  -d, --database TEXT             Database path (default: XDG data dir)
  -f, --format [table|json|jsonl|csv]
                                  Output format (default: table)
  --help                          Show this message and exit.
```
<!-- [[[end]]] -->

### `monthly`
Monthly play counts with optional relative or absolute date bounds and an optional limit on the number of months returned.

<!-- [[[cog
result = runner.invoke(cli, ["stats", "monthly", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli stats monthly [OPTIONS]

  Display scrobble statistics rolled up by month.

  Shows scrobble counts, unique artists, albums, and tracks for each month.
  Results are ordered by date, most recent first.

  Examples:

      # View all months     scrobbledb stats monthly

      # View last 12 months     scrobbledb stats monthly --limit 12

      # View since a specific date     scrobbledb stats monthly --since
      2024-01-01

      # View last year     scrobbledb stats monthly --since "1 year ago"

      # Export to CSV     scrobbledb stats monthly --format csv >
      monthly_stats.csv

Options:
  -d, --database TEXT             Database path (default: XDG data dir)
  -s, --since TEXT                Start date (ISO 8601 or relative like '7 days
                                  ago')
  -u, --until TEXT                End date (ISO 8601 or relative)
  -l, --limit INTEGER             Maximum number of months to display
  -f, --format [table|json|jsonl|csv]
                                  Output format (default: table)
  --help                          Show this message and exit.
```
<!-- [[[end]]] -->

### `yearly`
Yearly play counts using the same filtering options as `monthly`.

<!-- [[[cog
result = runner.invoke(cli, ["stats", "yearly", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli stats yearly [OPTIONS]

  Display scrobble statistics rolled up by year.

  Shows scrobble counts, unique artists, albums, and tracks for each year.
  Results are ordered by date, most recent first.

  Examples:

      # View all years     scrobbledb stats yearly

      # View last 5 years     scrobbledb stats yearly --limit 5

      # View since a specific year     scrobbledb stats yearly --since
      2020-01-01

      # Export to JSON     scrobbledb stats yearly --format json

Options:
  -d, --database TEXT             Database path (default: XDG data dir)
  -s, --since TEXT                Start date (ISO 8601 or relative like '7 days
                                  ago')
  -u, --until TEXT                End date (ISO 8601 or relative)
  -l, --limit INTEGER             Maximum number of years to display
  -f, --format [table|json|jsonl|csv]
                                  Output format (default: table)
  --help                          Show this message and exit.
```
<!-- [[[end]]] -->
