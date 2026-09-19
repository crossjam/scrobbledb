"""
Tests for the three read-only layers of design D7.

The point of the design is that the layers are not restatements of each other,
so the point of these tests is to keep them distinguishable. Two traps make
that harder than it looks, and both are load-bearing here:

- **A denial proves nothing unless the statement would otherwise succeed.**
  On a `mode=ro` connection SQLite refuses `INSERT` by itself, so an
  authorizer test run against the served connection passes with no authorizer
  installed at all. The authorizer's policy is therefore proved on a *writable*
  temporary database with `query_only` off, where the only thing that can
  refuse a statement is the rule under test.

- **`load_extension` is refused by default.** `SELECT load_extension(...)`
  raises "not authorized" on a connection with no authorizer whatsoever,
  because Python disables extension loading unless asked. So the naive check
  cannot tell a working authorizer from an absent one, and the test here turns
  extension loading *on* first.

What each layer alone leaves reachable -- `REINDEX`, `ATTACH`, `DETACH`, and
anything at all once `query_only` has been switched back off -- is covered
against the real served connection, not only the isolated one.
"""

import hashlib
import shutil
import sqlite3

import pytest

pytest.importorskip("datasette")
pytest.importorskip("pytest_asyncio")

import sqlite_utils  # noqa: E402

from scrobbledb.datasette_plugin import queries as cat  # noqa: E402
from scrobbledb.datasette_plugin import readonly  # noqa: E402

# Reused rather than rebuilt: a local re-creation of the fixture would drift
# from the one the catalog tests run against, and the whole-session test below
# has to run the real catalog against a real scrobbledb-shaped database.
# Task 10.2 moves these to a conftest; until then this import is the seam.
from tests import test_datasette_queries as catalog_tests  # noqa: E402

PARAMETERS_FOR = catalog_tests.PARAMETERS_FOR
populated_db = catalog_tests.populated_db
registered_plugin = catalog_tests.registered_plugin
unindexed_db = catalog_tests.unindexed_db


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


async def serve_read_only(path, name="scrobbles"):
    """A started Datasette serving `path` the way `serve` will register it."""
    from datasette.app import Datasette

    ds = Datasette()
    readonly.add_read_only_database(ds, path, name=name)
    await ds.invoke_startup()
    return ds


async def without_the_authorizer(db, fn):
    """
    Run `fn` against the served connection with its authorizer lifted.

    Reading `PRAGMA query_only` is denied, and correctly so: SQLite reports a
    pragma the same way whether it is being read or set, so allowing the read
    would allow `PRAGMA query_only=OFF` with it. Lifting the authorizer for the
    duration of an observation is how the middle layer can be inspected on its
    own -- and it is also how a test can show that layer refusing something the
    authorizer is not there to refuse.
    """

    def _run(conn):
        conn.set_authorizer(None)
        try:
            return fn(conn)
        finally:
            conn.set_authorizer(readonly.authorize)

    return await db.execute_fn(_run)


def on_served_connection(db, sql):
    """
    Run `sql` on a real served connection and return its error, or None.

    Datasette's own `validate_sql_select` refuses most of these before they
    reach SQLite, which is exactly the layer D7 declines to depend on -- so
    these tests reach past it to the connection itself.
    """

    def _run(conn):
        try:
            conn.execute(sql)
        except sqlite3.DatabaseError as exc:
            return str(exc)
        return None

    return db.execute_fn(_run)


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# 5.1 -- the database is registered with an explicit open mode of `ro`
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("write", [False, True])
async def test_every_connection_uri_carries_mode_ro(
    registered_plugin, populated_db, monkeypatch, write
):
    """
    Both branches of `Database.connect()` produce a `mode=ro` URI.

    `write=True` is the branch that matters: left to itself it clears the query
    string entirely and hands back a read-write handle. Parametrized over both
    so a `mode` that only happens to agree with the default is not mistaken for
    one that was stated.
    """
    ds = await serve_read_only(populated_db)
    try:
        db = ds.get_database("scrobbles")
        seen = []
        real_connect = sqlite3.connect

        def capture(database, *args, **kwargs):
            seen.append(database)
            return real_connect(database, *args, **kwargs)

        monkeypatch.setattr("datasette.database.sqlite3.connect", capture)
        db.connect(write=write).close()

        assert seen, "connect() did not reach sqlite3.connect"
        assert all("mode=ro" in uri for uri in seen), seen
    finally:
        ds.close()


@pytest.mark.asyncio
async def test_execute_write_fails_rather_than_succeeding(
    registered_plugin, populated_db
):
    """
    `db.execute_write()` is the documented gap, so it is checked directly.

    The control is the row count: a write that was refused must also not have
    landed, which distinguishes a refusal from a silently ignored statement.
    """
    ds = await serve_read_only(populated_db)
    try:
        db = ds.get_database("scrobbles")
        before = (await db.execute("SELECT COUNT(*) FROM plays")).first()[0]

        with pytest.raises(sqlite3.DatabaseError):
            await db.execute_write(
                "INSERT INTO plays (timestamp, track_id)"
                " VALUES ('2030-01-01T00:00:00+00:00', 't1')"
            )

        after = (await db.execute("SELECT COUNT(*) FROM plays")).first()[0]
        assert after == before
    finally:
        ds.close()


# --------------------------------------------------------------------------
# 5.2 -- `PRAGMA query_only=ON` on every connection
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_only_is_on_for_the_served_connection(
    registered_plugin, populated_db
):
    ds = await serve_read_only(populated_db)
    try:
        db = ds.get_database("scrobbles")
        value = await without_the_authorizer(
            db, lambda conn: conn.execute("PRAGMA query_only").fetchone()[0]
        )
        assert value == 1

        # What `query_only` alone is for: with the authorizer lifted, temp-object
        # creation is still refused, and by SQLite rather than by authorization.
        def _temp_table(conn):
            try:
                conn.execute("CREATE TEMP TABLE probe (a)")
            except sqlite3.DatabaseError as exc:
                return str(exc)
            return None

        error = await without_the_authorizer(db, _temp_table)
        assert error is not None, "query_only is not in force on its own"
        assert "not authorized" not in error.lower(), error
    finally:
        ds.close()


#: The statement shapes the spec names under "Write statement is rejected".
WRITE_STATEMENTS = {
    "INSERT": "INSERT INTO plays (timestamp, track_id) VALUES ('x', 'y')",
    "UPDATE": "UPDATE plays SET track_id = 'z'",
    "DELETE": "DELETE FROM plays",
    "DROP": "DROP TABLE plays",
    "ATTACH": "ATTACH DATABASE ':memory:' AS other",
    "DETACH": "DETACH DATABASE other",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", sorted(WRITE_STATEMENTS))
async def test_write_statements_are_rejected_through_the_query_interface(
    registered_plugin, populated_db, kind
):
    """
    Rejected at the HTTP surface a client actually uses, and at the connection.

    Both halves are needed. The HTTP half is the spec's scenario. The
    connection half is the guarantee: Datasette's view layer would reject most
    of these on its own, and D7 exists so the answer does not depend on it.
    """
    sql = WRITE_STATEMENTS[kind]
    ds = await serve_read_only(populated_db)
    try:
        response = await ds.client.get(
            "/scrobbles/-/query.json", params={"sql": sql, "_shape": "array"}
        )
        assert response.status_code != 200, f"{kind} was accepted: {response.text}"

        error = await on_served_connection(ds.get_database("scrobbles"), sql)
        assert error is not None, f"{kind} reached SQLite unrefused"

        db = sqlite_utils.Database(populated_db)
        assert "plays" in db.table_names()
        db.close()
    finally:
        ds.close()


# --------------------------------------------------------------------------
# 5.4 -- the authorizer policy, proved where nothing else can mask it
# --------------------------------------------------------------------------

#: One statement per denied action, each chosen so the action under test is
#: what SQLite reports. Declared here rather than derived from
#: `DENIED_ACTIONS`, so that deleting a rule from the policy fails
#: `test_the_policy_denies_exactly_these_actions` instead of quietly shrinking
#: this parametrization to match.
DENIED_STATEMENTS = {
    "SQLITE_INSERT": "INSERT INTO t VALUES (2)",
    "SQLITE_UPDATE": "UPDATE t SET a = 3",
    "SQLITE_DELETE": "DELETE FROM t",
    "SQLITE_ALTER_TABLE": "ALTER TABLE t RENAME TO t_renamed",
    "SQLITE_CREATE_INDEX": "CREATE INDEX t_a2 ON t(a)",
    "SQLITE_CREATE_TABLE": "CREATE TABLE fresh (a)",
    "SQLITE_CREATE_TEMP_INDEX": "CREATE INDEX temp.tt_a2 ON tt(a)",
    "SQLITE_CREATE_TEMP_TABLE": "CREATE TEMP TABLE fresh_temp (a)",
    "SQLITE_CREATE_TEMP_TRIGGER": (
        "CREATE TEMP TRIGGER fresh_tt AFTER INSERT ON tt BEGIN SELECT 1; END"
    ),
    "SQLITE_CREATE_TEMP_VIEW": "CREATE TEMP VIEW fresh_tv AS SELECT 1",
    "SQLITE_CREATE_TRIGGER": (
        "CREATE TRIGGER fresh_tr AFTER INSERT ON t BEGIN SELECT 1; END"
    ),
    "SQLITE_CREATE_VIEW": "CREATE VIEW fresh_v AS SELECT 1",
    "SQLITE_CREATE_VTABLE": "CREATE VIRTUAL TABLE fresh_fts USING fts5(x)",
    "SQLITE_DROP_INDEX": "DROP INDEX t_a",
    "SQLITE_DROP_TABLE": "DROP TABLE t",
    "SQLITE_DROP_TEMP_INDEX": "DROP INDEX temp.tt_a",
    "SQLITE_DROP_TEMP_TABLE": "DROP TABLE temp.tt",
    "SQLITE_DROP_TEMP_TRIGGER": "DROP TRIGGER temp.tt_tr",
    "SQLITE_DROP_TEMP_VIEW": "DROP VIEW temp.tv",
    "SQLITE_DROP_TRIGGER": "DROP TRIGGER t_tr",
    "SQLITE_DROP_VIEW": "DROP VIEW v",
    "SQLITE_DROP_VTABLE": "DROP TABLE ft",
    "SQLITE_REINDEX": "REINDEX",
    "SQLITE_ANALYZE": "ANALYZE",
    "SQLITE_ATTACH": "ATTACH DATABASE ':memory:' AS extra",
    "SQLITE_DETACH": "DETACH DATABASE attached",
}


@pytest.fixture
def writable_template(tmp_path):
    """
    A writable database carrying one object of every kind the policy names.

    Nothing about it is read-only: that is the point. `mode=ro` and
    `query_only` are both absent so that a denial can only have come from the
    authorizer.
    """
    path = tmp_path / "writable.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE t (a);
        INSERT INTO t VALUES (1);
        CREATE INDEX t_a ON t(a);
        CREATE VIEW v AS SELECT a FROM t;
        CREATE TRIGGER t_tr AFTER INSERT ON t BEGIN SELECT 1; END;
        CREATE VIRTUAL TABLE ft USING fts5(x);
        """
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def open_writable(writable_template, tmp_path):
    """
    Opens a fresh copy of the template per call, with temp objects in place.

    A copy per call because the statements destroy what the next one needs --
    `DROP TABLE t` and `INSERT INTO t` cannot share a database. The temp
    objects and the attached database are created *before* any authorizer is
    installed, since creating them is itself a denied action.
    """
    opened = []
    counter = iter(range(1000))

    def _open():
        path = tmp_path / f"copy{next(counter)}.db"
        shutil.copy(writable_template, path)
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TEMP TABLE tt (a);
            CREATE INDEX temp.tt_a ON tt(a);
            CREATE TEMP VIEW tv AS SELECT 1;
            CREATE TEMP TRIGGER tt_tr AFTER INSERT ON tt BEGIN SELECT 1; END;
            """
        )
        conn.execute("ATTACH DATABASE ':memory:' AS attached")
        opened.append(conn)
        return conn

    yield _open
    for conn in opened:
        conn.set_authorizer(None)
        conn.close()


def test_the_policy_denies_exactly_these_actions():
    """
    The policy and this module's expectation of it are the same set.

    This is what makes removing a rule fail the suite: the parametrization
    below is built from `DENIED_STATEMENTS`, so without this comparison a
    deleted rule would delete its own test case along with it.
    """
    assert set(DENIED_STATEMENTS) == set(readonly.DENIED_ACTIONS)


@pytest.mark.parametrize("action_name", sorted(DENIED_STATEMENTS))
def test_each_denied_action_is_refused_and_would_otherwise_succeed(
    action_name, open_writable
):
    """
    Three connections, because a denial on its own is not evidence.

    1. No authorizer: the statement succeeds, so the database really does
       permit it and the test is not asserting against an impossibility.
    2. The real policy: refused.
    3. A policy denying *only* this action: still refused, which is what
       attributes the refusal to this rule rather than to a neighbour that
       happens to fire on the same statement.
    """
    sql = DENIED_STATEMENTS[action_name]
    code = readonly.DENIED_ACTIONS[action_name]

    open_writable().execute(sql)

    with pytest.raises(sqlite3.DatabaseError):
        conn = open_writable()
        conn.set_authorizer(readonly.authorize)
        conn.execute(sql)

    with pytest.raises(sqlite3.DatabaseError):
        conn = open_writable()
        conn.set_authorizer(
            lambda action, *rest: (
                sqlite3.SQLITE_DENY if action == code else sqlite3.SQLITE_OK
            )
        )
        conn.execute(sql)


def test_select_still_succeeds_under_the_policy(open_writable):
    """The control: a policy that denies reading would pass every test above."""
    conn = open_writable()
    conn.set_authorizer(readonly.authorize)
    assert conn.execute("SELECT a FROM t").fetchall() == [(1,)]
    assert conn.execute("SELECT a FROM v").fetchall() == [(1,)]


def test_the_temp_variants_are_the_ones_query_only_would_have_hidden(open_writable):
    """
    Temp-object creation is refused by the authorizer with `query_only` off.

    `query_only=ON` also blocks these, which is why the isolated connection
    matters: run against the served connection this would pass whether the
    `_TEMP_` rules existed or not, and they are the rules that survive
    `PRAGMA query_only=OFF`.
    """
    temp_actions = [
        name for name in readonly.DENIED_ACTIONS if "_TEMP_" in name
    ]
    assert len(temp_actions) == 8, temp_actions

    for name in temp_actions:
        conn = open_writable()
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 0
        conn.set_authorizer(readonly.authorize)
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(DENIED_STATEMENTS[name])


# --------------------------------------------------------------------------
# 5.5 -- the statements with no second line of defence
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sql",
    [
        "REINDEX",
        "ATTACH DATABASE ':memory:' AS other",
        "DETACH DATABASE other",
    ],
)
async def test_the_authorizer_only_statements_are_denied_when_served(
    registered_plugin, populated_db, sql
):
    """
    Denied on the real served connection, not merely on the isolated one.

    These are the cases the D7 table marks as reaching the database through
    both other layers, so a policy that were somehow not installed on the
    served connection would show up right here.
    """
    ds = await serve_read_only(populated_db)
    try:
        error = await on_served_connection(ds.get_database("scrobbles"), sql)
        assert error is not None, f"{sql} was not refused on the served connection"
        assert "authorized" in error, error
    finally:
        ds.close()


# --------------------------------------------------------------------------
# 5.6 -- extension loading, told apart from Python's own refusal
# --------------------------------------------------------------------------


def test_extension_loading_is_denied_by_the_authorizer_not_by_the_default(
    open_writable,
):
    """
    Enable extension loading first, so the refusal can only be the authorizer.

    The control asserts the trap is real: with loading enabled and no
    authorizer, the statement gets *past* authorization and fails in the
    dynamic loader instead, with an error that names neither.
    """
    conn = open_writable()
    conn.enable_load_extension(True)
    with pytest.raises(sqlite3.DatabaseError) as unguarded:
        conn.execute("SELECT load_extension('no-such-extension')")
    assert "not authorized" not in str(unguarded.value).lower(), (
        "extension loading was still disabled; the guarded case would prove nothing"
    )

    conn = open_writable()
    conn.enable_load_extension(True)
    conn.set_authorizer(readonly.authorize)
    with pytest.raises(sqlite3.DatabaseError) as guarded:
        conn.execute("SELECT load_extension('no-such-extension')")
    assert "not authorized" in str(guarded.value).lower(), guarded.value


@pytest.mark.asyncio
async def test_extension_loading_is_denied_on_the_served_connection(
    registered_plugin, populated_db
):
    ds = await serve_read_only(populated_db)
    try:

        def _run(conn):
            conn.enable_load_extension(True)
            try:
                conn.execute("SELECT load_extension('no-such-extension')")
            except sqlite3.DatabaseError as exc:
                return str(exc)
            finally:
                conn.enable_load_extension(False)
            return None

        error = await ds.get_database("scrobbles").execute_fn(_run)
        assert error is not None and "not authorized" in error.lower(), error
    finally:
        ds.close()


# --------------------------------------------------------------------------
# 5.7 -- statements that produce a file rather than writing rows
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_statements_that_would_produce_a_file_are_rejected(
    registered_plugin, populated_db, tmp_path
):
    """
    `VACUUM INTO` and a journal-mode switch, neither of which writes a row.

    `VACUUM INTO` is covered by the `SQLITE_ATTACH` rule -- SQLite reports the
    output file as an attach -- and the pragma by the pragma allowlist. The
    output path is asserted absent afterwards, since "raised an error" and
    "wrote nothing" are not the same claim.
    """
    target = tmp_path / "copy-out.db"
    ds = await serve_read_only(populated_db)
    try:
        db = ds.get_database("scrobbles")

        error = await on_served_connection(db, f"VACUUM INTO '{target}'")
        assert error is not None, "VACUUM INTO was allowed"
        assert not target.exists(), "VACUUM INTO produced a file despite the error"

        error = await on_served_connection(db, "PRAGMA journal_mode=WAL")
        assert error is not None, "journal_mode was switchable"

        # Read from a connection of our own rather than the served one: the
        # journal mode is a property of the file, and `PRAGMA journal_mode` is
        # denied on the served connection precisely because it is settable.
        separate = sqlite3.connect(f"file:{populated_db}?mode=ro", uri=True)
        try:
            assert separate.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        finally:
            separate.close()
    finally:
        ds.close()


@pytest.mark.asyncio
async def test_read_only_cannot_be_switched_off(registered_plugin, populated_db):
    """
    The spec's second scenario: turn the middle layer off, then try again.

    `PRAGMA query_only=OFF` is itself refused, and the assertion that follows
    is the one that matters -- even granting that it had succeeded, the
    authorizer still refuses the write.
    """
    ds = await serve_read_only(populated_db)
    try:
        db = ds.get_database("scrobbles")

        assert await on_served_connection(db, "PRAGMA query_only=OFF") is not None

        error = await on_served_connection(
            db, "CREATE TEMP TABLE smuggled AS SELECT * FROM plays"
        )
        assert error is not None and "authorized" in error, error

        still_on = await without_the_authorizer(
            db, lambda conn: conn.execute("PRAGMA query_only").fetchone()[0]
        )
        assert still_on == 1
    finally:
        ds.close()


# --------------------------------------------------------------------------
# 5.8 -- open non-immutably, so an out-of-band write is tolerated
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_database_is_registered_mutable_rather_than_immutable(
    registered_plugin, populated_db
):
    """
    `is_mutable` is the flag that says the file may change, not that we may.

    Asserted as a property as well as behaviourally below, because
    `immutables=[path]` would pass a "the server still serves" test on a small
    fixture while promising something an `ingest` in another terminal breaks.
    """
    ds = await serve_read_only(populated_db)
    try:
        db = ds.get_database("scrobbles")
        assert db.is_mutable is True
        assert db.mode == "ro"
    finally:
        ds.close()


@pytest.mark.asyncio
async def test_serving_survives_an_out_of_band_write(registered_plugin, populated_db):
    """
    A write from another process mid-session, exactly as `ingest` would make it.

    The new row has to become visible: a server that kept serving but from a
    stale snapshot would satisfy "still starts and serves" and still be wrong
    (the spec's "Database changes while being served" scenario).
    """
    ds = await serve_read_only(populated_db)
    try:
        db = ds.get_database("scrobbles")
        before = (await db.execute("SELECT COUNT(*) FROM plays")).first()[0]

        outside = sqlite_utils.Database(populated_db)
        outside["plays"].insert(
            {"timestamp": "2031-02-03T04:05:06+00:00", "track_id": "t1"}
        )
        outside.conn.commit()
        outside.close()

        response = await ds.client.get("/scrobbles/plays.json?_shape=array")
        assert response.status_code == 200, response.text

        after = (await db.execute("SELECT COUNT(*) FROM plays")).first()[0]
        assert after == before + 1, "the server is serving a stale snapshot"
    finally:
        ds.close()


# --------------------------------------------------------------------------
# 5.9 -- a whole session leaves the file byte-identical
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture_name", ["populated_db", "unindexed_db"])
async def test_a_full_session_leaves_the_file_byte_identical(
    registered_plugin, request, fixture_name
):
    """
    Start, browse, run every stored query, shut down; hash before and after.

    `unindexed_db` is the case the task singles out: with no analytics indexes
    the rollups fall back to full scans, and a scan is where SQLite would reach
    for an automatic index or a temp store if anything let it.

    Every entry in the catalog is run rather than a chosen few, so a query
    added later is covered the day it is added.
    """
    path = request.getfixturevalue(fixture_name)
    before = file_digest(path)

    ds = await serve_read_only(path)
    try:
        assert (await ds.client.get("/scrobbles.json")).status_code == 200
        for table in ("plays", "tracks", "albums", "artists"):
            response = await ds.client.get(f"/scrobbles/{table}.json?_shape=array")
            assert response.status_code == 200, response.text

        assert set(PARAMETERS_FOR) == {entry.name for entry in cat.CATALOG}, (
            "the catalog changed; this session is no longer running all of it"
        )
        tables = set(sqlite_utils.Database(path).table_names())
        for entry in cat.CATALOG:
            response = await ds.client.get(
                f"/scrobbles/{entry.name}.json",
                params={"_shape": "array", **PARAMETERS_FOR[entry.name]},
            )
            if entry.requires_table and entry.requires_table not in tables:
                # Registered, but standing in for itself with the message that
                # names the command to run. Still executed here: the point is
                # that running it touches nothing.
                assert response.status_code == 400, f"{entry.name}: {response.text}"
                assert entry.missing_hint in response.text
            else:
                assert response.status_code == 200, f"{entry.name}: {response.text}"
    finally:
        ds.close()

    assert file_digest(path) == before, "the session modified the database file"
    assert not path.with_name(path.name + "-journal").exists()
    assert not path.with_name(path.name + "-wal").exists()
