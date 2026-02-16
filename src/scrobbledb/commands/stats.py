"""
Descriptive statistics commands for scrobbledb.

This module provides CLI commands for viewing scrobble statistics:
- stats overview: Overall metrics (total scrobbles, unique artists/albums/tracks)
- stats monthly: Monthly rollup statistics
- stats yearly: Yearly rollup statistics
"""

import click
from rich.console import Console

from ..command_utils import (
    database_option,
    limit_option,
    format_option,
    time_range_options,
    check_database,
)
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
@database_option
@format_option()
@click.pass_context
def overview(ctx, database, format):
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
    db = check_database(ctx, database)

    stats_data = get_overview_stats(db)

    if format == "table":
        format_overview_stats(stats_data, console)
    else:
        output = format_output([stats_data], format)
        console.print(output)


@stats.command()
@database_option
@time_range_options
@limit_option(default=None)
@format_option()
@click.pass_context
def monthly(ctx, database, since, until, period, limit, format):
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
    db = check_database(ctx, database)

    # Parse date filters
    since_dt = None
    until_dt = None

    if period:
        from .. import domain_queries
        since_dt, until_dt = domain_queries.parse_period_to_dates(period)
    else:
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

    if format == "table":
        format_monthly_rollup(rows, console)
    else:
        output = format_output(rows, format)
        console.print(output)


@stats.command()
@database_option
@time_range_options
@limit_option(default=None)
@format_option()
@click.pass_context
def yearly(ctx, database, since, until, period, limit, format):
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
    db = check_database(ctx, database)

    # Parse date filters
    since_dt = None
    until_dt = None

    if period:
        from .. import domain_queries
        since_dt, until_dt = domain_queries.parse_period_to_dates(period)
    else:
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

    if format == "table":
        format_yearly_rollup(rows, console)
    else:
        output = format_output(rows, format)
        console.print(output)
