"""
Descriptive statistics commands for scrobbledb.

This module provides CLI commands for viewing scrobble statistics:
- stats overview: Overall metrics (total scrobbles, unique artists/albums/tracks)
- stats monthly: Monthly rollup statistics
- stats yearly: Yearly rollup statistics
"""

import click
import sqlite_utils
from pathlib import Path
from rich.console import Console

from ..domain_queries import (
    get_overview_stats,
    get_monthly_rollup,
    get_yearly_rollup,
    parse_relative_time,
)
from ..domain_format import (
    format_output,
    format_overview_stats,
    format_monthly_rollup,
    format_yearly_rollup,
)

console = Console()


def get_default_db_path():
    """Get the default path for the database in XDG compliant directory."""
    from platformdirs import user_data_dir

    APP_NAME = "dev.pirateninja.scrobbledb"
    data_dir = Path(user_data_dir(APP_NAME))
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "scrobbledb.db")


def validate_database(db_path: str) -> sqlite_utils.Database:
    """
    Validate database exists and has the expected tables.

    Args:
        db_path: Path to the database file

    Returns:
        sqlite_utils.Database instance

    Raises:
        click.ClickException: If database doesn't exist or is missing tables
    """
    path = Path(db_path)
    if not path.exists():
        raise click.ClickException(
            f"Database not found: {db_path}\n"
            "Run 'scrobbledb config init' to create one."
        )

    db = sqlite_utils.Database(db_path)
    required_tables = {"plays", "tracks", "albums", "artists"}
    existing_tables = set(db.table_names())
    missing = required_tables - existing_tables

    if missing:
        raise click.ClickException(
            f"Database is missing required tables: {', '.join(missing)}\n"
            "Run 'scrobbledb config init' to initialize the database."
        )

    return db


@click.group()
def stats():
    """
    Descriptive statistics about your scrobbles.

    View overview metrics, monthly rollups, and yearly summaries of your
    listening history.

    Examples:

        # View overall statistics
        scrobbledb stats overview

        # View monthly rollup
        scrobbledb stats monthly

        # View yearly rollup
        scrobbledb stats yearly

        # Export to JSON
        scrobbledb stats monthly --format json
    """
    pass


@stats.command()
@click.option(
    "--database",
    "-d",
    default=None,
    help="Database path (default: XDG data dir)",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "jsonl", "csv"]),
    default="table",
    help="Output format (default: table)",
)
def overview(database, output_format):
    """
    Display overall scrobble statistics.

    Shows total scrobbles, unique artists, albums, and tracks,
    plus the date range of your listening history.

    Examples:

        # View statistics as a table
        scrobbledb stats overview

        # Export to JSON
        scrobbledb stats overview --format json
    """
    db_path = database or get_default_db_path()
    db = validate_database(db_path)

    stats_data = get_overview_stats(db)

    if output_format == "table":
        format_overview_stats(stats_data, console)
    else:
        output = format_output([stats_data], output_format)
        console.print(output)


@stats.command()
@click.option(
    "--database",
    "-d",
    default=None,
    help="Database path (default: XDG data dir)",
)
@click.option(
    "--since",
    "-s",
    default=None,
    help="Start date (ISO 8601 or relative like '7 days ago')",
)
@click.option(
    "--until",
    "-u",
    default=None,
    help="End date (ISO 8601 or relative)",
)
@click.option(
    "--limit",
    "-l",
    type=int,
    default=None,
    help="Maximum number of months to display",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "jsonl", "csv"]),
    default="table",
    help="Output format (default: table)",
)
def monthly(database, since, until, limit, output_format):
    """
    Display scrobble statistics rolled up by month.

    Shows scrobble counts, unique artists, albums, and tracks for each month.
    Results are ordered by date, most recent first.

    Examples:

        # View all months
        scrobbledb stats monthly

        # View last 12 months
        scrobbledb stats monthly --limit 12

        # View since a specific date
        scrobbledb stats monthly --since 2024-01-01

        # View last year
        scrobbledb stats monthly --since "1 year ago"

        # Export to CSV
        scrobbledb stats monthly --format csv > monthly_stats.csv
    """
    db_path = database or get_default_db_path()
    db = validate_database(db_path)

    # Parse date filters
    since_dt = None
    until_dt = None

    if since:
        since_dt = parse_relative_time(since)
        if since_dt is None:
            raise click.ClickException(
                f"Invalid date format: {since}\n"
                "Use ISO 8601 (YYYY-MM-DD) or relative time (e.g., '7 days ago')"
            )

    if until:
        until_dt = parse_relative_time(until)
        if until_dt is None:
            raise click.ClickException(
                f"Invalid date format: {until}\n"
                "Use ISO 8601 (YYYY-MM-DD) or relative time (e.g., '7 days ago')"
            )

    rows = get_monthly_rollup(db, since=since_dt, until=until_dt, limit=limit)

    if output_format == "table":
        format_monthly_rollup(rows, console)
    else:
        output = format_output(rows, output_format)
        console.print(output)


@stats.command()
@click.option(
    "--database",
    "-d",
    default=None,
    help="Database path (default: XDG data dir)",
)
@click.option(
    "--since",
    "-s",
    default=None,
    help="Start date (ISO 8601 or relative like '7 days ago')",
)
@click.option(
    "--until",
    "-u",
    default=None,
    help="End date (ISO 8601 or relative)",
)
@click.option(
    "--limit",
    "-l",
    type=int,
    default=None,
    help="Maximum number of years to display",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "jsonl", "csv"]),
    default="table",
    help="Output format (default: table)",
)
def yearly(database, since, until, limit, output_format):
    """
    Display scrobble statistics rolled up by year.

    Shows scrobble counts, unique artists, albums, and tracks for each year.
    Results are ordered by date, most recent first.

    Examples:

        # View all years
        scrobbledb stats yearly

        # View last 5 years
        scrobbledb stats yearly --limit 5

        # View since a specific year
        scrobbledb stats yearly --since 2020-01-01

        # Export to JSON
        scrobbledb stats yearly --format json
    """
    db_path = database or get_default_db_path()
    db = validate_database(db_path)

    # Parse date filters
    since_dt = None
    until_dt = None

    if since:
        since_dt = parse_relative_time(since)
        if since_dt is None:
            raise click.ClickException(
                f"Invalid date format: {since}\n"
                "Use ISO 8601 (YYYY-MM-DD) or relative time (e.g., '7 days ago')"
            )

    if until:
        until_dt = parse_relative_time(until)
        if until_dt is None:
            raise click.ClickException(
                f"Invalid date format: {until}\n"
                "Use ISO 8601 (YYYY-MM-DD) or relative time (e.g., '7 days ago')"
            )

    rows = get_yearly_rollup(db, since=since_dt, until=until_dt, limit=limit)

    if output_format == "table":
        format_yearly_rollup(rows, console)
    else:
        output = format_output(rows, output_format)
        console.print(output)
