"""
Domain formatting utilities for scrobbledb.

This module provides shared formatting functions for domain-specific CLI commands,
including Rich console output and multiple export formats.
"""

import json
import csv as csv_module
from io import StringIO


from rich.console import Console
from rich.table import Table
from rich.panel import Panel


def format_output(rows: list[dict], format: str, no_headers: bool = False) -> str:
    """
    Format rows according to specified format.

    Args:
        rows: List of dictionaries to format
        format: Output format - 'json', 'jsonl', 'csv', or 'tsv'
        no_headers: If True, omit headers in CSV/TSV output

    Returns:
        Formatted string
    """
    if not rows:
        if format == "jsonl":
            return ""
        elif format in ("csv", "tsv"):
            return ""
        else:  # json
            return "[]"

    if format == "json":
        return json.dumps(rows, indent=2, default=str)

    elif format == "jsonl":
        return "\n".join(json.dumps(row, default=str) for row in rows)

    elif format in ("csv", "tsv"):
        output = StringIO()
        delimiter = "\t" if format == "tsv" else ","
        fieldnames = list(rows[0].keys())
        writer = csv_module.DictWriter(
            output, fieldnames=fieldnames, delimiter=delimiter
        )
        if not no_headers:
            writer.writeheader()
        writer.writerows(rows)
        return output.getvalue().rstrip("\n")

    else:
        raise ValueError(f"Unknown format: {format}")


def format_overview_stats(stats: dict, console: Console) -> None:
    """
    Display overview statistics in a Rich panel.

    Args:
        stats: Dictionary with overview statistics
        console: Rich Console instance for output
    """
    # Create a summary table
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="yellow")

    table.add_row("Total Scrobbles", f"{stats['total_scrobbles']:,}")
    table.add_row("Unique Artists", f"{stats['unique_artists']:,}")
    table.add_row("Unique Albums", f"{stats['unique_albums']:,}")
    table.add_row("Unique Tracks", f"{stats['unique_tracks']:,}")

    # Add date range if available
    if stats.get("first_scrobble") and stats.get("last_scrobble"):
        table.add_row("", "")  # Spacer
        table.add_row("First Scrobble", stats["first_scrobble"])
        table.add_row("Last Scrobble", stats["last_scrobble"])

    console.print(Panel(table, title="Scrobble Overview", border_style="blue"))


def format_monthly_rollup(
    rows: list[dict], console: Console, show_totals: bool = True
) -> None:
    """
    Display monthly rollup statistics in a Rich table.

    Args:
        rows: List of monthly statistics dictionaries
        console: Rich Console instance for output
        show_totals: If True, show a totals row at the bottom
    """
    if not rows:
        console.print("[yellow]No data found for the specified period.[/yellow]")
        return

    table = Table(title="Monthly Statistics")
    table.add_column("Year", justify="right", style="cyan")
    table.add_column("Month", justify="right", style="cyan")
    table.add_column("Scrobbles", justify="right", style="yellow")
    table.add_column("Artists", justify="right", style="green")
    table.add_column("Albums", justify="right", style="green")
    table.add_column("Tracks", justify="right", style="green")

    total_scrobbles = 0
    for row in rows:
        month_name = _get_month_name(row["month"])
        table.add_row(
            str(row["year"]),
            month_name,
            f"{row['scrobbles']:,}",
            f"{row['unique_artists']:,}",
            f"{row['unique_albums']:,}",
            f"{row['unique_tracks']:,}",
        )
        total_scrobbles += row["scrobbles"]

    if show_totals and len(rows) > 1:
        table.add_section()
        table.add_row(
            "Total",
            f"({len(rows)} months)",
            f"{total_scrobbles:,}",
            "-",
            "-",
            "-",
            style="bold",
        )

    console.print(table)


def format_yearly_rollup(
    rows: list[dict], console: Console, show_totals: bool = True
) -> None:
    """
    Display yearly rollup statistics in a Rich table.

    Args:
        rows: List of yearly statistics dictionaries
        console: Rich Console instance for output
        show_totals: If True, show a totals row at the bottom
    """
    if not rows:
        console.print("[yellow]No data found for the specified period.[/yellow]")
        return

    table = Table(title="Yearly Statistics")
    table.add_column("Year", justify="right", style="cyan")
    table.add_column("Scrobbles", justify="right", style="yellow")
    table.add_column("Artists", justify="right", style="green")
    table.add_column("Albums", justify="right", style="green")
    table.add_column("Tracks", justify="right", style="green")

    total_scrobbles = 0
    for row in rows:
        table.add_row(
            str(row["year"]),
            f"{row['scrobbles']:,}",
            f"{row['unique_artists']:,}",
            f"{row['unique_albums']:,}",
            f"{row['unique_tracks']:,}",
        )
        total_scrobbles += row["scrobbles"]

    if show_totals and len(rows) > 1:
        table.add_section()
        table.add_row(
            "Total",
            f"{total_scrobbles:,}",
            "-",
            "-",
            "-",
            style="bold",
        )

    console.print(table)


def _get_month_name(month: int) -> str:
    """Convert month number to abbreviated name."""
    months = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]
    if 1 <= month <= 12:
        return months[month - 1]
    return str(month)


def format_timestamp(ts: str) -> str:
    """
    Format timestamp consistently across commands.

    Args:
        ts: Timestamp string (ISO format)

    Returns:
        Formatted timestamp string (YYYY-MM-DD HH:MM:SS)
    """
    import dateutil.parser
    from datetime import datetime

    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d %H:%M:%S")

    try:
        dt = dateutil.parser.parse(ts)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return str(ts)


def format_plays_list(plays: list[dict], console: Console) -> None:
    """
    Format plays as a rich table.

    Args:
        plays: List of play dictionaries
        console: Rich Console instance for output
    """
    if not plays:
        console.print("[yellow]No plays found.[/yellow]")
        return

    table = Table(title=f"Plays ({len(plays)} found)")
    table.add_column("Timestamp", style="yellow")
    table.add_column("Artist", style="cyan")
    table.add_column("Track", style="green")
    table.add_column("Album", style="magenta")

    for play in plays:
        table.add_row(
            format_timestamp(play["timestamp"]),
            play["artist_name"],
            play["track_title"],
            play["album_title"],
        )

    console.print(table)


def format_artists_list(artists: list[dict], console: Console) -> None:
    """
    Format artists list as a rich table.

    Args:
        artists: List of artist dictionaries
        console: Rich Console instance for output
    """
    if not artists:
        console.print("[yellow]No artists found.[/yellow]")
        return

    table = Table(title=f"Artists ({len(artists)} found)")
    table.add_column("Artist", style="cyan")
    table.add_column("Plays", justify="right", style="yellow")
    table.add_column("Tracks", justify="right", style="green")
    table.add_column("Albums", justify="right", style="magenta")
    table.add_column("Last Played", style="blue")

    for artist in artists:
        table.add_row(
            artist["artist_name"],
            f"{artist['play_count']:,}",
            f"{artist['track_count']:,}",
            f"{artist['album_count']:,}",
            format_timestamp(artist["last_played"])
            if artist.get("last_played")
            else "-",
        )

    console.print(table)


def format_top_artists(artists: list[dict], console: Console, since: str = None, until: str = None) -> None:
    """
    Format top artists as a rich table with ranking.

    Args:
        artists: List of artist dictionaries with rank and percentage
        console: Rich Console instance for output
        since: Optional start date string for title
        until: Optional end date string for title
    """
    if not artists:
        console.print("[yellow]No artists found.[/yellow]")
        return

    # Build title
    title = "Top Artists"
    if since or until:
        if since and until:
            title += f" ({since} to {until})"
        elif since:
            title += f" (since {since})"
        elif until:
            title += f" (until {until})"

    table = Table(title=title)
    table.add_column("Rank", justify="right", style="dim")
    table.add_column("Artist", style="cyan")
    table.add_column("Plays", justify="right", style="yellow")
    table.add_column("%", justify="right", style="magenta")
    table.add_column("Avg/Day", justify="right", style="green")

    for artist in artists:
        table.add_row(
            str(artist["rank"]),
            artist["artist_name"],
            f"{artist['play_count']:,}",
            f"{artist['percentage']:.1f}%",
            f"{artist['avg_plays_per_day']:.1f}",
        )

    console.print(table)


def format_albums_search(albums: list[dict], console: Console) -> None:
    """
    Format album search results as a rich table.

    Args:
        albums: List of album dictionaries
        console: Rich Console instance for output
    """
    if not albums:
        console.print("[yellow]No albums found.[/yellow]")
        return

    table = Table(title=f"Albums ({len(albums)} found)")
    table.add_column("Album", style="magenta")
    table.add_column("Artist", style="cyan")
    table.add_column("Tracks", justify="right", style="green")
    table.add_column("Plays", justify="right", style="yellow")
    table.add_column("Last Played", style="blue")

    for album in albums:
        table.add_row(
            album["album_title"],
            album["artist_name"],
            f"{album['track_count']:,}",
            f"{album['play_count']:,}",
            format_timestamp(album["last_played"])
            if album.get("last_played")
            else "-",
        )

    console.print(table)


def format_album_details(album: dict, tracks: list[dict], console: Console) -> None:
    """
    Format album details with track listing.

    Args:
        album: Album details dictionary
        tracks: List of track dictionaries
        console: Rich Console instance for output
    """
    # Album summary panel
    summary = f"""[bold]{album['album_title']}[/bold]
[cyan]Artist:[/cyan] {album['artist_name']}
[cyan]Tracks:[/cyan] {album['track_count']}
[cyan]Total Plays:[/cyan] {album['play_count']:,}
[cyan]First Played:[/cyan] {format_timestamp(album['first_played']) if album.get('first_played') else 'Never'}
[cyan]Last Played:[/cyan] {format_timestamp(album['last_played']) if album.get('last_played') else 'Never'}"""

    console.print(Panel(summary, title="Album Details", border_style="magenta"))
    console.print()

    # Track listing
    if tracks:
        table = Table(title="Tracks")
        table.add_column("#", justify="right", style="dim")
        table.add_column("Track", style="green")
        table.add_column("Plays", justify="right", style="yellow")
        table.add_column("Last Played", style="blue")

        for i, track in enumerate(tracks, 1):
            table.add_row(
                str(i),
                track["track_title"],
                f"{track['play_count']:,}",
                format_timestamp(track["last_played"])
                if track.get("last_played")
                else "-",
            )

        console.print(table)


def format_tracks_search(tracks: list[dict], console: Console) -> None:
    """
    Format track search results as a rich table.

    Args:
        tracks: List of track dictionaries
        console: Rich Console instance for output
    """
    if not tracks:
        console.print("[yellow]No tracks found.[/yellow]")
        return

    table = Table(title=f"Tracks ({len(tracks)} found)")
    table.add_column("Track", style="green")
    table.add_column("Artist", style="cyan")
    table.add_column("Album", style="magenta")
    table.add_column("Plays", justify="right", style="yellow")
    table.add_column("Last Played", style="blue")

    for track in tracks:
        table.add_row(
            track["track_title"],
            track["artist_name"],
            track["album_title"],
            f"{track['play_count']:,}",
            format_timestamp(track["last_played"])
            if track.get("last_played")
            else "-",
        )

    console.print(table)


def format_top_tracks(tracks: list[dict], console: Console, since: str = None, until: str = None) -> None:
    """
    Format top tracks as a rich table with ranking.

    Args:
        tracks: List of track dictionaries with rank and percentage
        console: Rich Console instance for output
        since: Optional start date string for title
        until: Optional end date string for title
    """
    if not tracks:
        console.print("[yellow]No tracks found.[/yellow]")
        return

    # Build title
    title = "Top Tracks"
    if since or until:
        if since and until:
            title += f" ({since} to {until})"
        elif since:
            title += f" (since {since})"
        elif until:
            title += f" (until {until})"

    table = Table(title=title)
    table.add_column("Rank", justify="right", style="dim")
    table.add_column("Track", style="green")
    table.add_column("Artist", style="cyan")
    table.add_column("Album", style="magenta")
    table.add_column("Plays", justify="right", style="yellow")
    table.add_column("%", justify="right", style="blue")

    for track in tracks:
        table.add_row(
            str(track["rank"]),
            track["track_title"],
            track["artist_name"],
            track["album_title"],
            f"{track['play_count']:,}",
            f"{track['percentage']:.1f}%",
        )

    console.print(table)


def format_artist_details(
    artist: dict, top_tracks: list[dict], albums: list[dict], console: Console
) -> None:
    """
    Format artist details with top tracks and albums.

    Args:
        artist: Artist details dictionary
        top_tracks: List of top track dictionaries
        albums: List of album dictionaries
        console: Rich Console instance for output
    """
    # Artist summary panel
    summary = f"""[bold]{artist['artist_name']}[/bold]
[cyan]Total Plays:[/cyan] {artist['play_count']:,}
[cyan]Unique Tracks:[/cyan] {artist['track_count']:,}
[cyan]Unique Albums:[/cyan] {artist['album_count']:,}
[cyan]First Played:[/cyan] {format_timestamp(artist['first_played']) if artist.get('first_played') else 'Never'}
[cyan]Last Played:[/cyan] {format_timestamp(artist['last_played']) if artist.get('last_played') else 'Never'}"""

    console.print(Panel(summary, title="Artist Details", border_style="cyan"))
    console.print()

    # Top tracks
    if top_tracks:
        table = Table(title="Top Tracks")
        table.add_column("#", justify="right", style="dim")
        table.add_column("Track", style="green")
        table.add_column("Album", style="magenta")
        table.add_column("Plays", justify="right", style="yellow")
        table.add_column("Last Played", style="blue")

        for i, track in enumerate(top_tracks, 1):
            table.add_row(
                str(i),
                track["track_title"],
                track["album_title"],
                f"{track['play_count']:,}",
                format_timestamp(track["last_played"])
                if track.get("last_played")
                else "-",
            )

        console.print(table)
        console.print()

    # Albums
    if albums:
        table = Table(title="Albums")
        table.add_column("Album", style="magenta")
        table.add_column("Tracks", justify="right", style="green")
        table.add_column("Plays", justify="right", style="yellow")
        table.add_column("Last Played", style="blue")

        for album in albums:
            table.add_row(
                album["album_title"],
                f"{album['track_count']:,}",
                f"{album['play_count']:,}",
                format_timestamp(album["last_played"])
                if album.get("last_played")
                else "-",
            )

        console.print(table)


def format_track_details(
    track: dict, plays: list[dict] = None, console: Console = None
) -> None:
    """
    Format track details with optional play history.

    Args:
        track: Track details dictionary
        plays: Optional list of play dictionaries
        console: Rich Console instance for output
    """
    # Track summary panel
    summary = f"""[bold]{track['track_title']}[/bold]
[cyan]Artist:[/cyan] {track['artist_name']}
[cyan]Album:[/cyan] {track['album_title']}
[cyan]Total Plays:[/cyan] {track['play_count']:,}
[cyan]First Played:[/cyan] {format_timestamp(track['first_played']) if track.get('first_played') else 'Never'}
[cyan]Last Played:[/cyan] {format_timestamp(track['last_played']) if track.get('last_played') else 'Never'}"""

    # Calculate avg plays per month if we have enough data
    if track.get("first_played") and track.get("last_played"):
        import dateutil.parser
        from datetime import datetime

        first = dateutil.parser.parse(track["first_played"]) if isinstance(track["first_played"], str) else track["first_played"]
        last = dateutil.parser.parse(track["last_played"]) if isinstance(track["last_played"], str) else track["last_played"]
        months = ((last.year - first.year) * 12 + (last.month - first.month)) or 1
        if months >= 1:
            avg_per_month = track["play_count"] / months
            summary += f"\n[cyan]Avg Plays/Month:[/cyan] {avg_per_month:.1f}"

    console.print(Panel(summary, title="Track Details", border_style="green"))
    console.print()

    # Play history (if provided)
    if plays:
        table = Table(title=f"Play History ({len(plays)} plays)")
        table.add_column("Timestamp", style="yellow")
        table.add_column("Days Since Previous", justify="right", style="dim")

        prev_ts = None
        for play in plays:
            timestamp = play["timestamp"]

            # Calculate days since previous play
            days_since = ""
            if prev_ts:
                import dateutil.parser
                from datetime import datetime

                current = dateutil.parser.parse(timestamp) if isinstance(timestamp, str) else timestamp
                previous = dateutil.parser.parse(prev_ts) if isinstance(prev_ts, str) else prev_ts
                delta = (previous - current).days
                if delta > 0:
                    days_since = str(delta)
                else:
                    days_since = "<1"

            table.add_row(format_timestamp(timestamp), days_since)
            prev_ts = timestamp

        console.print(table)
