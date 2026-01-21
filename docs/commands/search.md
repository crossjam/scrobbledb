# `scrobbledb search`

Full-text search across artists, albums, and track titles using the FTS5 index. Customize the result limit and the fields displayed.

## Usage

<!-- [[[cog
from click.testing import CliRunner
from scrobbledb.cli import cli
runner = CliRunner()
result = runner.invoke(cli, ["search", "--help"], prog_name='scrobbledb')
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli search [OPTIONS] QUERY [DATABASE]

  Search for tracks using full-text search.

  Searches across artist names, album titles, and track titles using SQLite's
  FTS5 full-text search engine.

  Examples:     scrobbledb search "rolling stones"     scrobbledb search "love"
  --limit 10     scrobbledb search "beatles" --fields
  artist,track,plays,last_played

  If DATABASE is not specified, uses the default location in the XDG data
  directory.

  Note: You must run 'scrobbledb index' first to set up the search index.

Options:
  -l, --limit INTEGER  Maximum number of results to return  [default: 20]
  -f, --fields TEXT    Comma-separated list of fields to display (artist, album,
                       track, plays, last_played)  [default:
                       artist,album,track,plays]
  --help               Show this message and exit.
```
<!-- [[[end]]] -->

## Examples

- Search for tracks with the word "rolling" and show only artist and track columns:
  ```bash
  uv run scrobbledb search "rolling" --fields artist,track
  ```
- Return the top five results for a multi-word query:
  ```bash
  uv run scrobbledb search "talk talk spirit" --limit 5
  ```
