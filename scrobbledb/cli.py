import click
import os
import json
import sqlite_utils
from pathlib import Path
from platformdirs import user_data_dir
from . import lastfm
import dateutil.parser

APP_NAME = "dev.pirateninja.scrobbledb"


def get_default_auth_path():
    """Get the default path for the auth.json file in XDG compliant directory."""
    data_dir = Path(user_data_dir(APP_NAME))
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "auth.json")


def get_default_db_path():
    """Get the default path for the database in XDG compliant directory."""
    data_dir = Path(user_data_dir(APP_NAME))
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "scrobbledb.db")


@click.group()
@click.version_option()
def cli():
    "Save data from last.fm/libre.fm to a SQLite database"


@cli.command()
@click.option(
    "-a",
    "--auth",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    default=None,
    help="Path to save token to (default: XDG data directory)",
)
@click.option(
    "-n",
    "--network",
    type=click.Choice(["lastfm", "librefm"]),
    help="which scrobble network to use. this is saved to the auth file.",
    default="lastfm",
    show_default=True,
)
def auth(auth, network):
    "Save authentication credentials to a JSON file"

    if auth is None:
        auth = get_default_auth_path()

    if network == "lastfm":
        click.echo(
            f"Create an API account here: https://www.last.fm/api/account/create"
        )
    elif network == "librefm":
        click.echo(f"Create an API account here: xxxfixme")
    click.echo()
    username = click.prompt("Your username")
    api_key = click.prompt("API Key")
    shared_secret = click.prompt("Shared Secret")

    # TODO: we could test that this works by calling Network.get_user()

    auth_data = json.load(open(auth)) if os.path.exists(auth) else {}
    auth_data.update(
        {
            "lastfm_network": network,
            "lastfm_username": username,
            "lastfm_api_key": api_key,
            "lastfm_shared_secret": shared_secret,
        }
    )
    json.dump(auth_data, open(auth, "w"))


@cli.command()
@click.argument(
    "database",
    required=False,
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
)
@click.option(
    "-a",
    "--auth",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False, exists=True),
    default=None,
    help="Path to read auth token from (default: XDG data directory)",
)
@click.option(
    "--since",
    is_flag=True,
    default=False,
    help="Pull new posts since last saved post in DB",
)
@click.option("--since-date", metavar="DATE", help="Pull new posts since DATE")
def plays(database, auth, since, since_date):
    """
    Import play history from last.fm/libre.fm to a SQLite database.

    This command fetches your listening history and saves it to DATABASE,
    including artist, album, track, and play data with timestamps.
    If DATABASE is not specified, uses the default location in the XDG data directory.
    """
    if since and since_date:
        raise click.UsageError("use either --since or --since-date, not both")

    if database is None:
        database = get_default_db_path()

    if auth is None:
        auth = get_default_auth_path()

    db = sqlite_utils.Database(database)

    if since and db["plays"].exists:
        since_date = db.conn.execute("select max(timestamp) from plays").fetchone()[0]
    if since_date:
        since_date = dateutil.parser.parse(since_date)

    auth = json.load(open(auth))
    network = lastfm.get_network(
        auth["lastfm_network"],
        key=auth["lastfm_api_key"],
        secret=auth["lastfm_shared_secret"],
    )

    user = network.get_user(auth["lastfm_username"])
    playcount = user.get_playcount()
    history = lastfm.recent_tracks(user, since_date)

    # FIXME: the progress bar is wrong if there's a since_date
    with click.progressbar(
        history, length=playcount, label="Importing plays", show_pos=True
    ) as progress:
        for track in progress:
            lastfm.save_artist(db, track["artist"])
            lastfm.save_album(db, track["album"])
            lastfm.save_track(db, track["track"])
            lastfm.save_play(db, track["play"])
