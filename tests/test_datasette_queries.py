"""
Tests for the stored-query catalog served by the scrobbledb Datasette plugin.

Three properties are load-bearing and each is checked through the production
seam -- the real plugin module registered with Datasette's global plugin
manager, the real hook, the real HTTP surface:

- **The catalog is complete.** Every entry carries all of its fields, is
  uniquely named, and is a shared `domain_queries` builder rather than SQL
  written a second time in the plugin.

- **A time bound is resolved once per statement.** `parse_when` reads the wall
  clock and is deliberately not registered deterministic, so a query with
  several comparison sites would otherwise resolve each independently and could
  compare early rows against one instant and later rows against another
  (design D5). The rewrite that pins it is checked here; the projected queries
  are checked over HTTP once the hook lands.
"""

import re

import pytest
import sqlite_utils

from scrobbledb.datasette_plugin import functions as fns
from scrobbledb.datasette_plugin import queries as cat

pytest.importorskip("datasette")
pytest.importorskip("pytest_asyncio")


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def registered_plugin():
    """
    Register the plugin with Datasette's global plugin manager, then remove it.

    `pm.register` is process-global, so a leaked registration would silently
    apply to every later test in the session. The teardown is mandatory rather
    than polite (design D3).
    """
    from datasette.plugins import pm

    from scrobbledb import datasette_plugin

    pm.register(datasette_plugin, name="scrobbledb-queries-test")
    try:
        yield
    finally:
        pm.unregister(name="scrobbledb-queries-test")


def _create_schema(db):
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
#: own timestamp would silently exclude that play and the test below would be
#: asserting the wrong thing.
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


@pytest.fixture
def populated_db(tmp_path):
    """A populated scrobbledb database: 10 plays, 2 artists, 3 albums, 5 tracks."""
    path = tmp_path / "scrobbles.db"
    db = sqlite_utils.Database(path)
    _create_schema(db)

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
    db.conn.commit()
    db.close()
    return path


@pytest.fixture
def album_identity_db(tmp_path):
    """
    A database holding both album-identity failure shapes at once.

    "Doubles" is one album under two ids *and* two artist ids that resolve to
    the same name -- it must collapse to one row that still names the artist.
    "The DJ Mix" is a compilation: one title, one album row per contributor --
    it must collapse to one row credited to nobody in particular.

    The mix's ids are chosen so that the two independent aggregates of the
    original defect land on different rows: `MAX(albums.id)` is `md5:zmix`,
    owned by Contributor Two, while `MAX(artists.name)` is Contributor Zero,
    which owns `md5:amix`. Ids whose maxima happened to coincide would make the
    attribution assertions weaker than they look.
    """
    path = tmp_path / "aliases.db"
    db = sqlite_utils.Database(path)
    _create_schema(db)

    db["artists"].insert_all(
        [
            {"id": "art-solo-1", "name": "Solo Artist"},
            {"id": "art-solo-2", "name": "Solo Artist"},
            {"id": "art-c0", "name": "Contributor Zero"},
            {"id": "art-c1", "name": "Contributor One"},
            {"id": "art-c2", "name": "Contributor Two"},
        ]
    )
    db["albums"].insert_all(
        [
            {"id": "zzz-doubles", "title": "Doubles", "artist_id": "art-solo-1"},
            {"id": "md5:aaadoubles", "title": "doubles", "artist_id": "art-solo-2"},
            {"id": "md5:amix", "title": "The DJ Mix", "artist_id": "art-c0"},
            {"id": "md5:bmix", "title": "The DJ Mix", "artist_id": "art-c1"},
            {"id": "md5:zmix", "title": "The DJ Mix", "artist_id": "art-c2"},
        ]
    )
    db["tracks"].insert_all(
        [
            {"id": "trk-d1", "title": "Double One", "album_id": "zzz-doubles"},
            {"id": "trk-d2", "title": "Double Two", "album_id": "md5:aaadoubles"},
            {"id": "trk-m0", "title": "Mix Zero", "album_id": "md5:amix"},
            {"id": "trk-m1", "title": "Mix One", "album_id": "md5:bmix"},
            {"id": "trk-m2", "title": "Mix Two", "album_id": "md5:zmix"},
        ]
    )
    db["plays"].insert_all(
        [
            {"timestamp": "2024-05-01T10:00:00+00:00", "track_id": "trk-d1"},
            {"timestamp": "2024-05-02T10:00:00+00:00", "track_id": "trk-d1"},
            {"timestamp": "2024-05-03T10:00:00+00:00", "track_id": "trk-d2"},
            {"timestamp": "2024-05-04T10:00:00+00:00", "track_id": "trk-d2"},
            {"timestamp": "2024-05-05T10:00:00+00:00", "track_id": "trk-m0"},
            {"timestamp": "2024-05-06T10:00:00+00:00", "track_id": "trk-m1"},
            {"timestamp": "2024-05-07T10:00:00+00:00", "track_id": "trk-m2"},
        ]
    )
    db.conn.commit()
    db.close()
    return path


async def serve(path):
    """Build a started Datasette over `path`. The plugin must already be registered."""
    from datasette.app import Datasette

    ds = Datasette([str(path)])
    await ds.invoke_startup()
    return ds


async def run_query(ds, database, name, **params):
    """
    Execute one stored query over HTTP and return its rows as dicts.

    Goes through `/<db>/<query>.json`, the same URL a browser follows from the
    database index page, so a query that is registered but unreachable fails
    here.
    """
    response = await ds.client.get(
        f"/{database}/{name}.json", params={"_shape": "array", **params}
    )
    assert response.status_code == 200, (
        f"{name}: {response.status_code} {response.text}"
    )
    return response.json()


# --------------------------------------------------------------------------
# 3.1 -- the catalog itself
# --------------------------------------------------------------------------

#: The catalog must stay at least this large. A floor rather than an equality
#: so the pending 3.5/3.6 entries can be added without touching this test,
#: while a silently emptied catalog still fails.
CATALOG_FLOOR = 16


def test_catalog_entries_are_complete_and_uniquely_named():
    """Every entry carries all of its fields, and no two share a name."""
    assert len(cat.CATALOG) >= CATALOG_FLOOR, (
        f"catalog has shrunk to {len(cat.CATALOG)} entries"
    )

    names = []
    for entry in cat.CATALOG:
        assert isinstance(entry.name, str) and entry.name, f"{entry}: no name"
        assert isinstance(entry.title, str) and entry.title, f"{entry.name}: no title"
        assert isinstance(entry.description, str) and entry.description, (
            f"{entry.name}: no description"
        )
        assert callable(entry.builder), f"{entry.name}: builder is not callable"
        # Datasette routes a stored query at /<database>/<name>.
        assert re.fullmatch(r"[a-z][a-z0-9_]*", entry.name), (
            f"{entry.name}: not a usable URL slug"
        )
        names.append(entry.name)

    assert len(names) == len(set(names)), f"duplicate query names in {names}"


def test_every_entry_is_a_shared_builder_rather_than_local_sql():
    """
    No entry writes its own SQL.

    A second SQL catalog in the plugin is the alternative design D4 rejected:
    it duplicates every query and lets the web surface drift from the CLI.
    """
    for entry in cat.CATALOG:
        assert entry.builder.__module__ == "scrobbledb.domain_queries", (
            f"{entry.name}: builder is not a shared domain_queries builder"
        )
        assert entry.builder.__name__.startswith("build_"), (
            f"{entry.name}: {entry.builder.__name__} is not a builder"
        )


def test_definitions_expose_the_stored_query_dict_shape():
    """`stored_query_definitions()` is what `datasette.add_query` consumes."""
    definitions = cat.stored_query_definitions()

    assert list(definitions) == [entry.name for entry in cat.CATALOG]
    for entry in cat.CATALOG:
        definition = definitions[entry.name]
        assert set(definition) == {"sql", "title", "description"}
        assert definition["title"] == entry.title
        assert definition["description"] == entry.description
        assert definition["sql"].strip()


def test_the_bound_resolver_calls_a_function_the_plugin_registers():
    """
    The CTE is useless unless `prepare_connection` registers what it calls.

    Read from the registration table rather than repeating the name, so
    renaming the function without updating the catalog fails here instead of at
    the first query a user runs.
    """
    assert cat.PARSE_WHEN in fns.SQL_FUNCTIONS
    _arity, _fn, deterministic = fns.SQL_FUNCTIONS[cat.PARSE_WHEN]
    assert deterministic is False, (
        "if parse_when ever became deterministic the CTE would be redundant, "
        "but see design D5: the flag is an optimizer permission, not a guarantee"
    )


def test_no_entry_name_shadows_a_table(populated_db):
    """
    A stored query and a table share the `/<db>/<name>` URL space.

    Naming a query `plays` would collide with the `plays` table, so the names
    are checked against the real schema rather than assumed distinct.
    """
    db = sqlite_utils.Database(populated_db)
    try:
        tables = set(db.table_names())
    finally:
        db.close()

    assert tables, "fixture has no tables; the check would be vacuous"
    collisions = {entry.name for entry in cat.CATALOG} & tables
    assert not collisions, f"query names collide with table names: {collisions}"


# --------------------------------------------------------------------------
# 3.1/3.3 -- the bound rewrite itself
# --------------------------------------------------------------------------


#: Entries whose SQL carries the rewritten optional bounds, discovered from the
#: catalog rather than listed, so a new time-ranged entry is covered too.
def time_ranged_entries():
    return [entry for entry in cat.CATALOG if cat.BOUNDS_CTE in entry.sql]


def test_some_entries_are_time_ranged():
    """Guards the discovery above: an empty set would make its users vacuous."""
    ranged = {entry.name for entry in time_ranged_entries()}
    assert len(ranged) >= 5, f"only {ranged} were detected as time-ranged"


def test_entries_without_bounds_gain_no_bound_parameters():
    """
    A query with no time range must not sprout `:since`/`:until` form fields.

    The rewrite is driven by what the builder rendered, so an entry that never
    had bounds is returned untouched.
    """
    overview = next(entry for entry in cat.CATALOG if entry.name == "overview")
    assert cat.BOUNDS_CTE not in overview.sql
    for name in cat.BOUND_PARAMETERS:
        assert f":{name}" not in overview.sql


def test_the_rewrite_refuses_a_bound_it_cannot_route_through_parse_when():
    """
    A builder that renders a bound some other way fails loudly here.

    Silently passing it through would compare `plays.timestamp` against the
    literal text `last march`, which matches nothing and reports no error.
    """
    sql = (
        "SELECT * FROM plays WHERE (:since = '' OR plays.timestamp >= :since)"
        " AND plays.timestamp != :since"
    )
    with pytest.raises(ValueError, match="parse_when"):
        cat.resolve_time_bounds_once(sql)


def test_the_rewrite_keeps_a_builders_own_ctes():
    """
    Forward cover for the streaks builder of task 3.5, which needs its own CTE.

    Ours has to go first so the rest may reference it, and `RECURSIVE` has to
    survive the merge or a recursive builder becomes a syntax error.
    """
    body = (
        "WITH days AS (SELECT date(timestamp) AS d FROM plays"
        " WHERE (:since = '' OR plays.timestamp >= :since))"
        " SELECT * FROM days"
    )
    rewritten = cat.resolve_time_bounds_once(body)
    assert rewritten.startswith(f"WITH {cat.BOUNDS_CTE} AS MATERIALIZED")
    assert "days AS (SELECT" in rewritten
    assert rewritten.count("WITH") == 1

    recursive = cat.resolve_time_bounds_once("WITH RECURSIVE " + body[len("WITH ") :])
    assert recursive.startswith(f"WITH RECURSIVE {cat.BOUNDS_CTE} AS MATERIALIZED")
