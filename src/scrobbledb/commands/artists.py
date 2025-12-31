"""
Artists command group for scrobbledb.

Commands for listing artists, viewing top artists, and artist details.
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
def artists():
    """
    Artist investigation commands.

    Browse artists, view top artists, and see detailed statistics.
    """
    pass


@artists.command(name="list")
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
    default=50,
    help="Maximum results",
    show_default=True,
)
@click.option(
    "--sort",
    type=click.Choice(["plays", "name", "recent"], case_sensitive=False),
    default="plays",
    help="Sort by: plays, name, or recent",
    show_default=True,
)
@click.option(
    "--order",
    type=click.Choice(["desc", "asc"], case_sensitive=False),
    default="desc",
    help="Sort order",
    show_default=True,
)
@click.option(
    "--min-plays",
    type=int,
    default=0,
    help="Show only artists with at least N plays",
    show_default=True,
)
@click.option(
    "--format",
    type=click.Choice(["table", "csv", "json", "jsonl"], case_sensitive=False),
    default="table",
    help="Output format",
    show_default=True,
)
def list_artists(database, limit, sort, order, min_plays, format):
    """
    List all artists in the database with play statistics.

    Browse all artists you've listened to with sorting options.

    \b
    Examples:
        # List top 50 artists by play count
        scrobbledb artists list

        # List all artists alphabetically
        scrobbledb artists list --sort name --order asc --limit 1000

        # List artists with at least 100 plays
        scrobbledb artists list --min-plays 100

        # Show recently played artists
        scrobbledb artists list --sort recent
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

    # Check if we have any artists
    if "artists" not in db.table_names():
        console.print("[yellow]![/yellow] No artists found in database.")
        console.print(
            "[dim]Run 'scrobbledb ingest' to import your listening history first.[/dim]"
        )
        raise click.Abort()

    # Validate limit
    if limit < 1:
        console.print("[red]✗[/red] Limit must be at least 1")
        raise click.Abort()

    # Query artists
    try:
        artists = domain_queries.get_artists_with_stats(
            db,
            limit=limit,
            sort_by=sort,
            order=order,
            min_plays=min_plays,
        )
    except Exception as e:
        console.print(f"[red]✗[/red] Query failed: {e}")
        raise click.Abort()

    # Output results
    if format == "table":
        domain_format.format_artists_list(artists, console)
    else:
        output = domain_format.format_output(artists, format)
        click.echo(output)


@artists.command(name="top")
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
    default=10,
    help="Number of artists to show",
    show_default=True,
)
@click.option(
    "-s",
    "--since",
    type=str,
    default=None,
    help="Start date/time for analysis period",
)
@click.option(
    "-u",
    "--until",
    type=str,
    default=None,
    help="End date/time for analysis period",
)
@click.option(
    "--period",
    type=click.Choice(["week", "month", "quarter", "year", "all-time"], case_sensitive=False),
    default=None,
    help="Predefined period",
)
@click.option(
    "--format",
    type=click.Choice(["table", "csv", "json", "jsonl"], case_sensitive=False),
    default="table",
    help="Output format",
    show_default=True,
)
def top_artists(database, limit, since, until, period, format):
    """
    Show top artists with flexible time range support.

    Analyze your listening patterns over different time periods.

    \b
    Examples:
        # Top 10 artists all-time
        scrobbledb artists top

        # Top 20 artists this year
        scrobbledb artists top --limit 20 --period year

        # Top artists in last 30 days
        scrobbledb artists top --since "30 days ago"

        # Top artists in specific date range
        scrobbledb artists top --since 2024-01-01 --until 2024-03-31
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

    # Validate limit
    if limit < 1:
        console.print("[red]✗[/red] Limit must be at least 1")
        raise click.Abort()

    # Parse date filters
    since_dt = None
    until_dt = None

    if period:
        if since or until:
            console.print(
                "[yellow]![/yellow] Cannot use --period with --since or --until"
            )
            raise click.Abort()
        since_dt, until_dt = domain_queries.parse_period_to_dates(period)
    else:
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

    # Query top artists
    try:
        artists = domain_queries.get_top_artists(
            db, limit=limit, since=since_dt, until=until_dt
        )
    except Exception as e:
        console.print(f"[red]✗[/red] Query failed: {e}")
        raise click.Abort()

    # Output results
    if format == "table":
        since_str = since or (period if period else None)
        until_str = until or None
        domain_format.format_top_artists(artists, console, since=since_str, until=until_str)
    else:
        output = domain_format.format_output(artists, format)
        click.echo(output)


@artists.command(name="show")
@click.argument("artist_name", required=False)
@click.option(
    "-d",
    "--database",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    default=None,
    help="Database path (default: XDG data directory)",
)
@click.option(
    "--artist-id",
    type=int,
    default=None,
    help="Use artist ID instead of name",
)
@click.option(
    "--format",
    type=click.Choice(["table", "json", "jsonl"], case_sensitive=False),
    default="table",
    help="Output format",
    show_default=True,
)
def show_artist(artist_name, database, artist_id, format):
    """
    Display detailed information about a specific artist.

    Deep dive into a single artist's listening history.

    \b
    Examples:
        # Show artist details
        scrobbledb artists show "Radiohead"

        # Use artist ID
        scrobbledb artists show --artist-id 123
    """
    # Validate arguments
    if not artist_id and not artist_name:
        console.print("[red]✗[/red] Either ARTIST_NAME or --artist-id is required")
        raise click.Abort()

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

    # Check if we have any artists
    if "artists" not in db.table_names():
        console.print("[yellow]![/yellow] No artists found in database.")
        console.print(
            "[dim]Run 'scrobbledb ingest' to import your listening history first.[/dim]"
        )
        raise click.Abort()

    # Get artist details
    try:
        artist = domain_queries.get_artist_details(
            db, artist_id=artist_id, artist_name=artist_name
        )
    except ValueError as e:
        if "Multiple artists match" in str(e):
            console.print(f"[yellow]![/yellow] {e}")
            console.print(
                "\n[dim]Use --artist-id for exact selection, or be more specific with the name.[/dim]"
            )
            raise click.Abort()
        else:
            console.print(f"[red]✗[/red] Error: {e}")
            raise click.Abort()

    if not artist:
        if artist_id:
            console.print(f"[yellow]![/yellow] No artist found with ID: {artist_id}")
        else:
            console.print(
                f"[yellow]![/yellow] No artist found matching: {artist_name}"
            )
        raise click.Abort()

    # Get top tracks and albums for this artist
    try:
        top_tracks = domain_queries.get_artist_top_tracks(db, artist["artist_id"], limit=10)
        albums = domain_queries.get_artist_albums(db, artist["artist_id"])
    except Exception as e:
        console.print(f"[red]✗[/red] Failed to get artist data: {e}")
        raise click.Abort()

    # Output results
    if format == "table":
        domain_format.format_artist_details(artist, top_tracks, albums, console)
    else:
        # For JSON output, combine artist, tracks, and albums
        output_data = {**artist, "top_tracks": top_tracks, "albums": albums}
        if format == "json":
            import json

            click.echo(json.dumps(output_data, indent=2, default=str))
        else:  # jsonl
            import json

            click.echo(json.dumps(output_data, default=str))
