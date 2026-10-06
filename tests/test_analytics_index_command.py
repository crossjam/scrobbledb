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

from scrobbledb import domain_queries, lastfm
from scrobbledb.analytics_indexes import (
    ANALYTICS_INDEXES,
    REQUIRED_COLUMNS,
    SCROBBLE_TABLES,
    missing_analytics_indexes,
)
from scrobbledb.cli import cli

#: The index set the spec names: the three foreign-key columns joining plays to
#: tracks to albums to artists. Written out rather than derived from
#: `ANALYTICS_INDEXES`, which is the thing under test.
EXPECTED_COLUMNS = {
    ("plays", "track_id"),
    ("tracks", "album_id"),
    ("albums", "artist_id"),
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
    assert "already in place" in result.output
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


# --------------------------------------------------------------------------
# 9.5  Same answers; the plan uses the indexes where the query can
# --------------------------------------------------------------------------

#: The production builders, in the positional form the CLI executes. Both are
#: the spec's named queries.
QUERIES = {
    "top_artists": domain_queries.build_top_artists_sql,
    "monthly_rollup": domain_queries.build_monthly_rollup_sql,
}


def execute(path, builder):
    sql, params = builder(form=domain_queries.SQL_FORM_POSITIONAL)
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(sql, params).fetchall()
        plan = " | ".join(
            row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + sql, params)
        )
    finally:
        conn.close()
    return rows, plan


@pytest.mark.parametrize("name", sorted(QUERIES))
def test_results_are_identical_before_and_after(scrobble_db, name):
    before, _ = execute(scrobble_db, QUERIES[name])
    assert len(before) >= 2, "fixture returns too few rows to show an ordering"

    run("--analytics", str(scrobble_db))

    after, _ = execute(scrobble_db, QUERIES[name])
    assert after == before


def test_the_top_artists_plan_uses_an_analytics_index_afterward(scrobble_db):
    """
    The plan is read before as well, because a plan that mentions an analytics
    index both ways would prove nothing about the command.
    """
    _, before = execute(scrobble_db, QUERIES["top_artists"])
    assert not any(name in before for name in ANALYTICS_INDEXES), before

    run("--analytics", str(scrobble_db))

    _, after = execute(scrobble_db, QUERIES["top_artists"])
    assert any(name in after for name in ANALYTICS_INDEXES), after


# --------------------------------------------------------------------------
# Detection is by what an index covers, and the schema by its columns
# --------------------------------------------------------------------------


def execute_sql(path, *statements):
    conn = sqlite3.connect(path)
    for statement in statements:
        conn.execute(statement)
    conn.commit()
    conn.close()


@pytest.mark.parametrize(
    "table, column",
    [("plays", "track_id"), ("tracks", "album_id"), ("albums", "artist_id")],
)
def test_right_table_names_with_wrong_columns_is_nothing_to_index(tmp_path, table, column):
    """
    The four names are all present and one needed column is not. A names-only
    guard lets this through and then fails with "no such column" half way
    through creating the indexes.
    """
    path = tmp_path / "lookalike.db"
    db = sqlite_utils.Database(path)
    for name in SCROBBLE_TABLES:
        needed = REQUIRED_COLUMNS.get(name, frozenset()) - {column}
        db.execute(f"CREATE TABLE {name} (id TEXT, {', '.join(['other', *sorted(needed)])})")
    db.conn.commit()
    db.close()
    before = digest(path)

    result = run("--analytics", str(path))

    assert result.exit_code == 0, result.output
    assert "Nothing to index" in result.output
    # Rich wraps the line at the terminal width, so compare it unwrapped.
    assert f"{table} has no {column} column" in " ".join(result.output.split())
    assert result.output.count(" has no ") == 1, "only the one column is missing"
    assert secondary_indexes(path) == {}
    assert digest(path) == before


def test_a_name_taken_by_an_index_on_another_column_is_reported(scrobble_db):
    """
    `CREATE INDEX IF NOT EXISTS` would skip this silently, leaving
    plays(track_id) unindexed while the command reported success.
    """
    execute_sql(scrobble_db, "CREATE INDEX idx_plays_track_id ON plays(timestamp)")

    result = run("--analytics", str(scrobble_db))

    assert result.exit_code != 0
    assert "idx_plays_track_id" in result.output
    assert "plays(track_id)" in result.output.replace("\n", "")
    assert "already in place" not in result.output
    conn = sqlite3.connect(scrobble_db)
    try:
        assert missing_analytics_indexes(conn) == ["idx_plays_track_id"]
    finally:
        conn.close()
    # The other two were still created, so a later run only has the conflict left.
    assert {"idx_tracks_album_id", "idx_albums_artist_id"} <= set(
        secondary_indexes(scrobble_db)
    )


def test_an_equivalent_index_under_another_name_is_not_duplicated(scrobble_db):
    """Led by the same column, so a lookup on it can use it, whatever follows."""
    execute_sql(scrobble_db, "CREATE INDEX my_plays_idx ON plays(track_id, timestamp)")

    result = run("--analytics", str(scrobble_db))

    assert result.exit_code == 0, result.output
    assert "idx_plays_track_id" not in result.output
    assert "idx_plays_track_id" not in secondary_indexes(scrobble_db)
    assert "Created index" in result.output  # the other two


def test_a_partial_index_does_not_count(scrobble_db):
    """It covers only some rows, so a lookup cannot rely on it."""
    execute_sql(
        scrobble_db,
        "CREATE INDEX only_some ON plays(track_id) WHERE track_id <> 't1'",
    )

    run("--analytics", str(scrobble_db))

    assert "idx_plays_track_id" in secondary_indexes(scrobble_db)
