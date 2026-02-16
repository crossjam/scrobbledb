# `scrobbledb tracks`

Track investigation commands. Search for tracks, view top tracks over time periods, and see detailed statistics including play history for specific tracks.

## Group usage

<!-- [[[cog
from click.testing import CliRunner
from scrobbledb.cli import cli
runner = CliRunner()
result = runner.invoke(cli, ["tracks", "--help"], prog_name='scrobbledb')
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: scrobbledb tracks [OPTIONS] COMMAND [ARGS]...

  Track investigation commands.

  Search for tracks, view top tracks, and see detailed statistics.

Options:
  --help  Show this message and exit.

Commands:
  list    List tracks with optional filters.
  search  Search for tracks using fuzzy matching.
  show    Display detailed information about a specific track.
  top     Show top tracks with flexible time range support.
```
<!-- [[[end]]] -->

## Subcommands

### `search`
Search for tracks using fuzzy matching. Find tracks by partial title with optional artist and album filtering.

<!-- [[[cog
result = runner.invoke(cli, ["tracks", "search", "--help"], prog_name='scrobbledb')
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: scrobbledb tracks search [OPTIONS] QUERY

  Search for tracks using fuzzy matching.

  Find tracks by partial title, useful for quick lookups.

  Examples:
      # Search for tracks with "love" in title
      scrobbledb tracks search "love"

      # Search within specific artist     scrobbledb tracks search "love"
      --artist "The Beatles"

      # Search within specific album     scrobbledb tracks search "love" --album
      "Sgt. Pepper"

Options:
  -d, --database FILE             Database path (default: XDG data directory)
  -l, --limit INTEGER             Maximum results  [default: 20]
  --artist TEXT                   Filter by artist name
  --album TEXT                    Filter by album title
  -f, --format [table|csv|json|jsonl]
                                  Output format  [default: table]
  --fields TEXT                   Fields to include in output. Available: id,
                                  track, artist, album, plays, last_played
  --select                        Interactive mode: select a single result and
                                  output its details as JSON
  --help                          Show this message and exit.
```
<!-- [[[end]]] -->

### `top`
Show top tracks with flexible time range support. Discover your most played tracks over various time periods with ranking and percentage statistics.

<!-- [[[cog
result = runner.invoke(cli, ["tracks", "top", "--help"], prog_name='scrobbledb')
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: scrobbledb tracks top [OPTIONS]

  Show top tracks with flexible time range support.

  Discover your most played tracks over various time periods.

  Examples:
      # Top 10 tracks all-time
      scrobbledb tracks top

      # Top 25 tracks this month     scrobbledb tracks top --limit 25 --period
      month

      # Top tracks by specific artist in last year     scrobbledb tracks top
      --artist "Radiohead" --period year

Options:
  -d, --database FILE             Database path (default: XDG data directory)
  -l, --limit INTEGER             Maximum results  [default: 20]
  --period [week|month|quarter|year|all-time]
                                  Predefined period
  -u, --until TEXT                End date/time for analysis period
  -s, --since TEXT                Start date/time for analysis period
  --artist TEXT                   Filter by artist name
  -f, --format [table|csv|json|jsonl]
                                  Output format  [default: table]
  --fields TEXT                   Fields to include. Available: rank, track,
                                  artist, album, plays, percentage
  --album TEXT                    Filter by album title
  --help                          Show this message and exit.
```
<!-- [[[end]]] -->

### `show`
Display detailed information about a specific track including play history and statistics.

<!-- [[[cog
result = runner.invoke(cli, ["tracks", "show", "--help"], prog_name='scrobbledb')
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: scrobbledb tracks show [OPTIONS] [TRACK_TITLE]

  Display detailed information about a specific track.

  View play history and statistics for a single track.

  Examples:
      # Show track details
      scrobbledb tracks show "Bohemian Rhapsody"

      # Disambiguate by artist     scrobbledb tracks show "Here Comes the Sun"
      --artist "The Beatles"

      # Show with full play history     scrobbledb tracks show "Comfortably
      Numb" --show-plays

      # Use track ID     scrobbledb tracks show --track-id 456

Options:
  -d, --database FILE             Database path (default: XDG data directory)
  --track-id TEXT                 Use track ID instead of title
  --artist TEXT                   Artist name (to disambiguate tracks with same
                                  title)
  --album TEXT                    Album title (to disambiguate further)
  --show-plays                    Show individual play timestamps
  -f, --format [table|json|jsonl]
                                  Output format  [default: table]
  --help                          Show this message and exit.
```
<!-- [[[end]]] -->
