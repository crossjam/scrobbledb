"""
Albums command group for scrobbledb.

Commands for searching albums and viewing album details.
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
def albums():
    """
    Album investigation commands.

    Search for albums and view detailed information.
    """
    pass


@albums.command(name="search")
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
    help="Fields to include in output (comma-separated or repeated). Available: album, artist, tracks, plays, last_played",
)
@click.pass_context
def search_albums(ctx, query, database, limit, artist, format, fields):
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

    # Parse fields
    selected_fields = None
    if fields:
        selected_fields = []
        for field_arg in fields:
            selected_fields.extend(f.strip() for f in field_arg.split(","))

    # Filter data if fields specified and not table format
    if selected_fields and format != "table":
        field_mapping = {
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


@albums.command(name="show")
@click.argument("album_title", required=False)
@click.option(
    "-d",
    "--database",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    default=None,
    help="Database path (default: XDG data directory)",
)
@click.option(
    "--album-id",
    type=int,
    default=None,
    help="Use album ID instead of title",
)
@click.option(
    "--artist",
    type=str,
    default=None,
    help="Artist name (to disambiguate albums with same title)",
)
@click.option(
    "--format",
    type=click.Choice(["table", "json", "jsonl"], case_sensitive=False),
    default="table",
    help="Output format",
    show_default=True,
)
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
