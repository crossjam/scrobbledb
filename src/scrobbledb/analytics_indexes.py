"""
The analytics indexes: the secondary indexes scrobbledb's rollups need.

A scrobbledb database carries no non-PK indexes by default. These three cover
the foreign-key columns that join plays to tracks to albums to artists, so a
query that starts from the parent side -- the plays of a track, the tracks of an
album -- can look rows up instead of scanning. A full-history rollup reads every
play whatever indexes exist: measured against a 56k-play database, top artists
and the monthly rollup take the same time with or without them, while top tracks,
which looks plays up by track, gets faster. There is deliberately no index on
the month of a play: the rollup groups by `%Y` and
`%m` separately, so an expression on `%Y-%m` is never used, and regrouping to
match it was measured to save nothing (design D10).

They are created only on request, by `scrobbledb index --analytics`, and never
as a side effect of anything else -- `serve` in particular detects their absence
and says so, because its read-only guarantee is worth more than a faster first
query.

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
