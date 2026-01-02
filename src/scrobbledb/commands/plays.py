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
@click.option(
    "--fields",
    type=str,
    multiple=True,
    help="Fields to include in output (comma-separated or repeated). Available: timestamp, artist, track, album",
)
@click.pass_context
def list_plays(ctx, database, limit, since, until, artist, album, track, format, fields):
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
            "[yellow]→[/yellow] Run [cyan]scrobbledb config init[/cyan] to create a new database."
        )
        ctx.exit(1)

    db = sqlite_utils.Database(database)

    # Check if we have any plays
    if "plays" not in db.table_names() or db["plays"].count == 0:
        console.print("[yellow]![/yellow] No plays found in database.")
        console.print(
            "[yellow]→[/yellow] Run [cyan]scrobbledb ingest[/cyan] to import your listening history."
        )
        ctx.exit(1)

    # Parse date filters
    since_dt = None
    until_dt = None

    if since:
        since_dt = domain_queries.parse_relative_time(since)
        if not since_dt:
            console.print(
                f"[red]✗[/red] Invalid date format: [yellow]{since}[/yellow]"
            )
            console.print(
                "[yellow]→[/yellow] Use ISO 8601 format (YYYY-MM-DD) or relative time like '7 days ago'"
            )
            ctx.exit(1)

    if until:
        until_dt = domain_queries.parse_relative_time(until)
        if not until_dt:
            console.print(
                f"[red]✗[/red] Invalid date format: [yellow]{until}[/yellow]"
            )
            console.print(
                "[yellow]→[/yellow] Use ISO 8601 format (YYYY-MM-DD) or relative time expressions"
            )
            ctx.exit(1)

    # Validate limit
    if limit < 1:
        console.print("[red]✗[/red] Limit must be at least 1")
        ctx.exit(1)

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
        ctx.exit(1)

    # Parse fields (support both comma-separated and repeated --fields options)
    selected_fields = None
    if fields:
        selected_fields = []
        for field_arg in fields:
            selected_fields.extend(f.strip() for f in field_arg.split(","))

    # Filter data if fields specified and not table format
    if selected_fields and format != "table":
        # Map user-friendly field names to actual dict keys
        field_mapping = {
            "timestamp": "timestamp",
            "artist": "artist_name",
            "track": "track_title",
            "album": "album_title",
        }
        data_keys = [field_mapping.get(f, f) for f in selected_fields if field_mapping.get(f)]
        plays = domain_format.filter_fields(plays, data_keys)

    # Output results
    if format == "table":
        domain_format.format_plays_list(plays, console, fields=selected_fields)
    else:
        output = domain_format.format_output(plays, format)
        click.echo(output)
