"""
Track browsing TUI for scrobbledb.

This module provides an interactive terminal user interface (TUI) for browsing
scrobbles using Textual. It allows users to explore their listening history
without requiring a search term.
"""

from typing import Optional, List, Dict, Any
from sqlite_utils import Database


class ScrobbleDataAdapter:
    """
    Data adapter for retrieving scrobble data from SQLite database.

    Provides paginated access to tracks with play statistics, filtering,
    and sorting capabilities.
    """

    # Available columns for display
    COLUMNS = {
        "artist": "Artist",
        "album": "Album",
        "track": "Track",
        "plays": "Plays",
        "last_played": "Last Played",
    }

    # Available filter column options
    FILTER_COLUMNS = {
        "all": ("All", ["artists.name", "albums.title", "tracks.title"]),
        "artist": ("Artist", ["artists.name"]),
        "album": ("Album", ["albums.title"]),
        "track": ("Track", ["tracks.title"]),
    }

    # Available sort options
    SORT_OPTIONS = {
        "plays_desc": ("play_count", "DESC"),
        "plays_asc": ("play_count", "ASC"),
        "last_played_desc": ("last_played", "DESC"),
        "last_played_asc": ("last_played", "ASC"),
        "artist_asc": ("artist_name", "ASC"),
        "artist_desc": ("artist_name", "DESC"),
        "track_asc": ("track_title", "ASC"),
        "track_desc": ("track_title", "DESC"),
        "album_asc": ("album_title", "ASC"),
        "album_desc": ("album_title", "DESC"),
    }

    def __init__(self, db: Database):
        """
        Initialize the data adapter.

        Args:
            db: sqlite_utils Database instance
        """
        self.db = db

    def _build_filter_where_clause(
        self, filter_text: str, filter_column: str = "all"
    ) -> tuple:
        """
        Build WHERE clause for filtering.

        Args:
            filter_text: Filter string to search for
            filter_column: Column(s) to filter on ('all', 'artist', 'album', 'track')

        Returns:
            Tuple of (where_clause_sql, params_list)

        Security:
            - filter_column is validated against FILTER_COLUMNS whitelist
            - filter_text is passed as a parameterized query value (never interpolated)
            - Column names come from predefined constants, not user input
        """
        # Validate filter_column against whitelist to prevent SQL injection
        if filter_column not in self.FILTER_COLUMNS:
            filter_column = "all"

        _, columns = self.FILTER_COLUMNS[filter_column]
        like_pattern = f"%{filter_text}%"

        # Column names are from FILTER_COLUMNS whitelist, safe to interpolate
        # filter_text is passed as parameter (?) to prevent injection
        conditions = [f"{col} LIKE ?" for col in columns]
        where_clause = " OR ".join(conditions)
        params = [like_pattern] * len(columns)

        return where_clause, params

    def get_total_count(
        self, filter_text: Optional[str] = None, filter_column: str = "all"
    ) -> int:
        """
        Get total count of tracks, optionally filtered.

        Args:
            filter_text: Optional filter string to match against specified column(s)
            filter_column: Column to filter on ('all', 'artist', 'album', 'track')

        Returns:
            Total count of matching tracks, or 0 if database is empty/uninitialized
        """
        # Check if required tables exist
        table_names = self.db.table_names()

        if filter_text:
            # For filtered queries, we need tracks, albums, and artists tables
            required_tables = ["tracks", "albums", "artists"]
            if not all(table in table_names for table in required_tables):
                return 0

            try:
                where_clause, params = self._build_filter_where_clause(
                    filter_text, filter_column
                )
                sql = f"""
                    SELECT COUNT(DISTINCT tracks.id)
                    FROM tracks
                    JOIN albums ON tracks.album_id = albums.id
                    JOIN artists ON albums.artist_id = artists.id
                    WHERE {where_clause}
                """
                result = self.db.execute(sql, params).fetchone()
            except Exception:
                # Handle any SQL errors gracefully
                return 0
        else:
            # For simple count, we only need tracks table
            if "tracks" not in table_names:
                return 0

            try:
                sql = "SELECT COUNT(*) FROM tracks"
                result = self.db.execute(sql).fetchone()
            except Exception:
                # Handle any SQL errors gracefully
                return 0

        return result[0] if result else 0

    def get_tracks(
        self,
        offset: int = 0,
        limit: int = 50,
        filter_text: Optional[str] = None,
        filter_column: str = "all",
        sort_by: str = "plays_desc",
    ) -> List[Dict[str, Any]]:
        """
        Get paginated list of tracks with play statistics.

        Args:
            offset: Number of records to skip (must be non-negative integer)
            limit: Maximum number of records to return (must be positive integer)
            filter_text: Optional filter string to match against specified column(s)
            filter_column: Column to filter on ('all', 'artist', 'album', 'track')
            sort_by: Sort option key from SORT_OPTIONS

        Returns:
            List of track dictionaries with keys:
            - artist_name, album_title, track_title
            - play_count, last_played
            - track_id, album_id, artist_id

        Security:
            - offset/limit: Validated and constrained to safe integer ranges
            - filter_text: Passed as parameterized query value
            - filter_column: Validated against FILTER_COLUMNS whitelist
            - sort_by: Validated against SORT_OPTIONS whitelist
        """
        # Validate and sanitize offset and limit to prevent SQL injection
        # These are typed as int, but ensure they are valid integers
        try:
            offset = max(0, int(offset))  # Ensure non-negative
            limit = max(1, min(int(limit), 1000))  # Ensure 1-1000 range
        except (ValueError, TypeError):
            offset = 0
            limit = 50

        # Get sort column and direction from whitelist only
        # This prevents SQL injection since values come from predefined dict
        sort_column, sort_direction = self.SORT_OPTIONS.get(
            sort_by, ("play_count", "DESC")
        )
        # Extra validation: ensure values are in expected set
        if sort_direction not in ("ASC", "DESC"):
            sort_direction = "DESC"

        # Check if plays table exists
        has_plays = "plays" in self.db.table_names()

        if has_plays:
            base_sql = """
                SELECT
                    artists.name as artist_name,
                    albums.title as album_title,
                    tracks.title as track_title,
                    COUNT(plays.timestamp) as play_count,
                    MAX(plays.timestamp) as last_played,
                    tracks.id as track_id,
                    albums.id as album_id,
                    artists.id as artist_id
                FROM tracks
                JOIN albums ON tracks.album_id = albums.id
                JOIN artists ON albums.artist_id = artists.id
                LEFT JOIN plays ON tracks.id = plays.track_id
            """
        else:
            base_sql = """
                SELECT
                    artists.name as artist_name,
                    albums.title as album_title,
                    tracks.title as track_title,
                    0 as play_count,
                    NULL as last_played,
                    tracks.id as track_id,
                    albums.id as album_id,
                    artists.id as artist_id
                FROM tracks
                JOIN albums ON tracks.album_id = albums.id
                JOIN artists ON albums.artist_id = artists.id
            """

        params = []

        # Add filter condition using the helper method
        if filter_text:
            where_clause, filter_params = self._build_filter_where_clause(
                filter_text, filter_column
            )
            base_sql += f"""
                WHERE {where_clause}
            """
            params.extend(filter_params)

        # Add GROUP BY for play statistics
        base_sql += """
            GROUP BY tracks.id, albums.id, artists.id
        """

        # Add ORDER BY - sort_column and sort_direction are from SORT_OPTIONS whitelist
        # and validated above, so they are safe to interpolate
        base_sql += f" ORDER BY {sort_column} {sort_direction}"

        # Handle NULL values in sorting (put them at the end for DESC, beginning for ASC)
        if sort_column == "last_played":
            if sort_direction == "DESC":
                base_sql = base_sql.replace(
                    f"ORDER BY {sort_column} {sort_direction}",
                    f"ORDER BY {sort_column} IS NULL, {sort_column} {sort_direction}"
                )
            else:
                base_sql = base_sql.replace(
                    f"ORDER BY {sort_column} {sort_direction}",
                    f"ORDER BY {sort_column} IS NOT NULL, {sort_column} {sort_direction}"
                )

        # Add pagination - limit and offset are validated integers above
        base_sql += f" LIMIT {limit} OFFSET {offset}"

        results = self.db.execute(base_sql, params).fetchall()

        return [
            {
                "artist_name": row[0],
                "album_title": row[1],
                "track_title": row[2],
                "play_count": row[3],
                "last_played": row[4],
                "track_id": row[5],
                "album_id": row[6],
                "artist_id": row[7],
            }
            for row in results
        ]

    def get_artists(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get list of artists with track counts.

        Args:
            limit: Maximum number of artists to return

        Returns:
            List of artist dictionaries
        """
        sql = """
            SELECT
                artists.id,
                artists.name,
                COUNT(DISTINCT tracks.id) as track_count
            FROM artists
            JOIN albums ON artists.id = albums.artist_id
            JOIN tracks ON albums.id = tracks.album_id
            GROUP BY artists.id
            ORDER BY track_count DESC
            LIMIT ?
        """
        results = self.db.execute(sql, [limit]).fetchall()
        return [
            {"id": row[0], "name": row[1], "track_count": row[2]}
            for row in results
        ]

    def get_albums(self, artist_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get list of albums, optionally filtered by artist.

        Args:
            artist_id: Optional artist ID to filter by
            limit: Maximum number of albums to return

        Returns:
            List of album dictionaries
        """
        if artist_id:
            sql = """
                SELECT
                    albums.id,
                    albums.title,
                    artists.name as artist_name,
                    COUNT(DISTINCT tracks.id) as track_count
                FROM albums
                JOIN artists ON albums.artist_id = artists.id
                JOIN tracks ON albums.id = tracks.album_id
                WHERE artists.id = ?
                GROUP BY albums.id
                ORDER BY albums.title ASC
                LIMIT ?
            """
            params = [artist_id, limit]
        else:
            sql = """
                SELECT
                    albums.id,
                    albums.title,
                    artists.name as artist_name,
                    COUNT(DISTINCT tracks.id) as track_count
                FROM albums
                JOIN artists ON albums.artist_id = artists.id
                JOIN tracks ON albums.id = tracks.album_id
                GROUP BY albums.id
                ORDER BY track_count DESC
                LIMIT ?
            """
            params = [limit]

        results = self.db.execute(sql, params).fetchall()
        return [
            {
                "id": row[0],
                "title": row[1],
                "artist_name": row[2],
                "track_count": row[3],
            }
            for row in results
        ]
