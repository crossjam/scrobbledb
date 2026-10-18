"""
The search index must hold exactly one row per indexable track, and
`scrobbledb index --verify` must say so when it does not.
"""

import pytest
import sqlite_utils
from click.testing import CliRunner

from scrobbledb import cli, lastfm

# The trigger body that predates the fix: no DELETE before the INSERT.
OLD_TRACKS_AI = """
    CREATE TRIGGER tracks_ai AFTER INSERT ON tracks BEGIN
        INSERT INTO tracks_fts (artist_name, album_title, track_title, artist_id, album_id, track_id)
        SELECT artists.name, albums.title, new.title, artists.id, albums.id, new.id
        FROM albums JOIN artists ON albums.artist_id = artists.id
        WHERE albums.id = new.album_id;
    END;
"""


def make_db(path=None):
    db = sqlite_utils.Database(path) if path else sqlite_utils.Database(memory=True)
    lastfm.save_artist(db, {"id": "a1", "name": "Artist"})
    lastfm.save_album(db, {"id": "b1", "artist_id": "a1", "title": "Album"})
    lastfm.save_track(db, {"id": "t1", "album_id": "b1", "title": "Song"})
    lastfm.setup_fts5(db)
    lastfm.rebuild_fts5(db)
    return db


def fts_counts(db):
    return dict(
        db.execute("SELECT track_id, COUNT(*) FROM tracks_fts GROUP BY track_id").fetchall()
    )


def test_every_fts_inserting_trigger_clears_first():
    db = make_db()
    rows = db.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' "
        "AND sql LIKE '%INSERT INTO tracks_fts%'"
    ).fetchall()
    assert len(rows) >= 6  # artists/albums/tracks x insert/update
    lacking = [name for name, sql in rows if "DELETE FROM tracks_fts" not in sql]
    assert lacking == []


STALE_ROW = (
    "INSERT INTO tracks_fts (artist_name, album_title, track_title, artist_id, album_id, track_id) "
    "VALUES ('old', 'old', 'old', 'a1', 'b1', 't9')"
)
NEW_TRACK = "INSERT INTO tracks (id, album_id, title) VALUES ('t9', 'b1', 'Nine')"


def test_inserting_a_track_replaces_a_stale_index_row():
    db = make_db()
    db.execute(STALE_ROW)
    db.execute(NEW_TRACK)
    assert fts_counts(db)["t9"] == 1
    assert db.execute("SELECT track_title FROM tracks_fts WHERE track_id='t9'").fetchone()[0] == "Nine"


def test_reupserting_a_track_leaves_one_index_row():
    db = make_db()
    lastfm.save_track(db, {"id": "t1", "album_id": "b1", "title": "Song"})
    lastfm.save_track(db, {"id": "t1", "album_id": "b1", "title": "Renamed"})
    assert fts_counts(db) == {"t1": 1}


def test_track_inserted_before_album_and_artist_is_indexed_once():
    db = make_db()
    lastfm.save_track(db, {"id": "t2", "album_id": "b2", "title": "Early"})
    assert "t2" not in fts_counts(db)  # nothing to join yet
    lastfm.save_artist(db, {"id": "a2", "name": "Late Artist"})
    lastfm.save_album(db, {"id": "b2", "artist_id": "a2", "title": "Late Album"})
    lastfm.save_track(db, {"id": "t2", "album_id": "b2", "title": "Early"})
    assert fts_counts(db) == {"t1": 1, "t2": 1}
    assert lastfm.verify_fts5(db)["ok"]


def test_setup_fts5_upgrades_an_old_tracks_ai_trigger():
    db = make_db()
    db.execute("DROP TRIGGER tracks_ai")
    db.execute(OLD_TRACKS_AI)
    db.execute(STALE_ROW)
    db.execute(NEW_TRACK)
    assert fts_counts(db)["t9"] == 2  # the old trigger duplicates

    db.execute("DELETE FROM tracks WHERE id = 't9'")
    lastfm.setup_fts5(db)
    db.execute(STALE_ROW)
    db.execute(NEW_TRACK)
    assert fts_counts(db)["t9"] == 1
    # idempotent: a second call leaves the definition alone
    before = db.execute("SELECT sql FROM sqlite_master WHERE name = 'tracks_ai'").fetchone()
    lastfm.setup_fts5(db)
    after = db.execute("SELECT sql FROM sqlite_master WHERE name = 'tracks_ai'").fetchone()
    assert before == after


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "t.db")
    make_db(path).close()
    return path


def verify(path):
    return CliRunner().invoke(cli.cli, ["index", "--verify", path])


def test_verify_clean_database(db_path):
    result = verify(db_path)
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert "tracks 1" in lines and "indexed 1" in lines and "status ok" in lines


def test_verify_reports_missing_extra_and_duplicates(db_path):
    db = sqlite_utils.Database(db_path)
    lastfm.save_track(db, {"id": "t2", "album_id": "b1", "title": "Other"})
    db.execute("DELETE FROM tracks_fts WHERE track_id = 't2'")  # missing
    db.execute(
        "INSERT INTO tracks_fts (artist_name, album_title, track_title, artist_id, album_id, track_id) "
        "VALUES ('x', 'y', 'z', 'a1', 'b1', 'ghost')"
    )  # extra
    db.execute(
        "INSERT INTO tracks_fts (artist_name, album_title, track_title, artist_id, album_id, track_id) "
        "VALUES ('Artist', 'Album', 'Song', 'a1', 'b1', 't1')"
    )  # duplicate
    db.close()
    result = verify(db_path)
    assert result.exit_code == 1
    lines = result.output.splitlines()
    assert "missing t2" in lines
    assert "extra ghost" in lines
    assert "duplicated t1" in lines
    assert lines[-1] == "status drifted"


def test_verify_does_not_modify_the_database(db_path):
    db = sqlite_utils.Database(db_path)
    db.execute("DELETE FROM tracks_fts")
    db.close()
    assert verify(db_path).exit_code == 1
    db = sqlite_utils.Database(db_path)
    assert db.execute("SELECT COUNT(*) FROM tracks_fts").fetchone()[0] == 0


def test_verify_without_an_index_fails(tmp_path):
    path = str(tmp_path / "bare.db")
    db = sqlite_utils.Database(path)
    lastfm.save_artist(db, {"id": "a1", "name": "A"})
    lastfm.save_album(db, {"id": "b1", "artist_id": "a1", "title": "B"})
    lastfm.save_track(db, {"id": "t1", "album_id": "b1", "title": "T"})
    db.close()
    result = verify(path)
    assert result.exit_code == 1
    assert "status no-index" in result.output


def test_verify_flags_stale_text_with_correct_ids(db_path):
    db = sqlite_utils.Database(db_path)
    db.execute("UPDATE tracks_fts SET track_title = 'Old Title' WHERE track_id = 't1'")
    db.close()
    result = verify(db_path)
    assert result.exit_code == 1
    lines = result.output.splitlines()
    assert "stale t1" in lines and "missing 0" in lines and "extra 0" in lines


def test_verify_flags_null_track_id_without_hiding_missing(db_path):
    db = sqlite_utils.Database(db_path)
    lastfm.save_track(db, {"id": "t2", "album_id": "b1", "title": "Other"})
    db.execute("DELETE FROM tracks_fts WHERE track_id = 't2'")
    db.execute(
        "INSERT INTO tracks_fts (artist_name, album_title, track_title, artist_id, album_id, track_id) "
        "VALUES ('a', 'b', 'c', 'a1', 'b1', NULL)"
    )
    db.close()
    result = verify(db_path)
    assert result.exit_code == 1
    lines = result.output.splitlines()
    assert "missing t2" in lines
    assert "extra NULL" in lines


def test_verify_without_index_reports_real_track_count(tmp_path):
    path = str(tmp_path / "bare.db")
    db = sqlite_utils.Database(path)
    lastfm.save_artist(db, {"id": "a1", "name": "A"})
    lastfm.save_album(db, {"id": "b1", "artist_id": "a1", "title": "B"})
    lastfm.save_track(db, {"id": "t1", "album_id": "b1", "title": "T"})
    db.close()
    assert "tracks 1" in verify(path).output.splitlines()


def test_verify_rejects_analytics_combination(db_path):
    result = CliRunner().invoke(cli.cli, ["index", "--verify", "--analytics", db_path])
    assert result.exit_code != 0


@pytest.mark.parametrize(
    "track_id, key",
    [("ghost", "extra"), ("t1", "duplicated")],
)
def test_verify_fails_on_each_kind_of_drift_alone(db_path, track_id, key):
    db = sqlite_utils.Database(db_path)
    db.execute(
        "INSERT INTO tracks_fts (artist_name, album_title, track_title, artist_id, album_id, track_id) "
        f"VALUES ('Artist', 'Album', 'Song', 'a1', 'b1', '{track_id}')"
    )
    db.close()
    result = verify(db_path)
    assert result.exit_code == 1
    assert f"{key} {track_id}" in result.output.splitlines()
    assert "missing 0" in result.output.splitlines()
