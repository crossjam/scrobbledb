"""
Albums command group for scrobbledb.

Commands for searching albums and viewing album details.
"""

import click
from rich.console import Console

from ..command_utils import (
    database_option,
    limit_option,
    format_option,
    fields_option,
    sort_options,
    filter_options,
    time_range_options,
    check_database,
    parse_list_args
)
from .. import domain_queries
from .. import domain_format

console = Console(stderr=True)


@click.group()
def albums():
    """
    Album investigation commands.

    Search for albums and view detailed information.
    """
    pass


@albums.command(name="search")
@click.argument("query", required=True)
@database_option
@limit_option(default=20)
@filter_options(artist=True)
@format_option()
@fields_option("Fields to include. Available: id, album, artist, tracks, plays, last_played")
@click.option(
    "--select",
    is_flag=True,
    help="Interactive mode: select a single result and output its details as JSON",
)
@click.pass_context
def search_albums(ctx, query, database, limit, artist, format, fields, select):
    """
    Search for albums using fuzzy matching.

    Find albums by partial name, useful when you don't remember exact titles.

    \b
    Examples:
        # Search for albums with "dark" in the title
        scrobbledb albums search "dark"

        # Search for albums by specific artist
        scrobbledb albums search "dark" --artist "Pink Floyd"

        # Get top 10 results
        scrobbledb albums search "greatest" --limit 10
    """
    db = check_database(ctx, database)

    # Check if we have any albums
    if "albums" not in db.table_names():
        console.print("[yellow]![/yellow] No albums found in database.")
        console.print(
            "[yellow]→[/yellow] Run [cyan]scrobbledb ingest[/cyan] to import your listening history."
        )
        ctx.exit(1)

    # Validate limit
    if limit < 1:
        console.print("[red]✗[/red] Limit must be at least 1")
        ctx.exit(1)

    # Search albums
    try:
        albums = domain_queries.get_albums_by_search(
            db, query=query, artist=artist, limit=limit
        )
    except Exception as e:
        console.print(f"[red]✗[/red] Search failed: {e}")
        ctx.exit(1)

    if not albums:
        console.print(f"[yellow]![/yellow] No albums found matching [yellow]\"{query}\"[/yellow]")
        ctx.exit(0)

    # Parse fields
    selected_fields = parse_list_args(fields)

    # Interactive selection mode
    if select:
        if len(albums) == 1:
            # Only one result, auto-select it
            selected = albums[0]
        else:
            # Display numbered results
            console.print(f"\n[bold]Found {len(albums)} albums matching [cyan]\"{query}\"[/cyan]:[/bold]\n")
            for i, album in enumerate(albums, 1):
                console.print(f"  [dim]{i}.[/dim] [magenta]{album['album_title']}[/magenta] by [cyan]{album['artist_name']}[/cyan] - {album['play_count']:,} plays")

            # Prompt for selection
            from rich.prompt import Prompt
            try:
                choice = Prompt.ask(
                    f"\n[bold]Select an album[/bold] [dim](1-{len(albums)}, or 'q' to quit)[/dim]",
                    default="1",
                    console=console
                )
                if choice.lower() == 'q':
                    ctx.exit(0)

                choice_num = int(choice)
                if choice_num < 1 or choice_num > len(albums):
                    console.print(f"[red]✗[/red] Invalid selection: {choice_num}")
                    ctx.exit(1)

                selected = albums[choice_num - 1]
            except (ValueError, KeyboardInterrupt):
                console.print("\n[yellow]Selection cancelled[/yellow]")
                ctx.exit(0)

        # Filter selected record if fields specified
        if selected_fields:
            field_mapping = {
                "id": "album_id",
                "album": "album_title",
                "artist": "artist_name",
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
            "id": "album_id",
            "album": "album_title",
            "artist": "artist_name",
            "tracks": "track_count",
            "plays": "play_count",
            "last_played": "last_played",
        }
        data_keys = [field_mapping.get(f, f) for f in selected_fields if field_mapping.get(f)]
        albums = domain_format.filter_fields(albums, data_keys)

    # Output results
    if format == "table":
        domain_format.format_albums_search(albums, console, fields=selected_fields)
    else:
        output = domain_format.format_output(albums, format)
        click.echo(output)


@albums.command(name="list")
@database_option
@limit_option(default=20)
@filter_options(artist=True, artist_id=True)
@sort_options(sort_choices=["plays", "name", "recent"], default_sort="recent")
@click.option(
    "--min-plays",
    type=int,
    default=0,
    help="Show only albums with at least N plays",
    show_default=True,
)
@click.option(
    "--expand",
    is_flag=True,
    help="Show detailed view with tracks for each album",
)
@format_option()
@fields_option("Fields to include. Available: id, album, artist, tracks, plays, last_played")
@click.pass_context
def list_albums(ctx, database, limit, artist, artist_id, sort, order, min_plays, expand, format, fields):
    """
    List albums with optional artist filter.

    Browse albums in your collection with sorting options. Filter by artist
    name or artist ID to see all albums by a specific artist.

    \b
    Examples:
        # List top 50 albums by play count
        scrobbledb albums list

        # List albums by specific artist
        scrobbledb albums list --artist "Radiohead"

        # List albums alphabetically
        scrobbledb albums list --sort name --order asc

        # List recently played albums with tracks
        scrobbledb albums list --sort recent --expand
    """
    db = check_database(ctx, database)

    # Check if we have any albums
    if "albums" not in db.table_names():
        console.print("[yellow]![/yellow] No albums found in database.")
        console.print(
            "[yellow]→[/yellow] Run [cyan]scrobbledb ingest[/cyan] to import your listening history."
        )
        ctx.exit(1)

    # Validate limit
    if limit < 1:
        console.print("[red]✗[/red] Limit must be at least 1")
        ctx.exit(1)

    # Query albums
    try:
        albums = domain_queries.get_albums_list(
            db,
            artist=artist,
            artist_id=artist_id,
            limit=limit,
            sort=sort,
            order=order,
            min_plays=min_plays,
        )
    except Exception as e:
        console.print(f"[red]✗[/red] Query failed: {e}")
        ctx.exit(1)

    if not albums:
        if artist:
            console.print(f"[yellow]![/yellow] No albums found for artist: [yellow]{artist}[/yellow]")
        elif artist_id:
            console.print(f"[yellow]![/yellow] No albums found for artist ID: [yellow]{artist_id}[/yellow]")
        else:
            console.print("[yellow]![/yellow] No albums found in database.")
        ctx.exit(0)

    # Fetch tracks if expand is requested
    if expand:
        for album in albums:
            try:
                album_tracks = domain_queries.get_album_tracks(db, album['album_id'])
                album['tracks'] = album_tracks
            except Exception:
                album['tracks'] = []

    # Parse fields
    selected_fields = parse_list_args(fields)

    # Filter data if fields specified and not table format
    # Note: we generally keep all data for table format (which filters internally) or if expand is used
    if selected_fields and format != "table" and not expand:
        field_mapping = {
            "id": "album_id",
            "album": "album_title",
            "artist": "artist_name",
            "tracks": "track_count",
            "plays": "play_count",
            "last_played": "last_played",
        }
        data_keys = [field_mapping.get(f, f) for f in selected_fields if field_mapping.get(f)]
        albums = domain_format.filter_fields(albums, data_keys)

    # Output results
    if format == "table":
        domain_format.format_albums_list(albums, console, fields=selected_fields, expand=expand)
    else:
        output = domain_format.format_output(albums, format)
        click.echo(output)


@albums.command(name="top")
@database_option
@limit_option(default=20)
@time_range_options
@filter_options(artist=True)
@format_option()
@fields_option("Fields to include. Available: rank, album, artist, plays, percentage")
@click.pass_context
def top_albums(ctx, database, limit, since, until, period, artist, format, fields):
    """
    Show top albums with flexible time range support.

    Discover your most played albums over various time periods.

    \b
    Examples:
        # Top 10 albums all-time
        scrobbledb albums top

        # Top 25 albums this month
        scrobbledb albums top --limit 25 --period month

        # Top albums by specific artist
        scrobbledb albums top --artist "Radiohead"
    """
    db = check_database(ctx, database)

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

    # Query top albums
    try:
        albums = domain_queries.get_top_albums(
            db, limit=limit, since=since_dt, until=until_dt, artist=artist
        )
    except Exception as e:
        console.print(f"[red]✗[/red] Query failed: {e}")
        ctx.exit(1)

    # Parse fields
    selected_fields = parse_list_args(fields)

    # Filter data if fields specified and not table format
    if selected_fields and format != "table":
        field_mapping = {
            "rank": "rank",
            "album": "album_title",
            "artist": "artist_name",
            "plays": "play_count",
            "percentage": "percentage",
        }
        data_keys = [field_mapping.get(f, f) for f in selected_fields if field_mapping.get(f)]
        albums = domain_format.filter_fields(albums, data_keys)

    # Output results
    if format == "table":
        since_str = since or (period if period else None)
        until_str = until or None
        domain_format.format_top_albums(albums, console, since=since_str, until=until_str, fields=selected_fields)
    else:
        output = domain_format.format_output(albums, format)
        click.echo(output)


@albums.command(name="show")
@click.argument("album_title", required=False)
@database_option
@click.option(
    "--album-id",
    type=str,
    default=None,
    help="Use album ID instead of title",
)
@click.option(
    "--artist",
    type=str,
    default=None,
    help="Artist name (to disambiguate albums with same title)",
)
@format_option(formats=["table", "json", "jsonl"])
@click.pass_context
def show_album(ctx, album_title, database, album_id, artist, format):
    """
    Display detailed information about a specific album and list its tracks.

    View all tracks in an album with play statistics.

    \b
    Examples:
        # Show tracks in an album
        scrobbledb albums show "The Dark Side of the Moon"

        # Disambiguate by artist
        scrobbledb albums show "Rubber Soul" --artist "The Beatles"

        # Use album ID
        scrobbledb albums show --album-id 42
    """
    # Validate arguments
    if not album_id and not album_title:
        console.print("[red]✗[/red] Either ALBUM_TITLE or --album-id is required")
        console.print("[yellow]→[/yellow] Try: [cyan]scrobbledb albums show \"Album Name\"[/cyan]")
        ctx.exit(1)

    db = check_database(ctx, database)

    # Check if we have any albums
    if "albums" not in db.table_names():
        console.print("[yellow]![/yellow] No albums found in database.")
        console.print(
            "[yellow]→[/yellow] Run [cyan]scrobbledb ingest[/cyan] to import your listening history."
        )
        ctx.exit(1)

    # Get album details
    try:
        album = domain_queries.get_album_details(
            db, album_id=album_id, album_title=album_title, artist_name=artist
        )
    except ValueError as e:
        if "Multiple albums match" in str(e):
            console.print(f"[yellow]![/yellow] {e}")
            console.print(
                "[yellow]→[/yellow] Use [cyan]--artist[/cyan] to narrow down the search, or [cyan]--album-id[/cyan] for exact selection."
            )
            ctx.exit(1)
        else:
            console.print(f"[red]✗[/red] Error: {e}")
            ctx.exit(1)

    if not album:
        if album_id:
            console.print(f"[yellow]![/yellow] No album found with ID [cyan]{album_id}[/cyan]")
            console.print("[yellow]→[/yellow] Try searching: [cyan]scrobbledb albums search \"keyword\"[/cyan]")
        else:
            console.print(
                f"[yellow]![/yellow] No album found matching [yellow]\"{album_title}\"[/yellow]"
            )
            console.print("[yellow]→[/yellow] Try searching: [cyan]scrobbledb albums search \"{album_title}\"[/cyan]")
        ctx.exit(1)

    # Get tracks for this album
    assert album is not None  # Type narrowing for type checker
    try:
        tracks = domain_queries.get_album_tracks(db, album["album_id"])
    except Exception as e:
        console.print(f"[red]✗[/red] Failed to get tracks: {e}")
        ctx.exit(1)

    # Output results
    if format == "table":
        domain_format.format_album_details(album, tracks, console)
    else:
        # For JSON output, combine album and tracks
        output_data = {**album, "tracks": tracks}
        if format == "json":
            import json

            click.echo(json.dumps(output_data, indent=2, default=str))
        else:  # jsonl
            import json

            click.echo(json.dumps(output_data, default=str))
