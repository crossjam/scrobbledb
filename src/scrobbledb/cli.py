import click
import os
import json
import sqlite_utils
from pathlib import Path
from platformdirs import user_data_dir
from rich.console import Console
from rich.prompt import Prompt
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich.table import Table
from . import lastfm
import dateutil.parser

APP_NAME = "dev.pirateninja.scrobbledb"
console = Console()


def get_data_dir():
    """Get the XDG compliant data directory for the app."""
    return Path(user_data_dir(APP_NAME))


def get_default_auth_path():
    """Get the default path for the auth.json file in XDG compliant directory."""
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "auth.json")


def get_default_db_path():
    """Get the default path for the database in XDG compliant directory."""
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "scrobbledb.db")


@click.group()
@click.version_option()
def cli():
    "Save data from last.fm/libre.fm to a SQLite database"


@cli.command()
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Check initialization state without making changes",
)
def init(dry_run):
    """
    Initialize scrobbledb data directory and database.

    Creates the XDG compliant data directory and initializes
    a default SQLite database for storing scrobble data.

    Use --dry-run to check the current state without making any changes.
    """
    data_dir = get_data_dir()

    if dry_run:
        # In dry-run mode, construct paths without creating directories
        db_path = data_dir / "scrobbledb.db"
        auth_path = data_dir / "auth.json"
        # Dry-run mode: just report status without making changes
        console.print(Panel("[bold]Dry-run mode:[/bold] Checking initialization state...", border_style="blue"))
        console.print()

        actions_needed = []

        # Check directory
        if data_dir.exists():
            console.print(f"[green]✓[/green] Data directory exists: [cyan]{data_dir}[/cyan]")
        else:
            console.print(f"[yellow]○[/yellow] Data directory does not exist: [cyan]{data_dir}[/cyan]")
            actions_needed.append("Create data directory")

        # Check database
        if db_path.exists():
            console.print(f"[green]✓[/green] Database exists: [cyan]{db_path}[/cyan]")

            # Show database info
            db = sqlite_utils.Database(str(db_path))
            table = Table(title="Database Tables")
            table.add_column("Table", style="cyan")
            table.add_column("Rows", style="magenta", justify="right")

            for table_name in db.table_names():
                count = db[table_name].count
                table.add_row(table_name, str(count))

            if table.row_count > 0:
                console.print(table)
            else:
                console.print("[dim]  Database exists but has no tables yet[/dim]")
        else:
            console.print(f"[yellow]○[/yellow] Database does not exist: [cyan]{db_path}[/cyan]")
            actions_needed.append("Create database")

        # Check auth file
        if auth_path.exists():
            console.print(f"[green]✓[/green] Auth file exists: [cyan]{auth_path}[/cyan]")
        else:
            console.print(f"[yellow]○[/yellow] Auth file does not exist: [cyan]{auth_path}[/cyan]")
            console.print("[dim]  (Auth file will be created when you run 'scrobbledb auth')[/dim]")

        console.print()

        # Show what would happen
        if actions_needed:
            actions_list = "".join(f"  • {action}\n" for action in actions_needed)
            summary = f"""[bold yellow]Actions needed for initialization:[/bold yellow]

{actions_list}
Run [bold cyan]scrobbledb init[/bold cyan] (without --dry-run) to perform these actions.
"""
            console.print(Panel(summary, border_style="yellow"))
        else:
            summary = f"""[bold green]✓ Scrobbledb is already initialized![/bold green]

All required components are in place.

Next steps:
  • If you haven't configured credentials: [bold cyan]scrobbledb auth[/bold cyan]
  • To import listening history: [bold cyan]scrobbledb plays[/bold cyan]
"""
            console.print(Panel(summary, border_style="green"))

    else:
        # Normal mode: actually create things
        db_path = Path(get_default_db_path())
        auth_path = Path(get_default_auth_path())

        # Check if directory exists
        if data_dir.exists():
            console.print(f"[green]✓[/green] Data directory already exists: [cyan]{data_dir}[/cyan]")
        else:
            data_dir.mkdir(parents=True, exist_ok=True)
            console.print(f"[green]✓[/green] Created data directory: [cyan]{data_dir}[/cyan]")

        # Check if database exists
        if db_path.exists():
            console.print(f"[yellow]![/yellow] Database already exists: [cyan]{db_path}[/cyan]")

            # Show database info
            db = sqlite_utils.Database(str(db_path))

            table = Table(title="Database Tables")
            table.add_column("Table", style="cyan")
            table.add_column("Rows", style="magenta", justify="right")

            for table_name in db.table_names():
                count = db[table_name].count
                table.add_row(table_name, str(count))

            if table.row_count > 0:
                console.print(table)
            else:
                console.print("[dim]Database has no tables yet[/dim]")
        else:
            # Create new database
            db = sqlite_utils.Database(str(db_path))
            console.print(f"[green]✓[/green] Created database: [cyan]{db_path}[/cyan]")

        # Show summary in a panel
        summary = f"""[bold]Scrobbledb initialized successfully![/bold]

Data directory: [cyan]{data_dir}[/cyan]
Database: [cyan]{db_path}[/cyan]
Auth file: [cyan]{data_dir / 'auth.json'}[/cyan]

Next steps:
  1. Run [bold cyan]scrobbledb auth[/bold cyan] to configure your API credentials
  2. Run [bold cyan]scrobbledb plays[/bold cyan] to import your listening history
"""
        console.print(Panel(summary, border_style="green"))


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

    console.print(Panel(f"[bold]Configure {network.upper()} API Credentials[/bold]", border_style="blue"))

    if network == "lastfm":
        console.print(
            "Create an API account here: [link=https://www.last.fm/api/account/create]https://www.last.fm/api/account/create[/link]"
        )
    elif network == "librefm":
        console.print("Create an API account here: xxxfixme")

    console.print()
    username = Prompt.ask("[cyan]Your username[/cyan]")
    api_key = Prompt.ask("[cyan]API Key[/cyan]")
    shared_secret = Prompt.ask("[cyan]Shared Secret[/cyan]")
    password = Prompt.ask("[cyan]Your password[/cyan]", password=True)

    # Authenticate and get session key
    console.print("\n[cyan]Authenticating...[/cyan]")
    try:
        import pylast
        temp_network = lastfm.get_network(network, key=api_key, secret=shared_secret)
        password_hash = pylast.md5(password)
        sg = pylast.SessionKeyGenerator(temp_network)
        session_key = sg.get_session_key(username, password_hash)

        auth_data = json.load(open(auth)) if os.path.exists(auth) else {}
        auth_data.update(
            {
                "lastfm_network": network,
                "lastfm_username": username,
                "lastfm_api_key": api_key,
                "lastfm_shared_secret": shared_secret,
                "lastfm_session_key": session_key,
            }
        )
        json.dump(auth_data, open(auth, "w"))

        console.print(f"\n[green]✓[/green] Authentication successful!")
        console.print(f"[green]✓[/green] Credentials saved to: [cyan]{auth}[/cyan]")
    except Exception as e:
        console.print(f"\n[red]✗[/red] Authentication failed: {e}")
        console.print("[yellow]Please check your credentials and try again.[/yellow]")
        raise click.Abort()


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
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Maximum number of tracks to import",
)
def plays(database, auth, since, since_date, limit):
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

    auth_data = json.load(open(auth))

    # Check if session key exists in auth data
    session_key = auth_data.get("lastfm_session_key")
    if not session_key:
        console.print("[red]✗[/red] No session key found in authentication file.")
        console.print("[yellow]Please run 'scrobbledb auth' to re-authenticate.[/yellow]")
        raise click.Abort()

    network = lastfm.get_network(
        auth_data["lastfm_network"],
        key=auth_data["lastfm_api_key"],
        secret=auth_data["lastfm_shared_secret"],
        session_key=session_key,
    )

    user = network.get_user(auth_data["lastfm_username"])
    playcount = user.get_playcount()

    # Use limit if specified, otherwise use total playcount
    expected_count = min(limit, playcount) if limit else playcount

    history = lastfm.recent_tracks(user, since_date, limit=limit)

    if limit:
        console.print(f"[cyan]Importing up to {limit} plays from {auth_data['lastfm_username']}...[/cyan]")
    else:
        console.print(f"[cyan]Importing plays from {auth_data['lastfm_username']}...[/cyan]")

    # FIXME: the progress bar is wrong if there's a since_date
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Importing plays...", total=expected_count)
        for track in history:
            lastfm.save_artist(db, track["artist"])
            lastfm.save_album(db, track["album"])
            lastfm.save_track(db, track["track"])
            lastfm.save_play(db, track["play"])
            progress.advance(task)

    console.print(f"[green]✓[/green] Successfully imported plays to: [cyan]{database}[/cyan]")
