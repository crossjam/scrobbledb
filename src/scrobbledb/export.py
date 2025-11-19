"""
Export scrobble data in various formats.

This module provides export functionality for scrobbledb with support for:
- Multiple output formats (JSONL, CSV, TSV, JSON)
- Preset exports for common scrobble queries
- Custom SQL queries with validation
- Sampling and limiting
- Dry-run mode
- File and stdout output
"""

import click
import sys
import random
import sqlite_utils
from pathlib import Path


# Preset queries for common scrobble exports
PRESET_QUERIES = {
    "plays": """
        SELECT
            plays.timestamp,
            tracks.title as track_title,
            albums.title as album_title,
            artists.name as artist_name,
            tracks.id as track_id,
            albums.id as album_id,
            artists.id as artist_id
        FROM plays
        JOIN tracks ON plays.track_id = tracks.id
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
        ORDER BY plays.timestamp DESC
    """,
    "tracks": """
        SELECT
            tracks.id,
            tracks.title,
            albums.title as album_title,
            artists.name as artist_name,
            albums.id as album_id,
            artists.id as artist_id
        FROM tracks
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
        ORDER BY artists.name, albums.title, tracks.title
    """,
    "albums": """
        SELECT
            albums.id,
            albums.title,
            artists.name as artist_name,
            artists.id as artist_id,
            COUNT(DISTINCT tracks.id) as track_count
        FROM albums
        JOIN artists ON albums.artist_id = artists.id
        LEFT JOIN tracks ON albums.id = tracks.album_id
        GROUP BY albums.id, albums.title, artists.name, artists.id
        ORDER BY artists.name, albums.title
    """,
    "artists": """
        SELECT
            artists.id,
            artists.name,
            COUNT(DISTINCT albums.id) as album_count,
            COUNT(DISTINCT tracks.id) as track_count,
            COUNT(plays.timestamp) as play_count
        FROM artists
        LEFT JOIN albums ON artists.id = albums.artist_id
        LEFT JOIN tracks ON albums.id = tracks.album_id
        LEFT JOIN plays ON tracks.id = plays.track_id
        GROUP BY artists.id, artists.name
        ORDER BY artists.name
    """,
}

# Valid scrobble-related table names for validation
SCROBBLE_TABLES = {"plays", "tracks", "albums", "artists"}


def validate_sql(sql: str) -> bool:
    """
    Validate that SQL query references scrobble-related tables.

    Returns True if the query references at least one scrobble table.
    """
    sql_lower = sql.lower()
    return any(table in sql_lower for table in SCROBBLE_TABLES)


def apply_column_filter(sql: str, columns: tuple) -> str:
    """
    Modify SQL to select only specified columns.

    This wraps the original query in a SELECT to filter columns.
    """
    if not columns:
        return sql

    column_list = ", ".join(f"[{col}]" for col in columns)
    return f"SELECT {column_list} FROM ({sql})"


def apply_limit(sql: str, limit: int) -> str:
    """Add LIMIT clause to SQL query."""
    # Check if query already has LIMIT
    if "limit" in sql.lower():
        return sql
    return f"{sql.rstrip(';')} LIMIT {limit}"


def apply_sample(db: sqlite_utils.Database, sql: str, sample: float, seed: int = None) -> str:
    """
    Apply random sampling to query results.

    Uses ORDER BY RANDOM() with optional seed for reproducibility.
    """
    if seed is not None:
        # SQLite doesn't support RANDOM(seed), but we can use it in Python filtering
        random.seed(seed)

    # We'll handle sampling in Python after fetching results
    # to support the seed parameter properly
    return sql


def format_output(rows: list, format: str, no_headers: bool = False) -> str:
    """Format rows according to specified format."""
    if not rows:
        if format == "jsonl":
            return ""
        elif format in ("csv", "tsv"):
            return ""
        else:  # json
            return "[]"

    import json
    import csv as csv_module
    from io import StringIO

    if format == "json":
        return json.dumps(rows, indent=2, default=str)

    elif format == "jsonl":
        return "\n".join(json.dumps(row, default=str) for row in rows)

    elif format in ("csv", "tsv"):
        output = StringIO()
        delimiter = "\t" if format == "tsv" else ","

        if rows:
            fieldnames = rows[0].keys()
            writer = csv_module.DictWriter(output, fieldnames=fieldnames, delimiter=delimiter)

            if not no_headers:
                writer.writeheader()

            writer.writerows(rows)

        return output.getvalue()

    else:
        raise ValueError(f"Unsupported format: {format}")


@click.command()
@click.argument("preset", required=False, type=click.Choice(["plays", "tracks", "albums", "artists"]))
@click.option(
    "--database",
    "-d",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    default=None,
    help="Database path (default: scrobbledb database in XDG data dir)",
)
@click.option(
    "--sql",
    help="Custom SQL query to export",
)
@click.option(
    "--sql-file",
    type=click.Path(exists=True, file_okay=True, dir_okay=False),
    help="File containing SQL query to export",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["jsonl", "json", "csv", "tsv"]),
    default="jsonl",
    help="Output format (default: jsonl)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=True),
    default="-",
    help="Output file (use '-' for stdout, default: stdout)",
)
@click.option(
    "--limit",
    type=int,
    help="Maximum number of rows to export",
)
@click.option(
    "--sample",
    type=float,
    help="Random sample probability (0.0-1.0)",
)
@click.option(
    "--seed",
    type=int,
    help="Random seed for reproducible sampling (use with --sample)",
)
@click.option(
    "--columns",
    "-c",
    help="Comma-separated list of columns to include",
)
@click.option(
    "--no-headers",
    is_flag=True,
    help="Omit headers in CSV/TSV output",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show SQL query without executing",
)
def export(preset, database, sql, sql_file, format, output, limit, sample, seed, columns, no_headers, dry_run):
    """
    Export scrobble data in various formats.

    Export using presets (plays, tracks, albums, artists) or custom SQL queries.
    Supports multiple output formats and sampling options.

    Examples:

        \b
        # Export all plays to JSONL
        scrobbledb export plays --output plays.jsonl

        # Export 1000 most recent plays to CSV
        scrobbledb export plays --format csv --limit 1000 --output recent.csv

        # Export 10% sample of tracks
        scrobbledb export tracks --sample 0.1 --format json --output sample.json

        # Export with custom SQL
        scrobbledb export --sql "SELECT * FROM plays WHERE timestamp > '2025-01-01'" --format csv

        # Export from SQL file
        scrobbledb export --sql-file query.sql --format jsonl --output results.jsonl

        # Dry run to preview query
        scrobbledb export plays --limit 100 --dry-run

        # Select specific columns
        scrobbledb export plays --columns "timestamp,artist_name,track_title" --format csv
    """
    # Import here to avoid circular import
    from .cli import get_default_db_path

    # Validate arguments
    if not preset and not sql and not sql_file:
        raise click.UsageError("Must specify either a PRESET, --sql, or --sql-file")

    if sum([bool(preset), bool(sql), bool(sql_file)]) > 1:
        raise click.UsageError("Cannot specify more than one of PRESET, --sql, or --sql-file")

    if sample is not None:
        if not (0.0 <= sample <= 1.0):
            raise click.UsageError("--sample must be between 0.0 and 1.0")
        if sample == 0.0:
            raise click.UsageError("--sample cannot be 0.0 (no rows would be exported)")

    if seed is not None and sample is None:
        raise click.UsageError("--seed requires --sample")

    # Get database path
    if database is None:
        database = get_default_db_path()

    # Build SQL query
    if preset:
        query = PRESET_QUERIES[preset]
    elif sql:
        query = sql
    elif sql_file:
        query = Path(sql_file).read_text()

    # Validate SQL references scrobble tables
    if not validate_sql(query):
        click.echo(
            click.style("Warning: ", fg="yellow") +
            "SQL query does not reference scrobble tables (plays, tracks, albums, artists)",
            err=True
        )
        if not click.confirm("Continue anyway?"):
            raise click.Abort()

    # Apply column filter if specified
    if columns:
        column_list = [col.strip() for col in columns.split(",")]
        query = apply_column_filter(query, tuple(column_list))

    # Apply limit if specified
    if limit:
        query = apply_limit(query, limit)

    # Dry run mode - just show the query
    if dry_run:
        click.echo("SQL Query:", err=True)
        click.echo(query, err=True)
        if sample:
            click.echo(f"\nSampling: {sample * 100}% of results", err=True)
            if seed:
                click.echo(f"Random seed: {seed}", err=True)
        return

    # Execute query
    db = sqlite_utils.Database(database)

    try:
        results = list(db.execute(query).fetchall())

        # Convert to list of dicts
        if results:
            columns_from_query = [desc[0] for desc in db.execute(query).description]
            rows = [dict(zip(columns_from_query, row)) for row in results]
        else:
            rows = []

        # Apply sampling if specified
        if sample is not None:
            if seed is not None:
                random.seed(seed)
            rows = [row for row in rows if random.random() < sample]

        # Format output
        output_text = format_output(rows, format, no_headers)

        # Write output
        if output == "-":
            click.echo(output_text)
        else:
            Path(output).write_text(output_text)
            click.echo(f"Exported {len(rows)} rows to {output}", err=True)

    except Exception as e:
        click.echo(f"Error executing query: {e}", err=True)
        raise click.Abort()
