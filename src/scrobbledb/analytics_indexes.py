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


def missing_analytics_indexes(conn: sqlite3.Connection) -> list[str]:
    """The analytics indexes absent from `conn`'s database, in definition order."""
    present = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    return [name for name in ANALYTICS_INDEXES if name not in present]
