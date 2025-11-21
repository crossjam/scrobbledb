import click
import os
import json
import sqlite_utils
from pathlib import Path
from platformdirs import user_data_dir, user_config_dir
from importlib.metadata import version as get_version

from loguru_config import LoguruConfig
from rich.console import Console
from rich.prompt import Prompt
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    MofNCompleteColumn,
    TimeRemainingColumn,
)
from rich.panel import Panel
from rich.table import Table
from . import lastfm
from . import sql as sql_commands
from . import export as export_command
import dateutil.parser

APP_NAME = "dev.pirateninja.scrobbledb"
console = Console()


def version_callback(ctx, param, value):
    """Callback to handle version option."""
    if not value or ctx.resilient_parsing:
        return
    try:
        pkg_version = get_version("scrobbledb")
    except Exception:
        pkg_version = "unknown"
    click.echo(f"scrobbledb, version {pkg_version}")
    ctx.exit()


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


def get_default_log_config_path():
    """Get the default path for the log config file in XDG compliant directory."""
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "loguru_config.toml")


def ensure_default_log_config():
    """Ensure default log config exists, creating it if necessary.

    Returns:
        Path to the default log config file.
    """
    config_path = Path(get_default_log_config_path())

    if not config_path.exists():
        # Copy the default config from the package
        import importlib.resources

        try:
            # Python 3.9+
            default_config = (
                importlib.resources.files("scrobbledb")
                .joinpath("default_loguru_config.toml")
                .read_text()
            )
        except AttributeError:
            # Python 3.7-3.8 fallback
            import pkg_resources

            default_config = pkg_resources.resource_string(
                "scrobbledb", "default_loguru_config.toml"
            ).decode("utf-8")

        config_path.write_text(default_config)

    return str(config_path)


@click.group()
@click.option(
    "--log-config",
    type=click.Path(file_okay=True, dir_okay=False, exists=True),
    default=None,
    help="Path to loguru configuration file (JSON, YAML, or TOML)",
)
@click.option(
    "-V",
    "--version",
    is_flag=True,
    callback=version_callback,
    expose_value=False,
    is_eager=True,
    help="Show the version and exit.",
)
@click.pass_context
def cli(ctx, log_config):
    "Save data from last.fm/libre.fm to a SQLite database"
    # Store log_config in context for subcommands to use
    ctx.ensure_object(dict)
    ctx.obj["log_config"] = log_config


# Register sql subcommand group
cli.add_command(sql_commands.sql)

# Register export command
cli.add_command(export_command.export)


@click.group()
def config():
    """
    Configuration and database management commands.

    Manage scrobbledb initialization, database resets, and view configuration locations.
    """
    pass


# Register config subcommand group
cli.add_command(config)


@config.command()
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Check initialization state without making changes",
)
@click.option(
    "--no-index",
    is_flag=True,
    default=False,
    help="Skip FTS5 search index initialization",
)
def init(dry_run, no_index):
    """
    Initialize scrobbledb data directory and database.

    Creates the XDG compliant data directory and initializes
    a default SQLite database for storing scrobble data, including
    the FTS5 full-text search index.

    Use --dry-run to check the current state without making any changes.
    Use --no-index to skip FTS5 initialization (for minimal setup).
    """
    data_dir = get_data_dir()

    if dry_run:
        # In dry-run mode, construct paths without creating directories
        db_path = data_dir / "scrobbledb.db"
        auth_path = data_dir / "auth.json"
        # Dry-run mode: just report status without making changes
        console.print(
            Panel(
                "[bold]Dry-run mode:[/bold] Checking initialization state...",
                border_style="blue",
            )
        )
        console.print()

        actions_needed = []

        # Check directory
        if data_dir.exists():
            console.print(
                f"[green]✓[/green] Data directory exists: [cyan]{data_dir}[/cyan]"
            )
        else:
            console.print(
                f"[yellow]○[/yellow] Data directory does not exist: [cyan]{data_dir}[/cyan]"
            )
            actions_needed.append("Create data directory")

        # Check database
        if db_path.exists():
            console.print(f"[green]✓[/green] Database exists: [cyan]{db_path}[/cyan]")

            # Show database info
            db = sqlite_utils.Database(str(db_path))
            table = Table(title="Database Tables")
            table.add_column("Table", style="cyan")
            table.add_column("Rows", style="magenta", justify="right")
            table.add_column("Type", style="blue")

            for table_name in db.table_names():
                count = db[table_name].count
                # Check if it's a virtual table
                is_virtual = db.execute(
                    "SELECT sql FROM sqlite_master WHERE name=? AND type='table'",
                    [table_name],
                ).fetchone()
                table_type = (
                    "FTS5"
                    if is_virtual
                    and is_virtual[0]
                    and "fts5" in str(is_virtual[0]).lower()
                    else "Normal"
                )
                table.add_row(table_name, str(count), table_type)

            if table.row_count > 0:
                console.print(table)

                # Check if FTS5 exists
                if "tracks_fts" in db.table_names():
                    console.print("[green]✓[/green] FTS5 search index is initialized")
                else:
                    console.print(
                        "[yellow]○[/yellow] FTS5 search index is not initialized"
                    )
                    if not no_index:
                        actions_needed.append("Initialize FTS5 search index")
            else:
                console.print("[dim]  Database exists but has no tables yet[/dim]")
                if not no_index:
                    actions_needed.append("Initialize FTS5 search index")
        else:
            console.print(
                f"[yellow]○[/yellow] Database does not exist: [cyan]{db_path}[/cyan]"
            )
            actions_needed.append("Create database")
            if not no_index:
                actions_needed.append("Initialize FTS5 search index")

        # Check auth file
        if auth_path.exists():
            console.print(
                f"[green]✓[/green] Auth file exists: [cyan]{auth_path}[/cyan]"
            )
        else:
            console.print(
                f"[yellow]○[/yellow] Auth file does not exist: [cyan]{auth_path}[/cyan]"
            )
            console.print(
                "[dim]  (Auth file will be created when you run 'scrobbledb auth')[/dim]"
            )

        console.print()

        # Show what would happen
        if actions_needed:
            actions_list = "".join(f"  • {action}\n" for action in actions_needed)
            summary = f"""[bold yellow]Actions needed for initialization:[/bold yellow]

{actions_list}
Run [bold cyan]scrobbledb config init[/bold cyan] (without --dry-run) to perform these actions.
"""
            console.print(Panel(summary, border_style="yellow"))
        else:
            summary = """[bold green]✓ Scrobbledb is already initialized![/bold green]

All required components are in place.

Next steps:
  • If you haven't configured credentials: [bold cyan]scrobbledb auth[/bold cyan]
  • To import listening history: [bold cyan]scrobbledb ingest[/bold cyan]
  • To search your music: [bold cyan]scrobbledb search <query>[/bold cyan]
"""
            console.print(Panel(summary, border_style="green"))

    else:
        # Normal mode: actually create things
        db_path = Path(get_default_db_path())
        auth_path = Path(get_default_auth_path())

        # Check if directory exists
        if data_dir.exists():
            console.print(
                f"[green]✓[/green] Data directory already exists: [cyan]{data_dir}[/cyan]"
            )
        else:
            data_dir.mkdir(parents=True, exist_ok=True)
            console.print(
                f"[green]✓[/green] Created data directory: [cyan]{data_dir}[/cyan]"
            )

        # Check if database exists
        db_existed = db_path.exists()
        db = sqlite_utils.Database(str(db_path))

        if db_existed:
            console.print(
                f"[yellow]![/yellow] Database already exists: [cyan]{db_path}[/cyan]"
            )

            # Show database info
            table = Table(title="Database Tables")
            table.add_column("Table", style="cyan")
            table.add_column("Rows", style="magenta", justify="right")
            table.add_column("Type", style="blue")

            for table_name in db.table_names():
                count = db[table_name].count
                is_virtual = db.execute(
                    "SELECT sql FROM sqlite_master WHERE name=? AND type='table'",
                    [table_name],
                ).fetchone()
                table_type = (
                    "FTS5"
                    if is_virtual
                    and is_virtual[0]
                    and "fts5" in str(is_virtual[0]).lower()
                    else "Normal"
                )
                table.add_row(table_name, str(count), table_type)

            if table.row_count > 0:
                console.print(table)
            else:
                console.print("[dim]Database has no tables yet[/dim]")
        else:
            # Create new database
            console.print(f"[green]✓[/green] Created database: [cyan]{db_path}[/cyan]")

        # Initialize FTS5 if requested (default)
        if not no_index:
            if "tracks_fts" not in db.table_names():
                console.print("[cyan]Initializing FTS5 search index...[/cyan]")
                lastfm.setup_fts5(db)
                console.print("[green]✓[/green] FTS5 search index initialized")
            else:
                console.print("[green]✓[/green] FTS5 search index already exists")

        # Show summary in a panel
        fts5_status = (
            "initialized and ready"
            if not no_index
            else "skipped (use 'scrobbledb index' to set up later)"
        )

        summary = f"""[bold]Scrobbledb initialized successfully![/bold]

Data directory: [cyan]{data_dir}[/cyan]
Database: [cyan]{db_path}[/cyan]
Auth file: [cyan]{data_dir / 'auth.json'}[/cyan]
Search index: [cyan]{fts5_status}[/cyan]

Next steps:
  1. Run [bold cyan]scrobbledb auth[/bold cyan] to configure your API credentials
  2. Run [bold cyan]scrobbledb ingest[/bold cyan] to import your listening history
  3. Run [bold cyan]scrobbledb search <query>[/bold cyan] to search your music
"""
        console.print(Panel(summary, border_style="green"))


@config.command()
@click.argument(
    "database",
    required=False,
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
)
@click.option(
    "--no-index",
    is_flag=True,
    default=False,
    help="Skip FTS5 search index initialization",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    default=False,
    help="Skip confirmation prompt",
)
def reset(database, no_index, force):
    """
    Reset the scrobbledb database.

    This command will DELETE all data in the database and reinitialize it.
    This is a DESTRUCTIVE operation that cannot be undone.

    If DATABASE is not specified, uses the default location in the XDG data directory.

    Use --force to skip the confirmation prompt (dangerous!).
    Use --no-index to skip FTS5 initialization after reset.
    """
    if database is None:
        database = get_default_db_path()

    db_path = Path(database)

    # Check if database exists
    if not db_path.exists():
        console.print(
            f"[yellow]![/yellow] Database does not exist: [cyan]{db_path}[/cyan]"
        )
        console.print(
            "[dim]Nothing to reset. Use 'scrobbledb config init' to create a new database.[/dim]"
        )
        return

    # Get database info before deletion
    db = sqlite_utils.Database(str(db_path))
    table_names = list(db.table_names())
    total_rows = sum(
        db[table].count for table in table_names if table != "sqlite_sequence"
    )

    # Show what will be deleted
    console.print()
    console.print(
        Panel(
            f"[bold red]⚠️  WARNING: DESTRUCTIVE OPERATION[/bold red]\n\n"
            f"This will DELETE the database at:\n"
            f"[cyan]{db_path}[/cyan]\n\n"
            f"Current database contains:\n"
            f"  • {len(table_names)} table(s)\n"
            f"  • {total_rows} total row(s)\n\n"
            f"[bold]This action CANNOT be undone![/bold]",
            border_style="red",
            title="[bold red]⚠️  RESET DATABASE ⚠️[/bold red]",
        )
    )
    console.print()

    # Prompt for confirmation unless --force is used
    if not force:
        confirmation = Prompt.ask(
            "[bold yellow]Type 'yes' to confirm deletion[/bold yellow]", default="no"
        )

        if confirmation.lower() != "yes":
            console.print("[green]✓[/green] Reset cancelled. Database preserved.")
            return

    # Delete the database
    try:
        db_path.unlink()
        console.print(f"[green]✓[/green] Deleted database: [cyan]{db_path}[/cyan]")
    except Exception as e:
        console.print(f"[red]✗[/red] Failed to delete database: {e}")
        raise click.Abort()

    # Reinitialize the database
    console.print("[cyan]Creating new database...[/cyan]")
    db = sqlite_utils.Database(str(db_path))
    console.print(f"[green]✓[/green] Created new database: [cyan]{db_path}[/cyan]")

    # Initialize FTS5 if requested (default)
    if not no_index:
        console.print("[cyan]Initializing FTS5 search index...[/cyan]")
        lastfm.setup_fts5(db)
        console.print("[green]✓[/green] FTS5 search index initialized")
    else:
        console.print(
            "[yellow]○[/yellow] FTS5 search index skipped (use 'scrobbledb index' to set up later)"
        )

    # Show success summary
    fts5_status = "initialized and ready" if not no_index else "not initialized"

    summary = f"""[bold]Database reset complete![/bold]

Database: [cyan]{db_path}[/cyan]
Search index: [cyan]{fts5_status}[/cyan]

The database is now empty and ready to use.

Next steps:
  • Run [bold cyan]scrobbledb ingest[/bold cyan] to import your listening history
  • Run [bold cyan]scrobbledb import[/bold cyan] to manually import scrobbles
"""
    console.print(Panel(summary, border_style="green"))


@config.command()
def location():
    """
    Display scrobbledb configuration and data directory locations.

    Shows the OS-specific directories used by scrobbledb for configuration
    and data storage, based on XDG Base Directory specifications.
    """
    # Get directories
    data_dir = get_data_dir()
    config_dir_path = Path(user_config_dir(APP_NAME))

    # Create table
    table = Table(
        title="Scrobbledb Directory Locations",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Type", style="cyan", width=12)
    table.add_column("Path", style="white")
    table.add_column("Status", style="magenta", width=12)

    # Add data directory
    data_status = "✓ Exists" if data_dir.exists() else "Not created"
    table.add_row("Data", str(data_dir), data_status)

    # Add config directory
    config_status = "✓ Exists" if config_dir_path.exists() else "Not created"
    table.add_row("Config", str(config_dir_path), config_status)

    console.print()
    console.print(table)
    console.print()

    # Show what's in each directory if they exist
    if data_dir.exists():
        console.print(
            Panel(
                f"[bold]Data Directory Contents:[/bold]\n\n"
                f"Database: [cyan]{data_dir / 'scrobbledb.db'}[/cyan] "
                f"({'✓ Exists' if (data_dir / 'scrobbledb.db').exists() else 'Not created'})\n"
                f"Auth file: [cyan]{data_dir / 'auth.json'}[/cyan] "
                f"({'✓ Exists' if (data_dir / 'auth.json').exists() else 'Not created'})",
                border_style="blue",
                title="📁 Data Directory",
            )
        )
        console.print()

    # Show initialization hint if data directory doesn't exist
    if not data_dir.exists():
        console.print(
            "[dim]Run [cyan]scrobbledb config init[/cyan] to initialize the data directory.[/dim]"
        )
        console.print()


@cli.command()
def version():
    """
    Display the scrobbledb version.

    Shows the currently installed version of scrobbledb.
    """
    try:
        pkg_version = get_version("scrobbledb")
    except Exception:
        pkg_version = "unknown"
    click.echo(f"scrobbledb, version {pkg_version}")


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

    console.print(
        Panel(
            f"[bold]Configure {network.upper()} API Credentials[/bold]",
            border_style="blue",
        )
    )

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

        console.print("\n[green]✓[/green] Authentication successful!")
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
    "--newest",
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
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Enable verbose logging output",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Disable actual execution of ingest and db mods",
)
@click.pass_context
def ingest(ctx, database, auth, newest, since_date, limit, verbose, dry_run):
    """
    Ingest play history from last.fm/libre.fm to a SQLite database.

    This command fetches your listening history and saves it to DATABASE,
    including artist, album, track, and play data with timestamps.
    If DATABASE is not specified, uses the default location in the XDG data directory.
    """
    # Configure logging if verbose mode is enabled
    if verbose:
        log_config = ctx.obj.get("log_config") if ctx.obj else None
        if log_config:
            # Use user-specified config file
            LoguruConfig.load(log_config)
        else:
            # Use default config file from user data directory
            default_config = ensure_default_log_config()
            LoguruConfig.load(default_config)

    if newest and since_date:
        raise click.UsageError("use either --newest or --since-date, not both")

    if database is None:
        database = get_default_db_path()

    if auth is None:
        auth = get_default_auth_path()

    db = sqlite_utils.Database(database)

    if newest and db["plays"].exists:
        since_date = db.conn.execute("select max(timestamp) from plays").fetchone()[0]
    if since_date:
        since_date = dateutil.parser.parse(since_date)

    auth_data = json.load(open(auth))

    # Check if session key exists in auth data
    session_key = auth_data.get("lastfm_session_key")
    if not session_key:
        console.print("[red]✗[/red] No session key found in authentication file.")
        console.print(
            "[yellow]Please run 'scrobbledb auth' to re-authenticate.[/yellow]"
        )
        raise click.Abort()

    network = lastfm.get_network(
        auth_data["lastfm_network"],
        key=auth_data["lastfm_api_key"],
        secret=auth_data["lastfm_shared_secret"],
        session_key=session_key,
    )

    user = network.get_user(auth_data["lastfm_username"])
    # playcount = user.get_playcount()

    playcount = lastfm.recent_tracks_count(user, since_date)

    # Use limit if specified, otherwise use total playcount

    expected_count = min(limit, playcount) if limit else playcount

    if dry_run:
        console.print("[green]dry run indicated, ingest complete[/green]")
        return

    history = lastfm.recent_tracks(user, since_date, limit=limit)

    # Set up FTS5 index if it doesn't exist
    if "tracks_fts" not in db.table_names():
        console.print("[cyan]Setting up search index for the first time...[/cyan]")
        lastfm.setup_fts5(db)

    if limit:
        console.print(
            f"[cyan]Ingesting up to {limit} tracks from {auth_data['lastfm_username']}...[/cyan]"
        )
    else:
        console.print(
            f"[cyan]Ingesting tracks from {auth_data['lastfm_username']}...[/cyan]"
        )

    # Enhanced progress display with percentage and counts
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Ingesting tracks", total=expected_count)
        for track in history:
            lastfm.save_artist(db, track["artist"])
            lastfm.save_album(db, track["album"])
            lastfm.save_track(db, track["track"])
            lastfm.save_play(db, track["play"])
            progress.advance(task)

    console.print(
        f"[green]✓[/green] Successfully ingested tracks to: [cyan]{database}[/cyan]"
    )
    console.print(
        "[dim]Search index is automatically maintained and ready to use.[/dim]"
    )


@cli.command()
@click.argument(
    "database",
    required=False,
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
)
def index(database):
    """
    Set up and rebuild FTS5 full-text search index.

    Creates the FTS5 virtual table with triggers and rebuilds the search index
    from existing data. This enables fast full-text search across artists,
    albums, and tracks.

    If DATABASE is not specified, uses the default location in the XDG data directory.
    """
    if database is None:
        database = get_default_db_path()

    if not Path(database).exists():
        console.print(f"[red]✗[/red] Database not found: [cyan]{database}[/cyan]")
        console.print(
            "[yellow]Run 'scrobbledb config init' to create a new database.[/yellow]"
        )
        raise click.Abort()

    db = sqlite_utils.Database(database)

    # Check if we have data to index
    if not db["tracks"].exists:
        console.print("[yellow]![/yellow] No tracks found in database.")
        console.print(
            "[dim]Run 'scrobbledb ingest' to import your listening history first.[/dim]"
        )
        raise click.Abort()

    console.print("[cyan]Setting up FTS5 search index...[/cyan]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(
            "[cyan]Creating FTS5 virtual table and triggers...", total=None
        )
        lastfm.setup_fts5(db)
        progress.update(
            task, description="[cyan]Rebuilding search index from existing data..."
        )
        lastfm.rebuild_fts5(db)
        progress.update(task, description="[green]✓ FTS5 index ready!")

    # Show index statistics
    fts_count = db.execute("SELECT COUNT(*) FROM tracks_fts").fetchone()[0]

    console.print(f"[green]✓[/green] Indexed {fts_count} tracks from database")
    console.print(f"[cyan]Database:[/cyan] {database}")
    console.print(
        "\n[dim]You can now use 'scrobbledb search <query>' to search your music![/dim]"
    )


@cli.command()
@click.argument("query", required=True)
@click.argument(
    "database",
    required=False,
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
)
@click.option(
    "-l",
    "--limit",
    type=int,
    default=20,
    help="Maximum number of results to return",
    show_default=True,
)
@click.option(
    "-f",
    "--fields",
    default="artist,album,track,plays",
    help="Comma-separated list of fields to display (artist, album, track, plays, last_played)",
    show_default=True,
)
def search(query, database, limit, fields):
    """
    Search for tracks using full-text search.

    Searches across artist names, album titles, and track titles using
    SQLite's FTS5 full-text search engine.

    Examples:
        scrobbledb search "rolling stones"
        scrobbledb search "love" --limit 10
        scrobbledb search "beatles" --fields artist,track,plays,last_played

    If DATABASE is not specified, uses the default location in the XDG data directory.

    Note: You must run 'scrobbledb index' first to set up the search index.
    """
    if database is None:
        database = get_default_db_path()

    if not Path(database).exists():
        console.print(f"[red]✗[/red] Database not found: [cyan]{database}[/cyan]")
        console.print(
            "[yellow]Run 'scrobbledb config init' to create a new database.[/yellow]"
        )
        raise click.Abort()

    db = sqlite_utils.Database(database)

    # Check if FTS5 index exists
    if "tracks_fts" not in db.table_names():
        console.print("[red]✗[/red] Search index not found.")
        console.print(
            "[yellow]Run 'scrobbledb index' to set up the search index first.[/yellow]"
        )
        raise click.Abort()

    # Parse fields option
    field_list = [f.strip().lower() for f in fields.split(",")]
    valid_fields = {"artist", "album", "track", "plays", "last_played"}
    invalid_fields = set(field_list) - valid_fields

    if invalid_fields:
        console.print(f"[red]✗[/red] Invalid fields: {', '.join(invalid_fields)}")
        console.print(
            f"[yellow]Valid fields are: {', '.join(sorted(valid_fields))}[/yellow]"
        )
        raise click.Abort()

    # Perform search
    console.print(f"[cyan]Searching for:[/cyan] {query}\n")

    try:
        results = lastfm.search_tracks(db, query, limit=limit)
    except Exception as e:
        console.print(f"[red]✗[/red] Search failed: {e}")
        console.print(
            "[yellow]Make sure the FTS5 index is up to date by running 'scrobbledb index'.[/yellow]"
        )
        raise click.Abort()

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        console.print(
            "\n[dim]Try a different search query or check your database has data.[/dim]"
        )
        return

    # Create results table
    table = Table(title=f"Search Results ({len(results)} found)")

    # Add columns based on field selection
    if "artist" in field_list:
        table.add_column("Artist", style="cyan")
    if "album" in field_list:
        table.add_column("Album", style="magenta")
    if "track" in field_list:
        table.add_column("Track", style="green")
    if "plays" in field_list:
        table.add_column("Plays", justify="right", style="yellow")
    if "last_played" in field_list:
        table.add_column("Last Played", style="blue")

    # Add rows
    for result in results:
        row = []
        if "artist" in field_list:
            row.append(result["artist_name"])
        if "album" in field_list:
            row.append(result["album_title"])
        if "track" in field_list:
            row.append(result["track_title"])
        if "plays" in field_list:
            row.append(str(result["play_count"]))
        if "last_played" in field_list:
            last_played = result["last_played"]
            if last_played:
                # Parse and format the datetime
                if isinstance(last_played, str):
                    last_played = dateutil.parser.parse(last_played)
                    row.append(last_played.strftime("%Y-%m-%d %H:%M"))
                else:
                    row.append(str(last_played))
            else:
                row.append("-")

        table.add_row(*row)

    console.print(table)
    console.print(f"\n[dim]Showing {len(results)} of {len(results)} results[/dim]")


@cli.command(name="import")
@click.argument(
    "database",
    required=False,
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
)
@click.option(
    "-f",
    "--file",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, allow_dash=True),
    default=None,
    help="Read from file (use '-' for stdin)",
)
@click.option(
    "--format",
    type=click.Choice(["jsonl", "csv", "tsv", "auto"], case_sensitive=False),
    default="auto",
    help="Input format",
    show_default=True,
)
@click.option(
    "--skip-errors",
    is_flag=True,
    default=False,
    help="Continue on errors instead of aborting",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Validate input without saving to database",
)
@click.option(
    "--no-duplicates",
    is_flag=True,
    default=False,
    help="Skip scrobbles with duplicate timestamp+track",
)
@click.option(
    "--update-index/--no-update-index",
    default=None,
    help="Update FTS5 search index after importing",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Import at most N records",
)
@click.option(
    "--sample",
    type=float,
    default=None,
    help="Sample probability 0.0-1.0",
)
@click.option(
    "--seed",
    type=int,
    default=None,
    help="Random seed for reproducible sampling (use with --sample)",
)
def import_data(
    database,
    file,
    format,
    skip_errors,
    dry_run,
    no_duplicates,
    update_index,
    limit,
    sample,
    seed,
):
    """
    Import scrobbles to the database from a file or stdin.

    Supports JSONL (JSON Lines) and CSV/TSV formats with automatic detection.
    Each scrobble requires: artist, track, and timestamp.
    Album is optional (defaults to "(unknown album)").

    \b
    Examples:
        # Import from file
        scrobbledb import --file scrobbles.jsonl

        # Import from stdin
        cat scrobbles.jsonl | scrobbledb import

        # Limit to first 100 records
        scrobbledb import --file data.jsonl --limit 100

        # Sample 10% of records
        scrobbledb import --file data.jsonl --sample 0.1

        # Validate without importing
        scrobbledb import --file data.csv --dry-run
    """
    import sys

    # Validate --sample
    if sample is not None:
        if not 0.0 <= sample <= 1.0:
            raise click.BadParameter(
                "must be between 0.0 and 1.0", param_hint="--sample"
            )

        # Warn for edge cases
        if sample == 0.0:
            console.print(
                "[yellow]Warning:[/yellow] --sample=0.0 means NO records will be imported.\n"
                "This will process the input but import nothing to the database.\n"
                "Did you mean to use a higher probability?\n"
            )
        elif sample == 1.0:
            console.print(
                "[yellow]Warning:[/yellow] --sample=1.0 means ALL records will be imported.\n"
                "This is equivalent to not using --sample at all.\n"
                "Consider removing --sample for better performance.\n"
            )

    # Validate --seed (only valid with --sample)
    if seed is not None and sample is None:
        raise click.BadParameter(
            "--seed can only be used with --sample", param_hint="--seed"
        )

    # Validate --limit
    if limit is not None and limit < 1:
        raise click.BadParameter("must be at least 1", param_hint="--limit")

    # Determine input source
    if file == "-":
        input_file = sys.stdin
    elif file:
        input_file = open(file, "r", encoding="utf-8")
    elif not sys.stdin.isatty():
        # Data is being piped
        input_file = sys.stdin
    else:
        raise click.UsageError(
            "No input provided. Use --file to specify a file, or pipe data to stdin.\n"
            "Example: cat scrobbles.jsonl | scrobbledb import"
        )

    # Get database path
    if database is None:
        database = get_default_db_path()

    # Open database (in dry-run mode, we still need to check for duplicates)
    db = sqlite_utils.Database(database)

    try:
        # Read first line to detect format
        first_line = input_file.readline()
        if not first_line:
            console.print("[yellow]No data to process (empty input)[/yellow]")
            return

        # Auto-detect format
        if format == "auto":
            format = lastfm.detect_format(first_line)
            console.print(f"[dim]Auto-detected format: {format}[/dim]")

        # Parse scrobbles based on format
        def parse_input():
            """Generator that yields parsed scrobbles."""
            line_num = 1

            if format == "jsonl":
                # Process first line
                try:
                    yield lastfm.parse_scrobble_jsonl(first_line, line_num)
                except ValueError as e:
                    if not skip_errors:
                        raise click.ClickException(str(e))
                    console.print(f"[yellow]Error:[/yellow] {e}")

                # Process remaining lines
                for line_num, line in enumerate(input_file, start=2):
                    line = line.strip()
                    if not line:
                        continue  # Skip empty lines

                    try:
                        yield lastfm.parse_scrobble_jsonl(line, line_num)
                    except ValueError as e:
                        if not skip_errors:
                            raise click.ClickException(str(e))
                        console.print(f"[yellow]Error:[/yellow] {e}")

            else:  # CSV or TSV
                import csv
                import io

                # Combine first line with rest of file
                full_content = first_line + input_file.read()
                delimiter = "\t" if format == "tsv" else ","

                reader = csv.DictReader(io.StringIO(full_content), delimiter=delimiter)

                for line_num, row in enumerate(
                    reader, start=2
                ):  # Line 2 because of header
                    try:
                        yield lastfm.parse_scrobble_dict(row, line_num)
                    except ValueError as e:
                        if not skip_errors:
                            raise click.ClickException(str(e))
                        console.print(f"[yellow]Error:[/yellow] {e}")

        # Show processing message
        mode_parts = []
        if dry_run:
            mode_parts.append("dry-run")
        if sample is not None:
            mode_parts.append(f"sampling: {sample*100:.1f}%")
        if limit is not None:
            mode_parts.append(f"limit: {limit}")

        mode_str = f" ({', '.join(mode_parts)})" if mode_parts else ""
        console.print(
            f"[cyan]{'Validating' if dry_run else 'Adding'} scrobbles{mode_str}...[/cyan]\n"
        )

        # Process scrobbles
        if not dry_run:
            stats = lastfm.add_scrobbles(
                db,
                parse_input(),
                skip_errors=skip_errors,
                limit=limit,
                sample=sample,
                seed=seed,
                no_duplicates=no_duplicates,
            )
        else:
            # Dry run: just parse and count
            stats = {
                "total_processed": 0,
                "sampled": 0,
                "added": 0,
                "skipped": 0,
                "errors": [],
                "limit_reached": False,
            }

            for scrobble in parse_input():
                stats["total_processed"] += 1

                # Apply sampling logic (but don't actually import)
                if sample is not None:
                    import random

                    if seed is not None:
                        random.seed(seed + stats["total_processed"])  # Vary seed
                    if random.random() >= sample:
                        continue
                    stats["sampled"] += 1

                # Check limit
                if limit is not None and stats["added"] >= limit:
                    stats["limit_reached"] = True
                    break

                stats["added"] += 1

        # Display results
        console.print()

        if dry_run:
            console.print("[green]✓[/green] Validation complete (dry-run mode)\n")
        elif stats["added"] > 0:
            console.print(
                "[green]✓[/green] Successfully added scrobbles to database!\n"
            )
        else:
            console.print("[yellow]![/yellow] No scrobbles were added\n")

        # Show statistics
        table = Table(title="Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Count", style="magenta", justify="right")

        table.add_row("Total processed", str(stats["total_processed"]))

        if sample is not None:
            actual_rate = (
                (stats["sampled"] / stats["total_processed"] * 100)
                if stats["total_processed"] > 0
                else 0
            )
            table.add_row(
                f"Sampled ({sample*100:.1f}%)",
                f"{stats['sampled']} ({actual_rate:.1f}%)",
            )

        if dry_run:
            table.add_row("Would import", str(stats["added"]))
        else:
            table.add_row("Successfully imported", str(stats["added"]))

        if stats["skipped"] > 0:
            table.add_row("Skipped (duplicates)", str(stats["skipped"]))

        if stats["errors"]:
            table.add_row("Errors", str(len(stats["errors"])))

        console.print(table)

        # Show limit reached message
        if stats["limit_reached"]:
            console.print(
                f"\n[yellow]Note:[/yellow] Processing stopped after reaching --limit of {limit} records.\n"
                "      Input may contain more records."
            )

        # Show errors if any
        if stats["errors"]:
            console.print("\n[red]Errors:[/red]")
            for i, error in enumerate(stats["errors"][:10], 1):  # Show first 10
                console.print(f"  {i}. {error}")
            if len(stats["errors"]) > 10:
                console.print(f"  ... and {len(stats['errors']) - 10} more errors")

        # Show database info
        if not dry_run:
            console.print(f"\n[dim]Database:[/dim] [cyan]{database}[/cyan]")

            # Update FTS5 index if requested or auto
            should_update_index = update_index
            if should_update_index is None:
                # Auto: update if index exists
                should_update_index = "tracks_fts" in db.table_names()

            if should_update_index and stats["added"] > 0:
                console.print("[cyan]Updating search index...[/cyan]")
                if "tracks_fts" not in db.table_names():
                    lastfm.setup_fts5(db)
                lastfm.rebuild_fts5(db)
                console.print("[green]✓[/green] Search index updated")

    finally:
        # Close file if we opened it
        if file and file != "-":
            input_file.close()
