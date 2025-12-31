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
