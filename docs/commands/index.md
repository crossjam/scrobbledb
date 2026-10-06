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

  With --analytics, creates the secondary indexes that analytical queries
  (rollups, top lists, `scrobbledb serve`) rely on, and leaves the search index
  alone. Safe to repeat; it never changes any row.

  If DATABASE is not specified, uses the default location in the XDG data
  directory.

Options:
  --analytics  Create the secondary indexes that speed up analytical queries,
               instead of rebuilding the search index.
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
