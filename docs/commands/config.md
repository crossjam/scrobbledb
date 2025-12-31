# `scrobbledb config`

Initialize and manage the scrobbledb database, including optional FTS5 search setup. Defaults place files in the XDG data directory under `dev.pirateninja.scrobbledb`.

## Group usage

<!-- [[[cog
from click.testing import CliRunner
from scrobbledb.cli import cli
runner = CliRunner()
result = runner.invoke(cli, ["config", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli config [OPTIONS] COMMAND [ARGS]...

  Configuration and database management commands.

  Manage scrobbledb initialization, database resets, and view configuration
  locations.

Options:
  --help  Show this message and exit.

Commands:
  init      Initialize scrobbledb data directory and database.
  location  Display scrobbledb configuration and data directory locations.
  reset     Reset the scrobbledb database.
```
<!-- [[[end]]] -->

## Subcommands

### `init`
Create the data directory, initialize the database, and set up the FTS5 index unless `--no-index` is used. Use `--dry-run` to see what would be created without modifying disk.

<!-- [[[cog
result = runner.invoke(cli, ["config", "init", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli config init [OPTIONS]

  Initialize scrobbledb data directory and database.

  Creates the XDG compliant data directory and initializes a default SQLite
  database for storing scrobble data, including the FTS5 full-text search index.

  Use --dry-run to check the current state without making any changes. Use --no-
  index to skip FTS5 initialization (for minimal setup).

Options:
  --dry-run   Check initialization state without making changes
  --no-index  Skip FTS5 search index initialization
  --help      Show this message and exit.
```
<!-- [[[end]]] -->

### `reset`
Drop and recreate the database, optionally skipping FTS5 with `--no-index`. Prompts for confirmation unless `--force`/`-f` is provided.

<!-- [[[cog
result = runner.invoke(cli, ["config", "reset", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli config reset [OPTIONS] [DATABASE]

  Reset the scrobbledb database.

  This command will DELETE all data in the database and reinitialize it. This is
  a DESTRUCTIVE operation that cannot be undone.

  If DATABASE is not specified, uses the default location in the XDG data
  directory.

  Use --force to skip the confirmation prompt (dangerous!). Use --no-index to
  skip FTS5 initialization after reset.

Options:
  --no-index   Skip FTS5 search index initialization
  -f, --force  Skip confirmation prompt
  --help       Show this message and exit.
```
<!-- [[[end]]] -->

### `location`
Show the resolved data and config directories plus expected file paths.

<!-- [[[cog
result = runner.invoke(cli, ["config", "location", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli config location [OPTIONS]

  Display scrobbledb configuration and data directory locations.

  Shows the OS-specific directories used by scrobbledb for configuration and
  data storage, based on XDG Base Directory specifications.

Options:
  --help  Show this message and exit.
```
<!-- [[[end]]] -->
