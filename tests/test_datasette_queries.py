"""
Tests for the stored-query catalog served by the scrobbledb Datasette plugin.

Three properties are load-bearing and each is checked through the production
seam -- the real plugin module registered with Datasette's global plugin
manager, the real hook, the real HTTP surface:

- **The catalog is complete and projected.** Every entry reaches the database
  index page with its description and returns the rows we expect against a
  populated database, not merely a 200 with nothing in it.

- **A time bound is resolved exactly once per statement.** `parse_when` reads
  the wall clock and is deliberately not registered deterministic, so a query
  with several comparison sites would otherwise resolve each independently and
  could compare early rows against one instant and later rows against another
  (design D5).

- **Album aggregates collapse identifiers and never misattribute an artist.**
  `tests/test_album_identity.py` establishes this at the builder level; here it
  is confirmed to survive the projection into stored queries, for every album
  aggregate the catalog exposes rather than a hand-written list of two.
"""

import re
import sqlite3

import pytest
import sqlite_utils

from scrobbledb import domain_queries
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


# --------------------------------------------------------------------------
# 3.2 -- projection into Datasette
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_entry_reaches_the_database_index_page(
    registered_plugin, populated_db
):
    """
    The hook actually registers the catalog, descriptions included.

    1.0a39's database index page itself shows only the first five stored
    queries and links to the database's full listing at `/<db>/-/queries`, so
    "listed on the index page" is checked against that listing -- in its JSON
    form, because the HTML escapes the quotes some descriptions carry -- plus
    the rendered pages linking through to each query.
    """
    ds = await serve(populated_db)
    database = populated_db.stem

    response = await ds.client.get(
        f"/{database}/-/queries.json", params={"limit": 1000}
    )
    assert response.status_code == 200, response.text
    listed = {query["name"]: query for query in response.json()["queries"]}

    for entry in cat.CATALOG:
        assert entry.name in listed, f"{entry.name} is not listed for the database"
        assert listed[entry.name]["title"] == entry.title
        assert listed[entry.name]["description"] == entry.description

    index = await ds.client.get(f"/{database}")
    assert index.status_code == 200
    assert f"/{database}/-/queries" in index.text, (
        "the database index page does not link to the stored queries"
    )

    page = await ds.client.get(f"/{database}/-/queries", params={"limit": 1000})
    assert page.status_code == 200
    for entry in cat.CATALOG:
        assert f"/{database}/{entry.name}" in page.text, (
            f"{entry.name} is not linked from the rendered listing"
        )


@pytest.mark.asyncio
async def test_a_database_without_plays_gets_no_stored_queries(
    registered_plugin, tmp_path
):
    """
    The catalog is only projected onto scrobbledb-shaped databases.

    Every entry reads `plays`; registering them against an unrelated database
    sharing the process would list queries that can only fail.
    """
    path = tmp_path / "unrelated.db"
    db = sqlite_utils.Database(path)
    db.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    db.conn.commit()
    db.close()

    ds = await serve(path)
    response = await ds.client.get(f"/{path.stem}.json")
    assert response.status_code == 200, response.text
    assert response.json()["queries"] == []


#: Parameters that make each entry return rows against `populated_db`.
#:
#: Entries needing none map to an empty dict. Every catalog entry must appear,
#: so a new entry cannot be added without saying what makes it return rows.
PARAMETERS_FOR = {
    "overview": {},
    "plays_feed": {},
    "monthly_rollup": {},
    "yearly_rollup": {},
    "top_artists": {},
    "top_albums": {},
    "top_tracks": {},
    "artist_list": {},
    "album_list": {},
    "track_list": {},
    "artist_detail": {"artist_id": "a1"},
    "artist_top_tracks": {"artist_id": "a1"},
    "album_detail": {"album_id": "alb1"},
    "album_tracks": {"album_ids": '["alb1", "alb2"]'},
    "track_detail": {"track_id": "t1"},
    "track_plays": {"track_id": "t1"},
}


def test_every_entry_has_an_execution_expectation():
    """A new catalog entry must be given parameters before it can be trusted."""
    assert set(PARAMETERS_FOR) == {entry.name for entry in cat.CATALOG}


@pytest.mark.asyncio
async def test_every_entry_returns_rows_against_a_populated_database(
    registered_plugin, populated_db
):
    """
    Each entry executes and returns data.

    "Executes successfully" has to mean rows: an entry whose SQL silently
    matched nothing would pass a status-code-only check while being useless.
    """
    ds = await serve(populated_db)
    database = populated_db.stem

    for entry in cat.CATALOG:
        rows = await run_query(ds, database, entry.name, **PARAMETERS_FOR[entry.name])
        assert rows, f"{entry.name} returned no rows against a populated database"


@pytest.mark.asyncio
async def test_overview_reports_the_fixtures_totals(registered_plugin, populated_db):
    ds = await serve(populated_db)
    (row,) = await run_query(ds, populated_db.stem, "overview")

    assert row["total_scrobbles"] == len(FIXTURE_PLAYS)
    assert row["unique_artists"] == 2
    assert row["unique_albums"] == 3
    assert row["unique_tracks"] == 5
    assert row["first_scrobble"] == FIXTURE_PLAYS[0][0]
    assert row["last_scrobble"] == FIXTURE_PLAYS[-1][0]


@pytest.mark.asyncio
async def test_top_artists_carries_counts_and_share_of_total(
    registered_plugin, populated_db
):
    """Hand-computed: a1 owns t1/t2/t3 (7 plays), a2 owns t4/t5 (3 plays)."""
    ds = await serve(populated_db)
    rows = await run_query(ds, populated_db.stem, "top_artists")

    assert [row["artist_name"] for row in rows] == ["Artist One", "Artist Two"]
    assert [row["play_count"] for row in rows] == [7, 3]
    assert [round(row["percentage"]) for row in rows] == [70, 30]


@pytest.mark.asyncio
async def test_monthly_rollup_has_one_row_per_month_with_plays(
    registered_plugin, populated_db
):
    ds = await serve(populated_db)
    rows = await run_query(ds, populated_db.stem, "monthly_rollup")

    assert [(row["year"], row["month"], row["scrobbles"]) for row in rows] == [
        (2024, 3, 3),
        (2024, 2, 1),
        (2024, 1, 2),
        (2023, 12, 1),
        (2023, 7, 1),
        (2023, 6, 2),
    ]


@pytest.mark.asyncio
async def test_the_play_feed_is_denormalized(registered_plugin, populated_db):
    """Each row carries the names, so no manual joining is required."""
    ds = await serve(populated_db)
    rows = await run_query(ds, populated_db.stem, "plays_feed", limit="1")

    assert len(rows) == 1
    assert rows[0] == {
        "timestamp": "2024-03-25T20:00:00+00:00",
        "artist_name": "Artist Two",
        "track_title": "Track Four",
        "album_title": "Album Three",
    }


@pytest.mark.asyncio
async def test_stored_queries_agree_with_the_cli(registered_plugin, populated_db):
    """
    The shared builders really are shared: same rows, same order, both ways.

    Drift between the two surfaces is the failure the extraction of group 2
    exists to prevent, so it is checked rather than assumed.
    """
    ds = await serve(populated_db)
    db = sqlite_utils.Database(populated_db)
    try:
        cli_top_artists = domain_queries.get_top_artists(db, limit=10)
        cli_monthly = domain_queries.get_monthly_rollup(db)
    finally:
        db.close()

    served = await run_query(ds, populated_db.stem, "top_artists")
    assert [(r["artist_id"], r["play_count"]) for r in served] == [
        (r["artist_id"], r["play_count"]) for r in cli_top_artists
    ]

    served = await run_query(ds, populated_db.stem, "monthly_rollup")
    assert [(r["year"], r["month"], r["scrobbles"]) for r in served] == [
        (r["year"], r["month"], r["scrobbles"]) for r in cli_monthly
    ]


# --------------------------------------------------------------------------
# 3.3 -- optional bounds, resolved once per statement
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_omitting_both_bounds_covers_the_whole_history(
    registered_plugin, populated_db
):
    ds = await serve(populated_db)
    rows = await run_query(ds, populated_db.stem, "plays_feed", limit="100")
    assert len(rows) == len(FIXTURE_PLAYS)

    # Explicitly blank, which is what a submitted form with empty fields sends.
    rows = await run_query(
        ds, populated_db.stem, "plays_feed", limit="100", since="", until=""
    )
    assert len(rows) == len(FIXTURE_PLAYS)


@pytest.mark.asyncio
async def test_supplied_bounds_are_inclusive_at_both_ends(
    registered_plugin, populated_db
):
    """
    A play exactly at `since` and one exactly at `until` are both counted.

    The bounds are the second and the ninth play's own timestamps, so a `>`
    where `>=` belongs drops two rows and an exclusive pair drops both ends --
    eight rows is the only answer an inclusive range gives.
    """
    since = FIXTURE_PLAYS[1][0]
    until = FIXTURE_PLAYS[-2][0]

    ds = await serve(populated_db)
    rows = await run_query(
        ds, populated_db.stem, "plays_feed", limit="100", since=since, until=until
    )

    timestamps = {row["timestamp"] for row in rows}
    assert since in timestamps, "the play at the since bound was excluded"
    assert until in timestamps, "the play at the until bound was excluded"
    assert len(rows) == len(FIXTURE_PLAYS) - 2
    assert FIXTURE_PLAYS[0][0] not in timestamps
    assert FIXTURE_PLAYS[-1][0] not in timestamps


@pytest.mark.asyncio
async def test_human_time_expressions_match_the_cli(registered_plugin, populated_db):
    """
    `1 january 2024` in a form field selects what `--since` selects.

    Both sides are computed here rather than hard-coded, because the CLI reads
    a naive expression as *local* wall clock, so the UTC instant -- and with a
    play at midnight UTC, the row count -- depends on the host's timezone.
    """
    ds = await serve(populated_db)
    db = sqlite_utils.Database(populated_db)
    try:
        expected = domain_queries.get_plays_with_filters(
            db, limit=100, since=domain_queries.parse_relative_time("1 january 2024")
        )
    finally:
        db.close()

    rows = await run_query(
        ds, populated_db.stem, "plays_feed", limit="100", since="1 january 2024"
    )

    assert expected, "the fixture must have plays in range or this proves nothing"
    assert [row["timestamp"] for row in rows] == [p["timestamp"] for p in expected]


def _counting_connection(path):
    """
    A connection prepared exactly as Datasette's is, counting `parse_when`.

    Goes through `functions.prepare_connection` rather than registering a local
    function, so the determinism flags and arities under test are production's.
    """
    calls = []
    original = fns.SQL_FUNCTIONS

    def counting(text):
        calls.append(text)
        return original["parse_when"][1](text)

    conn = sqlite3.connect(path)
    try:
        fns.SQL_FUNCTIONS = dict(original, parse_when=(1, counting, False))
        fns.prepare_connection(conn)
    finally:
        fns.SQL_FUNCTIONS = original
    return conn, calls


def test_each_bound_is_resolved_exactly_once_per_statement(populated_db):
    """
    The materialized CTE pins the bound; every comparison site reads that value.

    `top_artists` has four bound comparison sites -- the ranked rows and the
    scalar subquery computing the period total each carry both predicates --
    over ten rows. Without the CTE those resolve independently, and a statement
    straddling a cache generation boundary can total one range while ranking
    another (design D5).
    """
    entries = time_ranged_entries()
    assert entries, "no time-ranged entries found; the loop below would be vacuous"

    conn, calls = _counting_connection(str(populated_db))
    try:
        for entry in entries:
            calls.clear()
            conn.execute(
                entry.sql,
                {
                    "since": "2023-01-01T00:00:00+00:00",
                    "until": "2025-01-01T00:00:00+00:00",
                    **{
                        name: ""
                        for name in re.findall(r":(\w+)", entry.sql)
                        if name not in cat.BOUND_PARAMETERS
                    },
                },
            ).fetchall()
            assert len(calls) == len(cat.BOUND_PARAMETERS), (
                f"{entry.name}: expected one resolution per bound, "
                f"got {len(calls)}: {calls}"
            )
    finally:
        conn.close()


def test_without_the_cte_a_bound_resolves_more_than_once(populated_db):
    """
    Evidence the test above is not vacuous.

    The naive rewrite -- `parse_when` at each comparison site -- is applied to
    the same builder output and counted the same way. If it resolved once too,
    the CTE would be decoration.
    """
    entry = next(entry for entry in cat.CATALOG if entry.name == "top_artists")
    sql, _params = entry.builder(form=domain_queries.SQL_FORM_NAMED)
    for name in cat.BOUND_PARAMETERS:
        sql = cat._guard_pattern(name).sub(
            lambda m, name=name: (
                f"(:{name} = '' OR {m['column']} {m['op']} parse_when(:{name}))"
            ),
            sql,
        )

    conn, calls = _counting_connection(str(populated_db))
    try:
        conn.execute(
            sql,
            {
                "since": "2023-01-01T00:00:00+00:00",
                "until": "2025-01-01T00:00:00+00:00",
                "limit": "",
            },
        ).fetchall()
    finally:
        conn.close()

    assert len(calls) > len(cat.BOUND_PARAMETERS), (
        f"the naive form resolved only {len(calls)} times, so the CTE proves nothing"
    )
