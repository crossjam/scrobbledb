"""
Tracks command group for scrobbledb.

Commands for searching tracks, viewing top tracks, and track details.
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
def tracks():
    """
    Track investigation commands.

    Search for tracks, view top tracks, and see detailed statistics.
    """
    pass


@tracks.command(name="search")
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
    "--artist",
    type=str,
    default=None,
    help="Filter by artist name",
)
@click.option(
    "--album",
    type=str,
    default=None,
    help="Filter by album title",
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
    help="Fields to include in output (comma-separated or repeated). Available: id, track, artist, album, plays, last_played",
)
@click.option(
    "--select",
    is_flag=True,
    help="Interactive mode: select a single result and output its details as JSON",
)
@click.pass_context
def search_tracks(ctx, query, database, limit, artist, album, format, fields, select):
    """
    Search for tracks using fuzzy matching.

    Find tracks by partial title, useful for quick lookups.

    \b
    Examples:
        # Search for tracks with "love" in title
        scrobbledb tracks search "love"

        # Search within specific artist
        scrobbledb tracks search "love" --artist "The Beatles"

        # Search within specific album
        scrobbledb tracks search "love" --album "Sgt. Pepper"
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

    # Check if we have any tracks
    if "tracks" not in db.table_names():
        console.print("[yellow]![/yellow] No tracks found in database.")
        console.print(
            "[yellow]→[/yellow] Run [cyan]scrobbledb ingest[/cyan] to import your listening history."
        )
        ctx.exit(1)

    # Validate limit
    if limit < 1:
        console.print("[red]✗[/red] Limit must be at least 1")
        ctx.exit(1)

    # Search tracks
    try:
        tracks = domain_queries.get_tracks_by_search(
            db, query=query, artist=artist, album=album, limit=limit
        )
    except Exception as e:
        console.print(f"[red]✗[/red] Search failed: {e}")
        ctx.exit(1)

    if not tracks:
        console.print(f"[yellow]![/yellow] No tracks found matching [yellow]\"{query}\"[/yellow]")
        ctx.exit(0)

    # Interactive selection mode
    if select:
        if len(tracks) == 1:
            # Only one result, auto-select it
            selected = tracks[0]
        else:
            # Display numbered results
            console.print(f"\n[bold]Found {len(tracks)} tracks matching [cyan]\"{query}\"[/cyan]:[/bold]\n")
            for i, track in enumerate(tracks, 1):
                console.print(f"  [dim]{i}.[/dim] [green]{track['track_title']}[/green] by [cyan]{track['artist_name']}[/cyan] - {track['play_count']:,} plays")

            # Prompt for selection
            from rich.prompt import Prompt
            try:
                choice = Prompt.ask(
                    f"\n[bold]Select a track[/bold] [dim](1-{len(tracks)}, or 'q' to quit)[/dim]",
                    default="1"
                )
                if choice.lower() == 'q':
                    ctx.exit(0)

                choice_num = int(choice)
                if choice_num < 1 or choice_num > len(tracks):
                    console.print(f"[red]✗[/red] Invalid selection: {choice_num}")
                    ctx.exit(1)

                selected = tracks[choice_num - 1]
            except (ValueError, KeyboardInterrupt):
                console.print("\n[yellow]Selection cancelled[/yellow]")
                ctx.exit(0)

        # Output selected record as JSON
        import json
        output = json.dumps(selected, indent=2, default=str)
        click.echo(output)
        return

    # Parse fields
    selected_fields = None
    if fields:
        selected_fields = []
        for field_arg in fields:
            selected_fields.extend(f.strip() for f in field_arg.split(","))

    # Filter data if fields specified and not table format
    if selected_fields and format != "table":
        field_mapping = {
            "id": "track_id",
            "track": "track_title",
            "artist": "artist_name",
            "album": "album_title",
            "plays": "play_count",
            "last_played": "last_played",
        }
        data_keys = [field_mapping.get(f, f) for f in selected_fields if field_mapping.get(f)]
        tracks = domain_format.filter_fields(tracks, data_keys)

    # Output results
    if format == "table":
        domain_format.format_tracks_search(tracks, console, fields=selected_fields)
    else:
        output = domain_format.format_output(tracks, format)
        click.echo(output)


@tracks.command(name="top")
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
    help="Number of tracks to show",
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
    "--artist",
    type=str,
    default=None,
    help="Filter by artist name",
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
    help="Fields to include in output (comma-separated or repeated). Available: rank, track, artist, album, plays, percentage",
)
@click.pass_context
def top_tracks(ctx, database, limit, since, until, period, artist, format, fields):
    """
    Show top tracks with flexible time range support.

    Discover your most played tracks over various time periods.

    \b
    Examples:
        # Top 10 tracks all-time
        scrobbledb tracks top

        # Top 25 tracks this month
        scrobbledb tracks top --limit 25 --period month

        # Top tracks by specific artist in last year
        scrobbledb tracks top --artist "Radiohead" --period year

        # Top tracks in date range
        scrobbledb tracks top --since 2024-01-01 --until 2024-12-31
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

    # Query top tracks
    try:
        tracks = domain_queries.get_top_tracks(
            db, limit=limit, since=since_dt, until=until_dt, artist=artist
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
            "track": "track_title",
            "artist": "artist_name",
            "album": "album_title",
            "plays": "play_count",
            "percentage": "percentage",
        }
        data_keys = [field_mapping.get(f, f) for f in selected_fields if field_mapping.get(f)]
        tracks = domain_format.filter_fields(tracks, data_keys)

    # Output results
    if format == "table":
        since_str = since or (period if period else None)
        until_str = until or None
        domain_format.format_top_tracks(tracks, console, since=since_str, until=until_str, fields=selected_fields)
    else:
        output = domain_format.format_output(tracks, format)
        click.echo(output)


@tracks.command(name="show")
@click.argument("track_title", required=False)
@click.option(
    "-d",
    "--database",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    default=None,
    help="Database path (default: XDG data directory)",
)
@click.option(
    "--track-id",
    type=str,
    default=None,
    help="Use track ID instead of title",
)
@click.option(
    "--artist",
    type=str,
    default=None,
    help="Artist name (to disambiguate tracks with same title)",
)
@click.option(
    "--album",
    type=str,
    default=None,
    help="Album title (to disambiguate further)",
)
@click.option(
    "--show-plays",
    is_flag=True,
    default=False,
    help="Show individual play timestamps",
)
@click.option(
    "--format",
    type=click.Choice(["table", "json", "jsonl"], case_sensitive=False),
    default="table",
    help="Output format",
    show_default=True,
)
@click.pass_context
def show_track(ctx, track_title, database, track_id, artist, album, show_plays, format):
    """
    Display detailed information about a specific track.

    View play history and statistics for a single track.

    \b
    Examples:
        # Show track details
        scrobbledb tracks show "Bohemian Rhapsody"

        # Disambiguate by artist
        scrobbledb tracks show "Here Comes the Sun" --artist "The Beatles"

        # Show with full play history
        scrobbledb tracks show "Comfortably Numb" --show-plays

        # Use track ID
        scrobbledb tracks show --track-id 456
    """
    # Validate arguments
    if not track_id and not track_title:
        console.print("[red]✗[/red] Either TRACK_TITLE or --track-id is required")
        console.print("[yellow]→[/yellow] Try: [cyan]scrobbledb tracks show \"Track Name\"[/cyan]")
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

    # Check if we have any tracks
    if "tracks" not in db.table_names():
        console.print("[yellow]![/yellow] No tracks found in database.")
        console.print(
            "[yellow]→[/yellow] Run [cyan]scrobbledb ingest[/cyan] to import your listening history."
        )
        ctx.exit(1)

    # Get track details
    try:
        track = domain_queries.get_track_details(
            db,
            track_id=track_id,
            track_title=track_title,
            artist_name=artist,
            album_title=album,
        )
    except ValueError as e:
        if "Multiple tracks match" in str(e):
            console.print(f"[yellow]![/yellow] {e}")
            console.print(
                "\n[dim]Use --artist and/or --album to narrow down, or use --track-id for exact selection.[/dim]"
            )
            ctx.exit(1)
        else:
            console.print(f"[red]✗[/red] Error: {e}")
            ctx.exit(1)

    if not track:
        if track_id:
            console.print(f"[yellow]![/yellow] No track found with ID [cyan]{track_id}[/cyan]")
            console.print("[yellow]→[/yellow] Try searching: [cyan]scrobbledb tracks search \"keyword\"[/cyan]")
        else:
            console.print(f"[yellow]![/yellow] No track found matching [yellow]\"{track_title}\"[/yellow]")
            console.print(f"[yellow]→[/yellow] Try searching: [cyan]scrobbledb tracks search \"{track_title}\"[/cyan]")
        ctx.exit(1)

    # Get plays if requested
    assert track is not None  # Type narrowing for type checker
    plays = None
    if show_plays:
        try:
            # Limit to 100 most recent plays
            plays = domain_queries.get_track_plays(db, track["track_id"], limit=100)
        except Exception as e:
            console.print(f"[red]✗[/red] Failed to get play history: {e}")
            ctx.exit(1)

    # Output results
    if format == "table":
        domain_format.format_track_details(track, plays, console)
    else:
        # For JSON output, combine track and plays
        output_data = {**track}
        if plays:
            output_data["plays"] = plays

        if format == "json":
            import json

            click.echo(json.dumps(output_data, indent=2, default=str))
        else:  # jsonl
            import json

            click.echo(json.dumps(output_data, default=str))
