"""
The small scrobble library the Datasette, MCP and `serve` tests share.

Kept out of `conftest.py` so a test module can import the data itself --
`FIXTURE_PLAYS` to compute an expectation, `populate` to build a variant --
without importing a conftest. The fixtures built on it live in `conftest.py`.
"""

import sqlite_utils


def create_schema(db):
    db.execute("CREATE TABLE artists (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
    db.execute(
        "CREATE TABLE albums (id TEXT PRIMARY KEY, title TEXT NOT NULL,"
        " artist_id TEXT NOT NULL, FOREIGN KEY (artist_id) REFERENCES artists(id))"
    )
    db.execute(
        "CREATE TABLE tracks (id TEXT PRIMARY KEY, title TEXT NOT NULL,"
        " album_id TEXT NOT NULL, FOREIGN KEY (album_id) REFERENCES albums(id))"
    )
    db.execute(
        "CREATE TABLE plays (timestamp TEXT NOT NULL, track_id TEXT NOT NULL,"
        " PRIMARY KEY (timestamp, track_id),"
        " FOREIGN KEY (track_id) REFERENCES tracks(id))"
    )


#: The ten plays of the shared fixture, in the shape of
#: `tests/test_stats.py:47-144`: 2 artists, 3 albums, 5 tracks, 2023-06 to
#: 2024-03.
#:
#: The timestamps carry an explicit UTC offset, which the CLI fixture omits,
#: because that is what `lastfm._extract_track_data` actually stores and what
#: `parse_when` returns. A naive stored timestamp sorts *before* the same
#: instant rendered with an offset, so an inclusive bound taken from a play's
#: own timestamp would silently exclude that play and a test relying on it
#: would be asserting the wrong thing.
FIXTURE_PLAYS = (
    ("2023-06-15T10:00:00+00:00", "t1"),
    ("2023-06-16T11:00:00+00:00", "t2"),
    ("2023-07-01T12:00:00+00:00", "t1"),
    ("2023-12-25T08:00:00+00:00", "t3"),
    ("2024-01-01T00:00:00+00:00", "t4"),
    ("2024-01-15T14:00:00+00:00", "t5"),
    ("2024-02-14T18:00:00+00:00", "t1"),
    ("2024-03-10T09:00:00+00:00", "t2"),
    ("2024-03-20T16:00:00+00:00", "t3"),
    ("2024-03-25T20:00:00+00:00", "t4"),
)


def populate(path):
    """The shared fixture content, without a search index. Returns an open db."""
    db = sqlite_utils.Database(path)
    create_schema(db)

    db["artists"].insert_all(
        [{"id": "a1", "name": "Artist One"}, {"id": "a2", "name": "Artist Two"}]
    )
    db["albums"].insert_all(
        [
            {"id": "alb1", "title": "Album One", "artist_id": "a1"},
            {"id": "alb2", "title": "Album Two", "artist_id": "a1"},
            {"id": "alb3", "title": "Album Three", "artist_id": "a2"},
        ]
    )
    db["tracks"].insert_all(
        [
            {"id": "t1", "title": "Track One", "album_id": "alb1"},
            {"id": "t2", "title": "Track Two", "album_id": "alb1"},
            {"id": "t3", "title": "Track Three", "album_id": "alb2"},
            {"id": "t4", "title": "Track Four", "album_id": "alb3"},
            {"id": "t5", "title": "Track Five", "album_id": "alb3"},
        ]
    )
    db["plays"].insert_all(
        [{"timestamp": ts, "track_id": track} for ts, track in FIXTURE_PLAYS]
    )
    return db
