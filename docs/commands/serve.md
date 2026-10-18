# `scrobbledb serve`

Browse and query your scrobbles in a web browser. `serve` starts a read-only [Datasette](https://datasette.io) server over your scrobbledb database, with stored queries for the analytics the CLI already provides and an MCP endpoint so AI assistants can ask about your listening history. It runs in the foreground until you press Ctrl+C. The default database path is the XDG data directory.

## Installation

The web server is an optional extra, so the core CLI stays light:

```bash
uv sync --extra serve
# or
pip install 'scrobbledb[serve]'
```

Without the extra, `scrobbledb serve --help` still works, and running the command names the extra to install.

## Usage

<!-- [[[cog
from click.testing import CliRunner
from scrobbledb.cli import cli
runner = CliRunner()
result = runner.invoke(cli, ["serve", "--help"], prog_name='scrobbledb')
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: scrobbledb serve [OPTIONS]

  Browse and query your scrobbles in a web browser.

  Starts a read-only Datasette web server over the database, with scrobbledb's
  stored queries and an MCP endpoint for AI assistants. The server runs in the
  foreground until interrupted with Ctrl+C.

  If --database is not specified, uses the default location in the XDG data
  directory.

Options:
  -d, --database FILE   Database path (default: XDG data directory)
  --host TEXT           Interface to listen on. Anything other than localhost
                        exposes your history.  [default: 127.0.0.1]
  --port INTEGER RANGE  Port to listen on.  [default: 8001; 0<=x<=65535]
  --help                Show this message and exit.
```
<!-- [[[end]]] -->

## Examples

- Serve the default database on `http://127.0.0.1:8001/`:
  ```bash
  uv run scrobbledb serve
  ```
- Serve a specific database file on another port:
  ```bash
  uv run scrobbledb serve --database ~/data/scrobbledb.db --port 8080
  ```

The server prints where it is listening, and where the MCP endpoint is when it is available:

```text
Serving scrobbledb at http://127.0.0.1:8001/
MCP endpoint at http://127.0.0.1:8001/-/mcp
Press Ctrl+C to stop.
```

## What it serves

- **Read-only access.** The database is opened read-only and the server refuses writes, including through the SQL box and the MCP `execute_sql` tool. The file is never changed. You can run it while `scrobbledb ingest` is writing in another terminal. The database uses SQLite's default rollback journal, so a query that lands in the instant an ingest commits can fail; running it again works.
- **One database.** Only your scrobbledb database is served; there is no extra in-memory database.
- **Stored queries.** The database page lists queries that mirror the analytics commands: collection overview, play feed, plays by day, month and year, top artists, albums and tracks, artist, album and track lists and details, listening clock, weekday rollup, streaks, artist discovery dates and full-text search. Time-bounded queries take the same `since` and `until` values as the CLI, including natural language such as `last month`.
- **Table descriptions and search.** Tables and columns carry descriptions, and full-text search over tracks is wired up as the `search` stored query.

### Customizations only apply to `scrobbledb serve`

The scrobbledb plugin is registered inside `scrobbledb serve` only. It is deliberately not installed as a Datasette plugin entry point, so it never loads into other Datasette processes in the same environment. Running Datasette directly on the file serves the plain tables with none of the stored queries, SQL functions or descriptions:

```bash
datasette scrobbledb.db   # no scrobbledb customizations
```

## Startup warnings

`serve` checks the database before starting and prints a warning with the command that fixes it. It never applies the fix itself.

- **No plays yet.** Run `scrobbledb ingest` to import your listening history.
- **Missing analytics indexes.** Lookups by track, album or artist may be slow. Run `scrobbledb index --analytics`.
- **Incomplete search index.** Search results will be incomplete. Run `scrobbledb index` to rebuild it.

When you serve a database with `--database`, each suggested command names that file too.

## Security

The server has no authentication. By default it listens only on `127.0.0.1`, so only your machine can reach it. Binding another interface with `--host` exposes your whole listening history to anyone who can reach that address.

## MCP endpoint

When the `serve` extra is installed, the server also exposes an [MCP](https://modelcontextprotocol.io) endpoint over Streamable HTTP at:

```text
http://127.0.0.1:8001/-/mcp
```

Use the host and port you passed to `serve`. The endpoint is provided by [datasette-mcp](https://github.com/datasette/datasette-mcp) and extended with tools that speak scrobbledb's data model.

### Tools

| Tool | Purpose |
| --- | --- |
| `collection_overview` | Totals and the first and last play |
| `top_artists`, `top_albums`, `top_tracks` | Rankings, optionally within a time range or for one artist |
| `recent_plays` | Play history, filterable by artist, album, track and time |
| `listening_rollup` | Plays by day, month or year |
| `artist_details`, `album_details`, `track_details` | Details for one artist, album or track |
| `search_music` | Full-text search across the library |
| `list_databases`, `get_database_schema`, `execute_sql` | Read-only built-ins from datasette-mcp |

### Connecting a client

Start the server, then point your MCP client at the URL above. For Claude Code:

```bash
claude mcp add --transport http scrobbledb http://127.0.0.1:8001/-/mcp
```

For a client configured with a JSON file, add a server entry of the same shape:

```json
{
  "mcpServers": {
    "scrobbledb": {
      "type": "http",
      "url": "http://127.0.0.1:8001/-/mcp"
    }
  }
}
```

Once connected, the client lists the tools above. Try asking for your top artists last month or what you listened to most recently.
