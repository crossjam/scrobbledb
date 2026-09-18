"""
Tests for the stored-query catalog served by the scrobbledb Datasette plugin.

Three properties are load-bearing and each is checked through the production
seam -- the real plugin module registered with Datasette's global plugin
manager, the real hook, the real HTTP surface:

- **The catalog is complete and projected.** Every entry is discoverable from
  the database index with its description, and returns the rows we expect
  against a populated database, not merely a 200 with nothing in it.

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
from html import unescape
from urllib.parse import unquote

import pytest
import sqlite_utils

from scrobbledb import domain_queries, lastfm
from scrobbledb.datasette_plugin import functions as fns
from scrobbledb.datasette_plugin import queries as cat
from scrobbledb.domain_queries import VARIOUS_ARTISTS

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


def _populate(path):
    """The shared fixture content, without a search index. Returns an open db."""
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
    return db


@pytest.fixture
def populated_db(tmp_path):
    """
    A populated scrobbledb database: 10 plays, 2 artists, 3 albums, 5 tracks,
    with the search index built.

    The index is built through the production seam -- the same two functions
    `scrobbledb index` calls -- rather than by a hand-written CREATE VIRTUAL
    TABLE, so a change to the indexed columns reaches this fixture.
    """
    path = tmp_path / "scrobbles.db"
    db = _populate(path)
    lastfm.setup_fts5(db)
    lastfm.rebuild_fts5(db)
    db.conn.commit()
    db.close()
    return path


@pytest.fixture
def unindexed_db(tmp_path):
    """The same database with the base tables but no search index built."""
    path = tmp_path / "scrobbles.db"
    db = _populate(path)
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


#: How many stored queries 1.0a39's *rendered* listing puts on one page. The
#: JSON listing honours `limit` up to 1000; the HTML one ignores it and
#: paginates with `_next` instead, so a catalog larger than this is only wholly
#: visible by following the link. Asserted, not assumed -- if a later alpha
#: renders them all, `_whole_rendered_listing` still works and this constant is
#: what says the behaviour changed.
RENDERED_LISTING_PAGE_SIZE = 20

_NEXT_LINK = re.compile(r'href="[^"]*?/-/queries\?[^"]*?_next=([^"&]+)"')


async def _whole_rendered_listing(ds, database) -> str:
    """
    The rendered stored-query listing, every page of it, concatenated.

    Following `_next` rather than raising `limit`, because the HTML listing
    ignores `limit`. The loop is bounded by the catalog size so a paginator that
    ever pointed at itself fails the test instead of hanging it.
    """
    pages = []
    params = {}
    for _ in range(len(cat.CATALOG) + 1):
        page = await ds.client.get(f"/{database}/-/queries", params=params)
        assert page.status_code == 200, page.text
        pages.append(page.text)
        match = _NEXT_LINK.search(page.text)
        if not match:
            return "".join(pages)
        params = {"_next": unquote(match.group(1))}
    raise AssertionError("the stored-query listing never stopped paginating")


# --------------------------------------------------------------------------
# 3.1 -- the catalog itself
# --------------------------------------------------------------------------

#: The catalog must stay at least this large. A floor rather than an equality
#: so the pending 3.5/3.6 entries can be added without touching this test,
#: while a silently emptied catalog still fails.
CATALOG_FLOOR = 22


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


def test_the_rewrite_refuses_a_bound_it_recognizes_nowhere():
    """
    The fail-open case: *no* bound is in the shape the rewrite knows.

    Nothing matches, so there is nothing to rewrite and nothing to wrap -- and
    an early "no bounds here" return would hand SQLite a query comparing
    `plays.timestamp` against the literal string `last march`. Bounds are
    therefore checked before that return, not after it.
    """
    for sql in (
        "SELECT * FROM plays WHERE plays.timestamp >= :since",
        "SELECT * FROM plays WHERE (:until = '' OR date(plays.timestamp) <= :until)",
    ):
        with pytest.raises(ValueError, match="parse_when"):
            cat.resolve_time_bounds_once(sql)

    # Still unchanged when there is genuinely no bound to route.
    unbounded = "SELECT COUNT(*) FROM plays"
    assert cat.resolve_time_bounds_once(unbounded) == unbounded


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
async def test_every_entry_is_discoverable_from_the_database_index(
    registered_plugin, populated_db
):
    """
    The hook registers the whole catalog and a reader can find all of it.

    What "listed on the database index page" means is decided by 1.0a39, not
    by us: the index renders the first *five* stored queries -- name, and
    description as the link's title -- and then a "View N queries" link to the
    database's complete listing at `/<db>/-/queries`. Discovery is therefore
    those two pages together, and both halves are asserted: the count the index
    advertises must be the whole catalog (an entry that failed to register is
    caught right there), the entries it does render must carry their
    descriptions, and the listing it points at must carry every entry with its
    title and description.

    The exact text is read from the listing's JSON; the rendered pages are
    unescaped before being searched, since the quotes some descriptions carry
    come back as entities.
    """
    ds = await serve(populated_db)
    database = populated_db.stem

    index = await ds.client.get(f"/{database}")
    assert index.status_code == 200
    assert 'id="queries"' in index.text, "the index page has no queries section"
    assert f"View {len(cat.CATALOG):,} queries" in index.text, (
        "the index page does not advertise the whole catalog"
    )

    response = await ds.client.get(
        f"/{database}/-/queries.json", params={"limit": 1000}
    )
    assert response.status_code == 200, response.text
    listed = {query["name"]: query for query in response.json()["queries"]}

    for entry in cat.CATALOG:
        assert entry.name in listed, f"{entry.name} is not listed for the database"
        assert listed[entry.name]["title"] == entry.title
        assert listed[entry.name]["description"] == entry.description

    # The entries the index page itself renders carry their description as the
    # link title, which is how 1.0a39's index shows one.
    rendered_index = unescape(index.text)
    shown = [name for name in listed if f"/{database}/{name}" in rendered_index]
    assert shown, "the index page rendered none of the catalog"
    for name in shown:
        assert listed[name]["description"] in rendered_index, (
            f"{name} is shown on the index page without its description"
        )

    rendered_listing = unescape(await _whole_rendered_listing(ds, database))
    for entry in cat.CATALOG:
        assert f"/{database}/{entry.name}" in rendered_listing, (
            f"{entry.name} is not linked from the rendered listing"
        )
        assert entry.description in rendered_listing, (
            f"{entry.name} is listed without its description"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "schema, why",
    [
        (
            ["CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)"],
            "no scrobble tables at all",
        ),
        (
            ["CREATE TABLE plays (id INTEGER PRIMARY KEY, script TEXT)"],
            "a plays table of its own, but none of the rest of the schema",
        ),
        (
            [
                "CREATE TABLE plays (id INTEGER PRIMARY KEY, script TEXT)",
                "CREATE TABLE tracks (id INTEGER PRIMARY KEY, gauge TEXT)",
                "CREATE TABLE albums (id INTEGER PRIMARY KEY, photographer TEXT)",
                "CREATE TABLE artists (id INTEGER PRIMARY KEY, medium TEXT)",
            ],
            "all four table names, none of the columns",
        ),
    ],
)
async def test_an_unrelated_database_gets_no_stored_queries(
    registered_plugin, tmp_path, schema, why
):
    """
    The catalog is only projected onto databases carrying the scrobble schema.

    Every entry but the play history joins through `tracks`, `albums` and
    `artists`, so recognising a database by its `plays` table alone would give
    a theatre-scripts database sixteen trusted queries that can only raise
    "no such table". Table names alone are not enough either: a gallery
    database whose four tables happen to share those names fails just as
    completely, only at execution time instead of registration time.
    """
    path = tmp_path / "unrelated.db"
    db = sqlite_utils.Database(path)
    for statement in schema:
        db.execute(statement)
    db.conn.commit()
    db.close()

    ds = await serve(path)
    response = await ds.client.get(f"/{path.stem}/-/queries.json")
    assert response.status_code == 200, response.text
    assert response.json()["queries"] == [], f"queries registered on {why}"


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
    "daily_rollup": {},
    "listening_clock": {},
    "weekday_rollup": {},
    "streaks": {},
    "discovery": {},
    "search": {"q": "Track"},
}


@pytest.mark.asyncio
async def test_the_rendered_listing_paginates_rather_than_showing_everything(
    registered_plugin, populated_db
):
    """
    Pin the surface `_whole_rendered_listing` exists to work around.

    The catalog outgrew one rendered page. `limit` raises the cap on the JSON
    listing but is ignored entirely by the HTML one, which is why following
    `_next` is the only way to see all of it -- so `limit` is passed here in
    three forms and asserted to change nothing. If a later Datasette renders
    them all, this is what says so, rather than the discovery test failing for a
    reason that looks like ours.
    """
    assert len(cat.CATALOG) > RENDERED_LISTING_PAGE_SIZE, (
        "the catalog no longer exercises pagination; this test proves nothing"
    )
    ds = await serve(populated_db)
    database = populated_db.stem

    for params in ({}, {"limit": len(cat.CATALOG)}, {"limit": 1000}):
        page = await ds.client.get(f"/{database}/-/queries", params=params)
        linked = {
            entry.name
            for entry in cat.CATALOG
            if f"/{database}/{entry.name}" in page.text
        }
        assert len(linked) == RENDERED_LISTING_PAGE_SIZE, (
            f"the rendered listing showed {len(linked)} entries for {params}"
        )
        assert _NEXT_LINK.search(page.text), "a truncated listing must link onward"


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


# --------------------------------------------------------------------------
# 3.4 -- album aggregates through the catalog
# --------------------------------------------------------------------------

_GROUP_BY = re.compile(
    r"(?is)\bGROUP\s+BY\s+(?P<clause>.+?)"
    r"(?=\bHAVING\b|\bORDER\s+BY\b|\bLIMIT\b|\bWINDOW\b|\)|\Z)"
)
_QUALIFIED = re.compile(r"\b([A-Za-z_]\w*)\.\w+")


def album_aggregate_entries():
    """
    Catalog entries that report one row per album, discovered from their SQL.

    An entry aggregates albums when it has a GROUP BY whose only qualified
    columns belong to `albums` -- which is true of the album listing and the
    album ranking and would be true of any future one, and false for the track
    and artist aggregates that merely mention `albums.title` in their grouping.
    """
    found = []
    for entry in cat.CATALOG:
        for match in _GROUP_BY.finditer(entry.sql):
            clause = match.group("clause")
            tables = set(_QUALIFIED.findall(clause))
            if tables == {"albums"}:
                found.append((entry, " ".join(clause.split())))
                break
    return found


def test_album_aggregates_are_discoverable():
    """The discovery finds the aggregates we know about, and does not stop there."""
    found = {entry.name for entry, _clause in album_aggregate_entries()}
    assert {"album_list", "top_albums"} <= found, f"discovery missed one: {found}"
    assert len(found) >= 2


def test_every_album_aggregate_groups_on_title_and_derives_its_artist():
    """
    Grouping on `albums.id` fails to collapse synthesized aliases, and an
    independent `MAX(artists.name)` names an artist that may not own the group.
    Neither may appear in any album aggregate the catalog exposes (task 2.5).
    """
    aggregates = album_aggregate_entries()
    assert aggregates, "no album aggregates found; the assertions would be vacuous"

    for entry, clause in aggregates:
        assert clause == "albums.title COLLATE NOCASE", (
            f"{entry.name} groups albums by {clause!r}"
        )
        normalized = " ".join(entry.sql.split())
        assert "COUNT(DISTINCT artists.name COLLATE NOCASE) = 1" in normalized, (
            f"{entry.name} does not derive artist_name from the group"
        )
        assert f"'{VARIOUS_ARTISTS}'" in normalized, (
            f"{entry.name} has no sentinel for a group spanning several artists"
        )


@pytest.mark.asyncio
async def test_album_aggregates_hold_through_the_catalog(
    registered_plugin, album_identity_db
):
    """
    The corrected attribution survives the projection into stored queries.

    Checked for every discovered album aggregate rather than the two we happen
    to ship, so a future one inherits the coverage.
    """
    ds = await serve(album_identity_db)
    database = album_identity_db.stem

    for entry, _clause in album_aggregate_entries():
        rows = await run_query(ds, database, entry.name, **PARAMETERS_FOR[entry.name])
        by_title = {}
        for row in rows:
            by_title.setdefault(row["album_title"].lower(), []).append(row)

        # A compilation stays one row and names nobody in particular.
        assert len(by_title["the dj mix"]) == 1, f"{entry.name} split the compilation"
        mix = by_title["the dj mix"][0]
        assert mix["artist_name"] == VARIOUS_ARTISTS, (
            f"{entry.name} credited the mix to {mix['artist_name']!r}"
        )
        assert set(mix["album_ids"].split(",")) == {
            "md5:zmix",
            "md5:amix",
            "md5:bmix",
        }, f"{entry.name} lost identifiers from the mix group"
        assert mix["play_count"] == 3, f"{entry.name} split the mix's plays"

        # Duplicate identifiers collapse, and one artist under several artist
        # ids is still named rather than reported as Various Artists.
        assert len(by_title["doubles"]) == 1, f"{entry.name} failed to collapse aliases"
        doubles = by_title["doubles"][0]
        assert doubles["artist_name"] == "Solo Artist", (
            f"{entry.name} declined to name a single-artist group"
        )
        assert set(doubles["album_ids"].split(",")) == {
            "zzz-doubles",
            "md5:aaadoubles",
        }
        assert doubles["play_count"] == 4, (
            f"{entry.name} counted only one identifier's plays"
        )


@pytest.mark.asyncio
async def test_no_album_aggregate_names_an_artist_that_does_not_own_it(
    registered_plugin, album_identity_db
):
    """
    The invariant behind the two cases above, asserted over every returned row.

    A named artist owns every identifier in its group; otherwise the row names
    nobody. This is what the original `MAX(albums.id)`/`MAX(artists.name)` pair
    violated on 909 rows of the live database.
    """
    db = sqlite_utils.Database(album_identity_db)
    try:
        owner = dict(
            db.execute(
                "SELECT albums.id, artists.name FROM albums"
                " JOIN artists ON albums.artist_id = artists.id"
            ).fetchall()
        )
    finally:
        db.close()

    ds = await serve(album_identity_db)
    for entry, _clause in album_aggregate_entries():
        rows = await run_query(
            ds, album_identity_db.stem, entry.name, **PARAMETERS_FOR[entry.name]
        )
        assert rows, f"{entry.name} returned nothing to check"
        for row in rows:
            owners = {owner[album_id] for album_id in row["album_ids"].split(",")}
            if row["artist_name"] == VARIOUS_ARTISTS:
                assert len(owners) > 1, (
                    f"{entry.name}: sentinel used for a single-artist group: {row}"
                )
            else:
                assert owners == {row["artist_name"]}, (
                    f"{entry.name}: false attribution: {row}"
                )


# --------------------------------------------------------------------------
# 3.5 -- the analytics the CLI does not have
# --------------------------------------------------------------------------

#: A deliberately uneven history, because the shared `populated_db` fixture
#: cannot tell a right answer from a wrong one here: it has exactly one play on
#: each of ten days, so `COUNT(*)` and `COUNT(DISTINCT tracks.id)` agree, a
#: streak's length equals its play count, and every hour bucket holds one row.
#:
#: This one breaks all three ties. 2024-01-01 carries three plays of two tracks
#: by one artist, so the day's counts are three different numbers; 01-01 to
#: 01-03 is a three-day run holding five plays, so a streak that numbered rows
#: over plays rather than distinct days would split it; and two plays share an
#: hour while falling on different days.
ANALYTICS_PLAYS = (
    ("2024-01-01T09:00:00+00:00", "t1"),
    ("2024-01-01T09:30:00+00:00", "t1"),
    ("2024-01-01T22:00:00+00:00", "t2"),
    ("2024-01-02T09:00:00+00:00", "t3"),
    ("2024-01-03T09:00:00+00:00", "t1"),
    ("2024-02-10T09:00:00+00:00", "t1"),
)


@pytest.fixture
def analytics_db(tmp_path):
    """A small history shaped to discriminate the analytics entries."""
    path = tmp_path / "analytics.db"
    db = sqlite_utils.Database(path)
    _create_schema(db)
    db["artists"].insert_all(
        [{"id": "a1", "name": "Artist One"}, {"id": "a2", "name": "Artist Two"}]
    )
    db["albums"].insert_all(
        [
            {"id": "alb1", "title": "Album One", "artist_id": "a1"},
            {"id": "alb2", "title": "Album Two", "artist_id": "a2"},
        ]
    )
    db["tracks"].insert_all(
        [
            {"id": "t1", "title": "Track One", "album_id": "alb1"},
            {"id": "t2", "title": "Track Two", "album_id": "alb1"},
            {"id": "t3", "title": "Track Three", "album_id": "alb2"},
        ]
    )
    db["plays"].insert_all(
        [{"timestamp": ts, "track_id": track} for ts, track in ANALYTICS_PLAYS]
    )
    lastfm.setup_fts5(db)
    lastfm.rebuild_fts5(db)
    db.conn.commit()
    db.close()
    return path


@pytest.mark.asyncio
async def test_daily_rollup_counts_each_day_separately(
    registered_plugin, analytics_db
):
    """
    One row per day with plays, most recent first, with distinct-entity counts.

    2024-01-01's three values differ, so a rollup that reported plays where it
    means distinct tracks -- or the reverse -- fails here.
    """
    ds = await serve(analytics_db)
    rows = await run_query(ds, analytics_db.stem, "daily_rollup")

    assert [
        (r["day"], r["scrobbles"], r["unique_artists"], r["unique_albums"],
         r["unique_tracks"])
        for r in rows
    ] == [
        ("2024-02-10", 1, 1, 1, 1),
        ("2024-01-03", 1, 1, 1, 1),
        ("2024-01-02", 1, 1, 1, 1),
        ("2024-01-01", 3, 1, 1, 2),
    ]


@pytest.mark.asyncio
async def test_listening_clock_buckets_plays_by_hour(registered_plugin, analytics_db):
    """
    Hours ascending, in UTC, with empty hours absent.

    Four of the six plays are at 09:00 and one at 09:30, so the 09 bucket
    holding five is what distinguishes counting plays from counting days.
    """
    ds = await serve(analytics_db)
    rows = await run_query(ds, analytics_db.stem, "listening_clock")

    assert [(r["hour"], r["scrobbles"]) for r in rows] == [(9, 5), (22, 1)]
    assert len(rows) <= 24


@pytest.mark.asyncio
async def test_weekday_rollup_is_monday_first(registered_plugin, analytics_db):
    """
    Weekdays ascending from Monday, each with its name.

    2024-01-01 is a Monday carrying three plays. Under SQLite's own Sunday-first
    `strftime('%w')` it would be weekday 1 and Saturday would be 6, so this
    fixture fails on the wrong convention rather than merely renaming rows.
    """
    ds = await serve(analytics_db)
    rows = await run_query(ds, analytics_db.stem, "weekday_rollup")

    assert [(r["weekday"], r["weekday_name"], r["scrobbles"]) for r in rows] == [
        (0, "Monday", 3),
        (1, "Tuesday", 1),
        (2, "Wednesday", 1),
        (5, "Saturday", 1),
    ]


@pytest.mark.asyncio
async def test_streaks_are_runs_of_consecutive_days(registered_plugin, analytics_db):
    """
    Consecutive-day runs, longest first, with length and play count separate.

    The three-day run holds five plays. A streak query that numbered rows over
    plays instead of distinct days would see the two 2024-01-01 plays consume
    two row numbers and report the run as broken.
    """
    ds = await serve(analytics_db)
    rows = await run_query(ds, analytics_db.stem, "streaks")

    assert [
        (r["start_date"], r["end_date"], r["days"], r["scrobbles"]) for r in rows
    ] == [
        ("2024-01-01", "2024-01-03", 3, 5),
        ("2024-02-10", "2024-02-10", 1, 1),
    ]


@pytest.mark.asyncio
async def test_discovery_reports_each_artists_first_play(
    registered_plugin, analytics_db
):
    """
    One row per artist with its earliest play, most recently discovered first.

    Artist One is played on 01-01 and again on 01-03 and 02-10, so a query
    reporting the *latest* play would put it first and carry 2024-02-10.
    """
    ds = await serve(analytics_db)
    rows = await run_query(ds, analytics_db.stem, "discovery")

    assert [(r["artist_id"], r["first_played"]) for r in rows] == [
        ("a2", "2024-01-02T09:00:00+00:00"),
        ("a1", "2024-01-01T09:00:00+00:00"),
    ]


@pytest.mark.asyncio
async def test_the_analytics_entries_accept_bounds_like_every_other(
    registered_plugin, analytics_db
):
    """
    The new entries take the same optional bounds as the rest of the catalog.

    Bounding to January alone drops the isolated February day from every one of
    them, which is the cheapest thing that fails if an entry were registered
    from a builder whose bounds the catalog could not rewrite.
    """
    ds = await serve(analytics_db)
    database = analytics_db.stem
    bounds = {"since": "2024-01-01", "until": "2024-01-31"}

    assert len(await run_query(ds, database, "daily_rollup", **bounds)) == 3
    assert await run_query(ds, database, "listening_clock", **bounds) == [
        {"hour": 9, "scrobbles": 4},
        {"hour": 22, "scrobbles": 1},
    ]
    assert [r["days"] for r in await run_query(ds, database, "streaks", **bounds)] == [3]


# --------------------------------------------------------------------------
# 3.6 -- full-text search
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_matches_across_artist_album_and_track(
    registered_plugin, populated_db
):
    """
    One term searches all three names at once.

    `Three` is the title of a track and a word in a different album's title, so
    a search of the track column alone returns one row and a search of the album
    column alone returns two. Only searching all three returns all three rows.
    """
    ds = await serve(populated_db)
    rows = await run_query(ds, populated_db.stem, "search", q="Three")

    assert {r["track_id"] for r in rows} == {"t3", "t4", "t5"}
    assert all(
        r["artist_name"] and r["album_title"] and r["track_title"] for r in rows
    )


@pytest.mark.asyncio
async def test_search_matches_a_prefix(registered_plugin, populated_db):
    """A partial word finds what it starts, so a search box works as typed."""
    ds = await serve(populated_db)
    rows = await run_query(ds, populated_db.stem, "search", q="Art")

    assert len(rows) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "term", ["zzzznothinghere", "*", "**", '"', 'a"b', "OR", "NEAR(", "^", "-", ""]
)
async def test_search_returns_an_empty_result_set_rather_than_an_error(
    registered_plugin, populated_db, term
):
    """
    A term that matches nothing returns no rows, and does not fail.

    The list is not only terms that fail to match: most of these are fts5
    *syntax* errors on a bare `MATCH ?`, and an empty term is what Datasette
    sends for a parameter the user left blank. All of them have to come back as
    an empty result set, because a search box that 500s on a stray quote is
    worse than one that finds nothing.
    """
    ds = await serve(populated_db)
    assert await run_query(ds, populated_db.stem, "search", q=term) == []


# --------------------------------------------------------------------------
# 3.7 -- the search index is not built
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_without_an_index_names_the_command_that_builds_it(
    registered_plugin, unindexed_db
):
    """
    On a database with the scrobble tables but no search index, the search
    entry fails with a message naming `scrobbledb index`.

    The bare SQLite error for this is `no such table: tracks_fts`, which tells
    a user nothing about how to obtain one -- so the message, not merely the
    failure, is what is asserted.
    """
    ds = await serve(unindexed_db)
    response = await ds.client.get(
        f"/{unindexed_db.stem}/search.json", params={"q": "Track"}
    )

    assert response.status_code != 200, "search must fail without an index"
    assert "scrobbledb index" in response.text, response.text


@pytest.mark.asyncio
async def test_the_rest_of_the_catalog_still_works_without_an_index(
    registered_plugin, unindexed_db
):
    """
    Only the entry that needs the index is affected.

    A missing index is the normal state of a freshly ingested database, so
    withholding the whole catalog over it -- or failing startup -- would make
    the server useless exactly when it is first opened.
    """
    ds = await serve(unindexed_db)
    database = unindexed_db.stem

    for entry in cat.CATALOG:
        if entry.requires_table is not None:
            continue
        rows = await run_query(ds, database, entry.name, **PARAMETERS_FOR[entry.name])
        assert rows, f"{entry.name} returned no rows without a search index"


@pytest.mark.asyncio
async def test_an_entry_with_its_prerequisite_present_runs_the_real_query(
    registered_plugin, populated_db
):
    """
    The substitution is conditional, not permanent.

    Without this the 3.7 test above would pass just as well against a catalog
    that had replaced the search entry with the error unconditionally.
    """
    ds = await serve(populated_db)
    rows = await run_query(ds, populated_db.stem, "search", q="Track")

    assert len(rows) == 5


def test_only_the_search_entry_declares_a_prerequisite():
    """
    Derived rather than typed, so a second prerequisite entry is noticed.

    Any entry naming a `requires_table` must also carry the hint that explains
    how to get it, since the hint is the entire point of the mechanism.
    """
    with_prerequisites = [e for e in cat.CATALOG if e.requires_table is not None]

    assert [e.name for e in with_prerequisites] == ["search"]
    for entry in with_prerequisites:
        assert entry.missing_hint, f"{entry.name} has no missing_hint"
        assert "scrobbledb" in entry.missing_hint, (
            f"{entry.name}'s hint must name the command that builds "
            f"{entry.requires_table}"
        )


def test_the_missing_table_sql_carries_the_hint_into_the_error(unindexed_db):
    """
    The mechanism itself: SQLite reports the hint as the unresolved name.

    Asserted directly against sqlite3 as well as over HTTP, because this rests
    on how SQLite words one specific error, and that is the assumption most
    worth failing loudly if a future SQLite reworded it.
    """
    sql = cat.missing_table_sql("tracks_fts is not built; run `scrobbledb index`")
    conn = sqlite3.connect(unindexed_db)
    try:
        with pytest.raises(sqlite3.OperationalError) as caught:
            conn.execute(sql)
    finally:
        conn.close()

    assert "scrobbledb index" in str(caught.value)
