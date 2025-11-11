import datetime as dt
from datetime import timezone
import hashlib
import json
import random
import csv
from typing import Dict, List, Optional, Iterator, Tuple
from xml.dom.minidom import Node

import pylast
import dateutil.parser
from loguru import logger
from sqlite_utils import Database


def recent_tracks(user: pylast.User, since: dt.datetime, limit: int = None):
    """
    This is similar to pylast.User.get_recent_tracks
    (https://github.com/pylast/pylast/blob/master/src/pylast/__init__.py#L2362),
    with a few specific additions to make the -to-sqlite part of this work
    better:

        1. Pulls the mbids from the recent tracks response, to get primary
           keys for artist/albums/tracks without having to make subsequent
           calls to the info API (which just slows things down)

        2. Returns dicts ready for upsert'ing with sqlite-utils.

        3. Converts the timestamp to a datetime.

        4. It's a generator so that the caller can display a progress bar.

        5. Accepts an optional limit parameter to cap the number of tracks returned.
    """

    page = 1
    params = dict(user._get_params(), limit=200)
    if since:
        params["from"] = int(since.timestamp())
        logger.info(f"Fetching tracks since {since.isoformat()}")
    else:
        logger.info("Fetching all available tracks")

    if limit:
        logger.info(f"Limiting to {limit} tracks")

    tracks_yielded = 0
    total_pages = None

    while True:
        params["page"] = page
        logger.info(f"Fetching page {page}" + (f" of {total_pages}" if total_pages else ""))
        doc = user._request("user.getRecentTracks", cacheable=True, params=params)
        main = pylast.cleanup_nodes(doc).documentElement.childNodes[0]

        # Get total pages on first request
        if total_pages is None:
            total_pages = int(main.getAttribute("totalPages"))
            logger.info(f"Total pages to fetch: {total_pages}")

        tracks_in_page = 0
        for node in main.childNodes:
            if node.nodeType != Node.TEXT_NODE:
                yield _extract_track_data(node)
                tracks_yielded += 1
                tracks_in_page += 1
                if limit and tracks_yielded >= limit:
                    logger.info(f"Reached limit of {limit} tracks")
                    return

        logger.info(f"Yielded {tracks_in_page} tracks from page {page} (total: {tracks_yielded})")

        page += 1
        if page > total_pages:
            logger.info(f"Completed fetching all {tracks_yielded} tracks")
            break


def _extract_track_data(track: Node):
    track_mbid = pylast._extract(track, "mbid")
    track_title = pylast._extract(track, "name")
    timestamp = dt.datetime.fromtimestamp(
        int(track.getElementsByTagName("date")[0].getAttribute("uts")),
        tz=timezone.utc
    )
    artist_name = pylast._extract(track, "artist")
    artist_mbid = track.getElementsByTagName("artist")[0].getAttribute("mbid")
    album_title = pylast._extract(track, "album")
    album_mbid = track.getElementsByTagName("album")[0].getAttribute("mbid")

    # TODO: could call track/album/artist.getInfo here, and get more info?

    # Handle missing titles
    if album_title is None:
        album_title = "(unknown album)"

    # If we don't have mbids, synthesize them
    if not artist_mbid:
        artist_mbid = "md5:" + hashlib.md5(artist_name.encode("utf8")).hexdigest()
    if not album_mbid:
        h = hashlib.md5()
        h.update(artist_mbid.encode("utf8"))
        h.update(album_title.encode("utf8"))
        album_mbid = "md5:" + h.hexdigest()
    if not track_mbid:
        h = hashlib.md5()
        h.update(album_mbid.encode("utf8"))
        h.update(track_title.encode("utf8"))
        track_mbid = "md5:" + h.hexdigest()

    return {
        "artist": {"id": artist_mbid, "name": artist_name},
        "album": {"id": album_mbid, "title": album_title, "artist_id": artist_mbid},
        "track": {"id": track_mbid, "album_id": album_mbid, "title": track_title},
        "play": {"track_id": track_mbid, "timestamp": timestamp},
    }


def get_network(name: str, key: str, secret: str, session_key: str = None):
    cls = {"lastfm": pylast.LastFMNetwork, "librefm": pylast.LibreFMNetwork}[name]
    if session_key:
        network = cls(api_key=key, api_secret=secret, session_key=session_key)
    else:
        network = cls(api_key=key, api_secret=secret)
    network.enable_caching()
    network.enable_rate_limit()
    return network


def save_artist(db: Database, data: Dict):
    db["artists"].upsert(data, pk="id", column_order=["id", "name"], not_null=["name"])


def save_album(db: Database, data: Dict):
    db["albums"].upsert(
        data, pk="id", foreign_keys=["artist_id"], not_null=["id", "artist_id", "title"]
    )


def save_track(db: Database, data: Dict):
    db["tracks"].upsert(
        data, pk="id", foreign_keys=["album_id"], not_null=["id", "album_id", "title"]
    )


def save_play(db: Database, data: Dict):
    db["plays"].upsert(data, pk=["timestamp", "track_id"], foreign_keys=["track_id"])


# Field name aliases for flexible input parsing
FIELD_ALIASES = {
    'timestamp': ['timestamp', 'time', 'played_at', 'date', 'datetime', 'when'],
    'artist': ['artist', 'artist_name', 'artistname'],
    'album': ['album', 'album_title', 'albumtitle', 'album_name'],
    'track': ['track', 'track_title', 'tracktitle', 'song', 'title', 'track_name', 'name'],
    'artist_mbid': ['artist_mbid', 'artist_id'],
    'album_mbid': ['album_mbid', 'album_id'],
    'track_mbid': ['track_mbid', 'track_id'],
}

# Timestamp formats to try when parsing
TIMESTAMP_FORMATS = [
    # ISO 8601 / RFC 3339
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S.%fZ",
    # Common formats
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    # Date only (assumes 00:00:00)
    "%Y-%m-%d",
    "%Y/%m/%d",
]


def normalize_field_name(field: str) -> str:
    """Normalize field name to canonical form using aliases."""
    field_lower = field.lower().strip()
    for canonical, aliases in FIELD_ALIASES.items():
        if field_lower in aliases:
            return canonical
    return field  # Unknown field, keep as-is


def parse_timestamp(timestamp_str: str) -> dt.datetime:
    """
    Parse timestamp with support for multiple formats.

    Supports Unix timestamps, ISO 8601, and common date formats.
    Falls back to dateutil.parser for maximum compatibility.

    All returned timestamps are timezone-aware and in UTC.
    """
    # Try Unix timestamp first (interpret as UTC)
    try:
        return dt.datetime.fromtimestamp(float(timestamp_str), tz=timezone.utc)
    except (ValueError, TypeError):
        pass

    # Try known formats (assume UTC if no timezone specified)
    for fmt in TIMESTAMP_FORMATS:
        try:
            parsed = dt.datetime.strptime(timestamp_str, fmt)
            # If naive, assume UTC
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            # If timezone-aware, convert to UTC
            return parsed.astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue

    # Fallback to dateutil.parser
    try:
        parsed = dateutil.parser.parse(timestamp_str)
        # If naive, assume UTC
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        # If timezone-aware, convert to UTC
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"Unable to parse timestamp: {timestamp_str}")


def synthesize_mbids(artist_name: str, album_title: str, track_title: str) -> Tuple[str, str, str]:
    """
    Generate MD5-based MBIDs for artist, album, and track.

    Uses the same logic as _extract_track_data to ensure consistency.

    Returns:
        Tuple of (artist_mbid, album_mbid, track_mbid)
    """
    # Generate artist MBID
    artist_mbid = "md5:" + hashlib.md5(artist_name.encode("utf8")).hexdigest()

    # Generate album MBID
    h = hashlib.md5()
    h.update(artist_mbid.encode("utf8"))
    h.update(album_title.encode("utf8"))
    album_mbid = "md5:" + h.hexdigest()

    # Generate track MBID
    h = hashlib.md5()
    h.update(album_mbid.encode("utf8"))
    h.update(track_title.encode("utf8"))
    track_mbid = "md5:" + h.hexdigest()

    return artist_mbid, album_mbid, track_mbid


def parse_scrobble_dict(data: Dict, line_num: int = None) -> Dict:
    """
    Parse a dictionary (from JSON or CSV) into scrobble data structure.

    Args:
        data: Dictionary with scrobble fields
        line_num: Optional line number for error messages

    Returns:
        Dictionary with 'artist', 'album', 'track', 'play' keys

    Raises:
        ValueError: If required fields are missing or invalid
    """
    # Normalize field names
    normalized = {}
    for key, value in data.items():
        norm_key = normalize_field_name(key)
        normalized[norm_key] = value

    # Build error prefix for messages
    error_prefix = f"Line {line_num}: " if line_num else ""

    # Check required fields
    required_fields = ['timestamp', 'artist', 'track']
    for field in required_fields:
        if field not in normalized or not normalized[field]:
            raise ValueError(f"{error_prefix}Missing required field: {field}")

    # Extract and parse fields
    try:
        timestamp = parse_timestamp(str(normalized['timestamp']))
    except ValueError as e:
        raise ValueError(f"{error_prefix}Invalid timestamp: {e}")

    artist_name = str(normalized['artist']).strip()
    track_title = str(normalized['track']).strip()
    album_title = str(normalized.get('album', '(unknown album)')).strip()

    if not album_title:
        album_title = "(unknown album)"

    # Get or synthesize MBIDs
    artist_mbid = normalized.get('artist_mbid', '')
    album_mbid = normalized.get('album_mbid', '')
    track_mbid = normalized.get('track_mbid', '')

    if not artist_mbid or not album_mbid or not track_mbid:
        synth_artist_mbid, synth_album_mbid, synth_track_mbid = synthesize_mbids(
            artist_name, album_title, track_title
        )
        artist_mbid = artist_mbid or synth_artist_mbid
        album_mbid = album_mbid or synth_album_mbid
        track_mbid = track_mbid or synth_track_mbid

    # Return same structure as _extract_track_data
    return {
        "artist": {"id": artist_mbid, "name": artist_name},
        "album": {"id": album_mbid, "title": album_title, "artist_id": artist_mbid},
        "track": {"id": track_mbid, "album_id": album_mbid, "title": track_title},
        "play": {"track_id": track_mbid, "timestamp": timestamp},
    }


def parse_scrobble_jsonl(line: str, line_num: int = None) -> Dict:
    """
    Parse a single JSON line into scrobble data structure.

    Args:
        line: JSON string
        line_num: Optional line number for error messages

    Returns:
        Scrobble data dictionary

    Raises:
        ValueError: If JSON is invalid or required fields missing
    """
    error_prefix = f"Line {line_num}: " if line_num else ""

    try:
        data = json.loads(line)
    except json.JSONDecodeError as e:
        raise ValueError(f"{error_prefix}Invalid JSON: {e}")

    if not isinstance(data, dict):
        raise ValueError(f"{error_prefix}Expected JSON object, got {type(data).__name__}")

    return parse_scrobble_dict(data, line_num)


def detect_format(first_line: str) -> str:
    """
    Detect input format from first line.

    Returns:
        'jsonl', 'csv', or 'tsv'
    """
    stripped = first_line.strip()

    # Try JSON
    if stripped.startswith('{'):
        try:
            json.loads(stripped)
            return 'jsonl'
        except (json.JSONDecodeError, ValueError):
            pass

    # Check for TSV (has tabs)
    if '\t' in stripped:
        return 'tsv'

    # Check for CSV (has commas)
    if ',' in stripped:
        return 'csv'

    # Default to JSONL
    return 'jsonl'


def add_scrobbles(
    db: Database,
    scrobbles_iter: Iterator[Dict],
    skip_errors: bool = False,
    limit: Optional[int] = None,
    sample: Optional[float] = None,
    seed: Optional[int] = None,
    no_duplicates: bool = False,
) -> Dict:
    """
    Add scrobbles to database with optional sampling and limiting.

    Args:
        db: Database instance
        scrobbles_iter: Iterator of scrobble dictionaries
        skip_errors: Continue processing on errors
        limit: Maximum number of records to add
        sample: Probability (0.0-1.0) to include each record
        seed: Random seed for reproducible sampling
        no_duplicates: Skip scrobbles with duplicate timestamp+track

    Returns:
        Statistics dictionary with:
        - total_processed: Total records processed
        - sampled: Records selected by sampling (if sampling enabled)
        - added: Records successfully added
        - skipped: Records skipped (duplicates)
        - errors: List of error messages
        - limit_reached: Whether limit was hit
    """
    # Set random seed if provided
    if seed is not None:
        random.seed(seed)

    stats = {
        'total_processed': 0,
        'sampled': 0,
        'added': 0,
        'skipped': 0,
        'errors': [],
        'limit_reached': False,
    }

    # Get existing plays for duplicate detection
    existing_plays = set()
    if no_duplicates and "plays" in db.table_names():
        for row in db["plays"].rows:
            existing_plays.add((str(row["timestamp"]), row["track_id"]))

    for scrobble in scrobbles_iter:
        stats['total_processed'] += 1

        # Apply sampling if enabled
        if sample is not None:
            if random.random() >= sample:
                continue  # Skip this record
            stats['sampled'] += 1

        # Check limit
        if limit is not None and stats['added'] >= limit:
            stats['limit_reached'] = True
            break

        try:
            # Check for duplicate
            # Use isoformat() to match database storage format
            timestamp_str = scrobble["play"]["timestamp"].isoformat() if isinstance(scrobble["play"]["timestamp"], dt.datetime) else str(scrobble["play"]["timestamp"])
            track_id = scrobble["track"]["id"]

            if no_duplicates and (timestamp_str, track_id) in existing_plays:
                stats['skipped'] += 1
                continue

            # Add to database
            save_artist(db, scrobble["artist"])
            save_album(db, scrobble["album"])
            save_track(db, scrobble["track"])
            save_play(db, scrobble["play"])

            # Track as existing for duplicate detection
            if no_duplicates:
                existing_plays.add((timestamp_str, track_id))

            stats['added'] += 1

        except Exception as e:
            error_msg = str(e)
            stats['errors'].append(error_msg)

            if not skip_errors:
                raise

    return stats


def setup_fts5(db: Database):
    """
    Set up FTS5 full-text search indexing for artists, albums, and tracks.

    Creates a virtual FTS5 table and triggers to keep it synchronized with
    the main tables. This should be called after the database schema is created.
    """
    # Create FTS5 virtual table - stores its own copy of the indexed content
    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts USING fts5(
            artist_name,
            album_title,
            track_title,
            artist_id UNINDEXED,
            album_id UNINDEXED,
            track_id UNINDEXED
        )
    """)

    # Create triggers to keep FTS5 index in sync when data is inserted
    # Only create triggers if the source tables exist
    table_names = db.table_names()

    if "artists" in table_names:
        # Trigger for artist inserts/updates
        db.execute("""
            CREATE TRIGGER IF NOT EXISTS artists_ai AFTER INSERT ON artists BEGIN
                DELETE FROM tracks_fts WHERE artist_id = new.id;
                INSERT INTO tracks_fts (artist_name, album_title, track_title, artist_id, album_id, track_id)
                SELECT new.name, albums.title, tracks.title, new.id, albums.id, tracks.id
                FROM albums JOIN tracks ON albums.id = tracks.album_id
                WHERE albums.artist_id = new.id;
            END;
        """)

        db.execute("""
            CREATE TRIGGER IF NOT EXISTS artists_au AFTER UPDATE ON artists BEGIN
                DELETE FROM tracks_fts WHERE artist_id = new.id;
                INSERT INTO tracks_fts (artist_name, album_title, track_title, artist_id, album_id, track_id)
                SELECT new.name, albums.title, tracks.title, new.id, albums.id, tracks.id
                FROM albums JOIN tracks ON albums.id = tracks.album_id
                WHERE albums.artist_id = new.id;
            END;
        """)

        db.execute("""
            CREATE TRIGGER IF NOT EXISTS artists_ad AFTER DELETE ON artists BEGIN
                DELETE FROM tracks_fts WHERE artist_id = old.id;
            END;
        """)

    if "albums" in table_names:
        # Trigger for album inserts/updates
        db.execute("""
            CREATE TRIGGER IF NOT EXISTS albums_ai AFTER INSERT ON albums BEGIN
                DELETE FROM tracks_fts WHERE album_id = new.id;
                INSERT INTO tracks_fts (artist_name, album_title, track_title, artist_id, album_id, track_id)
                SELECT artists.name, new.title, tracks.title, new.artist_id, new.id, tracks.id
                FROM artists JOIN tracks ON tracks.album_id = new.id
                WHERE artists.id = new.artist_id;
            END;
        """)

        db.execute("""
            CREATE TRIGGER IF NOT EXISTS albums_au AFTER UPDATE ON albums BEGIN
                DELETE FROM tracks_fts WHERE album_id = new.id;
                INSERT INTO tracks_fts (artist_name, album_title, track_title, artist_id, album_id, track_id)
                SELECT artists.name, new.title, tracks.title, new.artist_id, new.id, tracks.id
                FROM artists JOIN tracks ON tracks.album_id = new.id
                WHERE artists.id = new.artist_id;
            END;
        """)

        db.execute("""
            CREATE TRIGGER IF NOT EXISTS albums_ad AFTER DELETE ON albums BEGIN
                DELETE FROM tracks_fts WHERE album_id = old.id;
            END;
        """)

    if "tracks" in table_names:
        # Trigger for track inserts/updates
        db.execute("""
            CREATE TRIGGER IF NOT EXISTS tracks_ai AFTER INSERT ON tracks BEGIN
                INSERT INTO tracks_fts (artist_name, album_title, track_title, artist_id, album_id, track_id)
                SELECT artists.name, albums.title, new.title, artists.id, albums.id, new.id
                FROM albums JOIN artists ON albums.artist_id = artists.id
                WHERE albums.id = new.album_id;
            END;
        """)

        db.execute("""
            CREATE TRIGGER IF NOT EXISTS tracks_au AFTER UPDATE ON tracks BEGIN
                DELETE FROM tracks_fts WHERE track_id = new.id;
                INSERT INTO tracks_fts (artist_name, album_title, track_title, artist_id, album_id, track_id)
                SELECT artists.name, albums.title, new.title, artists.id, albums.id, new.id
                FROM albums JOIN artists ON albums.artist_id = artists.id
                WHERE albums.id = new.album_id;
            END;
        """)

        db.execute("""
            CREATE TRIGGER IF NOT EXISTS tracks_ad AFTER DELETE ON tracks BEGIN
                DELETE FROM tracks_fts WHERE track_id = old.id;
            END;
        """)


def rebuild_fts5(db: Database):
    """
    Rebuild the FTS5 index from existing data.

    This should be called after setup_fts5() to populate the index with
    existing data, or to rebuild the index if it becomes corrupted.
    """
    # Clear existing FTS5 data
    db.execute("DELETE FROM tracks_fts")

    # Populate FTS5 table with existing data
    db.execute("""
        INSERT INTO tracks_fts (artist_name, album_title, track_title, artist_id, album_id, track_id)
        SELECT artists.name, albums.title, tracks.title, artists.id, albums.id, tracks.id
        FROM tracks
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
    """)


def search_tracks(db: Database, query: str, limit: int = None):
    """
    Search for tracks using FTS5 full-text search.

    Args:
        db: Database instance
        query: Search query string
        limit: Maximum number of results to return (optional)

    Returns:
        List of dictionaries containing track information with keys:
        - track_id, track_title
        - album_id, album_title
        - artist_id, artist_name
        - play_count (number of times played)
        - last_played (most recent play timestamp)
        - rank (search relevance score)
    """
    # Check if plays table exists to include play statistics
    has_plays = "plays" in db.table_names()

    if has_plays:
        sql = """
            SELECT
                tracks_fts.track_id,
                tracks_fts.track_title,
                tracks_fts.album_id,
                tracks_fts.album_title,
                tracks_fts.artist_id,
                tracks_fts.artist_name,
                COUNT(plays.timestamp) as play_count,
                MAX(plays.timestamp) as last_played,
                tracks_fts.rank
            FROM tracks_fts
            LEFT JOIN plays ON tracks_fts.track_id = plays.track_id
            WHERE tracks_fts MATCH ?
            GROUP BY tracks_fts.track_id, tracks_fts.album_id, tracks_fts.artist_id
            ORDER BY tracks_fts.rank, play_count DESC
        """
    else:
        sql = """
            SELECT
                tracks_fts.track_id,
                tracks_fts.track_title,
                tracks_fts.album_id,
                tracks_fts.album_title,
                tracks_fts.artist_id,
                tracks_fts.artist_name,
                0 as play_count,
                NULL as last_played,
                tracks_fts.rank
            FROM tracks_fts
            WHERE tracks_fts MATCH ?
            ORDER BY tracks_fts.rank
        """

    if limit:
        sql += f" LIMIT {limit}"

    results = db.execute(sql, [query]).fetchall()

    # Convert to list of dictionaries
    return [
        {
            "track_id": row[0],
            "track_title": row[1],
            "album_id": row[2],
            "album_title": row[3],
            "artist_id": row[4],
            "artist_name": row[5],
            "play_count": row[6],
            "last_played": row[7],
            "rank": row[8],
        }
        for row in results
    ]
