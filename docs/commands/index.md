# `scrobbledb index`

Create or rebuild the FTS5 full-text search index. Use this after large imports or if you initialized without indexing.

## Usage

<!-- [[[cog
from click.testing import CliRunner
from scrobbledb.cli import cli
runner = CliRunner()
result = runner.invoke(cli, ["index", "--help"], prog_name='scrobbledb')
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: scrobbledb index [OPTIONS] [DATABASE]

  Set up and rebuild FTS5 full-text search index.

  Creates the FTS5 virtual table with triggers and rebuilds the search index
  from existing data. This enables fast full-text search across artists, albums,
  and tracks.

  With --analytics, creates secondary indexes on the foreign-key columns that
  join plays to tracks, tracks to albums and albums to artists, and leaves the
  search index alone. They speed up lookups that start from the parent side,
  such as the plays of a track; full-history rollups read every play and are not
  helped. `scrobbledb serve` suggests this when they are missing. Safe to
  repeat; it never changes any row.

  If DATABASE is not specified, uses the default location in the XDG data
  directory.

Options:
  --analytics  Create the foreign-key indexes used for lookups from a track,
               album or artist, instead of rebuilding the search index.
  --help       Show this message and exit.
```
<!-- [[[end]]] -->

## Examples

- Build the index for the default database:
  ```bash
  uv run scrobbledb index
  ```
- Rebuild indexing for a specific database file:
  ```bash
  uv run scrobbledb index ~/data/scrobbledb.db
  ```
