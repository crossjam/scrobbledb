# `scrobbledb auth`

Store credentials for Last.fm or Libre.fm. The command prompts for your username, API key, shared secret, and password, then saves them alongside the retrieved session key in `auth.json` (defaulting to the XDG data directory unless you override `--auth`).

## Usage

<!-- [[[cog
from click.testing import CliRunner
from scrobbledb.cli import cli
runner = CliRunner()
result = runner.invoke(cli, ["auth", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli auth [OPTIONS]

  Save authentication credentials to a JSON file

Options:
  -a, --auth FILE                 Path to save token to (default: XDG data
                                  directory)
  -n, --network [lastfm|librefm]  which scrobble network to use. this is saved
                                  to the auth file.  [default: lastfm]
  --help                          Show this message and exit.
```
<!-- [[[end]]] -->

## Examples

- Save credentials to the default location for Last.fm (default network):
  ```bash
  uv run scrobbledb auth
  ```
- Save Libre.fm credentials to a custom path:
  ```bash
  uv run scrobbledb auth --network librefm --auth ~/tmp/auth.json
  ```
