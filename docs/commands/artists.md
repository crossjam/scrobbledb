# `scrobbledb artists`

Artist investigation commands. Browse all artists, view top artists over different time periods, and see detailed statistics for specific artists.

## Group usage

<!-- [[[cog
from click.testing import CliRunner
from scrobbledb.cli import cli
runner = CliRunner()
result = runner.invoke(cli, ["artists", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli artists [OPTIONS] COMMAND [ARGS]...

  Artist investigation commands.

  Browse artists, view top artists, and see detailed statistics.

Options:
  --help  Show this message and exit.

Commands:
  list    List all artists in the database with play statistics.
  search  Search for artists using fuzzy matching.
  show    Display detailed information about a specific artist.
  top     Show top artists with flexible time range support.
```
<!-- [[[end]]] -->

## Subcommands

### `list`
List all artists in the database with play statistics. Supports sorting by play count, name, or recent activity.

<!-- [[[cog
result = runner.invoke(cli, ["artists", "list", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli artists list [OPTIONS]

  List all artists in the database with play statistics.

  Browse all artists you've listened to with sorting options.

  Examples:
      # List top 50 artists by play count
      scrobbledb artists list

      # List all artists alphabetically     scrobbledb artists list --sort name
      --order asc --limit 1000

      # List artists with at least 100 plays     scrobbledb artists list --min-
      plays 100

      # Show recently played artists     scrobbledb artists list --sort recent

Options:
  -d, --database FILE             Database path (default: XDG data directory)
  -l, --limit INTEGER             Maximum results  [default: 50]
  --sort [plays|name|recent]      Sort by: plays, name, or recent  [default:
                                  plays]
  --order [desc|asc]              Sort order  [default: desc]
  --min-plays INTEGER             Show only artists with at least N plays
                                  [default: 0]
  --format [table|csv|json|jsonl]
                                  Output format  [default: table]
  --fields TEXT                   Fields to include in output (comma-separated
                                  or repeated). Available: id, artist, plays,
                                  tracks, albums, last_played
  --help                          Show this message and exit.
```
<!-- [[[end]]] -->

### `top`
Show top artists with flexible time range support. Analyze listening patterns over different time periods with statistics including percentage of total plays and average plays per day.

<!-- [[[cog
result = runner.invoke(cli, ["artists", "top", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli artists top [OPTIONS]

  Show top artists with flexible time range support.

  Analyze your listening patterns over different time periods.

  Examples:
      # Top 10 artists all-time
      scrobbledb artists top

      # Top 20 artists this year     scrobbledb artists top --limit 20 --period
      year

      # Top artists in last 30 days     scrobbledb artists top --since "30 days
      ago"

      # Top artists in specific date range     scrobbledb artists top --since
      2024-01-01 --until 2024-03-31

Options:
  -d, --database FILE             Database path (default: XDG data directory)
  -l, --limit INTEGER             Number of artists to show  [default: 10]
  -s, --since TEXT                Start date/time for analysis period
  -u, --until TEXT                End date/time for analysis period
  --period [week|month|quarter|year|all-time]
                                  Predefined period
  --format [table|csv|json|jsonl]
                                  Output format  [default: table]
  --fields TEXT                   Fields to include in output (comma-separated
                                  or repeated). Available: rank, artist, plays,
                                  percentage, avg_per_day
  --help                          Show this message and exit.
```
<!-- [[[end]]] -->

### `show`
Display detailed information about a specific artist including top tracks and albums.

<!-- [[[cog
result = runner.invoke(cli, ["artists", "show", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli artists show [OPTIONS] [ARTIST_NAME]

  Display detailed information about a specific artist.

  Deep dive into a single artist's listening history.

  Examples:
      # Show artist details
      scrobbledb artists show "Radiohead"

      # Use artist ID     scrobbledb artists show --artist-id 123

Options:
  -d, --database FILE          Database path (default: XDG data directory)
  --artist-id INTEGER          Use artist ID instead of name
  --format [table|json|jsonl]  Output format  [default: table]
  --help                       Show this message and exit.
```
<!-- [[[end]]] -->
