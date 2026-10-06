"""
The analytics indexes: the secondary indexes scrobbledb's rollups need.

A scrobbledb database carries no non-PK indexes by default, so every top-N and
rollup is a full three-way join. These four make those queries cheap. They are
created only on request, by `scrobbledb index --analytics`, and never as a side
effect of anything else -- `serve` in particular detects their absence and says
so, because its read-only guarantee is worth more than a faster first query
(design D10).

This module holds the one definition both sides read: the command that creates
the indexes and the server that checks for them.
"""

import sqlite3

#: Index name -> the statement that creates it. Every statement is
#: `IF NOT EXISTS`, so creation is idempotent by construction.
ANALYTICS_INDEXES = {
    "idx_plays_track_id": (
        "CREATE INDEX IF NOT EXISTS idx_plays_track_id ON plays(track_id)"
    ),
    "idx_tracks_album_id": (
        "CREATE INDEX IF NOT EXISTS idx_tracks_album_id ON tracks(album_id)"
    ),
    "idx_albums_artist_id": (
        "CREATE INDEX IF NOT EXISTS idx_albums_artist_id ON albums(artist_id)"
    ),
    "idx_plays_month": (
        "CREATE INDEX IF NOT EXISTS idx_plays_month"
        " ON plays(strftime('%Y-%m', timestamp))"
    ),
}


#: The tables the indexes above sit on. All four have to exist before any index
#: can be created, and a database lacking them has nothing to index yet.
SCROBBLE_TABLES = ("artists", "albums", "tracks", "plays")


def missing_analytics_indexes(conn: sqlite3.Connection) -> list[str]:
    """The analytics indexes absent from `conn`'s database, in definition order."""
    present = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    return [name for name in ANALYTICS_INDEXES if name not in present]


def missing_scrobble_tables(conn: sqlite3.Connection) -> list[str]:
    """The scrobble tables `conn`'s database does not have yet."""
    present = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    return [name for name in SCROBBLE_TABLES if name not in present]


def create_analytics_indexes(conn: sqlite3.Connection) -> tuple[list[str], list[str]]:
    """
    Create whichever analytics indexes are missing; return `(created, existing)`.

    Only indexes are written -- no row is touched -- and an index that already
    exists is left alone, so a second call creates nothing.
    """
    missing = missing_analytics_indexes(conn)
    for name in missing:
        conn.execute(ANALYTICS_INDEXES[name])
    conn.commit()
    existing = [name for name in ANALYTICS_INDEXES if name not in missing]
    return missing, existing
