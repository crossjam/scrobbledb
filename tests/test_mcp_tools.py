"""
Tests for scrobbledb's MCP tools.

Everything is built through `serve.build_datasette`, the function the command
itself uses, and the server is the one `datasette-mcp` builds from the plugin
manager, so a tool missing from registration or a hook that is not wired up
fails here rather than in production. Tools are listed from that server rather
than from a list typed into a test: a tool added later is covered the day it is
added, and the floor on how many there are catches the opposite failure, a
fixture that finds no tools and so checks nothing.

The in-memory MCP client carries no HTTP request, so the caller is anonymous.
Permission tests therefore deny `execute-sql` to everyone in the database's
config. One test at the end goes over real HTTP against a live `scrobbledb
serve`.
"""

import contextlib
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("datasette")
pytest.importorskip("pytest_asyncio")
pytest.importorskip("datasette_mcp")

import sqlite_utils  # noqa: E402
from mcp import Client  # noqa: E402

import datasette_mcp  # noqa: E402
from scrobbledb import domain_queries as dq  # noqa: E402
from scrobbledb import lastfm  # noqa: E402
from scrobbledb import serve as serve_module  # noqa: E402
from scrobbledb.datasette_plugin import add_read_only_database  # noqa: E402
from scrobbledb.datasette_plugin import config as plugin_config  # noqa: E402
from scrobbledb.datasette_plugin import mcp_tools  # noqa: E402

from tests import test_datasette_queries as catalog_tests  # noqa: E402
from tests import test_serve  # noqa: E402

populated_db = catalog_tests.populated_db
live_server = test_serve.live_server

DATABASE = "scrobbles"

#: What `datasette-mcp` itself provides, which the domain tools sit beside.
UPSTREAM_TOOLS = {"list_databases", "get_database_schema", "execute_sql"}

#: The question categories the spec requires a tool for, each as a word that
#: must appear in some domain tool's name.
REQUIRED_CATEGORIES = [
    "overview",
    "top_artists",
    "top_albums",
    "top_tracks",
    "recent_plays",
    "artist_details",
    "album_details",
    "track_details",
    "search",
    "rollup",
]

#: Arguments a tool needs before it will do anything. Tools not listed here
#: must work when called with none at all, which the success control checks.
NEEDS_ARGUMENTS = {
    "artist_details": {"name": "x"},
    "album_details": {"title": "x"},
    "track_details": {"title": "x"},
    "search_music": {"query": "x"},
}


@pytest.fixture(autouse=True)
def unregister_plugins():
    """`serve` registers with the process-global plugin manager; undo it."""
    yield
    from datasette.plugins import pm

    for name in (serve_module.PLUGIN_NAME, serve_module.MCP_PLUGIN_NAME):
        if pm.get_plugin(name) is not None:
            pm.unregister(name=name)


@pytest.fixture
def mcp_db(populated_db):
    """
    `populated_db` plus plays at known distances from now, and an artist whose
    name FTS5 cannot parse.

    The recent plays sit 300, 100 and 2 days back, so "6 months ago" (about 183
    days) separates the first from the rest by months in both directions and
    no clock reading can move a row across it. The 2024 plays are further back
    still. That is what makes a bounded result differ from an unbounded one.
    """
    now = datetime.now(timezone.utc)
    db = sqlite_utils.Database(populated_db)
    db["plays"].insert_all(
        [
            {"timestamp": (now - timedelta(days=days)).isoformat(), "track_id": track}
            for days, track in [
                (300, "t1"),
                (300, "t4"),
                (100, "t2"),
                (100, "t5"),
                (2, "t3"),
                (2, "t1"),
            ]
        ]
    )
    db["artists"].insert({"id": "a3", "name": "Guns N' Roses"})
    db["albums"].insert({"id": "alb4", "title": "Appetite", "artist_id": "a3"})
    db["tracks"].insert({"id": "t6", "title": "Welcome", "album_id": "alb4"})
    db["plays"].insert(
        {"timestamp": (now - timedelta(days=1)).isoformat(), "track_id": "t6"}
    )
    lastfm.setup_fts5(db)
    lastfm.rebuild_fts5(db)
    db.conn.commit()
    db.close()
    return populated_db


@contextlib.asynccontextmanager
async def mcp_session(path, extra_database_config=None, monkeypatch=None):
    """
    A connected in-memory MCP client over a server built the production way.

    `extra_database_config` is merged into the packaged config for the served
    database, which is how a test denies a permission without a second code
    path to build the server.
    """
    if extra_database_config:
        real = plugin_config.load_config

        def patched(name):
            config = real(name)
            config.setdefault("databases", {}).setdefault(name, {}).update(
                extra_database_config
            )
            return config

        monkeypatch.setattr(plugin_config, "load_config", patched)

    ds = serve_module.build_datasette(path)
    await ds.invoke_startup()
    try:
        async with Client(datasette_mcp.create_mcp_server(ds)) as client:
            yield client, ds
    finally:
        ds.close()


def structured(result):
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def tools_by_name(client):
    return {tool.name: tool for tool in (await client.list_tools()).tools}


async def domain_tools(client):
    return {
        name: tool
        for name, tool in (await tools_by_name(client)).items()
        if name not in UPSTREAM_TOOLS
    }


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# 8.1  Registration
# --------------------------------------------------------------------------


def unmatched_hookimpls():
    """
    Hookimpls with no hookspec, as `pm.check_pending()` would report them.

    Written out rather than calling `check_pending()` because that raises in
    this environment for a reason unrelated to scrobbledb: `datasette-mcp` 0.2
    implements `skip_csrf`, which Datasette 1.0a39 has no hookspec for, so the
    first unmatched hookimpl it meets is that one. What matters here is that
    scrobbledb adds nothing to the list.
    """
    from datasette.plugins import pm

    found = []
    for name in pm.hook.__dict__:
        if name.startswith("_"):
            continue
        hook = getattr(pm.hook, name)
        if not hook.has_spec():
            found += [
                (name, impl.plugin)
                for impl in hook.get_hookimpls()
                if not impl.optionalhook
            ]
    return found


def test_registering_the_tools_adds_nothing_to_the_unmatched_hookimpls(populated_db):
    from datasette.plugins import pm

    from scrobbledb import datasette_plugin

    serve_module.register_plugin()

    assert pm.get_plugin(serve_module.MCP_PLUGIN_NAME) is mcp_tools
    assert pm.get_plugin(serve_module.PLUGIN_NAME) is datasette_plugin
    ours = [
        name
        for name, plugin in unmatched_hookimpls()
        if plugin in (mcp_tools, datasette_plugin)
    ]
    assert ours == []


def test_the_tools_hookimpl_is_unmatched_where_no_hookspec_exists():
    """
    The hazard design D8 names, shown rather than asserted: in a plugin manager
    that never saw `datasette-mcp`'s hookspec, this module's hookimpl is
    exactly what `check_pending()` rejects, which is why `serve` registers it
    only once that import has succeeded.
    """
    import pluggy

    pm = pluggy.PluginManager("datasette")
    pm.register(mcp_tools)

    with pytest.raises(pluggy.PluginValidationError, match="register_mcp_tools"):
        pm.check_pending()


def test_without_mcp_support_the_tools_module_is_not_registered(
    populated_db, monkeypatch
):
    from datasette.plugins import pm

    monkeypatch.setattr(serve_module, "mcp_available", lambda: False)

    serve_module.register_plugin()

    assert pm.get_plugin(serve_module.PLUGIN_NAME) is not None
    assert pm.get_plugin(serve_module.MCP_PLUGIN_NAME) is None
    assert [n for n, p in unmatched_hookimpls() if p is mcp_tools] == []


#: A run in which `datasette-mcp` is not installed. Hiding the distribution from
#: `importlib.metadata` stops pluggy loading it as an entry-point plugin, and
#: `None` in `sys.modules` makes any import of it fail, which together is what a
#: missing package looks like. Everything after that is production code.
WITHOUT_MCP = """
import asyncio, importlib.metadata as md, io, sys
real = md.distributions
md.distributions = lambda *a, **k: (
    d for d in real(*a, **k)
    if (d.metadata["Name"] or "").lower().replace("_", "-") != "datasette-mcp"
)
sys.modules["datasette_mcp"] = None

from datasette.plugins import pm
from scrobbledb import serve

async def main(path):
    assert "datasette_mcp" not in {p.__name__ for p in pm.get_plugins()}
    ds = serve.build_datasette(path)
    await ds.invoke_startup()
    pm.check_pending()
    index = await ds.client.get("/")
    mcp = await ds.client.get("/-/mcp")
    print("index", index.status_code, "mcp", mcp.status_code)
    serve.announce("127.0.0.1", 9000)
    ds.close()

asyncio.run(main(sys.argv[1]))
"""


def test_server_starts_and_says_so_when_mcp_support_is_absent(mcp_db):
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", WITHOUT_MCP, str(mcp_db)],
        capture_output=True,
        text=True,
        env=test_serve.subprocess_env(),
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "index 200 mcp 404" in result.stdout
    assert "MCP endpoint unavailable" in result.stdout
    assert "Serving scrobbledb at http://127.0.0.1:9000/" in result.stdout


# --------------------------------------------------------------------------
# 8.2 / 8.5  The tools exist, and describe themselves
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_required_category_has_a_tool_beside_the_upstream_three(mcp_db):
    async with mcp_session(mcp_db) as (client, _):
        every = await tools_by_name(client)
        domain = await domain_tools(client)

    assert UPSTREAM_TOOLS <= set(every), "datasette-mcp's own tools are missing"
    assert len(domain) >= len(REQUIRED_CATEGORIES), sorted(domain)
    for category in REQUIRED_CATEGORIES:
        assert any(category in name for name in domain), f"no tool for {category}"


@pytest.mark.asyncio
async def test_every_domain_tool_has_a_description_and_a_typed_schema(mcp_db):
    async with mcp_session(mcp_db) as (client, _):
        domain = await domain_tools(client)

    assert domain
    for name, tool in domain.items():
        assert (tool.description or "").strip(), f"{name} has no description"
        schema = tool.input_schema
        assert schema["type"] == "object", name
        for prop, spec in schema["properties"].items():
            assert spec.get("type") or spec.get("anyOf") or spec.get("enum"), (
                f"{name}.{prop} has no type"
            )
            assert spec.get("description"), f"{name}.{prop} has no description"


@pytest.mark.asyncio
async def test_time_ranged_tools_mark_since_until_and_limit_optional(mcp_db):
    async with mcp_session(mcp_db) as (client, _):
        domain = await domain_tools(client)

    ranged = {n: t for n, t in domain.items() if "since" in t.input_schema["properties"]}
    assert len(ranged) >= 5, sorted(ranged)
    for name, tool in ranged.items():
        properties = tool.input_schema["properties"]
        required = set(tool.input_schema.get("required", []))
        assert {"until", "limit"} <= set(properties), name
        assert not {"since", "until", "limit"} & required, (name, required)
        for optional in ("since", "until", "limit"):
            assert "default" in properties[optional], (name, optional)


# --------------------------------------------------------------------------
# 8.3 / 8.4  Authorization comes first, for every tool
# --------------------------------------------------------------------------


class ScrobbleDatabaseReads:
    """Counts every way a query can reach the scrobbledb database object."""

    def __init__(self, monkeypatch, ds):
        self.count = 0
        db = ds.get_database(DATABASE)
        for method in ("execute", "execute_fn", "execute_write_fn"):
            original = getattr(db, method)

            def counted(*args, _original=original, **kwargs):
                self.count += 1
                return _original(*args, **kwargs)

            monkeypatch.setattr(db, method, counted)


async def call_every_tool(client, domain):
    outcomes = {}
    for name in sorted(domain):
        outcomes[name] = await client.call_tool(name, NEEDS_ARGUMENTS.get(name, {}))
    return outcomes


@pytest.mark.asyncio
async def test_every_domain_tool_succeeds_when_permitted(mcp_db):
    """The control: the denial test below only means something if these pass."""
    async with mcp_session(mcp_db) as (client, _):
        domain = await domain_tools(client)
        outcomes = await call_every_tool(client, domain)

    assert len(outcomes) >= len(REQUIRED_CATEGORIES)
    for name, result in outcomes.items():
        assert not result.is_error, f"{name}: {result.content[0].text}"


@pytest.mark.asyncio
async def test_every_domain_tool_is_refused_without_execute_sql(mcp_db, monkeypatch):
    async with mcp_session(
        mcp_db, {"allow_sql": False}, monkeypatch=monkeypatch
    ) as (client, ds):
        domain = await domain_tools(client)
        reads = ScrobbleDatabaseReads(monkeypatch, ds)
        outcomes = await call_every_tool(client, domain)

        assert len(outcomes) >= len(REQUIRED_CATEGORIES)
        for name, result in outcomes.items():
            assert result.is_error, f"{name} ran for a caller without execute-sql"
            assert "permission to execute SQL" in result.content[0].text, name
        assert reads.count == 0, "a refused tool still reached the database"


@pytest.mark.asyncio
async def test_every_domain_tool_is_refused_without_view_database(mcp_db, monkeypatch):
    """
    Visibility is a guarantee of its own: a caller who may not see a database
    must not query it even if SQL execution would be allowed.

    Datasette's config cannot isolate it -- denying `view-database` there denies
    `execute-sql` too, so a config-only test would pass with this check deleted.
    So only the `view-database` answer is withdrawn, at the `allowed()` call,
    and everything else stays real.
    """
    async with mcp_session(mcp_db) as (client, ds):
        real_allowed = ds.allowed
        asked = []

        async def allowed(*, action, resource=None, actor=None):
            asked.append(action)
            if action == "view-database":
                return False
            return await real_allowed(action=action, resource=resource, actor=actor)

        monkeypatch.setattr(ds, "allowed", allowed)
        domain = await domain_tools(client)
        reads = ScrobbleDatabaseReads(monkeypatch, ds)
        outcomes = await call_every_tool(client, domain)
        named = await client.call_tool("collection_overview", {"database": DATABASE})

    assert len(outcomes) >= len(REQUIRED_CATEGORIES)
    assert "view-database" in asked
    for name, result in outcomes.items():
        assert result.is_error, f"{name} ran for a caller who may not view the database"
        # Refused for visibility, not because execute-sql was withdrawn.
        assert "permission to execute SQL" not in result.content[0].text, name
    assert named.is_error
    assert "does not exist or is not available" in named.content[0].text
    assert reads.count == 0, "a refused tool still reached the database"


@pytest.mark.asyncio
async def test_the_upstream_sql_tool_is_refused_the_same_way(mcp_db, monkeypatch):
    async with mcp_session(
        mcp_db, {"allow_sql": False}, monkeypatch=monkeypatch
    ) as (client, _):
        result = await client.call_tool(
            "execute_sql", {"database": DATABASE, "sql": "select 1"}
        )
    assert result.is_error
    assert "permission" in result.content[0].text


@pytest.mark.asyncio
async def test_the_authorization_api_is_the_one_the_design_records():
    """The exact 1.0a39 shape (design D11), pinned so an alpha bump breaks here."""
    import inspect

    from datasette.app import Datasette
    from datasette.resources import DatabaseResource

    signature = inspect.signature(Datasette.allowed)
    assert [p.name for p in signature.parameters.values()][1:] == [
        "action",
        "resource",
        "actor",
    ]
    assert all(
        p.kind is inspect.Parameter.KEYWORD_ONLY
        for p in list(signature.parameters.values())[1:]
    )
    assert list(inspect.signature(DatabaseResource.__init__).parameters)[1:] == [
        "database"
    ]


# --------------------------------------------------------------------------
# Which database
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_extra_in_memory_database_does_not_confuse_the_default(mcp_db):
    """`serve` currently comes with an empty in-memory one; any would do."""
    from datasette.database import Database

    async with mcp_session(mcp_db) as (client, ds):
        ds.add_database(Database(ds, is_memory=True), name="scratch")
        assert {"scratch", DATABASE} <= set(ds.databases)
        result = await client.call_tool("collection_overview", {})

    assert structured(result)["total_scrobbles"] >= 16


@pytest.mark.asyncio
async def test_two_scrobbledb_databases_need_the_database_argument(
    mcp_db, tmp_path
):
    other = tmp_path / "second.db"
    other.write_bytes(mcp_db.read_bytes())

    async with mcp_session(mcp_db) as (client, ds):
        add_read_only_database(ds, other, name="second")
        ambiguous = await client.call_tool("collection_overview", {})
        chosen = await client.call_tool("collection_overview", {"database": "second"})
        missing = await client.call_tool("collection_overview", {"database": "nope"})

    assert ambiguous.is_error
    assert "database" in ambiguous.content[0].text
    assert DATABASE in ambiguous.content[0].text and "second" in ambiguous.content[0].text
    assert not chosen.is_error
    assert missing.is_error
    assert "does not exist or is not available" in missing.content[0].text


@pytest.mark.asyncio
async def test_a_database_without_the_schema_is_not_queried(tmp_path):
    path = tmp_path / "notes.db"
    sqlite_utils.Database(path)["notes"].insert({"id": 1})

    async with mcp_session(path) as (client, _):
        result = await client.call_tool("collection_overview", {})

    assert result.is_error
    assert "No scrobbledb database is available" in result.content[0].text


# --------------------------------------------------------------------------
# Parity with the CLI, and the time vocabulary (8.6)
# --------------------------------------------------------------------------


def cli_db(path):
    return sqlite_utils.Database(path)


def parse(text):
    parsed = dq.parse_relative_time(text)
    assert parsed is not None, text
    return parsed


def without_clock(items):
    """Drop `avg_plays_per_day`, the one field that reads the clock."""
    return [{k: v for k, v in item.items() if k != "avg_plays_per_day"} for item in items]


#: (tool, arguments, the CLI function the tool must agree with). Each is run
#: with the bound the spec names, "6 months ago".
PARITY_CASES = [
    (
        "top_artists",
        {"since": "6 months ago", "limit": 5},
        lambda db: dq.get_top_artists(db, limit=5, since=parse("6 months ago")),
    ),
    (
        "top_albums",
        {"since": "6 months ago", "limit": 5},
        lambda db: dq.get_top_albums(db, limit=5, since=parse("6 months ago")),
    ),
    (
        "top_tracks",
        {"since": "6 months ago", "limit": 5},
        lambda db: dq.get_top_tracks(db, limit=5, since=parse("6 months ago")),
    ),
    (
        "recent_plays",
        {"since": "6 months ago", "limit": 20},
        lambda db: dq.get_plays_with_filters(db, limit=20, since=parse("6 months ago")),
    ),
    (
        "listening_rollup",
        {"period": "month", "since": "6 months ago"},
        lambda db: dq.get_monthly_rollup(db, since=parse("6 months ago")),
    ),
    (
        "listening_rollup",
        {"period": "year", "since": "6 months ago"},
        lambda db: dq.get_yearly_rollup(db, since=parse("6 months ago")),
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool, arguments, cli", PARITY_CASES)
async def test_a_relative_bound_returns_what_the_cli_returns(
    mcp_db, tool, arguments, cli
):
    expected = cli(cli_db(mcp_db))
    unbounded_arguments = {k: v for k, v in arguments.items() if k != "since"}

    async with mcp_session(mcp_db) as (client, _):
        got = structured(await client.call_tool(tool, arguments))
        unbounded = structured(await client.call_tool(tool, unbounded_arguments))

    assert expected, "the CLI side returned nothing; the comparison is vacuous"
    assert without_clock(got["items"]) == without_clock(expected)
    assert got["items"] != unbounded["items"], (
        "the bound changed nothing, so it proves nothing about being read"
    )


@pytest.mark.asyncio
async def test_avg_plays_per_day_agrees_with_the_cli_within_a_day(mcp_db):
    expected = dq.get_top_artists(cli_db(mcp_db), limit=3, since=parse("6 months ago"))
    async with mcp_session(mcp_db) as (client, _):
        got = structured(
            await client.call_tool("top_artists", {"since": "6 months ago", "limit": 3})
        )
    for mine, theirs in zip(got["items"], expected):
        assert mine["avg_plays_per_day"] == pytest.approx(
            theirs["avg_plays_per_day"], rel=0.02
        )


@pytest.mark.asyncio
async def test_an_upper_bound_alone_is_measured_from_the_first_play(mcp_db):
    """
    Used to be `until - now`, negative for any `until` in the past. The CLI
    function shares the calculation, so this also pins that they agree.
    """
    expected = dq.get_top_artists(cli_db(mcp_db), limit=5, until=parse("50 days ago"))
    async with mcp_session(mcp_db) as (client, _):
        got = structured(
            await client.call_tool("top_artists", {"until": "50 days ago", "limit": 5})
        )

    assert expected, "the CLI side returned nothing; the comparison is vacuous"
    assert without_clock(got["items"]) == without_clock(expected)
    for mine, theirs in zip(got["items"], expected):
        assert mine["avg_plays_per_day"] > 0
        assert theirs["avg_plays_per_day"] > 0
        assert mine["avg_plays_per_day"] == pytest.approx(
            theirs["avg_plays_per_day"], rel=0.01
        )


@pytest.mark.asyncio
async def test_no_bounds_covers_the_whole_history(mcp_db):
    async with mcp_session(mcp_db) as (client, _):
        got = structured(await client.call_tool("top_artists", {"limit": 50}))
        overview = structured(await client.call_tool("collection_overview", {}))

    assert sum(item["play_count"] for item in got["items"]) == overview["total_scrobbles"]
    # Whole history has no clock in it -- the period runs from the first play
    # to the last -- so unlike a relative bound, avg_plays_per_day is compared
    # too. A tool that skipped the date-range probe would divide by one day.
    expected = dq.get_top_artists(cli_db(mcp_db), limit=50)
    assert got["items"] == expected
    assert any(item["avg_plays_per_day"] < item["play_count"] for item in got["items"])


@pytest.mark.asyncio
async def test_an_unreadable_bound_names_the_value_and_an_example(mcp_db):
    async with mcp_session(mcp_db) as (client, _):
        domain = await domain_tools(client)
        ranged = [n for n, t in domain.items() if "since" in t.input_schema["properties"]]
        assert len(ranged) >= 5, ranged
        for name in ranged:
            for field in ("since", "until"):
                result = await client.call_tool(name, {field: "not a time at all"})
                text = result.content[0].text
                assert result.is_error, name
                assert "not a time at all" in text, (name, field, text)
                assert field in text, (name, field, text)
                assert "6 months ago" in text, (name, field, text)


@pytest.mark.asyncio
async def test_a_blank_bound_is_no_bound(mcp_db):
    async with mcp_session(mcp_db) as (client, _):
        blank = structured(
            await client.call_tool("top_artists", {"since": "  ", "until": ""})
        )
        none = structured(await client.call_tool("top_artists", {}))
    assert blank["items"] == none["items"]


# --------------------------------------------------------------------------
# Detail tools and search (8.7)
# --------------------------------------------------------------------------


DETAIL_CASES = [
    # tool, a name matching several, a name matching none, a unique name
    ("artist_details", {"name": "Artist"}, {"name": "zzz nobody"}, {"name": "Artist One"}),
    ("album_details", {"title": "Album"}, {"title": "zzz nothing"}, {"title": "Album Two"}),
    ("track_details", {"title": "Track"}, {"title": "zzz nothing"}, {"title": "Track Five"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool, ambiguous, unknown, unique", DETAIL_CASES)
async def test_detail_tools_resolve_ambiguity_and_absence(
    mcp_db, tool, ambiguous, unknown, unique
):
    async with mcp_session(mcp_db) as (client, _):
        many = await client.call_tool(tool, ambiguous)
        none = await client.call_tool(tool, unknown)
        one = await client.call_tool(tool, unique)

    assert many.is_error
    text = many.content[0].text
    assert "More than one" in text and "id " in text, text
    assert list(ambiguous.values())[0] in text

    unmatched = structured(none)
    assert unmatched["found"] is False
    assert unmatched["match"] is None
    assert list(unknown.values())[0] in unmatched["message"]

    matched = structured(one)
    assert matched["found"] is True
    assert matched["match"]["play_count"] > 0


@pytest.mark.asyncio
async def test_detail_tools_return_what_the_cli_returns(mcp_db):
    db = cli_db(mcp_db)
    async with mcp_session(mcp_db) as (client, _):
        artist = structured(await client.call_tool("artist_details", {"name": "Artist One"}))
        album = structured(await client.call_tool("album_details", {"title": "Album Two"}))
        track = structured(await client.call_tool("track_details", {"title": "Track Five"}))

    assert artist["match"] == dq.get_artist_details(db, artist_name="Artist One")
    assert album["match"] == dq.get_album_details(db, album_title="Album Two")
    assert track["match"] == dq.get_track_details(db, track_title="Track Five")


@pytest.mark.asyncio
async def test_a_detail_tool_with_nothing_to_look_up_says_what_to_give(mcp_db):
    async with mcp_session(mcp_db) as (client, _):
        results = [
            await client.call_tool(tool, {})
            for tool in ("artist_details", "album_details", "track_details")
        ]
    for result in results:
        assert result.is_error
        assert "Give" in result.content[0].text


@pytest.mark.asyncio
async def test_search_hits_carry_ids_the_detail_tools_accept(mcp_db):
    async with mcp_session(mcp_db) as (client, _):
        hits = structured(await client.call_tool("search_music", {"query": "Artist One"}))
        artist = hits["artists"]["items"][0]
        by_id = structured(
            await client.call_tool("artist_details", {"artist_id": artist["artist_id"]})
        )
        album_hits = structured(await client.call_tool("search_music", {"query": "Album Two"}))
        track_hits = structured(await client.call_tool("search_music", {"query": "Track Five"}))
        album = structured(
            await client.call_tool(
                "album_details", {"album_id": album_hits["albums"]["items"][0]["album_id"]}
            )
        )
        track = structured(
            await client.call_tool(
                "track_details", {"track_id": track_hits["tracks"]["items"][0]["track_id"]}
            )
        )

    assert artist["artist_name"] == "Artist One"
    assert by_id["found"] and by_id["match"]["artist_name"] == "Artist One"
    assert album["found"] and album["match"]["album_title"] == "Album Two"
    assert track["found"] and track["match"]["track_title"] == "Track Five"


@pytest.mark.asyncio
async def test_search_returns_what_the_cli_searches_return(mcp_db):
    db = cli_db(mcp_db)
    async with mcp_session(mcp_db) as (client, _):
        got = structured(await client.call_tool("search_music", {"query": "Artist", "limit": 5}))

    expected_artists = dq.get_artists_by_search(db, "Artist", limit=5)
    assert len(expected_artists) >= 2, "fixture finds too few artists to compare"
    assert got["artists"]["items"] == expected_artists
    assert got["albums"]["items"] == dq.get_albums_by_search(db, "Artist", limit=5)
    assert got["tracks"]["items"] == dq.get_tracks_by_search(db, "Artist", limit=5)


@pytest.mark.asyncio
async def test_search_survives_text_that_fts5_cannot_parse(mcp_db):
    sql, params = dq.build_artist_fts_candidates_sql(
        query="Guns N' Roses", limit=5, form=dq.SQL_FORM_POSITIONAL
    )
    with pytest.raises(sqlite3.OperationalError):
        sqlite3.connect(mcp_db).execute(sql, params)

    async with mcp_session(mcp_db) as (client, _):
        got = structured(
            await client.call_tool("search_music", {"query": "Guns N' Roses"})
        )

    assert [a["artist_name"] for a in got["artists"]["items"]] == ["Guns N' Roses"]


# --------------------------------------------------------------------------
# 8.8  Caps
# --------------------------------------------------------------------------

#: Tool calls that list rows, each with enough rows behind it to pass a small cap.
LIST_CALLS = [
    ("top_artists", {}),
    ("top_albums", {}),
    ("top_tracks", {}),
    ("recent_plays", {}),
    ("listening_rollup", {"period": "day"}),
    ("listening_rollup", {"period": "month"}),
    ("search_music", {"query": "r"}),
]


def pages(structured_result):
    """The `Page`s in a result: the result itself, or each part of a search."""
    if "items" in structured_result:
        return [structured_result]
    return list(structured_result.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("tool, arguments", LIST_CALLS)
async def test_a_result_longer_than_the_cap_is_cut_and_says_so(
    mcp_db, monkeypatch, tool, arguments
):
    monkeypatch.setattr(mcp_tools, "ROW_CAP", 1)
    async with mcp_session(mcp_db) as (client, _):
        got = structured(await client.call_tool(tool, {**arguments, "limit": 50}))
        monkeypatch.setattr(mcp_tools, "ROW_CAP", 1000)
        whole = structured(await client.call_tool(tool, {**arguments, "limit": 50}))

    cut = [p for p in pages(got) if p["truncated"]]
    assert cut, f"{tool} reported no truncation with a cap of one"
    for page in pages(got):
        assert page["count"] == len(page["items"]) <= 1
    for whole_page, page in zip(pages(whole), pages(got)):
        assert not whole_page["truncated"]
        assert whole_page["count"] >= 2 or not page["truncated"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["top_artists", "top_albums", "top_tracks", "recent_plays"])
async def test_an_enormous_limit_is_not_handed_to_the_database(
    mcp_db, monkeypatch, tool
):
    """
    The cap is applied to the rows, but a request for a million must also not
    reach SQL as a million: the database would aggregate that many to throw
    nearly all of them away. At most one row past the cap is asked for -- the
    extra is how "exactly the cap" is told from "more than the cap".
    """
    seen = []
    async with mcp_session(mcp_db) as (client, ds):
        db = ds.get_database(DATABASE)
        real = db.execute

        async def spy(sql, params=None, *args, **kwargs):
            seen.append(list(params or []))
            return await real(sql, params, *args, **kwargs)

        monkeypatch.setattr(db, "execute", spy)
        result = await client.call_tool(tool, {"limit": 1_000_000})

    assert not result.is_error, result.content[0].text
    integers = [v for params in seen for v in params if isinstance(v, int)]
    assert integers, "no integer parameter reached the database; nothing to check"
    assert max(integers) <= mcp_tools.ROW_CAP + 1, integers
    assert mcp_tools.ROW_CAP + 1 in integers, "the one-past-the-cap row is not requested"


@pytest.fixture
def crowded_db(mcp_db):
    """`mcp_db` plus eight artists sharing a name prefix, each with a play."""
    now = datetime.now(timezone.utc)
    db = sqlite_utils.Database(mcp_db)
    for n in range(1, 9):
        db["artists"].insert({"id": f"c{n}", "name": f"Crowd {n}"})
        db["albums"].insert({"id": f"calb{n}", "title": f"Crowd Album {n}", "artist_id": f"c{n}"})
        db["tracks"].insert({"id": f"ct{n}", "title": f"Crowd Song {n}", "album_id": f"calb{n}"})
        db["plays"].insert(
            {"timestamp": (now - timedelta(hours=n)).isoformat(), "track_id": f"ct{n}"}
        )
    lastfm.setup_fts5(db)
    lastfm.rebuild_fts5(db)
    db.conn.commit()
    db.close()
    return mcp_db


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 2, 3])
async def test_artist_search_aggregates_at_most_twice_the_limit(
    crowded_db, monkeypatch, limit
):
    """
    The FTS candidate query over-fetches three times the limit, and every id it
    returns used to reach the statistics aggregation. Eight artists match, so
    for these limits the unbounded path hands over 3, 6 and 8 where the budget
    allows 2, 4 and 6.
    """
    import json

    seen = []
    async with mcp_session(crowded_db) as (client, ds):
        db = ds.get_database(DATABASE)
        real = db.execute

        async def spy(sql, params=None, *args, **kwargs):
            seen.append((sql, list(params or [])))
            return await real(sql, params, *args, **kwargs)

        monkeypatch.setattr(db, "execute", spy)
        got = structured(
            await client.call_tool("search_music", {"query": "Crowd", "limit": limit})
        )

    stats = [json.loads(p[0]) for sql, p in seen if "artists.id IN" in sql and "json_each" in sql]
    assert len(stats) == 1, "expected exactly one statistics query"
    assert len(stats[0]) == limit * 2, stats[0]
    assert got["artists"]["count"] == limit
    assert got["artists"]["items"] == dq.get_artists_by_search(
        cli_db(crowded_db), "Crowd", limit=limit
    )


@pytest.mark.asyncio
async def test_a_limit_inside_the_cap_is_not_a_truncation(mcp_db, monkeypatch):
    """The caller's own limit stops the list; only the cap counts as truncation."""
    monkeypatch.setattr(mcp_tools, "ROW_CAP", 3)
    async with mcp_session(mcp_db) as (client, _):
        inside = structured(await client.call_tool("recent_plays", {"limit": 3}))
        over = structured(await client.call_tool("recent_plays", {"limit": 50}))

    assert inside["count"] == 3 and inside["truncated"] is False
    assert over["count"] == 3 and over["truncated"] is True


@pytest.mark.asyncio
async def test_the_default_cap_is_sane():
    assert 10 <= mcp_tools.ROW_CAP <= 500


# --------------------------------------------------------------------------
# 8.9  Read-only, over MCP
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM plays",
        "INSERT INTO artists (id, name) VALUES ('x', 'x')",
        "DROP TABLE plays",
        "ATTACH DATABASE ':memory:' AS other",
        "PRAGMA query_only = OFF",
    ],
)
async def test_a_write_through_execute_sql_fails_and_changes_nothing(
    mcp_db, statement
):
    before = sha256(mcp_db)
    async with mcp_session(mcp_db) as (client, _):
        result = await client.call_tool(
            "execute_sql", {"database": DATABASE, "sql": statement}
        )
    assert result.is_error, statement
    assert sha256(mcp_db) == before


@pytest.mark.asyncio
async def test_a_full_mcp_session_leaves_the_file_byte_identical(mcp_db):
    before = sha256(mcp_db)
    async with mcp_session(mcp_db) as (client, _):
        domain = await domain_tools(client)
        outcomes = await call_every_tool(client, domain)
        await client.call_tool(
            "execute_sql", {"database": DATABASE, "sql": "select count(*) from plays"}
        )
        await client.call_tool("get_database_schema", {"database": DATABASE})

    assert len(outcomes) >= len(REQUIRED_CATEGORIES)
    assert sha256(mcp_db) == before
    assert not list(mcp_db.parent.glob("*-journal")) + list(mcp_db.parent.glob("*-wal"))


# --------------------------------------------------------------------------
# Over real HTTP, against the real command
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_client_can_use_the_tools_over_http(live_server, mcp_db):
    before = sha256(mcp_db)
    server = live_server(mcp_db)

    async with Client(server.url + "-/mcp") as client:
        domain = await domain_tools(client)
        assert len(domain) >= len(REQUIRED_CATEGORIES)
        overview = structured(await client.call_tool("collection_overview", {}))
        top = structured(await client.call_tool("top_artists", {"since": "6 months ago"}))
        write = await client.call_tool(
            "execute_sql", {"database": mcp_db.stem, "sql": "DELETE FROM plays"}
        )

    assert overview["total_scrobbles"] >= 16
    assert top["items"], "no artists over HTTP"
    assert write.is_error

    returncode, _, err = server.interrupt()
    assert returncode == 0, err
    assert sha256(mcp_db) == before
