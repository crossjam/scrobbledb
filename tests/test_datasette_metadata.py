"""
Tests for the packaged metadata and config the server is constructed with.

The property under test is the 1.0 split of design D9, and it is the kind that
fails silently. `Datasette.__init__` migrates the config-shaped keys out of
`metadata` for you, so a single combined file appears to work; the reverse has
no such shim, and a table description routed through `config=` renders nothing
at all -- no warning, no error, just a table page with no description on it.
Every check here is therefore against what the *page* shows or what the server
*does*, never against the parsed document alone, which would agree with itself
whichever argument it had been handed to.
"""

import sqlite3
import threading
import time
from html import unescape

import pytest

pytest.importorskip("datasette")
pytest.importorskip("pytest_asyncio")

import sqlite_utils  # noqa: E402

from scrobbledb.datasette_plugin import config as cfg  # noqa: E402
from scrobbledb.datasette_plugin import queries as cat  # noqa: E402
from scrobbledb.datasette_plugin import readonly  # noqa: E402

from tests import test_datasette_queries as catalog_tests  # noqa: E402

populated_db = catalog_tests.populated_db
registered_plugin = catalog_tests.registered_plugin
unindexed_db = catalog_tests.unindexed_db

DATABASE = "scrobbles"

#: The tables a reader should be offered. Written out rather than derived from
#: the metadata file, because the metadata file is one of the things under test:
#: derived from it, this would pass while describing a table that does not exist
#: and hiding one that does.
BROWSABLE_TABLES = {"artists", "albums", "tracks", "plays", "tracks_fts"}

#: The five FTS5 shadow tables, which are storage rather than content.
SHADOW_TABLES = {
    "tracks_fts_data",
    "tracks_fts_idx",
    "tracks_fts_content",
    "tracks_fts_docsize",
    "tracks_fts_config",
}


async def serve_configured(path, name=DATABASE, **overrides):
    """A started Datasette carrying the packaged metadata and config."""
    from datasette.app import Datasette

    kwargs = {
        "metadata": cfg.load_metadata(name),
        "config": cfg.load_config(name),
    }
    kwargs.update(overrides)
    ds = Datasette(**kwargs)
    readonly.add_read_only_database(ds, path, name=name)
    await ds.invoke_startup()
    return ds


def first_clause(description):
    """
    The opening clause of a description, as a substring to look for on a page.

    Long enough to be distinctive, short enough to survive the renderer's line
    wrapping and the folded-scalar joining that YAML has already done.
    """
    return " ".join(description.split())[:60]


# --------------------------------------------------------------------------
# 6.1 -- descriptions are packaged, loaded, and actually rendered
# --------------------------------------------------------------------------


def test_every_described_table_exists_in_the_schema(populated_db):
    """
    A description for a table nobody has is a description nobody reads.

    Derived from the metadata document, so adding an entry for a table the
    schema does not carry fails here rather than going unnoticed on a page that
    is never visited.
    """
    described = set(cfg.load_metadata(DATABASE)["databases"][DATABASE]["tables"])
    actual = set(sqlite_utils.Database(populated_db).table_names())

    assert described - actual == set(), f"described but absent: {described - actual}"
    assert described == BROWSABLE_TABLES


@pytest.mark.asyncio
async def test_every_table_description_renders_on_its_page(
    registered_plugin, populated_db
):
    """
    Each described table shows its description where a reader would look.

    Iterates the metadata document rather than naming four tables, so a table
    described later is covered the day it is described.
    """
    metadata = cfg.load_metadata(DATABASE)["databases"][DATABASE]["tables"]
    ds = await serve_configured(populated_db)
    try:
        for table, entry in metadata.items():
            page = await ds.client.get(f"/{DATABASE}/{table}")
            assert page.status_code == 200, f"{table}: {page.status_code}"
            assert first_clause(entry["description"]) in unescape(page.text), (
                f"{table} renders without its description"
            )
    finally:
        ds.close()


#: Columns a reader will actively misread without a note, taken from the
#: requirement ("columns whose meaning is not obvious from their name are
#: described") rather than from the metadata file. Iterating the file alone
#: cannot catch a deletion -- removing a description removes its own check with
#: it -- so this is the half that says which ones have to be there.
REQUIRED_COLUMN_DESCRIPTIONS = {
    # Half of these are `md5:` identifiers synthesized from names, so the same
    # entity exists under several ids and counting rows overstates the total.
    ("artists", "id"),
    ("albums", "id"),
    ("tracks", "id"),
    # Not the album's artist: one contributor of one track on it.
    ("albums", "artist_id"),
    # A UTC ISO 8601 string, sortable as text, half of a composite primary key
    # that silently drops a repeat play within the same second.
    ("plays", "timestamp"),
}


def test_the_columns_that_mislead_are_described():
    """The non-obvious columns carry a note, whatever else the file describes."""
    tables = cfg.load_metadata(DATABASE)["databases"][DATABASE]["tables"]
    described = {
        (table, column)
        for table, entry in tables.items()
        for column in (entry.get("columns") or {})
    }
    missing = sorted(REQUIRED_COLUMN_DESCRIPTIONS - described)
    assert missing == [], f"columns left undescribed: {missing}"


@pytest.mark.asyncio
async def test_every_column_description_renders_on_its_page(
    registered_plugin, populated_db
):
    """The per-column `columns` mapping reaches the page too, not just tables."""
    metadata = cfg.load_metadata(DATABASE)["databases"][DATABASE]["tables"]
    described = {
        (table, column): text
        for table, entry in metadata.items()
        for column, text in (entry.get("columns") or {}).items()
    }
    assert described, "no column descriptions to check; the fixture is vacuous"

    ds = await serve_configured(populated_db)
    try:
        pages = {}
        for table, _column in described:
            if table not in pages:
                pages[table] = unescape((await ds.client.get(f"/{DATABASE}/{table}")).text)
        for (table, column), text in described.items():
            assert first_clause(text) in pages[table], (
                f"{table}.{column} renders without its description"
            )
    finally:
        ds.close()


@pytest.mark.asyncio
async def test_descriptions_render_from_metadata_and_not_from_config(
    registered_plugin, populated_db
):
    """
    The D9 trap, pinned: `config=` swallows descriptions without complaining.

    This is the control that makes the test above mean something. Handed the
    same document through the other argument, the page comes back 200 with the
    description simply gone -- so a test that only asserted "the description is
    in the file" would pass on a server that shows none of them.
    """
    metadata = cfg.load_metadata(DATABASE)
    description = first_clause(
        metadata["databases"][DATABASE]["tables"]["plays"]["description"]
    )

    ds = await serve_configured(populated_db)
    try:
        correct = unescape((await ds.client.get(f"/{DATABASE}/plays")).text)
    finally:
        ds.close()
    assert description in correct

    ds = await serve_configured(populated_db, metadata=None, config=metadata)
    try:
        misrouted = unescape((await ds.client.get(f"/{DATABASE}/plays")).text)
    finally:
        ds.close()
    assert description not in misrouted, (
        "1.0a39 now renders descriptions from config=; D9's split may have changed"
    )


def test_the_two_files_do_not_overlap():
    """
    Each key is in the file Datasette reads it from, and in only one of them.

    The config-side key list is imported from Datasette rather than copied, so
    if a future alpha moves a key across the split this fails instead of
    quietly leaving a setting in the file that no longer reads it.
    """
    from datasette.utils import _table_config_keys

    metadata_tables = cfg.load_metadata(DATABASE)["databases"][DATABASE]["tables"]
    config_tables = cfg.load_config(DATABASE)["databases"][DATABASE]["tables"]

    for table, entry in metadata_tables.items():
        stray = set(entry) & set(_table_config_keys)
        assert stray == set(), f"{table} carries config keys in metadata.yaml: {stray}"

    for table, entry in config_tables.items():
        stray = set(entry) & {"description", "description_html", "title", "columns"}
        assert stray == set(), f"{table} carries metadata keys in datasette.yaml: {stray}"
        assert set(entry) <= set(_table_config_keys), (
            f"{table} carries keys Datasette does not read from config: "
            f"{set(entry) - set(_table_config_keys)}"
        )


def test_the_database_placeholder_is_substituted_not_left_behind():
    """
    Both documents name the served database, whatever the user called the file.

    A leftover `$DATABASE` key is the failure mode that renders nothing while
    parsing perfectly, so it is asserted absent rather than merely assumed.
    """
    for loader in (cfg.load_metadata, cfg.load_config):
        document = loader("some_users_file")
        assert set(document["databases"]) == {"some_users_file"}
        assert cfg.DATABASE_PLACEHOLDER not in document["databases"]


# --------------------------------------------------------------------------
# 6.2 -- the shadow tables are storage, not content
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_index_lists_exactly_the_scrobble_tables(
    registered_plugin, populated_db
):
    """
    Four tables and a search index, and nothing that is merely how it is stored.

    Datasette 1.0a39 hides FTS5 shadow tables on its own, so this passes with
    an empty config too -- which is why `datasette.yaml` names them anyway:
    the requirement is this project's, and the alpha's detection heuristic is
    not something to inherit it from. What this asserts is the requirement.
    """
    ds = await serve_configured(populated_db)
    try:
        index = (await ds.client.get(f"/{DATABASE}.json")).json()
        visible = {t["name"] for t in index["tables"] if not t["hidden"]}
        hidden = {t["name"] for t in index["tables"] if t["hidden"]}

        assert visible == BROWSABLE_TABLES
        assert SHADOW_TABLES <= hidden

        rendered = unescape((await ds.client.get(f"/{DATABASE}")).text)
        for shadow in SHADOW_TABLES:
            assert f"/{DATABASE}/{shadow}" not in rendered, (
                f"{shadow} is linked from the index page"
            )
    finally:
        ds.close()


def test_the_config_names_every_shadow_table_the_schema_has(populated_db):
    """
    The hidden list and the database's actual shadow tables are the same set.

    Derived from `sqlite_master` rather than typed twice, so an FTS5 version
    that adds a sixth shadow table fails here instead of leaking it onto the
    index page the day Datasette's own detection misses it.
    """
    db = sqlite_utils.Database(populated_db)
    actual = {
        name
        for name in db.table_names()
        if name.startswith("tracks_fts_")
    }
    db.close()
    assert actual, "the fixture has no FTS index; this check would be vacuous"

    config_tables = cfg.load_config(DATABASE)["databases"][DATABASE]["tables"]
    hidden = {name for name, entry in config_tables.items() if entry.get("hidden")}

    assert hidden == actual == SHADOW_TABLES


# --------------------------------------------------------------------------
# 6.3 -- a listening history reads as a timeline
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plays_defaults_to_most_recent_first(registered_plugin, populated_db):
    """
    The unsorted `plays` page is in descending timestamp order.

    The fixture is asserted to have more than one distinct timestamp first,
    because a single-row answer is in descending order by accident.
    """
    ds = await serve_configured(populated_db)
    try:
        rows = (await ds.client.get(f"/{DATABASE}/plays.json?_shape=array")).json()
    finally:
        ds.close()

    timestamps = [row["timestamp"] for row in rows]
    assert len(set(timestamps)) > 1, "fixture has one timestamp; order proves nothing"
    assert timestamps == sorted(timestamps, reverse=True)
    assert timestamps != sorted(timestamps), (
        "ascending and descending agree here; the fixture cannot tell them apart"
    )


@pytest.mark.asyncio
async def test_plays_offers_a_date_facet(registered_plugin, populated_db):
    """
    The date facet is applied and returns buckets, not merely configured.

    Checked through the facet Datasette actually computes rather than through
    the parsed config, because `facets: [{date: timestamp}]` is a shape it can
    accept and then decline to apply -- a date facet over a column it cannot
    read as a date yields nothing, and the page still renders fine.

    The fixture's plays fall on more than one calendar day, asserted here, or a
    single bucket would look like a working facet and like a broken one alike.
    """
    ds = await serve_configured(populated_db)
    try:
        response = await ds.client.get(
            f"/{DATABASE}/plays.json", params={"_facet_size": "50"}
        )
        assert response.status_code == 200, response.text
        payload = response.json()
    finally:
        ds.close()

    facets = (payload.get("facet_results") or {}).get("results") or {}
    dates = facets.get("timestamp")
    assert dates is not None, f"no facet computed on timestamp: {list(facets)}"
    assert dates["type"] == "date", dates["type"]

    buckets = {row["value"]: row["count"] for row in dates["results"]}
    assert len(buckets) > 1, f"one bucket only; the facet proves nothing: {buckets}"
    for value in buckets:
        assert len(str(value)) == 10, f"{value} is not a calendar day: {value!r}"


# --------------------------------------------------------------------------
# 6.4 -- the SQL time limit, reconciled with the lock wait
# --------------------------------------------------------------------------


#: The shape of the live database, not merely its row count. Measured there:
#: 56,388 plays over 26,408 tracks, 22,008 albums and 14,682 artists -- a
#: vocabulary nearly as large as the history itself, because `md5:` identifiers
#: fragment the same album and artist across many rows. That ratio is what
#: makes the aggregates expensive, and getting it wrong is how this test first
#: failed to do its job twice over: ten plays answered in microseconds, and a
#: scaled-up 47k plays over a *small* vocabulary still ran four times faster
#: than the real thing, so reverting the limit to Datasette's 1000ms default
#: passed both.
REPRESENTATIVE_PLAYS = 47_000
REPRESENTATIVE_TRACKS = 22_000
REPRESENTATIVE_ALBUMS = 18_000
REPRESENTATIVE_ARTISTS = 12_000

#: Parameter *values* that exist in that fixture. The parameter *names* come
#: from the catalog tests' map, so an entry that grows a new parameter fails
#: here with a KeyError rather than being quietly run without it.
FIXTURE_VALUES = {
    "artist_id": "art0",
    "album_id": "alb0",
    "album_ids": '["alb0"]',
    "track_id": "trk0",
    "q": "Track",
}

#: How much of the configured limit the slowest query may consume. The setting
#: exists to leave analytics room on a cold cache and a slower disk than
#: whatever runs this, so "it finished" is not the bar -- "it finished with the
#: limit still an order of magnitude away" is.
REQUIRED_HEADROOM = 2.0


@pytest.fixture(scope="session")
def representative_db(tmp_path_factory):
    """
    An unindexed database at the scale the setting was chosen for.

    Session-scoped and read-only: building it costs a fraction of a second, but
    there is no reason to pay it per test.

    Deliberately carries no indexes at all, which is the state `serve` warns
    about and the state the time limit has to survive. The play timestamps walk
    forward in fixed steps so every rollup -- daily, monthly, yearly -- has many
    non-empty buckets to group rather than one.
    """
    import datetime as dt

    path = tmp_path_factory.mktemp("representative") / "scrobbles.db"
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
        "CREATE TABLE plays (timestamp TEXT NOT NULL,"
        " track_id TEXT NOT NULL REFERENCES tracks(id),"
        " PRIMARY KEY (timestamp, track_id))"
    )
    db["artists"].insert_all(
        [{"id": f"art{i}", "name": f"Artist {i}"} for i in range(REPRESENTATIVE_ARTISTS)]
    )
    db["albums"].insert_all(
        [
            {
                "id": f"alb{i}",
                "title": f"Album {i}",
                "artist_id": f"art{i % REPRESENTATIVE_ARTISTS}",
            }
            for i in range(REPRESENTATIVE_ALBUMS)
        ]
    )
    db["tracks"].insert_all(
        [
            {
                "id": f"trk{i}",
                "title": f"Track {i}",
                "album_id": f"alb{i % REPRESENTATIVE_ALBUMS}",
            }
            for i in range(REPRESENTATIVE_TRACKS)
        ]
    )
    base = dt.datetime(2019, 1, 1, tzinfo=dt.timezone.utc)
    db["plays"].insert_all(
        [
            {
                "timestamp": (base + dt.timedelta(minutes=7 * i)).isoformat(),
                # A stride coprime with the track count, so plays spread over
                # the whole vocabulary instead of cycling through a few rows.
                "track_id": f"trk{(i * 37) % REPRESENTATIVE_TRACKS}",
            }
            for i in range(REPRESENTATIVE_PLAYS)
        ],
        batch_size=5_000,
    )
    db.conn.commit()
    db.close()
    return path


def runnable_entries(path):
    """Every catalog entry whose prerequisite table the fixture actually has."""
    db = sqlite_utils.Database(path)
    tables = set(db.table_names())
    db.close()
    return [
        entry
        for entry in cat.CATALOG
        if not entry.requires_table or entry.requires_table in tables
    ]


def parameters_for(entry):
    return {
        name: FIXTURE_VALUES[name] for name in catalog_tests.PARAMETERS_FOR[entry.name]
    }


@pytest.mark.asyncio
async def test_the_whole_catalog_fits_the_limit_at_representative_scale(
    registered_plugin, representative_db
):
    """
    Every stored query answers on ~47k unindexed plays, with headroom to spare.

    The whole catalog rather than the three rollups, because "the slowest one"
    is not knowable in advance and changes as entries are added. The slowest
    observed is compared against the configured limit, so lowering the limit
    back toward Datasette's default fails here -- which is the assertion the
    ten-row version of this test could not make.
    """
    db = sqlite_utils.Database(representative_db)
    assert db.execute("SELECT COUNT(*) FROM plays").fetchone()[0] >= 40_000
    assert (
        db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
        ).fetchone()[0]
        == 0
    ), "fixture is indexed; it is not the state the limit was chosen for"
    db.close()

    entries = runnable_entries(representative_db)
    assert set(catalog_tests.PARAMETERS_FOR) == {e.name for e in cat.CATALOG}
    assert len(entries) >= 20, f"only {len(entries)} entries ran"

    slowest = (0.0, None)
    ds = await serve_configured(representative_db)
    try:
        limit_ms = ds.setting("sql_time_limit_ms")
        for entry in entries:
            started = time.perf_counter()
            response = await ds.client.get(
                f"/{DATABASE}/{entry.name}.json",
                params={"_shape": "array", **parameters_for(entry)},
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            assert response.status_code == 200, f"{entry.name}: {response.text}"
            slowest = max(slowest, (elapsed_ms, entry.name))
    finally:
        ds.close()

    elapsed_ms, name = slowest
    assert elapsed_ms > 0
    assert limit_ms >= elapsed_ms * REQUIRED_HEADROOM, (
        f"{name} took {elapsed_ms:.0f}ms against a {limit_ms}ms limit; that is "
        f"less than {REQUIRED_HEADROOM}x headroom on an unindexed database"
    )


#: The analytics the task names as the workload ("rollups complete on an
#: unindexed ~47k-play database"), plus the aggregate measured slowest of all.
#: Used for the control below rather than the whole catalog, which costs 20s to
#: run against a limit it is all failing against -- the same evidence, slowly.
HEAVIEST_ENTRIES = ("monthly_rollup", "yearly_rollup", "daily_rollup", "top_albums")


@pytest.mark.asyncio
async def test_that_workload_is_capable_of_failing(
    registered_plugin, representative_db
):
    """
    The control: those queries are killable, so succeeding above meant something.

    Run under a limit far below what they need. Without this, a catalog that had
    somehow become trivially fast would pass the headroom assertion while
    telling us nothing about whether the limit governs these queries at all.
    """
    names = {entry.name for entry in cat.CATALOG}
    assert set(HEAVIEST_ENTRIES) <= names, (
        f"renamed out from under this test: {set(HEAVIEST_ENTRIES) - names}"
    )
    by_name = {entry.name: entry for entry in cat.CATALOG}

    ds = await serve_configured(
        representative_db, config={"settings": {"sql_time_limit_ms": 5}}
    )
    try:
        for name in HEAVIEST_ENTRIES:
            response = await ds.client.get(
                f"/{DATABASE}/{name}.json",
                params={"_shape": "array", **parameters_for(by_name[name])},
            )
            assert response.status_code != 200, f"{name} survived a 5ms limit"
            assert "sql_time_limit_ms" in response.text, (
                f"{name} was refused, but not by the time limit: {response.text}"
            )
    finally:
        ds.close()


#: A read that does enough work to be interruptible at all.
#:
#: A ten-row `SELECT` is not. Datasette enforces its limit through a progress
#: handler called every 1000 VDBE instructions, and a read of this fixture
#: finishes without the handler ever being called once -- measured: zero calls
#: for `SELECT * FROM plays`, 1850 for the query below. Any test that tries to
#: demonstrate the limit against the bare table passes with the setting deleted.
WORKING_READ = (
    "WITH RECURSIVE counter(x) AS ("
    " SELECT 1 UNION ALL SELECT x + 1 FROM counter WHERE x < 50000"
    ") SELECT COUNT(*) FROM counter, plays"
)


@pytest.mark.asyncio
async def test_the_configured_time_limit_is_enforced(registered_plugin, populated_db):
    """
    The setting reaches the server and decides something.

    Paired rather than single: the same query is run under a limit too small
    for it and under the configured one, so this fails both if the limit stops
    being applied and if it stops being generous enough to matter.
    """
    ds = await serve_configured(
        populated_db, config={"settings": {"sql_time_limit_ms": 5}}
    )
    try:
        too_tight = await ds.client.get(
            f"/{DATABASE}/-/query.json", params={"sql": WORKING_READ}
        )
    finally:
        ds.close()
    assert too_tight.status_code != 200
    assert "sql_time_limit_ms" in too_tight.text, (
        f"refused, but not by the time limit: {too_tight.text}"
    )

    ds = await serve_configured(populated_db)
    try:
        assert ds.setting("sql_time_limit_ms") == 10000
        configured = await ds.client.get(
            f"/{DATABASE}/-/query.json",
            params={"sql": WORKING_READ, "_shape": "array"},
        )
    finally:
        ds.close()
    assert configured.status_code == 200, configured.text


@pytest.fixture
def hold_the_write_lock(populated_db):
    """
    Take an EXCLUSIVE lock for a fixed duration, the way an ingest commit does.

    Rollback-journal mode means a writer blocks readers outright for the length
    of its commit, so this reproduces the one interaction a served read has with
    an ingest running in another terminal.

    The lock is taken on request rather than at fixture setup, and that ordering
    is the whole fixture. Datasette's `invoke_startup` reads the served database
    to build its schema tables, so a lock held before the server starts is
    waited out by *startup* -- which looks exactly like a query that sailed
    through a commit window, and passes a test that is measuring nothing.
    """
    threads = []
    failures = []

    def hold(seconds=1.5):
        acquired = threading.Event()

        def run():
            conn = sqlite3.connect(populated_db, isolation_level=None)
            try:
                conn.execute("BEGIN EXCLUSIVE")
                acquired.set()
                time.sleep(seconds)
                conn.execute("COMMIT")
            except Exception as exc:  # noqa: BLE001
                failures.append(exc)
                acquired.set()
            finally:
                conn.close()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        threads.append(thread)
        assert acquired.wait(timeout=10), "writer never acquired the lock"
        assert not failures, failures

    yield hold

    for thread in threads:
        thread.join(timeout=30)
    assert not failures, failures


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path, params",
    [
        ("plays.json", {"_shape": "array"}),
        ("monthly_rollup.json", {"_shape": "array"}),
        ("-/query.json", {"sql": "SELECT COUNT(*) FROM plays", "_shape": "array"}),
    ],
)
async def test_reads_succeed_against_a_concurrent_write(
    registered_plugin, populated_db, hold_the_write_lock, path, params
):
    """
    A request landing inside a commit window waits it out and answers.

    All three read paths, because they do not share one implementation: the
    table view, the stored-query view and the ad hoc query view each reach
    SQLite by their own route.

    The elapsed-time assertion is what makes this a test rather than a
    formality -- without it, a lock that was never actually taken, or a server
    that answered from a cache, reads as a pass.
    """
    ds = await serve_configured(populated_db)
    try:
        hold_the_write_lock(1.5)
        started = time.perf_counter()
        response = await ds.client.get(f"/{DATABASE}/{path}", params=params)
        elapsed = time.perf_counter() - started
    finally:
        ds.close()

    assert response.status_code == 200, response.text
    assert response.json(), "the read succeeded but returned nothing"
    assert elapsed > 1.0, (
        f"the read returned in {elapsed:.2f}s; it never waited on the lock, so "
        "this is not exercising a commit window"
    )


@pytest.mark.asyncio
async def test_the_lock_wait_is_not_governed_by_the_time_limit(
    registered_plugin, populated_db, hold_the_write_lock
):
    """
    The corrected claim: waiting out a commit does not consume the SQL budget.

    D7 originally reasoned that a read landing in a commit window would trip
    Datasette's 1000ms limit long before SQLite's 5000ms busy timeout gave up,
    and that the two therefore had to be set consistently. Measured here, they
    do not interact at all: the wait is absorbed before any timed statement
    begins and `sqlite_timelimit` sets its deadline afterwards, so a 1.5s wait
    under a 1000ms limit still succeeds.

    Pinned as a test because it is the reason `sql_time_limit_ms` is set for
    query cost alone. If a later alpha moves the wait inside the timed region,
    this fails and the reasoning behind the setting has to be revisited.
    """
    ds = await serve_configured(
        populated_db, config={"settings": {"sql_time_limit_ms": 1000}}
    )
    try:
        hold_the_write_lock(1.5)
        started = time.perf_counter()
        response = await ds.client.get(f"/{DATABASE}/plays.json?_shape=array")
        elapsed = time.perf_counter() - started
    finally:
        ds.close()

    assert elapsed > 1.0, "the lock was not actually contended"
    assert response.status_code == 200, (
        "a 1.5s lock wait now consumes the 1000ms SQL time limit; the wait has "
        "moved inside the timed region and D7's budget reasoning needs revisiting"
    )
