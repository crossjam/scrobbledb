# `scrobbledb browse`

Launch an interactive Textual TUI to explore your library without typing search queries. You can scroll, filter, and sort tracks with keyboard controls.

## Usage

<!-- [[[cog
from click.testing import CliRunner
from scrobbledb.cli import cli
runner = CliRunner()
result = runner.invoke(cli, ["browse", "--help"], prog_name='scrobbledb')
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: scrobbledb browse [OPTIONS] [DATABASE]

  Browse tracks in an interactive TUI.

  Opens an interactive terminal user interface for exploring your scrobble
  history. Features include:

  - View all tracks with play counts and last played dates
  - Filter by artist, album, or track name
  - Sort by various criteria (plays, date, name)
  - Navigate with keyboard shortcuts

  Keyboard shortcuts:
      /       Focus the filter input
      Escape  Clear the filter
      n       Next page
      p       Previous page
      r       Refresh data
      q       Quit

  If DATABASE is not specified, uses the default location in the XDG data
  directory.

Options:
  --help  Show this message and exit.
```
<!-- [[[end]]] -->

## Tips

- Ensure your database exists (`scrobbledb config init` and an ingest/import) before launching the TUI.
- Use the `--database` option to point the browser at a different SQLite file.
