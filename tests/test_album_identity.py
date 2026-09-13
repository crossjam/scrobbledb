"""
Tests for album aggregate identity.

An album aggregate row must describe exactly one album by exactly one artist.
Two distinct failures are possible and both are covered here:

- **Over-merging.** Grouping by title alone merges same-titled albums by
  different artists, and when ``album_id`` and ``artist_name`` are independent
  ``MAX()`` aggregates the pair can describe different rows -- so a row reports
  an artist that does not own the album id beside it.

- **Under-merging.** The same album can exist under several synthesized ``md5:``
  ids. Those must collapse into one row, with ``album_ids`` carrying the whole
  alias group, because that group is what the row's counts describe.

See design D4 of the add-datasette-web-server change.
"""

import json
import os
import tempfile

import pytest
import sqlite_utils
from click.testing import CliRunner

from scrobbledb import domain_queries
from scrobbledb.commands import albums as albums_cmd


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def alias_db():
    """
    A database containing both failure shapes.

    "Greatest Hits" exists once for each of two artists -- these must stay
    separate. "Doubles" exists twice for the same artist under two ids, one of
    them an md5 alias -- these must collapse into a single row.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = sqlite_utils.Database(path)

    db.execute("CREATE TABLE artists (id TEXT PRIMARY KEY, name TEXT)")
    db.execute(
        "CREATE TABLE albums (id TEXT PRIMARY KEY, title TEXT, artist_id TEXT,"
        " FOREIGN KEY(artist_id) REFERENCES artists(id))"
    )
    db.execute(
        "CREATE TABLE tracks (id TEXT PRIMARY KEY, title TEXT, album_id TEXT,"
        " FOREIGN KEY(album_id) REFERENCES albums(id))"
    )
    db.execute(
        "CREATE TABLE plays (track_id TEXT, timestamp TEXT,"
        " PRIMARY KEY (timestamp, track_id))"
    )

    # The ids and names are chosen so that MAX(albums.id) and MAX(artists.name)
    # fall on *different* rows of the merged group: the highest id (zzz-hits)
    # belongs to Artist Alpha, while the highest name is Artist Zulu. Under the
    # old title-only grouping that pairing is exactly the 909-row mismatch seen
    # on the live database. Picking ids whose maxima happened to coincide would
    # make the ownership assertion below vacuous.
    db["artists"].insert_all(
        [
            {"id": "art-1", "name": "Artist Alpha"},
            {"id": "art-2", "name": "Artist Zulu"},
        ]
    )
    db["albums"].insert_all(
        [
            # Same title, different artists -- must not merge.
            {"id": "zzz-hits", "title": "Greatest Hits", "artist_id": "art-1"},
            {"id": "aaa-hits", "title": "Greatest Hits", "artist_id": "art-2"},
            # Same title and artist under two ids -- must merge.
            {"id": "alb-a2", "title": "Doubles", "artist_id": "art-1"},
            {"id": "md5:aliasdup", "title": "doubles", "artist_id": "art-1"},
        ]
    )
    db["tracks"].insert_all(
        [
            {"id": "trk-a1", "title": "Hit One", "album_id": "zzz-hits"},
            {"id": "trk-b1", "title": "Other Hit", "album_id": "aaa-hits"},
            {"id": "trk-a2", "title": "Double One", "album_id": "alb-a2"},
            {"id": "trk-a3", "title": "Double Two", "album_id": "md5:aliasdup"},
        ]
    )
    db["plays"].insert_all(
        [
            {"track_id": "trk-a1", "timestamp": "2024-01-01T12:00:00+00:00"},
            {"track_id": "trk-b1", "timestamp": "2024-01-02T12:00:00+00:00"},
            {"track_id": "trk-a2", "timestamp": "2024-01-03T12:00:00+00:00"},
            {"track_id": "trk-a3", "timestamp": "2024-01-04T12:00:00+00:00"},
        ]
    )

    yield path

    db.close()
    if os.path.exists(path):
        os.unlink(path)


def _rows(path):
    db = sqlite_utils.Database(path)
    try:
        return domain_queries.get_albums_list(db, sort="name", order="asc")
    finally:
        db.close()


def test_same_title_different_artists_stay_separate(alias_db):
    """Two artists' identically titled albums are two rows, not one."""
    hits = [r for r in _rows(alias_db) if r["album_title"].lower() == "greatest hits"]

    assert len(hits) == 2
    assert {r["artist_name"] for r in hits} == {"Artist Alpha", "Artist Zulu"}
    assert {r["album_id"] for r in hits} == {"zzz-hits", "aaa-hits"}


def test_same_artist_alias_ids_collapse(alias_db):
    """One album under two ids collapses to a single row covering both."""
    doubles = [r for r in _rows(alias_db) if r["album_title"].lower() == "doubles"]

    assert len(doubles) == 1
    row = doubles[0]
    assert row["artist_name"] == "Artist Alpha"
    assert set(row["album_ids"]) == {"alb-a2", "md5:aliasdup"}
    # The counts describe the whole group, not the representative id alone.
    assert row["track_count"] == 2
    assert row["play_count"] == 2


def test_every_row_artist_owns_its_album_id(alias_db):
    """No row may report an artist that does not own the album id beside it."""
    db = sqlite_utils.Database(alias_db)
    try:
        owner = dict(
            db.execute(
                "SELECT albums.id, artists.name FROM albums"
                " JOIN artists ON albums.artist_id = artists.id"
            ).fetchall()
        )
        rows = domain_queries.get_albums_list(db)
    finally:
        db.close()

    mismatched = [r for r in rows if owner[r["album_id"]] != r["artist_name"]]
    assert mismatched == []


def test_album_id_is_a_member_of_album_ids(alias_db):
    """The representative id is always one of the group's own ids."""
    for row in _rows(alias_db):
        assert row["album_id"] in row["album_ids"]


def test_album_ids_partition_every_album(alias_db):
    """Together the groups account for every album exactly once."""
    db = sqlite_utils.Database(alias_db)
    try:
        all_ids = {r[0] for r in db.execute("SELECT id FROM albums").fetchall()}
        rows = domain_queries.get_albums_list(db)
    finally:
        db.close()

    grouped = [album_id for row in rows for album_id in row["album_ids"]]
    assert sorted(grouped) == sorted(all_ids)


def test_get_album_tracks_for_ids_covers_the_group(alias_db):
    """Expanding an alias group returns the tracks of every id in it."""
    db = sqlite_utils.Database(alias_db)
    try:
        single = domain_queries.get_album_tracks(db, "alb-a2")
        group = domain_queries.get_album_tracks_for_ids(
            db, ["alb-a2", "md5:aliasdup"]
        )
    finally:
        db.close()

    assert [t["track_id"] for t in single] == ["trk-a2"]
    assert [t["track_id"] for t in group] == ["trk-a2", "trk-a3"]


def test_expand_lists_as_many_tracks_as_track_count_claims(runner, alias_db):
    """
    `albums list --expand` must not show fewer tracks than track_count.

    It previously expanded the single representative album_id while the counts
    covered the whole alias group, so an expanded album could contradict itself.
    """
    result = runner.invoke(
        albums_cmd.albums,
        ["list", "--database", alias_db, "--format", "json", "--expand"],
    )
    assert result.exit_code == 0

    for album in json.loads(result.output):
        assert len(album["tracks"]) == album["track_count"]
