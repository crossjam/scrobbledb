# `scrobbledb plays`

View and filter your listening history chronologically. The `plays` command group provides domain-specific commands for exploring your scrobble history without requiring SQL knowledge.

## Group usage

<!-- [[[cog
from click.testing import CliRunner
from scrobbledb.cli import cli
runner = CliRunner()
result = runner.invoke(cli, ["plays", "--help"], prog_name='scrobbledb')
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli plays [OPTIONS] COMMAND [ARGS]...

  Play history commands.

  View and filter your listening history chronologically.

Options:
  --help  Show this message and exit.

Commands:
  list  List recent plays with filtering and pagination.
```
<!-- [[[end]]] -->

## Subcommands

### `list`
List recent plays with filtering and pagination. Supports flexible date filtering using relative expressions like "7 days ago" or ISO 8601 dates.

<!-- [[[cog
result = runner.invoke(cli, ["plays", "list", "--help"], prog_name='scrobbledb')
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli plays list [OPTIONS]

  List recent plays with filtering and pagination.

  View listening history chronologically with flexible filtering.

  Examples:
      # List last 20 plays
      scrobbledb plays list

      # List last 50 plays     scrobbledb plays list --limit 50

      # List plays in the last week     scrobbledb plays list --since "7 days
      ago"

      # List plays for a specific artist     scrobbledb plays list --artist
      "Pink Floyd" --limit 100

      # List plays in a specific date range     scrobbledb plays list --since
      2024-01-01 --until 2024-12-31

      # Export to CSV     scrobbledb plays list --format csv > my_plays.csv

Options:
  -d, --database FILE             Database path (default: XDG data directory)
  -l, --limit INTEGER             Maximum number of plays to return  [default:
                                  20]
  -s, --since TEXT                Show plays since date/time (ISO 8601 format or
                                  relative like "7 days ago")
  -u, --until TEXT                Show plays until date/time (ISO 8601 format)
  --artist TEXT                   Filter by artist name (case-insensitive
                                  partial match)
  --album TEXT                    Filter by album title (case-insensitive
                                  partial match)
  --track TEXT                    Filter by track title (case-insensitive
                                  partial match)
  --format [table|csv|json|jsonl]
                                  Output format  [default: table]
  --fields TEXT                   Fields to include in output (comma-separated
                                  or repeated). Available: timestamp, artist,
                                  track, album
  --help                          Show this message and exit.
```
<!-- [[[end]]] -->
