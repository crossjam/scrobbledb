"""
Shared Click options and utilities for scrobbledb commands.
"""

import click
from pathlib import Path
from rich.console import Console

from .config_utils import get_default_db_path

console = Console(stderr=True)


def database_option(f):
    """Add standard --database option."""
    return click.option(
        "-d",
        "--database",
        type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
        default=None,
        help="Database path (default: XDG data directory)",
    )(f)


def limit_option(default=20):
    """Add standard --limit option with customizable default."""
    def decorator(f):
        return click.option(
            "-l",
            "--limit",
            type=int,
            default=default,
            help="Maximum results",
            show_default=True,
        )(f)
    return decorator


def format_option(formats=None, default="table"):
    """Add standard --format option."""
    if formats is None:
        formats = ["table", "csv", "json", "jsonl"]
    
    def decorator(f):
        return click.option(
            "-f",
            "--format",
            type=click.Choice(formats, case_sensitive=False),
            default=default,
            help="Output format",
            show_default=True,
        )(f)
    return decorator


def fields_option(help_text="Fields to include in output (comma-separated or repeated)."):
    """Add standard --fields option."""
    return click.option(
        "--fields",
        type=str,
        multiple=True,
        help=help_text,
    )


def time_range_options(f):
    """Add --since, --until, and --period options."""
    f = click.option(
        "-s",
        "--since",
        type=str,
        default=None,
        help="Start date/time for analysis period",
    )(f)
    f = click.option(
        "-u",
        "--until",
        type=str,
        default=None,
        help="End date/time for analysis period",
    )(f)
    f = click.option(
        "--period",
        type=click.Choice(["week", "month", "quarter", "year", "all-time"], case_sensitive=False),
        default=None,
        help="Predefined period",
    )(f)
    return f


def sort_options(sort_choices=None, default_sort="plays", default_order="desc"):
    """Add --sort and --order options."""
    if sort_choices is None:
        sort_choices = ["plays", "name", "recent"]

    def decorator(f):
        f = click.option(
            "--sort",
            type=click.Choice(sort_choices, case_sensitive=False),
            default=default_sort,
            help=f"Sort by: {', '.join(sort_choices)}",
            show_default=True,
        )(f)
        f = click.option(
            "--order",
            type=click.Choice(["desc", "asc"], case_sensitive=False),
            default=default_order,
            help="Sort order",
            show_default=True,
        )(f)
        return f
    return decorator


def filter_options(artist=True, album=False, track=False, artist_id=False, album_id=False):
    """Add filter options for artist, album, track, etc."""
    def decorator(f):
        if track:
             f = click.option(
                "--track",
                type=str,
                default=None,
                help="Filter by track title",
            )(f)
        if album_id:
             f = click.option(
                "--album-id",
                type=str,
                default=None,
                help="Filter by album ID",
            )(f)
        if album:
            f = click.option(
                "--album",
                type=str,
                default=None,
                help="Filter by album title",
            )(f)
        if artist_id:
             f = click.option(
                "--artist-id",
                type=str,
                default=None,
                help="Filter by artist ID",
            )(f)
        if artist:
            f = click.option(
                "--artist",
                type=str,
                default=None,
                help="Filter by artist name",
            )(f)
        return f
    return decorator

def check_database(ctx, database):
    """
    Common database validation logic.
    Returns sqlite_utils.Database instance or exits.
    """
    import sqlite_utils
    
    if database is None:
        database = get_default_db_path()

    if not Path(database).exists():
        console.print(f"[red]✗[/red] Database not found: [cyan]{database}[/cyan]")
        console.print(
            "[yellow]→[/yellow] Run [cyan]scrobbledb config init[/cyan] to create a new database."
        )
        ctx.exit(1)

    return sqlite_utils.Database(database)

def parse_list_args(arg_list):
    """Helper to parse comma-separated list arguments."""
    if not arg_list:
        return None
    result = []
    for arg in arg_list:
        result.extend(x.strip() for x in arg.split(","))
    return result
