# `scrobbledb albums`

Album investigation commands. Search for albums and view detailed information about specific albums and their tracks.

## Group usage

<!-- [[[cog
from click.testing import CliRunner
from scrobbledb.cli import cli
runner = CliRunner()
result = runner.invoke(cli, ["albums", "--help"], prog_name='scrobbledb')
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: scrobbledb albums [OPTIONS] COMMAND [ARGS]...

  Album investigation commands.

  Search for albums and view detailed information.

Options:
  --help  Show this message and exit.

Commands:
  list    List albums with optional artist filter.
  search  Search for albums using fuzzy matching.
  show    Display detailed information about a specific album and list its...
```
<!-- [[[end]]] -->

## Subcommands

### `search`
Search for albums using fuzzy matching. Find albums by partial name when you don't remember exact titles.

<!-- [[[cog
result = runner.invoke(cli, ["albums", "search", "--help"], prog_name='scrobbledb')
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: scrobbledb albums search [OPTIONS] QUERY

  Search for albums using fuzzy matching.

  Find albums by partial name, useful when you don't remember exact titles.

  Examples:
      # Search for albums with "dark" in the title
      scrobbledb albums search "dark"

      # Search for albums by specific artist     scrobbledb albums search "dark"
      --artist "Pink Floyd"

      # Get top 10 results     scrobbledb albums search "greatest" --limit 10

Options:
  -d, --database FILE             Database path (default: XDG data directory)
  -l, --limit INTEGER             Maximum results  [default: 20]
  --artist TEXT                   Filter by artist name
  --format [table|csv|json|jsonl]
                                  Output format  [default: table]
  --fields TEXT                   Fields to include in output (comma-separated
                                  or repeated). Available: id, album, artist,
                                  tracks, plays, last_played
  --select                        Interactive mode: select a single result and
                                  output its details as JSON
  --help                          Show this message and exit.
```
<!-- [[[end]]] -->

### `show`
Display detailed information about a specific album and list its tracks with play statistics.

<!-- [[[cog
result = runner.invoke(cli, ["albums", "show", "--help"], prog_name='scrobbledb')
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: scrobbledb albums show [OPTIONS] [ALBUM_TITLE]

  Display detailed information about a specific album and list its tracks.

  View all tracks in an album with play statistics.

  Examples:
      # Show tracks in an album
      scrobbledb albums show "The Dark Side of the Moon"

      # Disambiguate by artist     scrobbledb albums show "Rubber Soul" --artist
      "The Beatles"

      # Use album ID     scrobbledb albums show --album-id 42

Options:
  -d, --database FILE          Database path (default: XDG data directory)
  --album-id TEXT              Use album ID instead of title
  --artist TEXT                Artist name (to disambiguate albums with same
                               title)
  --format [table|json|jsonl]  Output format  [default: table]
  --help                       Show this message and exit.
```
<!-- [[[end]]] -->
