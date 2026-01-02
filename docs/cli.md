# scrobbledb CLI overview

This guide orients you to the `scrobbledb` command-line interface and links to dedicated pages for each command group. Use these pages for option-by-option references and examples generated directly from the CLI help text.

- Install dependencies with [uv](https://github.com/astral-sh/uv):
  ```bash
  uv sync
  uv run scrobbledb --help
  ```
- Data is stored under the XDG data directory using the app name `dev.pirateninja.scrobbledb` (for example `~/.local/share/dev.pirateninja.scrobbledb`). The default database is `scrobbledb.db` and default credentials file is `auth.json` in that directory.
- The CLI supports a global `--log-config` option for custom Loguru settings and `-V/--version` for version output.

## Command index

| Command | Purpose | Reference |
| --- | --- | --- |
| `albums` | Search albums and view album details | [Albums](commands/albums.md) |
| `artists` | Browse artists, view top artists, and artist details | [Artists](commands/artists.md) |
| `auth` | Save Last.fm/Libre.fm credentials | [Auth](commands/auth.md) |
| `browse` | Launch the Textual TUI to browse tracks | [Browse](commands/browse.md) |
| `config` | Initialize or reset the database and show paths | [Config](commands/config.md) |
| `export` | Export data via presets or custom SQL | [Export](commands/export.md) |
| `import` | Import plays from files or stdin | [Import](commands/import.md) |
| `index` | Create or rebuild the FTS5 search index | [Index](commands/index.md) |
| `ingest` | Fetch recent plays from Last.fm/Libre.fm | [Ingest](commands/ingest.md) |
| `plays` | View play history with filtering | [Plays](commands/plays.md) |
| `search` | Full-text search across the library | [Search](commands/search.md) |
| `sql` | sqlite-utils passthrough commands | [SQL](commands/sql.md) |
| `stats` | Overview, monthly, and yearly listening stats | [Stats](commands/stats.md) |
| `tracks` | Search tracks, view top tracks, and track details | [Tracks](commands/tracks.md) |
| `version` | Print the installed package version | [Version](commands/version.md) |

## Regenerating help snippets

The command pages embed `--help` output using [cog](https://cog.readthedocs.io/en/latest/). After changing CLI options run:

```bash
PYTHONPATH=src uv run cog -r docs/commands/*.md
```

You can also use the poe task configured in `pyproject.toml`:

```bash
poe docs:cli
```

This keeps the documented usage in sync with the current CLI.
