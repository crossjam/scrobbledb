"""
Tests for `scrobbledb index --analytics`.

Everything goes through the real command with `CliRunner`. The properties that
matter are all about what the command does *not* do -- touch a row, rebuild the
search index, change the file on a repeat run, create anything on a database
with nothing to index -- so each test compares the database before and after
rather than reading the command's own report of what it did.
"""

import hashlib
import sqlite3

import pytest
import sqlite_utils
from click.testing import CliRunner

from scrobbledb import lastfm
from scrobbledb.analytics_indexes import (
    ANALYTICS_INDEXES,
    SCROBBLE_TABLES,
    missing_analytics_indexes,
)
from scrobbledb.cli import cli

#: The index set the spec names: the three foreign-key columns joining plays to
#: tracks to albums to artists, plus month-grained grouping of plays. Written
#: out rather than derived from `ANALYTICS_INDEXES`, which is the thing under
#: test.
EXPECTED_COLUMNS = {
    ("plays", "track_id"),
    ("tracks", "album_id"),
    ("albums", "artist_id"),
    ("plays", "strftime('%Y-%m', timestamp)"),
}


@pytest.fixture
def scrobble_db(tmp_path):
    """A populated database with the base tables and no secondary indexes."""
    path = tmp_path / "scrobbles.db"
    db = sqlite_utils.Database(path)
    db.execute("CREATE TABLE artists (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
    db.execute(
        "CREATE TABLE albums (id TEXT PRIMARY KEY, title TEXT NOT NULL,"
        " artist_id TEXT NOT NULL REFERENCES artists(id))"
    )
    db.execute(
        "CREATE TABLE tracks (id TEXT PRIMARY KEY, title TEXT NOT NULL,"
        " album_id TEXT NOT NULL REFERENCES albums(id))"
    )
    db.execute(
        "CREATE TABLE plays (timestamp TEXT NOT NULL, track_id TEXT NOT NULL"
        " REFERENCES tracks(id), PRIMARY KEY (timestamp, track_id))"
    )
    db["artists"].insert_all([{"id": "a1", "name": "One"}, {"id": "a2", "name": "Two"}])
    db["albums"].insert_all(
        [
            {"id": "al1", "title": "First", "artist_id": "a1"},
            {"id": "al2", "title": "Second", "artist_id": "a2"},
        ]
    )
    db["tracks"].insert_all(
        [
            {"id": "t1", "title": "A", "album_id": "al1"},
            {"id": "t2", "title": "B", "album_id": "al1"},
            {"id": "t3", "title": "C", "album_id": "al2"},
        ]
    )
    db["plays"].insert_all(
        [
            {"timestamp": "2024-01-05T10:00:00+00:00", "track_id": "t1"},
            {"timestamp": "2024-01-06T10:00:00+00:00", "track_id": "t2"},
            {"timestamp": "2024-02-07T10:00:00+00:00", "track_id": "t3"},
        ]
    )
    db.conn.commit()
    db.close()
    return path


def run(*args):
    return CliRunner().invoke(cli, ["index", *args], catch_exceptions=False)


def secondary_indexes(path):
    """Name -> CREATE statement for every index the user (not SQLite) made."""
    conn = sqlite3.connect(path)
    try:
        return dict(
            conn.execute(
                "SELECT name, sql FROM sqlite_master"
                " WHERE type = 'index' AND sql IS NOT NULL"
            )
        )
    finally:
        conn.close()


def table_contents(path):
    """Every row of every scrobble table, in a comparable form."""
    conn = sqlite3.connect(path)
    try:
        return {
            table: conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
            for table in SCROBBLE_TABLES
        }
    finally:
        conn.close()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# 9.1  Creation
# --------------------------------------------------------------------------


def test_the_fixture_starts_with_no_secondary_indexes(scrobble_db):
    assert secondary_indexes(scrobble_db) == {}


def test_analytics_creates_each_index_and_reports_it(scrobble_db):
    result = run("--analytics", str(scrobble_db))
    assert result.exit_code == 0, result.output

    created = secondary_indexes(scrobble_db)
    assert len(ANALYTICS_INDEXES) >= len(EXPECTED_COLUMNS)
    for name in ANALYTICS_INDEXES:
        assert name in created, name
        assert name in result.output, f"{name} was created but not reported"

    covered = set()
    for sql in created.values():
        target = sql.split(" ON ", 1)[1]
        table, _, rest = target.partition("(")
        covered.add((table, rest.removesuffix(")")))
    assert covered == EXPECTED_COLUMNS


def test_nothing_is_missing_afterwards(scrobble_db):
    run("--analytics", str(scrobble_db))
    conn = sqlite3.connect(scrobble_db)
    try:
        assert missing_analytics_indexes(conn) == []
    finally:
        conn.close()


# --------------------------------------------------------------------------
# 9.2  The flag is the only difference
# --------------------------------------------------------------------------


def test_index_without_the_flag_makes_no_analytics_indexes(scrobble_db):
    result = run(str(scrobble_db))
    assert result.exit_code == 0, result.output
    assert secondary_indexes(scrobble_db) == {}


def test_analytics_leaves_the_search_index_alone(scrobble_db):
    """
    The search index is made short on purpose, so a rebuild would be visible:
    `--analytics` creating indexes is not licence to repair a different one.
    """
    db = sqlite_utils.Database(scrobble_db)
    lastfm.setup_fts5(db)
    lastfm.rebuild_fts5(db)
    db.execute("DELETE FROM tracks_fts WHERE rowid = (SELECT MIN(rowid) FROM tracks_fts)")
    db.conn.commit()
    before = db.execute("SELECT COUNT(*) FROM tracks_fts").fetchone()[0]
    assert before < db["tracks"].count, "fixture index is not short"
    db.close()

    result = run("--analytics", str(scrobble_db))
    assert result.exit_code == 0, result.output

    conn = sqlite3.connect(scrobble_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM tracks_fts").fetchone()[0] == before
    finally:
        conn.close()


def test_a_missing_database_fails_like_plain_index(tmp_path):
    missing = tmp_path / "nowhere.db"
    plain = run(str(missing))
    analytics = run("--analytics", str(missing))
    assert plain.exit_code != 0
    assert analytics.exit_code == plain.exit_code
    assert str(missing) in analytics.output.replace("\n", "")
    assert not missing.exists()


# --------------------------------------------------------------------------
# 9.3  Idempotency
# --------------------------------------------------------------------------


def test_a_second_run_creates_nothing_and_says_so(scrobble_db):
    run("--analytics", str(scrobble_db))
    before = digest(scrobble_db)

    result = run("--analytics", str(scrobble_db))

    assert result.exit_code == 0, result.output
    assert "already exist" in result.output
    assert "Created" not in result.output
    assert digest(scrobble_db) == before, "a repeat run changed the file"


def test_a_partial_set_is_completed_and_only_the_gap_reported(scrobble_db):
    run("--analytics", str(scrobble_db))
    dropped = next(iter(ANALYTICS_INDEXES))
    conn = sqlite3.connect(scrobble_db)
    conn.execute(f"DROP INDEX {dropped}")
    conn.commit()
    conn.close()

    result = run("--analytics", str(scrobble_db))

    assert result.exit_code == 0, result.output
    assert f"Created index {dropped}" in result.output
    assert result.output.count("Created index") == 1
    assert set(ANALYTICS_INDEXES) <= set(secondary_indexes(scrobble_db))


# --------------------------------------------------------------------------
# 9.4  Row data, and nothing to index
# --------------------------------------------------------------------------


def test_row_data_is_untouched(scrobble_db):
    before = table_contents(scrobble_db)
    assert all(before.values()), "fixture has an empty table; the check is vacuous"

    run("--analytics", str(scrobble_db))

    assert table_contents(scrobble_db) == before


@pytest.mark.parametrize("tables", [(), ("artists",), ("artists", "albums", "tracks")])
def test_nothing_to_index_reports_and_exits_zero(tmp_path, tables):
    """No scrobble tables, or only some of them: nothing is created either way."""
    path = tmp_path / "partial.db"
    db = sqlite_utils.Database(path)
    db["unrelated"].insert({"id": 1})
    for table in tables:
        db.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY)")
    db.conn.commit()
    db.close()
    before = digest(path)

    result = run("--analytics", str(path))

    assert result.exit_code == 0, result.output
    assert "Nothing to index" in result.output
    assert secondary_indexes(path) == {}
    assert digest(path) == before
