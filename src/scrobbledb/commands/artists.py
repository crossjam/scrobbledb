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

console = Console(stderr=True)


@click.group()
def artists():
    """
    Artist investigation commands.

    Browse artists, view top artists, and see detailed statistics.
    """
    pass


@artists.command(name="search")
@click.argument("query", required=True)
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
    help="Maximum results",
    show_default=True,
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
    help="Fields to include in output (comma-separated or repeated). Available: id, artist, albums, tracks, plays, last_played",
)
@click.option(
    "--select",
    is_flag=True,
    help="Interactive mode: select a single result and output its details as JSON",
)
@click.pass_context
def search_artists(ctx, query, database, limit, format, fields, select):
    """
    Search for artists using fuzzy matching.

    Find artists by partial name, useful when you don't remember exact spelling.
    Uses FTS5 full-text search and rapidfuzz for intelligent matching.

    \b
    Examples:
        # Search for artists with "radio" in name
        scrobbledb artists search "radio"

        # Find artists similar to "beetles"
        scrobbledb artists search "beetles"

        # Get top 10 results
        scrobbledb artists search "rock" --limit 10
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

    # Check if we have any artists
    if "artists" not in db.table_names():
        console.print("[yellow]![/yellow] No artists found in database.")
        console.print(
            "[yellow]→[/yellow] Run [cyan]scrobbledb ingest[/cyan] to import your listening history."
        )
        ctx.exit(1)

    # Validate limit
    if limit < 1:
        console.print("[red]✗[/red] Limit must be at least 1")
        ctx.exit(1)

    # Search artists
    try:
        artists = domain_queries.get_artists_by_search(db, query=query, limit=limit)
    except Exception as e:
        console.print(f"[red]✗[/red] Search failed: {e}")
        ctx.exit(1)

    if not artists:
        console.print(f"[yellow]![/yellow] No artists found matching [yellow]\"{query}\"[/yellow]")
        console.print("[yellow]→[/yellow] Try a different search term or browse: [cyan]scrobbledb artists list[/cyan]")
        ctx.exit(0)

    # Parse fields
    selected_fields = None
    if fields:
        selected_fields = []
        for field_arg in fields:
            selected_fields.extend(f.strip() for f in field_arg.split(","))

    # Interactive selection mode
    if select:
        if len(artists) == 1:
            # Only one result, auto-select it
            selected = artists[0]
        else:
            # Display numbered results
            console.print(f"\n[bold]Found {len(artists)} artists matching [cyan]\"{query}\"[/cyan]:[/bold]\n")
            for i, artist in enumerate(artists, 1):
                console.print(f"  [dim]{i}.[/dim] [cyan]{artist['artist_name']}[/cyan] - {artist['play_count']:,} plays")

            # Prompt for selection
            from rich.prompt import Prompt
            try:
                choice = Prompt.ask(
                    f"\n[bold]Select an artist[/bold] [dim](1-{len(artists)}, or 'q' to quit)[/dim]",
                    default="1"
                )
                if choice.lower() == 'q':
                    ctx.exit(0)

                choice_num = int(choice)
                if choice_num < 1 or choice_num > len(artists):
                    console.print(f"[red]✗[/red] Invalid selection: {choice_num}")
                    ctx.exit(1)

                selected = artists[choice_num - 1]
            except (ValueError, KeyboardInterrupt):
                console.print("\n[yellow]Selection cancelled[/yellow]")
                ctx.exit(0)

        # Filter selected record if fields specified
        if selected_fields:
            field_mapping = {
                "id": "artist_id",
                "artist": "artist_name",
                "albums": "album_count",
                "tracks": "track_count",
                "plays": "play_count",
                "last_played": "last_played",
            }
            data_keys = [field_mapping.get(f, f) for f in selected_fields if field_mapping.get(f)]
            selected = {k: selected.get(k) for k in data_keys if k in selected}

        # Output selected record as JSON
        import json
        output = json.dumps(selected, indent=2, default=str)
        click.echo(output)
        return

    # Filter data if fields specified and not table format
    if selected_fields and format != "table":
        field_mapping = {
            "id": "artist_id",
            "artist": "artist_name",
            "albums": "album_count",
            "tracks": "track_count",
            "plays": "play_count",
            "last_played": "last_played",
        }
        data_keys = [field_mapping.get(f, f) for f in selected_fields if field_mapping.get(f)]
        artists = domain_format.filter_fields(artists, data_keys)

    # Output results
    if format == "table":
        domain_format.format_artists_search(artists, console, fields=selected_fields)
    else:
        output = domain_format.format_output(artists, format)
        click.echo(output)


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
@click.option(
    "--fields",
    type=str,
    multiple=True,
    help="Fields to include in output (comma-separated or repeated). Available: id, artist, plays, tracks, albums, last_played",
)
@click.pass_context
def list_artists(ctx, database, limit, sort, order, min_plays, format, fields):
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
            "[yellow]→[/yellow] Run [cyan]scrobbledb config init[/cyan] to create a new database."
        )
        ctx.exit(1)

    db = sqlite_utils.Database(database)

    # Check if we have any artists
    if "artists" not in db.table_names():
        console.print("[yellow]![/yellow] No artists found in database.")
        console.print(
            "[yellow]→[/yellow] Run [cyan]scrobbledb ingest[/cyan] to import your listening history."
        )
        ctx.exit(1)

    # Validate limit
    if limit < 1:
        console.print("[red]✗[/red] Limit must be at least 1")
        ctx.exit(1)

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
        ctx.exit(1)

    # Parse fields
    selected_fields = None
    if fields:
        selected_fields = []
        for field_arg in fields:
            selected_fields.extend(f.strip() for f in field_arg.split(","))

    # Filter data if fields specified and not table format
    if selected_fields and format != "table":
        field_mapping = {
            "id": "artist_id",
            "artist": "artist_name",
            "plays": "play_count",
            "tracks": "track_count",
            "albums": "album_count",
            "last_played": "last_played",
        }
        data_keys = [field_mapping.get(f, f) for f in selected_fields if field_mapping.get(f)]
        artists = domain_format.filter_fields(artists, data_keys)

    # Output results
    if format == "table":
        domain_format.format_artists_list(artists, console, fields=selected_fields)
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
@click.option(
    "--fields",
    type=str,
    multiple=True,
    help="Fields to include in output (comma-separated or repeated). Available: rank, artist, plays, percentage, avg_per_day",
)
@click.pass_context
def top_artists(ctx, database, limit, since, until, period, format, fields):
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

    # Validate limit
    if limit < 1:
        console.print("[red]✗[/red] Limit must be at least 1")
        ctx.exit(1)

    # Parse date filters
    since_dt = None
    until_dt = None

    if period:
        if since or until:
            console.print(
                "[yellow]![/yellow] Cannot use --period with --since or --until"
            )
            ctx.exit(1)
        since_dt, until_dt = domain_queries.parse_period_to_dates(period)
    else:
        if since:
            since_dt = domain_queries.parse_relative_time(since)
            if not since_dt:
                console.print(
                    f"[red]✗[/red] Invalid date format: {since}. Use ISO 8601 (YYYY-MM-DD) or relative time (7 days ago)"
                )
                ctx.exit(1)

        if until:
            until_dt = domain_queries.parse_relative_time(until)
            if not until_dt:
                console.print(
                    f"[red]✗[/red] Invalid date format: {until}. Use ISO 8601 (YYYY-MM-DD) or relative time expressions"
                )
                ctx.exit(1)

    # Query top artists
    try:
        artists = domain_queries.get_top_artists(
            db, limit=limit, since=since_dt, until=until_dt
        )
    except Exception as e:
        console.print(f"[red]✗[/red] Query failed: {e}")
        ctx.exit(1)

    # Parse fields
    selected_fields = None
    if fields:
        selected_fields = []
        for field_arg in fields:
            selected_fields.extend(f.strip() for f in field_arg.split(","))

    # Filter data if fields specified and not table format
    if selected_fields and format != "table":
        field_mapping = {
            "rank": "rank",
            "artist": "artist_name",
            "plays": "play_count",
            "percentage": "percentage",
            "avg_per_day": "avg_plays_per_day",
        }
        data_keys = [field_mapping.get(f, f) for f in selected_fields if field_mapping.get(f)]
        artists = domain_format.filter_fields(artists, data_keys)

    # Output results
    if format == "table":
        since_str = since or (period if period else None)
        until_str = until or None
        domain_format.format_top_artists(artists, console, since=since_str, until=until_str, fields=selected_fields)
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
    type=str,
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
@click.pass_context
def show_artist(ctx, artist_name, database, artist_id, format):
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
        console.print("[yellow]→[/yellow] Try: [cyan]scrobbledb artists show \"Artist Name\"[/cyan]")
        ctx.exit(1)

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

    # Check if we have any artists
    if "artists" not in db.table_names():
        console.print("[yellow]![/yellow] No artists found in database.")
        console.print(
            "[yellow]→[/yellow] Run [cyan]scrobbledb ingest[/cyan] to import your listening history."
        )
        ctx.exit(1)

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
            ctx.exit(1)
        else:
            console.print(f"[red]✗[/red] Error: {e}")
            ctx.exit(1)

    if not artist:
        if artist_id:
            console.print(f"[yellow]![/yellow] No artist found with ID [cyan]{artist_id}[/cyan]")
        else:
            console.print(f"[yellow]![/yellow] No artist found matching [yellow]\"{artist_name}\"[/yellow]")
        console.print("[yellow]→[/yellow] Try searching: [cyan]scrobbledb artists list[/cyan]")
        ctx.exit(1)

    # Get top tracks and albums for this artist
    assert artist is not None  # Type narrowing for type checker
    try:
        top_tracks = domain_queries.get_artist_top_tracks(db, artist["artist_id"], limit=10)
        albums = domain_queries.get_artist_albums(db, artist["artist_id"])
    except Exception as e:
        console.print(f"[red]✗[/red] Failed to get artist data: {e}")
        ctx.exit(1)

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
