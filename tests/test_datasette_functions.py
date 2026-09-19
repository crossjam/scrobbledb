"""
Tests for the custom SQL functions registered on Datasette connections.

The functions exist so a canned query can express scrobbledb's own time and
naming semantics. The property that matters most is agreement: `parse_when` in
a browser form field must select exactly the rows `--since` selects on the
command line, down to the UTC instant. See design D6.
"""

import sqlite3

import pytest

from scrobbledb import domain_queries
from scrobbledb.datasette_plugin import functions as fns

pytest_asyncio_installed = pytest.importorskip("pytest_asyncio")


@pytest.fixture(autouse=True)
def clear_parse_cache():
    """
    The parser cache is module-level, so it leaks between tests.

    Cleared before and after each test so a cache-hit count is meaningful and
    so one test's parse cannot satisfy another's.
    """
    fns._parse_when_cached.cache_clear()
    yield
    fns._parse_when_cached.cache_clear()


# --------------------------------------------------------------------------
# 4.1 -- each function is callable as a plain Python function
# --------------------------------------------------------------------------


def test_every_registered_function_is_plain_python():
    """
    Registration metadata and the callables agree, and none needs a connection.

    Iterates SQL_FUNCTIONS rather than naming the four, so a fifth function is
    covered as soon as it is registered.
    """
    assert set(fns.SQL_FUNCTIONS) == {
        "parse_when",
        "fuzz_partial_ratio",
        "month_name",
        "fmt_ts",
    }

    samples = {
        "parse_when": ("2024-01-01",),
        "fuzz_partial_ratio": ("Radiohead", "radiohead"),
        "month_name": (3,),
        "fmt_ts": ("2024-01-01T12:00:00+00:00",),
    }
    for name, (arity, fn, _deterministic) in fns.SQL_FUNCTIONS.items():
        args = samples[name]
        assert len(args) == arity, f"{name} declares arity {arity}"
        assert fn(*args) is not None


def test_month_name_matches_the_cli_tables():
    assert fns.month_name(1) == "Jan"
    assert fns.month_name(12) == "Dec"
    # Out of range falls back to the number, as the CLI helper does.
    assert fns.month_name(13) == "13"
    assert fns.month_name(None) is None


def test_fmt_ts_matches_the_cli_rendering():
    stored = "2024-06-01T09:30:00+00:00"
    assert fns.fmt_ts(stored) == "2024-06-01 09:30:00"
    assert fns.fmt_ts(None) is None


def test_fuzz_partial_ratio_is_case_insensitive_and_bounded():
    assert fns.fuzz_partial_ratio("Radiohead", "radiohead") == 100.0
    assert 0.0 <= fns.fuzz_partial_ratio("Radiohead", "Portishead") <= 100.0
    assert fns.fuzz_partial_ratio(None, "x") is None


# --------------------------------------------------------------------------
# 4.2 -- parse_when agrees with the CLI's --since, not with the importer
# --------------------------------------------------------------------------


def _cli_since_bound(expression):
    """The exact parameter the CLI binds for `--since <expression>`."""
    parsed = domain_queries.parse_relative_time(expression)
    assert parsed is not None, f"fixture expression no longer parses: {expression}"
    _sql, params = domain_queries.build_monthly_rollup_sql(since=parsed)
    return params["since"]


@pytest.mark.parametrize(
    "expression",
    [
        "2024-01-01",
        "2024-06-15 13:45:00",
        "January 2024",
        "2024-03-01T00:00:00+00:00",
        "2024-03-01T00:00:00-05:00",
    ],
)
def test_parse_when_matches_the_since_bound_exactly(expression):
    """
    `parse_when(x)` equals the parameter the CLI binds for `--since x`.

    Compared against the builder's own bound value rather than a hand-written
    expectation, so the two cannot drift: if the CLI's interpretation changes,
    this fails.
    """
    assert fns.parse_when(expression) == _cli_since_bound(expression)


@pytest.mark.parametrize("expression", ["3 weeks ago", "yesterday", "last monday"])
def test_parse_when_matches_the_since_bound_for_relative_expressions(expression):
    """
    Same agreement for expressions resolved against "now".

    These cannot be compared as strings: each parse reads the clock, so two
    calls a few microseconds apart legitimately differ in the sub-second
    field. Compared as instants with a tolerance that is far tighter than any
    real disagreement would be -- a wrong naive/UTC reading is hours out, and a
    wrong day is 24 hours out.
    """
    import dateutil.parser

    got = dateutil.parser.parse(fns.parse_when(expression))
    expected = dateutil.parser.parse(_cli_since_bound(expression))
    assert abs((got - expected).total_seconds()) < 5


def test_parse_when_reads_naive_input_as_local_not_utc():
    """
    A naive datetime is local wall clock, following `_to_utc_iso`.

    The import path's `parse_timestamp` reads naive input as UTC. Following the
    importer here would shift every web time filter by the host's UTC offset,
    so this pins the CLI's reading instead.
    """
    from datetime import datetime, timezone

    naive = datetime(2024, 1, 1, 12, 0, 0)
    expected = naive.astimezone().astimezone(timezone.utc).isoformat()

    assert fns.parse_when("2024-01-01 12:00:00") == expected


def test_parse_when_preserves_an_explicit_offset():
    """An expression pinning an instant keeps it, rather than being re-localized."""
    assert fns.parse_when("2024-03-01T00:00:00-05:00") == "2024-03-01T05:00:00+00:00"


# --------------------------------------------------------------------------
# 4.3 -- unparseable input is NULL, never an exception
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad", ["not a date", "", "   ", "????", None, "'; DROP TABLE plays; --"]
)
def test_parse_when_returns_none_rather_than_raising(bad):
    assert fns.parse_when(bad) is None


def test_parse_when_yields_null_inside_sql():
    """
    A statement containing `parse_when('not a date')` still executes.

    A raising SQL function aborts the whole statement, which would make every
    canned query with a blank or mistyped bound fail instead of matching
    everything.
    """
    conn = sqlite3.connect(":memory:")
    fns.register_sql_functions(conn)

    assert conn.execute("SELECT parse_when('not a date')").fetchone()[0] is None
    assert conn.execute("SELECT parse_when('')").fetchone()[0] is None
    assert conn.execute("SELECT parse_when(NULL)").fetchone()[0] is None


def test_the_guard_idiom_short_circuits_an_empty_bound():
    """
    The D5 guard plus a NULL-returning parser behaves as an absent filter.

    This is the combination the canned queries rely on: an empty bound must
    match every row, not none.
    """
    conn = sqlite3.connect(":memory:")
    fns.register_sql_functions(conn)
    conn.execute("CREATE TABLE plays (timestamp TEXT)")
    conn.executemany(
        "INSERT INTO plays VALUES (?)",
        [("2024-01-01T00:00:00+00:00",), ("2025-01-01T00:00:00+00:00",)],
    )

    sql = (
        "SELECT COUNT(*) FROM plays"
        " WHERE (:since = '' OR plays.timestamp >= parse_when(:since))"
    )
    assert conn.execute(sql, {"since": ""}).fetchone()[0] == 2
    assert conn.execute(sql, {"since": "2024-06-01"}).fetchone()[0] == 1
    # An unparseable bound yields NULL, so the comparison matches nothing --
    # visibly empty rather than a 500.
    assert conn.execute(sql, {"since": "not a date"}).fetchone()[0] == 0


# --------------------------------------------------------------------------
# 4.4 -- the parser is cached
# --------------------------------------------------------------------------


@pytest.fixture
def pinned_generation(monkeypatch):
    """
    Freeze the cache generation.

    Without this, a test counting cache misses is flaky: a run that happens to
    straddle a generation boundary sees an extra parse.
    """
    generation = fns._cache_generation()
    monkeypatch.setattr(fns, "_cache_generation", lambda: generation)
    return generation


@pytest.fixture
def count_parses(monkeypatch):
    """Count calls reaching the underlying dateparser path."""
    calls = []
    real = domain_queries.parse_relative_time

    def counting(text):
        calls.append(text)
        return real(text)

    monkeypatch.setattr(domain_queries, "parse_relative_time", counting)
    return calls


def test_repeated_parses_hit_the_cache(pinned_generation, count_parses):
    """
    The underlying dateparser path runs once per distinct argument.

    Without this, a `parse_when` that SQLite evaluates per row would cost
    milliseconds per row.
    """
    first = fns.parse_when("3 weeks ago")
    for _ in range(20):
        assert fns.parse_when("3 weeks ago") == first

    assert len(count_parses) == 1, f"expected one parse, got {len(count_parses)}"

    fns.parse_when("2024-01-01")
    assert len(count_parses) == 2


def test_cache_is_keyed_per_expression(pinned_generation):
    fns.parse_when("2024-01-01")
    fns.parse_when("2025-01-01")
    info = fns._parse_when_cached.cache_info()
    assert info.currsize == 2
    assert info.misses == 2


def test_relative_expressions_do_not_stay_cached_across_generations(
    monkeypatch, count_parses
):
    """
    A relative bound is re-parsed when the clock moves on.

    Keyed on the text alone, a long-running `serve` process would answer
    "yesterday" with whatever yesterday meant at startup, and every later
    request would silently select the wrong range. Regression test for that.
    """
    generation = fns._cache_generation()

    monkeypatch.setattr(fns, "_cache_generation", lambda: generation)
    for _ in range(5):
        fns.parse_when("yesterday")
    assert len(count_parses) == 1

    # Same expression, a later generation: must reach the parser again.
    monkeypatch.setattr(fns, "_cache_generation", lambda: generation + 1)
    fns.parse_when("yesterday")
    assert len(count_parses) == 2


def test_a_moved_clock_yields_a_moved_answer(monkeypatch):
    """
    The refreshed parse actually reflects the new "now", not just a cache miss.

    Counting misses alone would pass even if the value were somehow still
    stale, so this asserts the returned instant moves.
    """
    from datetime import timedelta

    import dateutil.parser

    real = domain_queries.parse_relative_time
    generation = fns._cache_generation()

    monkeypatch.setattr(fns, "_cache_generation", lambda: generation)
    before = fns.parse_when("yesterday")

    monkeypatch.setattr(fns, "_cache_generation", lambda: generation + 86400)
    monkeypatch.setattr(
        domain_queries, "parse_relative_time", lambda t: real(t) + timedelta(days=1)
    )
    after = fns.parse_when("yesterday")

    assert after != before
    delta = dateutil.parser.parse(after) - dateutil.parser.parse(before)
    # Inclusive bounds: across a daylight-saving transition, adding one
    # calendar day legitimately moves the UTC instant by exactly 23 or 25
    # hours, which strict bounds would reject twice a year.
    assert timedelta(hours=23) <= delta <= timedelta(hours=25)


def test_absolute_expressions_are_unaffected_by_the_generation(monkeypatch):
    """An absolute date resolves identically whatever the clock says."""
    generation = fns._cache_generation()

    monkeypatch.setattr(fns, "_cache_generation", lambda: generation)
    first = fns.parse_when("2024-01-01")
    monkeypatch.setattr(fns, "_cache_generation", lambda: generation + 999_999)
    assert fns.parse_when("2024-01-01") == first


# --------------------------------------------------------------------------
# 4.5 -- registered through the connection hook and reachable from SQL
# --------------------------------------------------------------------------


def test_registration_covers_every_function():
    """Each declared function resolves on a bare sqlite3 connection."""
    conn = sqlite3.connect(":memory:")
    fns.register_sql_functions(conn)

    assert conn.execute("SELECT parse_when('2024-01-01')").fetchone()[0]
    assert conn.execute("SELECT fuzz_partial_ratio('a','ab')").fetchone()[0] is not None
    assert conn.execute("SELECT month_name(3)").fetchone()[0] == "Mar"
    assert (
        conn.execute("SELECT fmt_ts('2024-01-01T12:00:00+00:00')").fetchone()[0]
        == "2024-01-01 12:00:00"
    )


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

    pm.register(datasette_plugin, name="scrobbledb-test")
    try:
        yield
    finally:
        pm.unregister(name="scrobbledb-test")


@pytest.fixture
def plays_db(tmp_path):
    """A database with two plays a year apart."""
    import sqlite_utils

    path = tmp_path / "scrobbles.db"
    db = sqlite_utils.Database(path)
    db.execute("CREATE TABLE plays (track_id TEXT, timestamp TEXT)")
    db["plays"].insert_all(
        [
            {"track_id": "t1", "timestamp": "2024-01-01T00:00:00+00:00"},
            {"track_id": "t2", "timestamp": "2025-01-01T00:00:00+00:00"},
        ]
    )
    db.close()
    return path


@pytest.mark.asyncio
async def test_functions_resolve_in_ad_hoc_sql_through_datasette(
    registered_plugin, plays_db
):
    """
    Each function is reachable from a real SQL request, not just a bare
    connection.

    This is what proves the connection hook is actually wired: the
    functions have to be registered on the connection Datasette hands to a
    query, in its own thread pool, not on one the test made itself.
    """
    from datasette.app import Datasette

    ds = Datasette([str(plays_db)])
    await ds.invoke_startup()

    sql = (
        "SELECT parse_when('2024-06-01') AS pw,"
        " fuzz_partial_ratio('Radiohead','radiohead') AS fz,"
        " month_name(3) AS mn,"
        " fmt_ts('2024-01-01T12:00:00+00:00') AS ft"
    )
    # Datasette 1.0a serves ad hoc SQL from /<db>/-/query; the older
    # /<db>.json?sql= form 302-redirects here.
    response = await ds.client.get(
        f"/{plays_db.stem}/-/query.json", params={"sql": sql, "_shape": "array"}
    )
    assert response.status_code == 200, response.text

    row = response.json()[0]
    assert row["pw"] == fns.parse_when("2024-06-01")
    assert row["fz"] == 100.0
    assert row["mn"] == "Mar"
    assert row["ft"] == "2024-01-01 12:00:00"


@pytest.mark.asyncio
async def test_guarded_bound_filters_over_http(registered_plugin, plays_db):
    """
    The canned-query idiom works end to end: blank matches all, a human
    expression filters, and garbage yields an empty result rather than an error.
    """
    from datasette.app import Datasette

    ds = Datasette([str(plays_db)])
    await ds.invoke_startup()

    sql = (
        "SELECT COUNT(*) AS n FROM plays"
        " WHERE (:since = '' OR plays.timestamp >= parse_when(:since))"
    )

    async def count(since):
        r = await ds.client.get(
            f"/{plays_db.stem}/-/query.json",
            params={"sql": sql, "since": since, "_shape": "array"},
        )
        assert r.status_code == 200, r.text
        return r.json()[0]["n"]

    assert await count("") == 2
    assert await count("2024-06-01") == 1
    assert await count("not a date") == 0


def test_registration_marks_only_the_deterministic_functions():
    """
    The determinism flag is claimed only where it is true.

    `parse_when` reads the wall clock, so asserting determinism for it would be
    a false claim to SQLite. Checked through `register_sql_functions` rather
    than a locally registered function, so losing or misapplying the flag in
    production registration fails here.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE rows_ (n INTEGER)")
    conn.executemany("INSERT INTO rows_ VALUES (?)", [(i,) for i in range(20)])

    calls = {name: [] for name in fns.SQL_FUNCTIONS}
    wrapped = {}
    for name, (arity, fn, deterministic) in fns.SQL_FUNCTIONS.items():
        def make(name=name, fn=fn):
            def counting(*args):
                calls[name].append(args)
                return fn(*args)
            return counting
        wrapped[name] = (arity, make(), deterministic)

    original = fns.SQL_FUNCTIONS
    try:
        fns.SQL_FUNCTIONS = wrapped
        fns.register_sql_functions(conn)
    finally:
        fns.SQL_FUNCTIONS = original

    # A deterministic function with a constant argument may be hoisted out of
    # the row loop; a non-deterministic one may not be.
    conn.execute("SELECT COUNT(*) FROM rows_ WHERE month_name(3) IS NOT NULL").fetchone()
    assert len(calls["month_name"]) == 1, (
        "month_name is deterministic and should be hoisted; "
        f"got {len(calls['month_name'])} invocations"
    )

    conn.execute(
        "SELECT COUNT(*) FROM rows_ WHERE parse_when('2024-01-01') IS NOT NULL"
    ).fetchone()
    assert len(calls["parse_when"]) == 20, (
        "parse_when must not be registered deterministic - it reads the clock; "
        f"got {len(calls['parse_when'])} invocations for 20 rows"
    )


def test_a_canned_query_needing_one_bound_must_resolve_it_in_sql():
    """
    Documents why the determinism flag is not a substitute for SQL structure.

    Two call sites yield two resolutions and a column-valued argument yields
    one per row, even when the flag is set, so a query that needs exactly one
    bound has to resolve it once itself -- e.g. in a materialized CTE.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE plays (timestamp TEXT)")
    conn.executemany(
        "INSERT INTO plays VALUES (?)",
        [(f"2024-01-{day:02d}T00:00:00+00:00",) for day in range(1, 11)],
    )

    calls = []

    def counting(text):
        calls.append(text)
        return "2024-01-05T00:00:00+00:00"

    # Even claiming determinism, which production does not for this function.
    conn.create_function("parse_when", 1, counting, deterministic=True)

    calls.clear()
    conn.execute(
        "SELECT COUNT(*) FROM plays"
        " WHERE timestamp >= parse_when(:s) OR timestamp > parse_when(:s)",
        {"s": "x"},
    ).fetchone()
    assert len(calls) == 2, "two call sites resolve independently"

    calls.clear()
    conn.execute(
        "SELECT COUNT(*) FROM plays WHERE timestamp >= parse_when(timestamp)"
    ).fetchone()
    assert len(calls) == 10, "a column-valued argument is evaluated per row"

    # Resolving once in a materialized CTE is what actually pins it.
    calls.clear()
    conn.execute(
        "WITH bound AS MATERIALIZED (SELECT parse_when(:s) AS since_utc)"
        " SELECT COUNT(*) FROM plays, bound"
        " WHERE timestamp >= bound.since_utc OR timestamp > bound.since_utc",
        {"s": "x"},
    ).fetchone()
    assert len(calls) == 1, "a materialized CTE resolves the bound exactly once"


def test_determinism_flags_are_justified():
    """
    Each function's determinism flag matches what the function actually does.

    SQLite's contract covers every accepted input, not the expected ones, and a
    SQL function accepts whatever an ad hoc query passes it. Two of these read
    the clock for some inputs and must not claim determinism.
    """
    flags = {name: flag for name, (_a, _f, flag) in fns.SQL_FUNCTIONS.items()}

    assert flags["parse_when"] is False, "parse_when resolves against now"
    assert flags["fmt_ts"] is False, (
        "fmt_ts defers to dateutil.parser.parse, which fills missing date "
        "components from today"
    )
    assert flags["month_name"] is True
    assert flags["fuzz_partial_ratio"] is True


def test_fmt_ts_is_date_dependent_for_partial_input():
    """
    Evidence for the flag above: a partial timestamp picks up today's date.

    This is why fmt_ts cannot claim determinism, even though it is stable for
    the full ISO timestamps the schema actually stores.
    """
    from datetime import date

    # Each call is bracketed by its own date reads, so a midnight rollover
    # between reading the clock and calling fmt_ts cannot fail the test.
    before = date.today()
    bare_time = fns.fmt_ts("12:00")
    after = date.today()
    # A bare time takes today's date entirely.
    assert bare_time.startswith(before.isoformat()) or bare_time.startswith(
        after.isoformat()
    )

    before = date.today()
    bare_month = fns.fmt_ts("March")
    after = date.today()
    # A bare month takes today's day and year.
    assert bare_month.startswith(f"{before.year}-03-{before.day:02d}") or (
        bare_month.startswith(f"{after.year}-03-{after.day:02d}")
    )

    # Stable for what the schema stores, which is why this is easy to miss.
    assert fns.fmt_ts("2024-01-01T12:00:00+00:00") == "2024-01-01 12:00:00"
