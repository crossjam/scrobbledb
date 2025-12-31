"""
Domain query functions for scrobbledb.

This module provides shared query functions for domain-specific CLI commands,
including statistics, filtering, and aggregation queries.
"""

from datetime import datetime
from typing import Optional
import sqlite_utils


def get_overview_stats(db: sqlite_utils.Database) -> dict:
    """
    Get overview statistics for the entire database.

    Returns a dict with:
    - total_scrobbles: Total number of plays
    - unique_artists: Count of distinct artists
    - unique_albums: Count of distinct albums
    - unique_tracks: Count of distinct tracks
    - first_scrobble: Earliest play timestamp
    - last_scrobble: Most recent play timestamp
    """
    result = db.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM plays) as total_scrobbles,
            (SELECT COUNT(*) FROM artists) as unique_artists,
            (SELECT COUNT(*) FROM albums) as unique_albums,
            (SELECT COUNT(*) FROM tracks) as unique_tracks,
            (SELECT MIN(timestamp) FROM plays) as first_scrobble,
            (SELECT MAX(timestamp) FROM plays) as last_scrobble
        """
    ).fetchone()

    return {
        "total_scrobbles": result[0] or 0,
        "unique_artists": result[1] or 0,
        "unique_albums": result[2] or 0,
        "unique_tracks": result[3] or 0,
        "first_scrobble": result[4],
        "last_scrobble": result[5],
    }


def get_monthly_rollup(
    db: sqlite_utils.Database,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    """
    Get scrobble statistics rolled up by month.

    Args:
        db: Database connection
        since: Optional start date filter
        until: Optional end date filter
        limit: Optional limit on number of results

    Returns a list of dicts, each containing:
    - year: The year
    - month: The month (1-12)
    - scrobbles: Number of plays in that month
    - unique_artists: Distinct artists played that month
    - unique_albums: Distinct albums played that month
    - unique_tracks: Distinct tracks played that month
    """
    conditions = []
    params = []

    if since:
        conditions.append("plays.timestamp >= ?")
        params.append(since.isoformat() if isinstance(since, datetime) else since)

    if until:
        conditions.append("plays.timestamp <= ?")
        params.append(until.isoformat() if isinstance(until, datetime) else until)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    limit_clause = ""
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be a positive integer")
        limit_clause = f"LIMIT {limit}"

    query = f"""
        SELECT
            CAST(strftime('%Y', plays.timestamp) AS INTEGER) as year,
            CAST(strftime('%m', plays.timestamp) AS INTEGER) as month,
            COUNT(*) as scrobbles,
            COUNT(DISTINCT artists.id) as unique_artists,
            COUNT(DISTINCT albums.id) as unique_albums,
            COUNT(DISTINCT tracks.id) as unique_tracks
        FROM plays
        JOIN tracks ON plays.track_id = tracks.id
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
        {where_clause}
        GROUP BY year, month
        ORDER BY year DESC, month DESC
        {limit_clause}
    """

    rows = db.execute(query, params).fetchall()
    return [
        {
            "year": row[0],
            "month": row[1],
            "scrobbles": row[2],
            "unique_artists": row[3],
            "unique_albums": row[4],
            "unique_tracks": row[5],
        }
        for row in rows
    ]


def get_yearly_rollup(
    db: sqlite_utils.Database,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    """
    Get scrobble statistics rolled up by year.

    Args:
        db: Database connection
        since: Optional start date filter
        until: Optional end date filter
        limit: Optional limit on number of results

    Returns a list of dicts, each containing:
    - year: The year
    - scrobbles: Number of plays in that year
    - unique_artists: Distinct artists played that year
    - unique_albums: Distinct albums played that year
    - unique_tracks: Distinct tracks played that year
    """
    conditions = []
    params = []

    if since:
        conditions.append("plays.timestamp >= ?")
        params.append(since.isoformat() if isinstance(since, datetime) else since)

    if until:
        conditions.append("plays.timestamp <= ?")
        params.append(until.isoformat() if isinstance(until, datetime) else until)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    limit_clause = ""
    if limit is not None:
        limit_value = int(limit)
        if limit_value > 0:
            limit_clause = f"LIMIT {limit_value}"

    query = f"""
        SELECT
            CAST(strftime('%Y', plays.timestamp) AS INTEGER) as year,
            COUNT(*) as scrobbles,
            COUNT(DISTINCT artists.id) as unique_artists,
            COUNT(DISTINCT albums.id) as unique_albums,
            COUNT(DISTINCT tracks.id) as unique_tracks
        FROM plays
        JOIN tracks ON plays.track_id = tracks.id
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
        {where_clause}
        GROUP BY year
        ORDER BY year DESC
        {limit_clause}
    """

    rows = db.execute(query, params).fetchall()
    return [
        {
            "year": row[0],
            "scrobbles": row[1],
            "unique_artists": row[2],
            "unique_albums": row[3],
            "unique_tracks": row[4],
        }
        for row in rows
    ]


def parse_relative_time(time_str: str) -> Optional[datetime]:
    """
    Parse relative time expressions like '7 days ago' or absolute dates.

    Supports:
    - "N days/weeks/months/years ago"
    - "yesterday", "today"
    - "last week/month/year"
    - ISO 8601 and other common date formats (via dateutil)

    Returns:
        datetime object or None if parsing fails
    """
    import re
    from datetime import timedelta
    from dateutil.relativedelta import relativedelta
    import dateutil.parser

    time_str = time_str.strip().lower()

    # Handle "today" and "yesterday"
    if time_str == "today":
        now = datetime.now()
        return datetime(now.year, now.month, now.day)

    if time_str == "yesterday":
        now = datetime.now()
        yesterday = now - timedelta(days=1)
        return datetime(yesterday.year, yesterday.month, yesterday.day)

    # Handle "last week/month/year"
    last_pattern = re.match(r"last\s+(week|month|year)", time_str)
    if last_pattern:
        unit = last_pattern.group(1)
        now = datetime.now()
        if unit == "week":
            return now - timedelta(weeks=1)
        elif unit == "month":
            return now - relativedelta(months=1)
        elif unit == "year":
            return now - relativedelta(years=1)

    # Handle "N days/weeks/months/years ago"
    ago_pattern = re.match(r"(\d+)\s+(day|week|month|year)s?\s+ago", time_str)
    if ago_pattern:
        amount = int(ago_pattern.group(1))
        unit = ago_pattern.group(2)
        now = datetime.now()
        if unit == "day":
            return now - timedelta(days=amount)
        elif unit == "week":
            return now - timedelta(weeks=amount)
        elif unit == "month":
            return now - relativedelta(months=amount)
        elif unit == "year":
            return now - relativedelta(years=amount)

    # Fall back to dateutil parser for absolute dates
    try:
        return dateutil.parser.parse(time_str)
    except (ValueError, TypeError):
        return None
