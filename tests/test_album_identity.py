"""
Tests for album aggregate identity.

An album aggregate is one row per album title, and no row may name an artist
that does not own it. Three failures are possible and all are covered here:

- **Fragmentation.** A compilation or DJ mix credits each track to a different
  artist, so grouping on artist gives one row per contributor -- the complaint
  in GitHub #47. Such an album must be a single row.

- **Under-merging.** The same album can exist under several synthesized ``md5:``
  ids. Those must collapse into one row, with ``album_ids`` carrying the whole
  group, because that group is what the row's counts describe.

- **False attribution.** The original defect: ``album_id`` and ``artist_name``
  were independent ``MAX()`` aggregates, so a row could name an artist that did
  not own the album id beside it (909 rows against the live database). A merged
  row must either name the single owning artist or decline to name one.

See design D4 of the add-datasette-web-server change.
"""

import json
import os
import tempfile

import pytest
import sqlite_utils
from click.testing import CliRunner

from scrobbledb import domain_queries
from scrobbledb.domain_queries import VARIOUS_ARTISTS
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


def test_same_title_across_artists_merges_without_naming_one(alias_db):
    """
    One title spanning several artists is one row, credited to nobody in
    particular.

    This is the deliberate trade recorded in design D4: a compilation and two
    genuinely distinct same-titled albums are indistinguishable in this schema,
    so both merge. What must not happen is the row picking one of the artists
    and presenting it as the album's own.
    """
    hits = [r for r in _rows(alias_db) if r["album_title"].lower() == "greatest hits"]

    assert len(hits) == 1
    row = hits[0]
    assert row["artist_name"] == VARIOUS_ARTISTS
    assert set(row["album_ids"]) == {"zzz-hits", "aaa-hits"}
    # Specifically not the old behavior, where MAX() picked a real artist.
    assert row["artist_name"] not in ("Artist Alpha", "Artist Zulu")


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


def test_no_row_names_an_artist_that_does_not_own_it(alias_db):
    """
    A named artist owns every album id in its group; otherwise nobody is named.

    This is the invariant that replaces "every row's artist owns its album_id".
    It still fails against the original MAX()-pair code, which is the point.
    """
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

    for row in rows:
        owners = {owner[album_id] for album_id in row["album_ids"]}
        if row["artist_name"] == VARIOUS_ARTISTS:
            assert len(owners) > 1, f"sentinel used for a single-artist group: {row}"
        else:
            assert owners == {row["artist_name"]}, f"false attribution: {row}"


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


@pytest.fixture
def dj_mix_db():
    """
    A DJ mix in the shape GitHub #47 reported: one album title whose tracks are
    each credited to a different artist, so the album has one `albums` row per
    contributor.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = sqlite_utils.Database(path)

    db.execute("CREATE TABLE artists (id TEXT PRIMARY KEY, name TEXT)")
    db.execute(
        "CREATE TABLE albums (id TEXT PRIMARY KEY, title TEXT, artist_id TEXT)"
    )
    db.execute(
        "CREATE TABLE tracks (id TEXT PRIMARY KEY, title TEXT, album_id TEXT)"
    )
    db.execute(
        "CREATE TABLE plays (track_id TEXT, timestamp TEXT,"
        " PRIMARY KEY (timestamp, track_id))"
    )

    title = "MK at Ushuaia Ibiza (DJ Mix)"
    for i in range(8):
        db["artists"].insert({"id": f"art-{i}", "name": f"Contributor {i}"})
        db["albums"].insert(
            {"id": f"md5:mix{i}", "title": title, "artist_id": f"art-{i}"}
        )
        db["tracks"].insert(
            {"id": f"trk-{i}", "title": f"Mixed Track {i}", "album_id": f"md5:mix{i}"}
        )
        db["plays"].insert(
            {"track_id": f"trk-{i}", "timestamp": f"2026-02-16T01:0{i}:00+00:00"}
        )

    yield path, title

    db.close()
    if os.path.exists(path):
        os.unlink(path)


def test_dj_mix_is_one_row_not_one_per_contributor(dj_mix_db):
    """
    Regression test for GitHub #47.

    The listing showed a DJ mix as one row per contributing artist, which made
    `albums list` unusable for anyone whose library contains mixes. It must be a
    single row whose counts cover the whole mix.
    """
    path, title = dj_mix_db
    db = sqlite_utils.Database(path)
    try:
        rows = domain_queries.get_albums_list(db, sort="recent")
    finally:
        db.close()

    assert len(rows) == 1, f"#47 regression: {len(rows)} rows for one DJ mix"
    row = rows[0]
    assert row["album_title"] == title
    assert row["artist_name"] == VARIOUS_ARTISTS
    assert row["track_count"] == 8
    assert row["play_count"] == 8
    assert len(row["album_ids"]) == 8


def test_dj_mix_ranks_as_one_album_in_top_albums(dj_mix_db):
    """
    The same must hold for the ranking, or a heavily played mix is ranked below
    albums it actually outplays because its count is split.
    """
    path, title = dj_mix_db
    db = sqlite_utils.Database(path)
    try:
        rows = domain_queries.get_top_albums(db, limit=10)
    finally:
        db.close()

    assert len(rows) == 1
    assert rows[0]["play_count"] == 8
    assert rows[0]["artist_name"] == VARIOUS_ARTISTS
    assert rows[0]["percentage"] == 100.0


def test_dj_mix_expands_to_every_contributed_track(runner, dj_mix_db):
    """`--expand` on a merged mix lists all of its tracks, not one."""
    path, _title = dj_mix_db
    result = runner.invoke(
        albums_cmd.albums,
        ["list", "--database", path, "--format", "json", "--expand"],
    )
    assert result.exit_code == 0

    albums = json.loads(result.output)
    assert len(albums) == 1
    assert len(albums[0]["tracks"]) == 8 == albums[0]["track_count"]


@pytest.fixture
def duplicate_artist_db():
    """
    One album whose two identifiers are attributed to two *different artist
    ids carrying the same name* -- the common shape when an artist exists both
    under a MusicBrainz id and a synthesized `md5:` one.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = sqlite_utils.Database(path)

    db.execute("CREATE TABLE artists (id TEXT PRIMARY KEY, name TEXT)")
    db.execute(
        "CREATE TABLE albums (id TEXT PRIMARY KEY, title TEXT, artist_id TEXT)"
    )
    db.execute(
        "CREATE TABLE tracks (id TEXT PRIMARY KEY, title TEXT, album_id TEXT)"
    )
    db.execute(
        "CREATE TABLE plays (track_id TEXT, timestamp TEXT,"
        " PRIMARY KEY (timestamp, track_id))"
    )

    db["artists"].insert_all(
        [
            {"id": "mbid-shadow", "name": "DJ Shadow"},
            {"id": "md5:shadow", "name": "DJ Shadow"},
        ]
    )
    db["albums"].insert_all(
        [
            {"id": "alb-1", "title": "Endtroducing", "artist_id": "mbid-shadow"},
            {"id": "md5:alb2", "title": "Endtroducing", "artist_id": "md5:shadow"},
        ]
    )
    db["tracks"].insert_all(
        [
            {"id": "trk-1", "title": "Building Steam", "album_id": "alb-1"},
            {"id": "trk-2", "title": "Midnight", "album_id": "md5:alb2"},
        ]
    )
    db["plays"].insert_all(
        [
            {"track_id": "trk-1", "timestamp": "2024-01-01T12:00:00+00:00"},
            {"track_id": "trk-2", "timestamp": "2024-01-02T12:00:00+00:00"},
        ]
    )

    yield path

    db.close()
    if os.path.exists(path):
        os.unlink(path)


def test_one_artist_under_several_ids_is_still_named(duplicate_artist_db):
    """
    The sentinel means "many artists", not "many artist ids".

    Counting distinct artist ids instead of names mislabels an album that
    plainly belongs to one artist -- 19 such albums in the live database,
    "Endtroducing (Deluxe Edition)" among them.
    """
    db = sqlite_utils.Database(duplicate_artist_db)
    try:
        rows = domain_queries.get_albums_list(db)
    finally:
        db.close()

    assert len(rows) == 1
    assert rows[0]["artist_name"] == "DJ Shadow"
    assert rows[0]["artist_name"] != VARIOUS_ARTISTS
    assert set(rows[0]["album_ids"]) == {"alb-1", "md5:alb2"}
