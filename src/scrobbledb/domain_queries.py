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


def parse_period_to_dates(period: str) -> tuple[Optional[datetime], Optional[datetime]]:
    """
    Convert period string to since/until dates.

    Supported periods:
    - 'week': last 7 days
    - 'month': last 30 days
    - 'quarter': last 90 days
    - 'year': last 365 days
    - 'all-time': no date filter (returns None, None)

    Returns:
        Tuple of (since, until) datetime objects
    """
    from datetime import timedelta

    now = datetime.now()
    period = period.lower().strip()

    if period == "week":
        return (now - timedelta(days=7), now)
    elif period == "month":
        return (now - timedelta(days=30), now)
    elif period == "quarter":
        return (now - timedelta(days=90), now)
    elif period == "year":
        return (now - timedelta(days=365), now)
    elif period == "all-time":
        return (None, None)
    else:
        raise ValueError(f"Unknown period: {period}")


def get_plays_with_filters(
    db: sqlite_utils.Database,
    limit: int = 20,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    track: Optional[str] = None,
) -> list[dict]:
    """
    Query plays with various filters.

    Args:
        db: Database connection
        limit: Maximum number of plays to return
        since: Start date filter
        until: End date filter
        artist: Artist name filter (partial match)
        album: Album title filter (partial match)
        track: Track title filter (partial match)

    Returns:
        List of dicts with play information
    """
    conditions = []
    params = []

    if since:
        conditions.append("plays.timestamp >= ?")
        params.append(since.isoformat() if isinstance(since, datetime) else since)

    if until:
        conditions.append("plays.timestamp <= ?")
        params.append(until.isoformat() if isinstance(until, datetime) else until)

    if artist:
        conditions.append("artists.name LIKE ?")
        params.append(f"%{artist}%")

    if album:
        conditions.append("albums.title LIKE ?")
        params.append(f"%{album}%")

    if track:
        conditions.append("tracks.title LIKE ?")
        params.append(f"%{track}%")

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    query = f"""
        SELECT
            plays.timestamp,
            artists.name as artist_name,
            tracks.title as track_title,
            albums.title as album_title
        FROM plays
        JOIN tracks ON plays.track_id = tracks.id
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
        {where_clause}
        ORDER BY plays.timestamp DESC
        LIMIT ?
    """
    params.append(limit)

    rows = db.execute(query, params).fetchall()
    return [
        {
            "timestamp": row[0],
            "artist_name": row[1],
            "track_title": row[2],
            "album_title": row[3],
        }
        for row in rows
    ]


def get_artists_with_stats(
    db: sqlite_utils.Database,
    limit: int = 50,
    sort_by: str = "plays",
    order: str = "desc",
    min_plays: int = 0,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> list[dict]:
    """
    Query artists with aggregated statistics.

    Args:
        db: Database connection
        limit: Maximum number of artists to return
        sort_by: Sort field ('plays', 'name', or 'recent')
        order: Sort order ('asc' or 'desc')
        min_plays: Minimum play count filter
        since: Start date filter
        until: End date filter

    Returns:
        List of dicts with artist statistics
    """
    conditions = []
    params = []

    # Date filters apply to plays
    if since:
        conditions.append("plays.timestamp >= ?")
        params.append(since.isoformat() if isinstance(since, datetime) else since)

    if until:
        conditions.append("plays.timestamp <= ?")
        params.append(until.isoformat() if isinstance(until, datetime) else until)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    # Determine ORDER BY clause
    if sort_by == "plays":
        order_clause = f"ORDER BY play_count {order.upper()}"
    elif sort_by == "name":
        order_clause = f"ORDER BY artist_name {order.upper()}"
    elif sort_by == "recent":
        order_clause = "ORDER BY last_played DESC"
    else:
        raise ValueError(f"Unknown sort_by: {sort_by}")

    query = f"""
        SELECT
            artists.id as artist_id,
            artists.name as artist_name,
            COUNT(*) as play_count,
            COUNT(DISTINCT tracks.id) as track_count,
            COUNT(DISTINCT albums.id) as album_count,
            MAX(plays.timestamp) as last_played
        FROM plays
        JOIN tracks ON plays.track_id = tracks.id
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
        {where_clause}
        GROUP BY artists.id, artists.name
        HAVING play_count >= ?
        {order_clause}
        LIMIT ?
    """
    params.extend([min_plays, limit])

    rows = db.execute(query, params).fetchall()
    return [
        {
            "artist_id": row[0],
            "artist_name": row[1],
            "play_count": row[2],
            "track_count": row[3],
            "album_count": row[4],
            "last_played": row[5],
        }
        for row in rows
    ]


def get_albums_by_search(
    db: sqlite_utils.Database,
    query: str,
    artist: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """
    Search albums by title with optional artist filter.

    Args:
        db: Database connection
        query: Search query for album title
        artist: Optional artist name filter
        limit: Maximum results

    Returns:
        List of dicts with album information
    """
    conditions = ["albums.title LIKE ?"]
    params = [f"%{query}%"]

    if artist:
        conditions.append("artists.name LIKE ?")
        params.append(f"%{artist}%")

    where_clause = "WHERE " + " AND ".join(conditions)

    sql = f"""
        SELECT
            albums.id as album_id,
            albums.title as album_title,
            artists.name as artist_name,
            COUNT(DISTINCT tracks.id) as track_count,
            COUNT(plays.timestamp) as play_count,
            MAX(plays.timestamp) as last_played
        FROM albums
        JOIN artists ON albums.artist_id = artists.id
        LEFT JOIN tracks ON tracks.album_id = albums.id
        LEFT JOIN plays ON plays.track_id = tracks.id
        {where_clause}
        GROUP BY albums.id, albums.title, artists.name
        ORDER BY play_count DESC, albums.title ASC
        LIMIT ?
    """
    params.append(limit)

    rows = db.execute(sql, params).fetchall()
    return [
        {
            "album_id": row[0],
            "album_title": row[1],
            "artist_name": row[2],
            "track_count": row[3],
            "play_count": row[4],
            "last_played": row[5],
        }
        for row in rows
    ]


def get_tracks_by_search(
    db: sqlite_utils.Database,
    query: str,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """
    Search tracks by title with optional filters.

    Args:
        db: Database connection
        query: Search query for track title
        artist: Optional artist name filter
        album: Optional album title filter
        limit: Maximum results

    Returns:
        List of dicts with track information
    """
    conditions = ["tracks.title LIKE ?"]
    params = [f"%{query}%"]

    if artist:
        conditions.append("artists.name LIKE ?")
        params.append(f"%{artist}%")

    if album:
        conditions.append("albums.title LIKE ?")
        params.append(f"%{album}%")

    where_clause = "WHERE " + " AND ".join(conditions)

    sql = f"""
        SELECT
            tracks.id as track_id,
            tracks.title as track_title,
            artists.name as artist_name,
            albums.title as album_title,
            COUNT(plays.timestamp) as play_count,
            MAX(plays.timestamp) as last_played
        FROM tracks
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
        LEFT JOIN plays ON plays.track_id = tracks.id
        {where_clause}
        GROUP BY tracks.id, tracks.title, artists.name, albums.title
        ORDER BY play_count DESC, tracks.title ASC
        LIMIT ?
    """
    params.append(limit)

    rows = db.execute(sql, params).fetchall()
    return [
        {
            "track_id": row[0],
            "track_title": row[1],
            "artist_name": row[2],
            "album_title": row[3],
            "play_count": row[4],
            "last_played": row[5],
        }
        for row in rows
    ]


def get_artists_by_search(
    db: sqlite_utils.Database,
    query: str,
    limit: int = 20,
) -> list[dict]:
    """
    Search artists by name using FTS5 and fuzzy matching.

    Args:
        db: Database connection
        query: Search query for artist name
        limit: Maximum results

    Returns:
        List of dicts with artist information
    """
    from rapidfuzz import fuzz

    # First try FTS5 search if the tracks_fts table exists
    if "tracks_fts" in db.table_names():
        # Use FTS5 to search artist names
        fts_sql = """
            SELECT DISTINCT
                tracks_fts.artist_id,
                tracks_fts.artist_name
            FROM tracks_fts
            WHERE tracks_fts MATCH ?
            LIMIT ?
        """
        # FTS5 MATCH query - search in artist_name field
        fts_query = f"artist_name:{query}*"
        fts_results = db.execute(fts_sql, [fts_query, limit * 3]).fetchall()

        # Get unique artist IDs from FTS results
        artist_ids = list(set(row[0] for row in fts_results))
    else:
        # Fallback to LIKE search if FTS5 not available
        artist_ids = []

    # If FTS5 didn't return enough results, supplement with LIKE search
    if len(artist_ids) < limit:
        like_sql = """
            SELECT DISTINCT artists.id
            FROM artists
            WHERE artists.name LIKE ?
            LIMIT ?
        """
        like_results = db.execute(like_sql, [f"%{query}%", limit * 2]).fetchall()
        like_ids = [row[0] for row in like_results]

        # Combine FTS and LIKE results, removing duplicates
        all_ids = artist_ids + [aid for aid in like_ids if aid not in artist_ids]
        artist_ids = all_ids[:limit * 2]

    if not artist_ids:
        return []

    # Get full artist details with play statistics
    placeholders = ",".join("?" * len(artist_ids))
    sql = f"""
        SELECT
            artists.id as artist_id,
            artists.name as artist_name,
            COUNT(DISTINCT albums.id) as album_count,
            COUNT(DISTINCT tracks.id) as track_count,
            COUNT(plays.timestamp) as play_count,
            MAX(plays.timestamp) as last_played
        FROM artists
        LEFT JOIN albums ON albums.artist_id = artists.id
        LEFT JOIN tracks ON tracks.album_id = albums.id
        LEFT JOIN plays ON plays.track_id = tracks.id
        WHERE artists.id IN ({placeholders})
        GROUP BY artists.id, artists.name
    """

    rows = db.execute(sql, artist_ids).fetchall()
    results = [
        {
            "artist_id": row[0],
            "artist_name": row[1],
            "album_count": row[2],
            "track_count": row[3],
            "play_count": row[4],
            "last_played": row[5],
        }
        for row in rows
    ]

    # Use rapidfuzz to score and rank results
    for result in results:
        result["fuzzy_score"] = fuzz.partial_ratio(query.lower(), result["artist_name"].lower())

    # Sort by fuzzy score (descending), then by play count
    results.sort(key=lambda x: (x["fuzzy_score"], x["play_count"]), reverse=True)

    return results[:limit]


def get_top_artists(
    db: sqlite_utils.Database,
    limit: int = 10,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> list[dict]:
    """
    Get top artists by play count with flexible time range.

    Args:
        db: Database connection
        limit: Number of artists to return
        since: Start date filter
        until: End date filter

    Returns:
        List of dicts with artist statistics including rank and percentage
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

    # First get total plays in period
    total_query = f"""
        SELECT COUNT(*) FROM plays {where_clause}
    """
    total_plays = db.execute(total_query, params).fetchone()[0]

    # Get top artists
    query = f"""
        SELECT
            artists.id as artist_id,
            artists.name as artist_name,
            COUNT(*) as play_count
        FROM plays
        JOIN tracks ON plays.track_id = tracks.id
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
        {where_clause}
        GROUP BY artists.id, artists.name
        ORDER BY play_count DESC
        LIMIT ?
    """
    params.append(limit)

    rows = db.execute(query, params).fetchall()

    # Calculate days in period for avg plays/day
    if since and until:
        days = (until - since).days or 1
    elif since:
        days = (datetime.now() - since).days or 1
    elif until:
        days = (until - datetime.now()).days or 1
    else:
        # All time - calculate from first to last play
        import dateutil.parser

        date_range = db.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM plays"
        ).fetchone()
        if date_range[0] and date_range[1]:
            first = dateutil.parser.parse(date_range[0]) if isinstance(date_range[0], str) else date_range[0]
            last = dateutil.parser.parse(date_range[1]) if isinstance(date_range[1], str) else date_range[1]
            days = (last - first).days or 1
        else:
            days = 1

    return [
        {
            "rank": i + 1,
            "artist_id": row[0],
            "artist_name": row[1],
            "play_count": row[2],
            "percentage": (row[2] / total_plays * 100) if total_plays > 0 else 0,
            "avg_plays_per_day": row[2] / days,
        }
        for i, row in enumerate(rows)
    ]


def get_top_tracks(
    db: sqlite_utils.Database,
    limit: int = 10,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    artist: Optional[str] = None,
) -> list[dict]:
    """
    Get top tracks by play count with flexible time range.

    Args:
        db: Database connection
        limit: Number of tracks to return
        since: Start date filter
        until: End date filter
        artist: Optional artist name filter

    Returns:
        List of dicts with track statistics including rank and percentage
    """
    conditions = []
    params = []

    if since:
        conditions.append("plays.timestamp >= ?")
        params.append(since.isoformat() if isinstance(since, datetime) else since)

    if until:
        conditions.append("plays.timestamp <= ?")
        params.append(until.isoformat() if isinstance(until, datetime) else until)

    if artist:
        conditions.append("artists.name LIKE ?")
        params.append(f"%{artist}%")

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    # First get total plays in period
    total_query = f"""
        SELECT COUNT(*) FROM plays
        JOIN tracks ON plays.track_id = tracks.id
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
        {where_clause}
    """
    total_plays = db.execute(total_query, params[:]).fetchone()[0]

    # Get top tracks
    query = f"""
        SELECT
            tracks.id as track_id,
            tracks.title as track_title,
            artists.name as artist_name,
            albums.title as album_title,
            COUNT(*) as play_count
        FROM plays
        JOIN tracks ON plays.track_id = tracks.id
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
        {where_clause}
        GROUP BY tracks.id, tracks.title, artists.name, albums.title
        ORDER BY play_count DESC
        LIMIT ?
    """
    params.append(limit)

    rows = db.execute(query, params).fetchall()
    return [
        {
            "rank": i + 1,
            "track_id": row[0],
            "track_title": row[1],
            "artist_name": row[2],
            "album_title": row[3],
            "play_count": row[4],
            "percentage": (row[4] / total_plays * 100) if total_plays > 0 else 0,
        }
        for i, row in enumerate(rows)
    ]


def get_artist_details(
    db: sqlite_utils.Database,
    artist_id: Optional[int] = None,
    artist_name: Optional[str] = None,
) -> Optional[dict]:
    """
    Get detailed information about a specific artist.

    Args:
        db: Database connection
        artist_id: Artist ID (exact match)
        artist_name: Artist name (partial match if no ID provided)

    Returns:
        Dict with artist details or None if not found
    """
    if artist_id:
        # Exact match by ID
        artist_row = db.execute(
            "SELECT id, name FROM artists WHERE id = ?",
            [artist_id],
        ).fetchone()
    elif artist_name:
        # Partial match by name
        matches = db.execute(
            "SELECT id, name FROM artists WHERE name LIKE ? LIMIT 2",
            [f"%{artist_name}%"],
        ).fetchall()

        if not matches:
            return None
        if len(matches) > 1:
            # Multiple matches - caller should handle disambiguation
            raise ValueError(f"Multiple artists match '{artist_name}'")

        artist_row = matches[0]
    else:
        raise ValueError("Either artist_id or artist_name must be provided")

    if not artist_row:
        return None

    artist_id = artist_row[0]
    artist_name = artist_row[1]

    # Get statistics
    stats = db.execute(
        """
        SELECT
            COUNT(*) as play_count,
            COUNT(DISTINCT tracks.id) as track_count,
            COUNT(DISTINCT albums.id) as album_count,
            MIN(plays.timestamp) as first_played,
            MAX(plays.timestamp) as last_played
        FROM plays
        JOIN tracks ON plays.track_id = tracks.id
        JOIN albums ON tracks.album_id = albums.id
        WHERE albums.artist_id = ?
        """,
        [artist_id],
    ).fetchone()

    return {
        "artist_id": artist_id,
        "artist_name": artist_name,
        "play_count": stats[0],
        "track_count": stats[1],
        "album_count": stats[2],
        "first_played": stats[3],
        "last_played": stats[4],
    }


def get_artist_top_tracks(
    db: sqlite_utils.Database,
    artist_id: int,
    limit: int = 10,
) -> list[dict]:
    """
    Get top tracks for a specific artist.

    Args:
        db: Database connection
        artist_id: Artist ID
        limit: Maximum number of tracks

    Returns:
        List of dicts with track information
    """
    query = """
        SELECT
            tracks.id as track_id,
            tracks.title as track_title,
            albums.title as album_title,
            COUNT(*) as play_count,
            MAX(plays.timestamp) as last_played
        FROM plays
        JOIN tracks ON plays.track_id = tracks.id
        JOIN albums ON tracks.album_id = albums.id
        WHERE albums.artist_id = ?
        GROUP BY tracks.id, tracks.title, albums.title
        ORDER BY play_count DESC
        LIMIT ?
    """

    rows = db.execute(query, [artist_id, limit]).fetchall()
    return [
        {
            "track_id": row[0],
            "track_title": row[1],
            "album_title": row[2],
            "play_count": row[3],
            "last_played": row[4],
        }
        for row in rows
    ]


def get_artist_albums(
    db: sqlite_utils.Database,
    artist_id: int,
) -> list[dict]:
    """
    Get all albums for a specific artist.

    Args:
        db: Database connection
        artist_id: Artist ID

    Returns:
        List of dicts with album information
    """
    query = """
        SELECT
            albums.id as album_id,
            albums.title as album_title,
            COUNT(DISTINCT tracks.id) as track_count,
            COUNT(plays.timestamp) as play_count,
            MAX(plays.timestamp) as last_played
        FROM albums
        LEFT JOIN tracks ON tracks.album_id = albums.id
        LEFT JOIN plays ON plays.track_id = tracks.id
        WHERE albums.artist_id = ?
        GROUP BY albums.id, albums.title
        ORDER BY play_count DESC
    """

    rows = db.execute(query, [artist_id]).fetchall()
    return [
        {
            "album_id": row[0],
            "album_title": row[1],
            "track_count": row[2],
            "play_count": row[3],
            "last_played": row[4],
        }
        for row in rows
    ]


def get_album_details(
    db: sqlite_utils.Database,
    album_id: Optional[int] = None,
    album_title: Optional[str] = None,
    artist_name: Optional[str] = None,
) -> Optional[dict]:
    """
    Get detailed information about a specific album.

    Args:
        db: Database connection
        album_id: Album ID (exact match)
        album_title: Album title (partial match if no ID provided)
        artist_name: Artist name for disambiguation

    Returns:
        Dict with album details or None if not found
    """
    if album_id:
        # Exact match by ID
        album_row = db.execute(
            """
            SELECT albums.id, albums.title, artists.name
            FROM albums
            JOIN artists ON albums.artist_id = artists.id
            WHERE albums.id = ?
            """,
            [album_id],
        ).fetchone()
    elif album_title:
        # Partial match by title
        if artist_name:
            matches = db.execute(
                """
                SELECT albums.id, albums.title, artists.name
                FROM albums
                JOIN artists ON albums.artist_id = artists.id
                WHERE albums.title LIKE ? AND artists.name LIKE ?
                LIMIT 2
                """,
                [f"%{album_title}%", f"%{artist_name}%"],
            ).fetchall()
        else:
            matches = db.execute(
                """
                SELECT albums.id, albums.title, artists.name
                FROM albums
                JOIN artists ON albums.artist_id = artists.id
                WHERE albums.title LIKE ?
                LIMIT 2
                """,
                [f"%{album_title}%"],
            ).fetchall()

        if not matches:
            return None
        if len(matches) > 1:
            raise ValueError(f"Multiple albums match '{album_title}'")

        album_row = matches[0]
    else:
        raise ValueError("Either album_id or album_title must be provided")

    if not album_row:
        return None

    album_id = album_row[0]
    album_title = album_row[1]
    artist_name = album_row[2]

    # Get statistics
    stats = db.execute(
        """
        SELECT
            COUNT(DISTINCT tracks.id) as track_count,
            COUNT(plays.timestamp) as play_count,
            MIN(plays.timestamp) as first_played,
            MAX(plays.timestamp) as last_played
        FROM albums
        LEFT JOIN tracks ON tracks.album_id = albums.id
        LEFT JOIN plays ON plays.track_id = tracks.id
        WHERE albums.id = ?
        """,
        [album_id],
    ).fetchone()

    return {
        "album_id": album_id,
        "album_title": album_title,
        "artist_name": artist_name,
        "track_count": stats[0],
        "play_count": stats[1],
        "first_played": stats[2],
        "last_played": stats[3],
    }


def get_album_tracks(
    db: sqlite_utils.Database,
    album_id: int,
) -> list[dict]:
    """
    Get all tracks for a specific album.

    Args:
        db: Database connection
        album_id: Album ID

    Returns:
        List of dicts with track information
    """
    query = """
        SELECT
            tracks.id as track_id,
            tracks.title as track_title,
            COUNT(plays.timestamp) as play_count,
            MAX(plays.timestamp) as last_played
        FROM tracks
        LEFT JOIN plays ON plays.track_id = tracks.id
        WHERE tracks.album_id = ?
        GROUP BY tracks.id, tracks.title
        ORDER BY tracks.id ASC
    """

    rows = db.execute(query, [album_id]).fetchall()
    return [
        {
            "track_id": row[0],
            "track_title": row[1],
            "play_count": row[2],
            "last_played": row[3],
        }
        for row in rows
    ]


def get_track_details(
    db: sqlite_utils.Database,
    track_id: Optional[int] = None,
    track_title: Optional[str] = None,
    artist_name: Optional[str] = None,
    album_title: Optional[str] = None,
) -> Optional[dict]:
    """
    Get detailed information about a specific track.

    Args:
        db: Database connection
        track_id: Track ID (exact match)
        track_title: Track title (partial match if no ID provided)
        artist_name: Artist name for disambiguation
        album_title: Album title for disambiguation

    Returns:
        Dict with track details or None if not found
    """
    if track_id:
        # Exact match by ID
        track_row = db.execute(
            """
            SELECT tracks.id, tracks.title, artists.name, albums.title
            FROM tracks
            JOIN albums ON tracks.album_id = albums.id
            JOIN artists ON albums.artist_id = artists.id
            WHERE tracks.id = ?
            """,
            [track_id],
        ).fetchone()
    elif track_title:
        # Build conditions
        conditions = ["tracks.title LIKE ?"]
        params = [f"%{track_title}%"]

        if artist_name:
            conditions.append("artists.name LIKE ?")
            params.append(f"%{artist_name}%")

        if album_title:
            conditions.append("albums.title LIKE ?")
            params.append(f"%{album_title}%")

        where_clause = " AND ".join(conditions)

        matches = db.execute(
            f"""
            SELECT tracks.id, tracks.title, artists.name, albums.title
            FROM tracks
            JOIN albums ON tracks.album_id = albums.id
            JOIN artists ON albums.artist_id = artists.id
            WHERE {where_clause}
            LIMIT 2
            """,
            params,
        ).fetchall()

        if not matches:
            return None
        if len(matches) > 1:
            raise ValueError(f"Multiple tracks match '{track_title}'")

        track_row = matches[0]
    else:
        raise ValueError("Either track_id or track_title must be provided")

    if not track_row:
        return None

    track_id = track_row[0]
    track_title = track_row[1]
    artist_name = track_row[2]
    album_title = track_row[3]

    # Get statistics
    stats = db.execute(
        """
        SELECT
            COUNT(*) as play_count,
            MIN(timestamp) as first_played,
            MAX(timestamp) as last_played
        FROM plays
        WHERE track_id = ?
        """,
        [track_id],
    ).fetchone()

    return {
        "track_id": track_id,
        "track_title": track_title,
        "artist_name": artist_name,
        "album_title": album_title,
        "play_count": stats[0],
        "first_played": stats[1],
        "last_played": stats[2],
    }


def get_track_plays(
    db: sqlite_utils.Database,
    track_id: int,
    limit: Optional[int] = None,
) -> list[dict]:
    """
    Get play history for a specific track.

    Args:
        db: Database connection
        track_id: Track ID
        limit: Optional limit on number of plays

    Returns:
        List of dicts with play timestamps
    """
    limit_clause = f"LIMIT {limit}" if limit else ""

    query = f"""
        SELECT timestamp
        FROM plays
        WHERE track_id = ?
        ORDER BY timestamp DESC
        {limit_clause}
    """

    rows = db.execute(query, [track_id]).fetchall()
    return [{"timestamp": row[0]} for row in rows]
