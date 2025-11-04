import datetime as dt
import hashlib
from typing import Dict
from xml.dom.minidom import Node

import pylast
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

    tracks_yielded = 0

    while True:
        params["page"] = page
        doc = user._request("user.getRecentTracks", cacheable=True, params=params)
        main = pylast.cleanup_nodes(doc).documentElement.childNodes[0]
        for node in main.childNodes:
            if node.nodeType != Node.TEXT_NODE:
                yield _extract_track_data(node)
                tracks_yielded += 1
                if limit and tracks_yielded >= limit:
                    return

        page += 1
        total_pages = int(main.getAttribute("totalPages"))
        if page > total_pages:
            break


def _extract_track_data(track: Node):
    track_mbid = pylast._extract(track, "mbid")
    track_title = pylast._extract(track, "name")
    timestamp = dt.datetime.fromtimestamp(
        int(track.getElementsByTagName("date")[0].getAttribute("uts"))
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
