"""
Plays command group for scrobbledb.

Commands for viewing play history with filtering and pagination.
"""

import click
import sqlite_utils
from pathlib import Path
from rich.console import Console

from ..config_utils import get_default_db_path
from .. import domain_queries
from .. import domain_format

console = Console()


@click.group()
def plays():
    """
    Play history commands.

    View and filter your listening history chronologically.
    """
    pass


@plays.command(name="list")
@click.option(
    "-d",
    "--database",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    default=None,
    help="Database path (default: XDG data directory)",
)
@click.option(
    "-l",
    "--limit",
    type=int,
    default=20,
    help="Maximum number of plays to return",
    show_default=True,
)
@click.option(
    "-s",
    "--since",
    type=str,
    default=None,
    help='Show plays since date/time (ISO 8601 format or relative like "7 days ago")',
)
@click.option(
    "-u",
    "--until",
    type=str,
    default=None,
    help="Show plays until date/time (ISO 8601 format)",
)
@click.option(
    "--artist",
    type=str,
    default=None,
    help="Filter by artist name (case-insensitive partial match)",
)
@click.option(
    "--album",
    type=str,
    default=None,
    help="Filter by album title (case-insensitive partial match)",
)
@click.option(
    "--track",
    type=str,
    default=None,
    help="Filter by track title (case-insensitive partial match)",
)
@click.option(
    "--format",
    type=click.Choice(["table", "csv", "json", "jsonl"], case_sensitive=False),
    default="table",
    help="Output format",
    show_default=True,
)
def list_plays(database, limit, since, until, artist, album, track, format):
    """
    List recent plays with filtering and pagination.

    View listening history chronologically with flexible filtering.

    \b
    Examples:
        # List last 20 plays
        scrobbledb plays list

        # List last 50 plays
        scrobbledb plays list --limit 50

        # List plays in the last week
        scrobbledb plays list --since "7 days ago"

        # List plays for a specific artist
        scrobbledb plays list --artist "Pink Floyd" --limit 100

        # List plays in a specific date range
        scrobbledb plays list --since 2024-01-01 --until 2024-12-31

        # Export to CSV
        scrobbledb plays list --format csv > my_plays.csv
    """
    # Get database path
    if database is None:
        database = get_default_db_path()

    if not Path(database).exists():
        console.print(f"[red]✗[/red] Database not found: [cyan]{database}[/cyan]")
        console.print(
            "[yellow]Run 'scrobbledb config init' to create a new database.[/yellow]"
        )
        raise click.Abort()

    db = sqlite_utils.Database(database)

    # Check if we have any plays
    if "plays" not in db.table_names() or db["plays"].count == 0:
        console.print("[yellow]![/yellow] No plays found in database.")
        console.print(
            "[dim]Run 'scrobbledb ingest' to import your listening history first.[/dim]"
        )
        raise click.Abort()

    # Parse date filters
    since_dt = None
    until_dt = None

    if since:
        since_dt = domain_queries.parse_relative_time(since)
        if not since_dt:
            console.print(
                f"[red]✗[/red] Invalid date format: {since}. Use ISO 8601 (YYYY-MM-DD) or relative time (7 days ago)"
            )
            raise click.Abort()

    if until:
        until_dt = domain_queries.parse_relative_time(until)
        if not until_dt:
            console.print(
                f"[red]✗[/red] Invalid date format: {until}. Use ISO 8601 (YYYY-MM-DD) or relative time expressions"
            )
            raise click.Abort()

    # Validate limit
    if limit < 1:
        console.print("[red]✗[/red] Limit must be at least 1")
        raise click.Abort()

    # Query plays
    try:
        plays = domain_queries.get_plays_with_filters(
            db,
            limit=limit,
            since=since_dt,
            until=until_dt,
            artist=artist,
            album=album,
            track=track,
        )
    except Exception as e:
        console.print(f"[red]✗[/red] Query failed: {e}")
        raise click.Abort()

    # Output results
    if format == "table":
        domain_format.format_plays_list(plays, console)
    else:
        output = domain_format.format_output(plays, format)
        click.echo(output)
